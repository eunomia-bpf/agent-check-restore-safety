// Package vmevidence independently checks the retained standalone VM demo.
package vmevidence

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/history"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

var manifestFiles = []string{
	"guest-network.jsonl",
	"guest-operation.json",
	"guest-script.sh",
	"guest.qcow2",
	"guest.serial.log",
	"host-supervisor.jsonl",
	"host.head",
	"host.history",
	"payment.history",
	"provenance.json",
	"provider-deliveries.jsonl",
	"qemu-command.json",
	"qemu.log",
	"qmp-protocol.jsonl",
	"result.json",
	"snapshots.txt",
}

var expectedSelectedSourcePaths = []string{
	"Makefile", "README.md", "runtime/README.md", "runtime/go.mod", "runtime/go.sum",
	"runtime/cmd/check-vm-evidence", "runtime/cmd/vm-demo",
	"runtime/internal/api", "runtime/internal/certcheck", "runtime/internal/control",
	"runtime/internal/gateway", "runtime/internal/headanchor", "runtime/internal/history",
	"runtime/internal/kernel", "runtime/internal/payment", "runtime/internal/sandboxhost",
	"runtime/internal/vmevidence",
}

const (
	expectedBaseImageSHA  = "d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac"
	expectedBaseImageSize = 624105472
	qemuImageToolTimeout  = 30 * time.Second
)

// Report contains only facts recomputed from retained evidence.
type Report struct {
	Valid                   bool   `json:"valid"`
	GitRevision             string `json:"git_revision"`
	Accelerator             string `json:"accelerator"`
	GuestKernel             string `json:"guest_kernel"`
	HistorySequence         uint64 `json:"history_sequence"`
	OperationID             string `json:"operation_id"`
	SandboxGenerations      int    `json:"sandbox_generations"`
	ProviderDeliveries      int    `json:"provider_deliveries"`
	ProviderCommits         int    `json:"provider_commits"`
	SnapshotLoadedPaused    bool   `json:"snapshot_loaded_paused"`
	ReplacementBeforeResume bool   `json:"replacement_before_resume"`
	GuestCredentialFree     bool   `json:"injected_guest_credential_free"`
	GuestProviderFree       bool   `json:"injected_guest_provider_free"`
}

type resultFile struct {
	Accelerator                      string   `json:"accelerator"`
	BaseImageSHA256                  string   `json:"base_image_sha256"`
	DirectHostCanaryFromGuest        string   `json:"direct_host_canary_from_guest"`
	EvidenceSchema                   int      `json:"evidence_schema"`
	EndpointReboundWhileVMPaused     bool     `json:"endpoint_rebound_while_vm_paused"`
	EvidenceDirectory                string   `json:"evidence_directory,omitempty"`
	FirstNetworkResult               string   `json:"first_network_result"`
	FullLinuxGuest                   bool     `json:"full_linux_guest"`
	GuestKernel                      string   `json:"guest_kernel"`
	HistoryOutsideGuestRestoreDomain bool     `json:"history_outside_guest_restore_domain"`
	HostBoundSandboxGenerations      []uint64 `json:"host_bound_sandbox_generations"`
	HostHistorySequence              uint64   `json:"host_history_sequence"`
	HostOwnedRestrictedNetwork       bool     `json:"host_owned_restricted_network"`
	InjectedGuestBearerToken         bool     `json:"injected_guest_bearer_token"`
	InjectedGuestProviderTarget      bool     `json:"injected_guest_provider_target"`
	OldSandboxGenerationRejected     bool     `json:"old_sandbox_generation_rejected"`
	PaymentOutsideGuestRestoreDomain bool     `json:"payment_outside_guest_restore_domain"`
	RemoteCommits                    int      `json:"remote_commits"`
	RemoteDeliveries                 int      `json:"remote_deliveries"`
	RestoredOperation                string   `json:"restored_operation"`
	RuleAndSandboxCutovers           int      `json:"rule_and_sandbox_cutovers"`
	RunnerCompleted                  bool     `json:"runner_completed"`
	SnapshotSavedBeforeOperation     bool     `json:"snapshot_saved_before_operation"`
	WholeVMRestored                  bool     `json:"whole_vm_restored"`
}

type provenanceFile struct {
	Accelerator string `json:"accelerator"`
	GitRevision string `json:"git_revision"`
	GoVersion   string `json:"go_version"`
	HostTools   []struct {
		Name   string `json:"name"`
		Path   string `json:"path"`
		SHA256 string `json:"sha256"`
	} `json:"host_tools"`
	HostUname           string   `json:"host_uname"`
	KVMDeviceReadWrite  bool     `json:"kvm_device_read_write"`
	PublicEntrypoint    string   `json:"public_entrypoint"`
	RecordedAt          string   `json:"recorded_at"`
	ReproductionCommand string   `json:"reproduction_command"`
	RunnerArguments     []string `json:"runner_arguments"`
	Schema              int      `json:"schema"`
	SelectedSourceClean bool     `json:"selected_source_clean"`
	SelectedSourcePaths []string `json:"selected_source_paths"`
	SourceState         string   `json:"source_state"`
}

type guestOperation struct {
	CallID string `json:"call_id"`
	Kind   string `json:"kind"`
	Body   []byte `json:"body"`
}

type qemuCommandFile struct {
	Arguments  []string `json:"arguments"`
	Executable string   `json:"executable"`
	Schema     int      `json:"schema"`
}

type traceRecord struct {
	Sequence  uint64          `json:"sequence"`
	TimeNS    int64           `json:"time_ns"`
	Event     string          `json:"event,omitempty"`
	Direction string          `json:"direction,omitempty"`
	Details   json.RawMessage `json:"details,omitempty"`
	Payload   json.RawMessage `json:"payload,omitempty"`
}

type traceBindingDetails struct {
	Address         string                 `json:"address,omitempty"`
	Binding         control.SandboxBinding `json:"binding"`
	HistorySequence uint64                 `json:"history_sequence,omitempty"`
	Reason          string                 `json:"reason,omitempty"`
}

type providerDetails struct {
	Method      string `json:"method"`
	Path        string `json:"path"`
	OperationID string `json:"operation_id"`
}

type providerFact struct {
	providerDetails
	TimeNS int64
}

type qmpPayload struct {
	Execute   string          `json:"execute,omitempty"`
	ID        string          `json:"id,omitempty"`
	Event     string          `json:"event,omitempty"`
	Error     json.RawMessage `json:"error,omitempty"`
	Arguments struct {
		CommandLine string `json:"command-line"`
	} `json:"arguments,omitempty"`
	Return json.RawMessage `json:"return,omitempty"`
}

type qmpCommand struct {
	Name        string
	ID          string
	CommandLine string
	TimeNS      int64
}

type qmpFacts struct {
	Commands      []qmpCommand
	ResponseTimes map[string]int64
	Paused        map[string]bool
	Returns       map[string]json.RawMessage
}

type supervisorFacts struct {
	Times          map[string][]int64
	FirstBinding   control.SandboxBinding
	SecondBinding  control.SandboxBinding
	FirstAddress   string
	SecondAddress  string
	FirstUnknownAt int64
	RestoredAt     int64
}

type paymentRecord struct {
	OperationID     string `json:"operation_id"`
	RequestHash     string `json:"request_hash"`
	ResultHash      string `json:"result_hash"`
	RemoteReference string `json:"remote_reference"`
	Path            string `json:"path"`
}

type operationReceipt struct {
	Schema          int    `json:"schema"`
	OperationID     string `json:"operation_id"`
	Outcome         string `json:"outcome"`
	ResultHash      string `json:"result_hash"`
	RemoteReference string `json:"remote_reference"`
}

type guestFacts struct {
	DirectCanaryPort int
	ScriptSHA256     string
	UserDataSHA256   string
}

type metadataDetails struct {
	Method            string `json:"method"`
	Path              string `json:"path"`
	Address           string `json:"address"`
	GuestScriptSHA256 string `json:"guest_script_sha256"`
	UserDataSHA256    string `json:"user_data_sha256"`
}

type metadataFacts struct {
	Address             string
	TimeNS              int64
	DirectCanaryAddress string
	DirectCanaryTimeNS  int64
	GateOpenTimeNS      int64
	GateServedTimeNS    int64
}

type canaryDetails struct {
	Address string `json:"address"`
}

type qemuImageInfo struct {
	ActualSize            int64  `json:"actual-size"`
	BackingFilename       string `json:"full-backing-filename"`
	BackingFilenameFormat string `json:"backing-filename-format"`
	Dirty                 bool   `json:"dirty-flag"`
	Filename              string `json:"filename"`
	Format                string `json:"format"`
	VirtualSize           int64  `json:"virtual-size"`
	Snapshots             []struct {
		ID          string `json:"id"`
		Name        string `json:"name"`
		VMStateSize int64  `json:"vm-state-size"`
	} `json:"snapshots"`
	FormatSpecific struct {
		Data struct {
			Corrupt bool `json:"corrupt"`
		} `json:"data"`
	} `json:"format-specific"`
}

type qemuImageCheck struct {
	AllocatedClusters int64 `json:"allocated-clusters"`
	CheckErrors       int64 `json:"check-errors"`
	Corruptions       int64 `json:"corruptions"`
	Leaks             int64 `json:"leaks"`
	TotalClusters     int64 `json:"total-clusters"`
}

type historySequenceDetails struct {
	HistorySequence uint64 `json:"history_sequence"`
}

type cutoverEvent struct {
	SemanticVersion int                      `json:"semantic_version"`
	Certificate     kernel.Certificate       `json:"certificate"`
	Bindings        []control.SandboxBinding `json:"bindings"`
}

type prepareEvent struct {
	SemanticVersion int              `json:"semantic_version"`
	Operation       kernel.Operation `json:"operation"`
}

type phaseEvent struct {
	SemanticVersion int                    `json:"semantic_version"`
	ID              string                 `json:"id"`
	Update          kernel.OperationUpdate `json:"update"`
}

type historyFacts struct {
	State         *kernel.State
	Events        []history.Event
	FirstBinding  control.SandboxBinding
	SecondBinding control.SandboxBinding
	Operation     kernel.Operation
}

// Check independently replays and cross-checks one finalized evidence tree.
func Check(directory string) (Report, error) {
	directory, err := filepath.Abs(directory)
	if err != nil {
		return Report{}, err
	}
	if err := checkDirectory(directory); err != nil {
		return Report{}, err
	}
	if err := checkManifest(directory); err != nil {
		return Report{}, err
	}
	var result resultFile
	if err := readStrictJSON(filepath.Join(directory, "result.json"), &result); err != nil {
		return Report{}, err
	}
	var provenance provenanceFile
	if err := readStrictJSON(filepath.Join(directory, "provenance.json"), &provenance); err != nil {
		return Report{}, err
	}
	if err := checkProvenance(provenance); err != nil {
		return Report{}, err
	}
	var guest guestOperation
	guestData, err := readStrictJSONBytes(filepath.Join(directory, "guest-operation.json"), &guest)
	if err != nil {
		return Report{}, err
	}
	guestScript, err := os.ReadFile(filepath.Join(directory, "guest-script.sh"))
	if err != nil {
		return Report{}, err
	}
	guestContract, err := checkGuest(guest, guestData, guestScript)
	if err != nil {
		return Report{}, err
	}
	var qemu qemuCommandFile
	if err := readStrictJSON(filepath.Join(directory, "qemu-command.json"), &qemu); err != nil {
		return Report{}, err
	}
	if err := checkQEMU(qemu, result.Accelerator); err != nil {
		return Report{}, err
	}
	metadata, err := checkGuestNetworkTrace(filepath.Join(directory, "guest-network.jsonl"), guestContract)
	if err != nil {
		return Report{}, err
	}
	if err := checkDiskImage(directory, provenance); err != nil {
		return Report{}, err
	}
	if err := checkQEMULog(filepath.Join(directory, "qemu.log")); err != nil {
		return Report{}, err
	}
	qmp, err := checkQMP(filepath.Join(directory, "qmp-protocol.jsonl"))
	if err != nil {
		return Report{}, err
	}
	supervisor, err := checkSupervisor(filepath.Join(directory, "host-supervisor.jsonl"))
	if err != nil {
		return Report{}, err
	}
	providers, err := checkProviderTrace(filepath.Join(directory, "provider-deliveries.jsonl"))
	if err != nil {
		return Report{}, err
	}
	if err := checkTimeline(qmp, supervisor, providers, metadata); err != nil {
		return Report{}, err
	}
	history, err := checkHistory(directory, guest)
	if err != nil {
		return Report{}, err
	}
	if err := crossCheckNetwork(qemu, supervisor, history, metadata, guestContract); err != nil {
		return Report{}, err
	}
	payment, err := checkPayment(filepath.Join(directory, "payment.history"), history.Operation)
	if err != nil {
		return Report{}, err
	}
	if err := crossCheckBindings(supervisor, history); err != nil {
		return Report{}, err
	}
	guestKernel, err := checkSerial(filepath.Join(directory, "guest.serial.log"))
	if err != nil {
		return Report{}, err
	}
	if err := checkSnapshot(filepath.Join(directory, "snapshots.txt")); err != nil {
		return Report{}, err
	}
	if err := crossCheckResult(result, provenance, history, guestKernel, providers); err != nil {
		return Report{}, err
	}
	if providers[0].OperationID != history.Operation.ID || providers[1].OperationID != history.Operation.ID ||
		payment.OperationID != history.Operation.ID {
		return Report{}, errors.New("provider evidence refers to different Operation identities")
	}
	return Report{
		Valid: true, GitRevision: provenance.GitRevision, Accelerator: result.Accelerator,
		GuestKernel: guestKernel, HistorySequence: history.State.History.Sequence,
		OperationID: history.Operation.ID, SandboxGenerations: 2,
		ProviderDeliveries: len(providers), ProviderCommits: 1,
		SnapshotLoadedPaused: true, ReplacementBeforeResume: true,
		GuestCredentialFree: true, GuestProviderFree: true,
	}, nil
}

func checkDirectory(directory string) error {
	info, err := os.Stat(directory)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode().Perm()&0o077 != 0 {
		return errors.New("VM evidence must be a private directory")
	}
	entries, err := os.ReadDir(directory)
	if err != nil {
		return err
	}
	allowed := make(map[string]bool, len(manifestFiles)+2)
	for _, name := range manifestFiles {
		allowed[name] = true
	}
	allowed["SHA256SUMS"] = true
	allowed["host.head.lock"] = true
	for _, entry := range entries {
		if !allowed[entry.Name()] {
			return fmt.Errorf("unexpected VM evidence entry %q", entry.Name())
		}
		if entry.Name() == "host.head.lock" || entry.Name() == "SHA256SUMS" {
			info, err := os.Lstat(filepath.Join(directory, entry.Name()))
			if err != nil {
				return err
			}
			if !info.Mode().IsRegular() || info.Mode().Perm()&0o077 != 0 {
				return errors.New("host.head.lock is not a private regular file")
			}
		}
	}
	return nil
}

func checkManifest(directory string) error {
	data, err := os.ReadFile(filepath.Join(directory, "SHA256SUMS"))
	if err != nil {
		return err
	}
	lines := strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
	if len(lines) != len(manifestFiles) {
		return fmt.Errorf("SHA256SUMS has %d entries, want %d", len(lines), len(manifestFiles))
	}
	wanted := append([]string(nil), manifestFiles...)
	sort.Strings(wanted)
	for index, line := range lines {
		parts := strings.Split(line, "  ")
		if len(parts) != 2 || parts[1] != wanted[index] || !validDigest(parts[0]) {
			return fmt.Errorf("invalid SHA256SUMS entry %q", line)
		}
		path := filepath.Join(directory, parts[1])
		info, err := os.Lstat(path)
		if err != nil {
			return err
		}
		if !info.Mode().IsRegular() || info.Mode().Perm()&0o077 != 0 {
			return fmt.Errorf("evidence file %q is not a private regular file", parts[1])
		}
		actual, err := hashFile(path)
		if err != nil {
			return err
		}
		if actual != parts[0] {
			return fmt.Errorf("evidence file %q has SHA-256 %s, want %s", parts[1], actual, parts[0])
		}
	}
	return nil
}

func checkProvenance(value provenanceFile) error {
	if value.Schema != 1 || value.Accelerator != "kvm" || value.PublicEntrypoint != "make runtime-vm-demo" ||
		value.SourceState != "git" || !value.SelectedSourceClean || !value.KVMDeviceReadWrite {
		return fmt.Errorf("invalid VM provenance: %+v", value)
	}
	decodedRevision, err := hex.DecodeString(value.GitRevision)
	if err != nil || len(decodedRevision) != 20 || hex.EncodeToString(decodedRevision) != value.GitRevision {
		return errors.New("VM provenance has an invalid git revision")
	}
	if value.ReproductionCommand != "make runtime-vm-demo VM_ACCEL=kvm VM_DEMO_ARGS=-keep" ||
		strings.Join(value.RunnerArguments, " ") != "-accel kvm -keep" || value.GoVersion == "" || value.HostUname == "" ||
		!equalStrings(value.SelectedSourcePaths, expectedSelectedSourcePaths) {
		return errors.New("VM provenance does not retain the public invocation and host versions")
	}
	if _, err := time.Parse(time.RFC3339Nano, value.RecordedAt); err != nil {
		return errors.New("VM provenance has an invalid recording time")
	}
	if len(value.HostTools) != 3 {
		return errors.New("VM provenance does not retain all host tools")
	}
	wantedTools := map[string]bool{"qemu-system-x86_64": true, "qemu-img": true, "nc": true}
	for _, tool := range value.HostTools {
		if !wantedTools[tool.Name] || !filepath.IsAbs(tool.Path) || !validDigest(tool.SHA256) {
			return fmt.Errorf("invalid host tool provenance: %+v", tool)
		}
		delete(wantedTools, tool.Name)
	}
	if len(wantedTools) != 0 {
		return errors.New("VM provenance repeats or omits a host tool")
	}
	rootOutput, err := exec.Command("git", "rev-parse", "--show-toplevel").CombinedOutput()
	if err != nil {
		return fmt.Errorf("locate verifier checkout: %w: %s", err, rootOutput)
	}
	root := strings.TrimSpace(string(rootOutput))
	headOutput, err := exec.Command("git", "-C", root, "rev-parse", "HEAD").CombinedOutput()
	if err != nil || strings.TrimSpace(string(headOutput)) != value.GitRevision {
		return errors.New("verifier checkout differs from the retained git revision")
	}
	statusArguments := []string{"-C", root, "status", "--porcelain", "--untracked-files=all", "--"}
	statusArguments = append(statusArguments, expectedSelectedSourcePaths...)
	statusOutput, err := exec.Command("git", statusArguments...).CombinedOutput()
	if err != nil || strings.TrimSpace(string(statusOutput)) != "" {
		return fmt.Errorf("verifier checkout has changed selected sources: %s", statusOutput)
	}
	return nil
}

func checkGuest(value guestOperation, encoded, script []byte) (guestFacts, error) {
	if value.CallID != "vm/job-1/write" || value.Kind != "vm-write" || string(value.Body) != `{"job":"job-1","value":42}` {
		return guestFacts{}, fmt.Errorf("unexpected injected guest Operation: %+v", value)
	}
	compact := bytes.TrimSpace(encoded)
	port, err := directCanaryPort(script)
	if err != nil {
		return guestFacts{}, err
	}
	wanted := expectedGuestScript(base64.StdEncoding.EncodeToString(compact), port)
	if !bytes.Equal(script, []byte(wanted)) {
		return guestFacts{}, errors.New("guest script differs from the fixed credential-free contract")
	}
	userData := expectedUserData(wanted)
	return guestFacts{
		DirectCanaryPort: port,
		ScriptSHA256:     dataSHA256(script),
		UserDataSHA256:   dataSHA256([]byte(userData)),
	}, nil
}

func directCanaryPort(script []byte) (int, error) {
	const prefix = "if curl -fsS --connect-timeout 2 --max-time 3 http://10.0.2.2:"
	const suffix = "/v1/stats >/dev/null; then"
	text := string(script)
	start := strings.Index(text, prefix)
	if start == -1 || strings.Count(text, prefix) != 1 {
		return 0, errors.New("guest script lacks one direct-host canary")
	}
	start += len(prefix)
	end := strings.Index(text[start:], suffix)
	if end <= 0 {
		return 0, errors.New("guest script has an invalid direct-host canary")
	}
	port, err := strconv.Atoi(text[start : start+end])
	if err != nil || port < 1 || port > 65535 {
		return 0, errors.New("guest script has an invalid direct-host canary port")
	}
	return port, nil
}

func expectedUserData(script string) string {
	return "#cloud-config\n" +
		"write_files:\n" +
		"  - path: /usr/local/sbin/safe-change-guest\n" +
		"    owner: root:root\n" +
		"    permissions: '0700'\n" +
		"    encoding: b64\n" +
		"    content: " + base64.StdEncoding.EncodeToString([]byte(script)) + "\n" +
		"runcmd:\n" +
		"  - [bash, -lc, /usr/local/sbin/safe-change-guest]\n"
}

func expectedGuestScript(encodedRequest string, directCanaryPort int) string {
	return fmt.Sprintf(`#!/usr/bin/env bash
set -uo pipefail
log_marker() { printf '%%s\n' "$1" > /dev/ttyS0; }
log_marker "SAFE_CHANGE_VM_READY kernel=$(uname -r)"
until curl -fsS --connect-timeout 2 --max-time 3 http://10.0.2.100:8000/go >/dev/null; do sleep 1; done
if curl -fsS --connect-timeout 2 --max-time 3 http://10.0.2.2:%d/v1/stats >/dev/null; then
  log_marker SAFE_CHANGE_VM_DIRECT_BYPASS_REACHABLE
  /sbin/poweroff -f
  exit 1
fi
log_marker SAFE_CHANGE_VM_DIRECT_BYPASS_BLOCKED
printf '%%s' '%s' | base64 -d > /run/safe-change-execute.json
status=$(curl -sS --max-time 45 -o /run/safe-change-response.json -w '%%{http_code}' \
	-X POST -H 'Content-Type: application/json' \
	--data-binary @/run/safe-change-execute.json http://10.0.2.100:8787/v1/execute) || status=transport-error
phase=$(python3 -c 'import json; d=json.load(open("/run/safe-change-response.json")); print((d.get("outcome") or d).get("phase", ""))' 2>/dev/null || true)
if [[ "$status" == 409 && "$phase" == unknown ]]; then
  log_marker SAFE_CHANGE_VM_FIRST_UNKNOWN
  sync
  while true; do sleep 60; done
fi
if [[ "$status" == 200 && "$phase" == succeeded ]]; then
  log_marker SAFE_CHANGE_VM_RESTORED_SUCCEEDED
  sync
  /sbin/poweroff -f
  exit 0
fi
log_marker "SAFE_CHANGE_VM_UNEXPECTED status=$status phase=$phase"
/sbin/poweroff -f
exit 1
`, directCanaryPort, encodedRequest)
}

func checkGuestNetworkTrace(path string, guest guestFacts) (metadataFacts, error) {
	records, err := readTrace(path)
	if err != nil {
		return metadataFacts{}, err
	}
	if len(records) < 2 || records[0].Event != "direct-host-canary-listening" ||
		records[0].Direction != "" || len(records[0].Payload) != 0 {
		return metadataFacts{}, errors.New("guest network trace lacks the direct-host canary")
	}
	var canary canaryDetails
	if err := decodeStrict(records[0].Details, &canary); err != nil {
		return metadataFacts{}, err
	}
	canaryHost, canaryPort, err := net.SplitHostPort(canary.Address)
	if err != nil || net.ParseIP(canaryHost) == nil || !net.ParseIP(canaryHost).IsLoopback() ||
		strconv.Itoa(guest.DirectCanaryPort) != canaryPort {
		return metadataFacts{}, errors.New("guest script differs from the recorded direct-host canary")
	}
	facts := metadataFacts{DirectCanaryAddress: canary.Address, DirectCanaryTimeNS: records[0].TimeNS}
	phase := 0
	userDataCount := 0
	for index, record := range records[1:] {
		if record.Direction != "" || len(record.Payload) != 0 {
			return metadataFacts{}, fmt.Errorf("invalid guest metadata record %d", index+2)
		}
		switch record.Event {
		case "guest-user-data-served":
			if phase != 0 {
				return metadataFacts{}, errors.New("guest user-data was served after the Operation gate changed")
			}
			var details metadataDetails
			if err := decodeStrict(record.Details, &details); err != nil {
				return metadataFacts{}, err
			}
			host, _, err := net.SplitHostPort(details.Address)
			if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() ||
				details.Method != httpMethodGet || details.Path != "/user-data" ||
				details.GuestScriptSHA256 != guest.ScriptSHA256 || details.UserDataSHA256 != guest.UserDataSHA256 {
				return metadataFacts{}, fmt.Errorf("guest metadata differs from the retained guest contract: %+v", details)
			}
			if userDataCount == 0 {
				facts.Address, facts.TimeNS = details.Address, record.TimeNS
			} else if details.Address != facts.Address {
				return metadataFacts{}, errors.New("guest metadata was served by different endpoints")
			}
			userDataCount++
		case "guest-operation-gate-opened":
			if phase != 0 || userDataCount == 0 || len(record.Details) != 0 {
				return metadataFacts{}, errors.New("guest Operation gate opened out of order")
			}
			facts.GateOpenTimeNS = record.TimeNS
			phase = 1
		case "guest-operation-gate-served":
			if phase != 1 || len(record.Details) != 0 {
				return metadataFacts{}, errors.New("guest Operation gate was served out of order")
			}
			facts.GateServedTimeNS = record.TimeNS
			phase = 2
		default:
			return metadataFacts{}, fmt.Errorf("unexpected guest network event %q", record.Event)
		}
	}
	if phase != 2 {
		return metadataFacts{}, errors.New("guest network trace does not prove the saved-before-Operation gate")
	}
	return facts, nil
}

const httpMethodGet = "GET"

func checkDiskImage(directory string, provenance provenanceFile) error {
	toolPath, err := exec.LookPath("qemu-img")
	if err != nil {
		return fmt.Errorf("locate qemu-img for evidence inspection: %w", err)
	}
	toolDigest, err := hashFile(toolPath)
	if err != nil {
		return err
	}
	var recordedToolDigest string
	for _, tool := range provenance.HostTools {
		if tool.Name == "qemu-img" {
			recordedToolDigest = tool.SHA256
		}
	}
	if recordedToolDigest != toolDigest {
		return errors.New("current qemu-img differs from the retained tool provenance")
	}
	cacheDirectory, err := os.UserCacheDir()
	if err != nil {
		return fmt.Errorf("locate verifier cache: %w", err)
	}
	expectedBacking := filepath.Join(
		cacheDirectory, "safe-change-runtime", "images", "ubuntu-24.04-20260725-amd64.img",
	)
	imagePath := filepath.Join(directory, "guest.qcow2")
	if err := checkQCOWBackingReference(imagePath, expectedBacking); err != nil {
		return err
	}
	backingInfo, err := os.Lstat(expectedBacking)
	if err != nil || !backingInfo.Mode().IsRegular() || backingInfo.Size() != expectedBaseImageSize ||
		backingInfo.Mode().Perm()&0o077 != 0 {
		return fmt.Errorf("qcow2 backing image is not the private pinned regular file: %v", err)
	}
	resolvedBacking, err := filepath.EvalSymlinks(expectedBacking)
	if err != nil || resolvedBacking != expectedBacking {
		return errors.New("qcow2 backing image path contains a symbolic link")
	}
	baseDigest, err := hashFile(expectedBacking)
	if err != nil {
		return fmt.Errorf("hash qcow2 backing image: %w", err)
	}
	if baseDigest != expectedBaseImageSHA {
		return fmt.Errorf("qcow2 backing image has SHA-256 %s, want %s", baseDigest, expectedBaseImageSHA)
	}
	infoContext, cancelInfo := context.WithTimeout(context.Background(), qemuImageToolTimeout)
	defer cancelInfo()
	infoOutput, err := exec.CommandContext(infoContext, toolPath, "info", "--output=json", imagePath).Output()
	if err != nil {
		if errors.Is(infoContext.Err(), context.DeadlineExceeded) {
			return errors.New("qemu-img info exceeded its 30-second deadline")
		}
		return fmt.Errorf("inspect guest qcow2: %w", err)
	}
	var info qemuImageInfo
	if err := json.Unmarshal(infoOutput, &info); err != nil {
		return fmt.Errorf("decode qemu-img info: %w", err)
	}
	if info.Format != "qcow2" || info.VirtualSize != 8<<30 || info.ActualSize <= 64<<20 ||
		info.Filename != imagePath || info.BackingFilenameFormat != "qcow2" ||
		filepath.Clean(info.BackingFilename) != expectedBacking || info.Dirty || info.FormatSpecific.Data.Corrupt ||
		len(info.Snapshots) != 1 || info.Snapshots[0].ID == "" ||
		info.Snapshots[0].Name != "before_operation" || info.Snapshots[0].VMStateSize <= 64<<20 {
		return fmt.Errorf("guest qcow2 lacks the retained full-VM snapshot: %+v", info)
	}
	checkContext, cancelCheck := context.WithTimeout(context.Background(), qemuImageToolTimeout)
	defer cancelCheck()
	checkOutput, err := exec.CommandContext(checkContext, toolPath, "check", "--output=json", imagePath).Output()
	if err != nil {
		if errors.Is(checkContext.Err(), context.DeadlineExceeded) {
			return errors.New("qemu-img check exceeded its 30-second deadline")
		}
		return fmt.Errorf("check guest qcow2: %w", err)
	}
	var checked qemuImageCheck
	if err := json.Unmarshal(checkOutput, &checked); err != nil {
		return fmt.Errorf("decode qemu-img check: %w", err)
	}
	if checked.CheckErrors != 0 || checked.Corruptions != 0 || checked.Leaks != 0 ||
		checked.TotalClusters <= 0 || checked.AllocatedClusters <= 0 {
		return fmt.Errorf("qemu-img rejected the retained guest qcow2: %+v", checked)
	}
	return nil
}

func checkQCOWBackingReference(imagePath, expectedBacking string) error {
	file, err := os.Open(imagePath)
	if err != nil {
		return err
	}
	defer file.Close()
	header := make([]byte, 104)
	if _, err := io.ReadFull(file, header); err != nil {
		return errors.New("guest disk lacks a complete qcow2 v3 header")
	}
	if !bytes.Equal(header[:4], []byte{'Q', 'F', 'I', 0xfb}) ||
		binary.BigEndian.Uint32(header[4:8]) != 3 ||
		binary.BigEndian.Uint32(header[20:24]) != 16 ||
		binary.BigEndian.Uint32(header[32:36]) != 0 ||
		binary.BigEndian.Uint64(header[72:80]) != 0 ||
		binary.BigEndian.Uint32(header[100:104]) != 112 {
		return errors.New("guest disk has an unsupported qcow2 header or external feature")
	}
	backingOffset := binary.BigEndian.Uint64(header[8:16])
	backingSize := binary.BigEndian.Uint32(header[16:20])
	imageInfo, err := file.Stat()
	if err != nil {
		return err
	}
	if backingOffset < 112 || backingSize != uint32(len(expectedBacking)) ||
		backingOffset > uint64(imageInfo.Size()) ||
		uint64(backingSize) > uint64(imageInfo.Size())-backingOffset {
		return errors.New("guest disk has an invalid qcow2 backing reference")
	}
	backingName := make([]byte, backingSize)
	if _, err := file.ReadAt(backingName, int64(backingOffset)); err != nil {
		return err
	}
	if string(backingName) != expectedBacking {
		return errors.New("guest disk does not name the pinned backing image")
	}
	return nil
}

func checkQEMULog(path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	if len(data) != 0 {
		return fmt.Errorf("QEMU emitted unexpected diagnostics: %q", string(data))
	}
	return nil
}

func checkQEMU(value qemuCommandFile, accelerator string) error {
	if value.Schema != 1 || value.Executable != "qemu-system-x86_64" || accelerator != "kvm" {
		return errors.New("invalid QEMU command envelope")
	}
	options, err := qemuOptions(value.Arguments)
	if err != nil {
		return err
	}
	if options["-machine"] != "q35" || options["-m"] != "1024" || options["-smp"] != "2" ||
		options["-name"] != "safe-change-vm" || options["-nic"] != "none" ||
		options["-accel"] != "kvm" || options["-monitor"] != "none" ||
		options["-display"] != "none" || options["-no-reboot"] != "" ||
		options["-drive"] != "file=<vm-evidence>/guest.qcow2,if=virtio,format=qcow2,cache=none" ||
		options["-serial"] != "file:<vm-evidence>/guest.serial.log" ||
		options["-qmp"] != "unix:<vm-evidence>/qmp.sock,server=on,wait=off" ||
		options["-device"] != "virtio-net-pci,netdev=opnet" ||
		options["-smbios"] != "type=1,serial=ds=nocloud;s=http://10.0.2.100:8000/" || len(options) != 15 {
		return fmt.Errorf("unexpected QEMU isolation options: %+v", options)
	}
	netdev := options["-netdev"]
	if !strings.Contains(netdev, "restrict=on") || strings.Count(netdev, "guestfwd=") != 2 ||
		strings.Contains(netdev, "hostfwd=") || strings.Contains(netdev, "/v1/charge") ||
		!strings.HasPrefix(netdev, "user,id=opnet,") || strings.Count(netdev, "/usr/bin/nc 127.0.0.1 ") != 2 {
		return fmt.Errorf("unexpected QEMU network boundary %q", netdev)
	}
	if !strings.Contains(netdev, "10.0.2.100:8000") || !strings.Contains(netdev, "10.0.2.100:8787") {
		return errors.New("QEMU network omits a required fixed guest forward")
	}
	return nil
}

func qemuOptions(arguments []string) (map[string]string, error) {
	options := make(map[string]string)
	for index := 0; index < len(arguments); index++ {
		argument := arguments[index]
		if !strings.HasPrefix(argument, "-") {
			return nil, fmt.Errorf("unexpected positional QEMU argument %q", argument)
		}
		if index+1 >= len(arguments) || strings.HasPrefix(arguments[index+1], "-") {
			options[argument] = ""
			continue
		}
		if _, duplicate := options[argument]; duplicate {
			return nil, fmt.Errorf("QEMU option %q is repeated", argument)
		}
		options[argument] = arguments[index+1]
		index++
	}
	return options, nil
}

func checkQMP(path string) (qmpFacts, error) {
	records, err := readTrace(path)
	if err != nil {
		return qmpFacts{}, err
	}
	facts := qmpFacts{
		ResponseTimes: make(map[string]int64), Paused: make(map[string]bool),
		Returns: make(map[string]json.RawMessage),
	}
	commandIDs := make(map[string]bool)
	for _, record := range records {
		if record.Direction == "" || len(record.Payload) == 0 || record.Event != "" || len(record.Details) != 0 {
			return qmpFacts{}, fmt.Errorf("invalid QMP trace record %d", record.Sequence)
		}
		if err := rejectDuplicateJSONKeys(record.Payload); err != nil {
			return qmpFacts{}, err
		}
		var payload qmpPayload
		if err := json.Unmarshal(record.Payload, &payload); err != nil {
			return qmpFacts{}, err
		}
		switch record.Direction {
		case "client_to_server":
			if payload.Execute == "" || payload.ID == "" {
				return qmpFacts{}, fmt.Errorf("QMP client record %d lacks command identity", record.Sequence)
			}
			if commandIDs[payload.ID] {
				return qmpFacts{}, fmt.Errorf("QMP command ID %q is repeated", payload.ID)
			}
			commandIDs[payload.ID] = true
			facts.Commands = append(facts.Commands, qmpCommand{
				Name: payload.Execute, ID: payload.ID, CommandLine: payload.Arguments.CommandLine, TimeNS: record.TimeNS,
			})
		case "server_to_client":
			if payload.ID != "" {
				if !commandIDs[payload.ID] {
					return qmpFacts{}, fmt.Errorf("QMP response names unknown command %q", payload.ID)
				}
				if _, duplicate := facts.ResponseTimes[payload.ID]; duplicate {
					return qmpFacts{}, fmt.Errorf("QMP command %q has repeated responses", payload.ID)
				}
				if len(payload.Error) != 0 || len(payload.Return) == 0 {
					return qmpFacts{}, fmt.Errorf("QMP command %q did not return successfully", payload.ID)
				}
				facts.ResponseTimes[payload.ID] = record.TimeNS
				facts.Returns[payload.ID] = append(json.RawMessage(nil), payload.Return...)
				if len(payload.Return) != 0 && payload.Return[0] == '{' {
					var status struct {
						Status  string `json:"status"`
						Running bool   `json:"running"`
					}
					if err := json.Unmarshal(payload.Return, &status); err == nil && status.Status != "" {
						facts.Paused[payload.ID] = status.Status == "paused" && !status.Running
					}
				}
			}
		default:
			return qmpFacts{}, fmt.Errorf("invalid QMP direction %q", record.Direction)
		}
	}
	expected := []struct {
		name    string
		command string
	}{
		{name: "qmp_capabilities"}, {name: "stop"}, {name: "query-status"},
		{name: "human-monitor-command", command: "savevm before_operation"}, {name: "cont"},
		{name: "stop"}, {name: "query-status"},
		{name: "human-monitor-command", command: "loadvm before_operation"},
		{name: "query-status"}, {name: "cont"},
	}
	if len(facts.Commands) != len(expected) {
		return qmpFacts{}, fmt.Errorf("QMP has %d commands, want %d", len(facts.Commands), len(expected))
	}
	for index, want := range expected {
		actual := facts.Commands[index]
		if actual.Name != want.name || actual.CommandLine != want.command || facts.ResponseTimes[actual.ID] <= actual.TimeNS {
			return qmpFacts{}, fmt.Errorf("unexpected QMP command %d: %+v", index, actual)
		}
		if index+1 < len(facts.Commands) && facts.Commands[index+1].TimeNS <= facts.ResponseTimes[actual.ID] {
			return qmpFacts{}, fmt.Errorf("QMP command %d began before command %d completed", index+1, index)
		}
	}
	for _, index := range []int{2, 6, 8} {
		if !facts.Paused[facts.Commands[index].ID] {
			return qmpFacts{}, fmt.Errorf("QMP query-status %d did not prove a paused VM", index)
		}
	}
	for _, index := range []int{0, 1, 4, 5, 9} {
		if string(facts.Returns[facts.Commands[index].ID]) != "{}" {
			return qmpFacts{}, fmt.Errorf("QMP command %d has an unexpected return value", index)
		}
	}
	for _, index := range []int{3, 7} {
		if string(facts.Returns[facts.Commands[index].ID]) != `""` {
			return qmpFacts{}, fmt.Errorf("QMP HMP command %d reported an error string", index)
		}
	}
	return facts, nil
}

func checkSupervisor(path string) (supervisorFacts, error) {
	records, err := readTrace(path)
	if err != nil {
		return supervisorFacts{}, err
	}
	expected := []string{
		"rule-and-sandbox-cutover", "sandbox-endpoint-bound", "snapshot-save-paused",
		"first-operation-unknown", "restore-pause-confirmed", "old-sandbox-endpoint-closed",
		"snapshot-loaded-paused", "rule-and-sandbox-cutover", "old-sandbox-generation-rejected",
		"sandbox-endpoint-bound", "restored-operation-succeeded",
	}
	if len(records) != len(expected) {
		return supervisorFacts{}, fmt.Errorf("host supervisor trace has %d records, want %d", len(records), len(expected))
	}
	facts := supervisorFacts{Times: make(map[string][]int64)}
	for index, record := range records {
		if record.Event != expected[index] || record.Direction != "" || len(record.Payload) != 0 {
			return supervisorFacts{}, fmt.Errorf("unexpected host supervisor record %d: %+v", index+1, record)
		}
		facts.Times[record.Event] = append(facts.Times[record.Event], record.TimeNS)
		switch index {
		case 0, 1, 5, 7, 8, 9:
			var details traceBindingDetails
			if err := decodeStrict(record.Details, &details); err != nil {
				return supervisorFacts{}, err
			}
			switch index {
			case 0:
				facts.FirstBinding = details.Binding
				if details.HistorySequence != 1 {
					return supervisorFacts{}, errors.New("first cutover did not produce History sequence 1")
				}
			case 1:
				if !bindingEqual(details.Binding, facts.FirstBinding) {
					return supervisorFacts{}, errors.New("first endpoint binding differs from the first cutover")
				}
				facts.FirstAddress = details.Address
			case 5:
				if details.Address != facts.FirstAddress || !bindingEqual(details.Binding, facts.FirstBinding) {
					return supervisorFacts{}, errors.New("closed endpoint address differs from the first endpoint")
				}
			case 7:
				facts.SecondBinding = details.Binding
				if details.HistorySequence != 5 {
					return supervisorFacts{}, errors.New("second cutover did not produce History sequence 5")
				}
			case 8:
				if details.Reason != control.ErrStaleSandboxBinding.Error() ||
					!bindingEqual(details.Binding, facts.FirstBinding) {
					return supervisorFacts{}, errors.New("old sandbox rejection trace is inconsistent")
				}
			case 9:
				if !bindingEqual(details.Binding, facts.SecondBinding) {
					return supervisorFacts{}, errors.New("replacement endpoint binding differs from the second cutover")
				}
				facts.SecondAddress = details.Address
			}
		case 3:
			var details historySequenceDetails
			if err := decodeStrict(record.Details, &details); err != nil || details.HistorySequence != 4 {
				return supervisorFacts{}, errors.New("first unknown trace did not prove History sequence 4")
			}
			facts.FirstUnknownAt = record.TimeNS
		case 10:
			var details historySequenceDetails
			if err := decodeStrict(record.Details, &details); err != nil || details.HistorySequence != 7 {
				return supervisorFacts{}, errors.New("restored success trace did not prove History sequence 7")
			}
			facts.RestoredAt = record.TimeNS
		default:
			if len(record.Details) != 0 {
				return supervisorFacts{}, fmt.Errorf("host supervisor record %d has unexpected details", index+1)
			}
		}
	}
	if facts.FirstBinding.SandboxID == "" || facts.FirstBinding.SandboxID != facts.SecondBinding.SandboxID ||
		facts.FirstBinding.Domain != facts.SecondBinding.Domain || facts.FirstBinding.Generation != 1 ||
		facts.SecondBinding.Generation != 2 || facts.FirstBinding.HostInstanceID == facts.SecondBinding.HostInstanceID ||
		facts.FirstAddress == "" || facts.FirstAddress != facts.SecondAddress {
		return supervisorFacts{}, errors.New("host supervisor did not replace one sandbox with a fresh generation on the same endpoint")
	}
	return facts, nil
}

func checkProviderTrace(path string) ([]providerFact, error) {
	records, err := readTrace(path)
	if err != nil {
		return nil, err
	}
	if len(records) != 2 {
		return nil, fmt.Errorf("provider trace has %d deliveries, want 2", len(records))
	}
	providers := make([]providerFact, len(records))
	for index, record := range records {
		if record.Event != "provider-request-received" || record.Direction != "" || len(record.Payload) != 0 {
			return nil, fmt.Errorf("invalid provider trace record %d", index+1)
		}
		if err := decodeStrict(record.Details, &providers[index].providerDetails); err != nil {
			return nil, err
		}
		providers[index].TimeNS = record.TimeNS
		if providers[index].Method != "POST" || providers[index].Path != "/v1/charge" || providers[index].OperationID == "" {
			return nil, fmt.Errorf("unexpected provider delivery %+v", providers[index])
		}
	}
	if providers[0].OperationID != providers[1].OperationID {
		return nil, errors.New("provider deliveries use different Operation identities")
	}
	return providers, nil
}

func checkTimeline(qmp qmpFacts, supervisor supervisorFacts, providers []providerFact, metadata metadataFacts) error {
	commands := qmp.Commands
	firstPaused := qmp.ResponseTimes[commands[2].ID]
	secondPaused := qmp.ResponseTimes[commands[6].ID]
	loadedPaused := qmp.ResponseTimes[commands[8].ID]
	firstProviderTimes := supervisor.Times["first-operation-unknown"]
	cutovers := supervisor.Times["rule-and-sandbox-cutover"]
	endpoints := supervisor.Times["sandbox-endpoint-bound"]
	if len(firstProviderTimes) != 1 || len(cutovers) != 2 || len(endpoints) != 2 {
		return errors.New("host trace is missing required lifecycle events")
	}
	ordered := []int64{
		metadata.DirectCanaryTimeNS,
		cutovers[0],
		endpoints[0],
		commands[0].TimeNS,
		qmp.ResponseTimes[commands[0].ID],
		metadata.TimeNS,
		commands[1].TimeNS,
		firstPaused,
		supervisor.Times["snapshot-save-paused"][0],
		commands[3].TimeNS,
		qmp.ResponseTimes[commands[3].ID],
		metadata.GateOpenTimeNS,
		commands[4].TimeNS,
		qmp.ResponseTimes[commands[4].ID],
		providers[0].TimeNS,
		supervisor.FirstUnknownAt,
		commands[5].TimeNS,
		secondPaused,
		supervisor.Times["restore-pause-confirmed"][0],
		supervisor.Times["old-sandbox-endpoint-closed"][0],
		commands[7].TimeNS,
		qmp.ResponseTimes[commands[7].ID],
		commands[8].TimeNS,
		loadedPaused,
		supervisor.Times["snapshot-loaded-paused"][0],
		cutovers[1],
		supervisor.Times["old-sandbox-generation-rejected"][0],
		endpoints[1],
		commands[9].TimeNS,
		qmp.ResponseTimes[commands[9].ID],
		providers[1].TimeNS,
		supervisor.RestoredAt,
	}
	for index := 1; index < len(ordered); index++ {
		if ordered[index-1] <= 0 || ordered[index] <= ordered[index-1] {
			return fmt.Errorf("VM lifecycle is not strictly ordered at step %d: %v", index, ordered)
		}
	}
	if metadata.GateServedTimeNS <= commands[4].TimeNS || metadata.GateServedTimeNS >= providers[0].TimeNS {
		return errors.New("guest Operation gate was not served after resume and before provider delivery")
	}
	return nil
}

func checkHistory(directory string, guest guestOperation) (historyFacts, error) {
	temporary, err := os.MkdirTemp("", "safe-change-vm-check-")
	if err != nil {
		return historyFacts{}, err
	}
	defer os.RemoveAll(temporary)
	historyPath := filepath.Join(temporary, "host.history")
	anchorPath := filepath.Join(temporary, "host.head")
	if err := copyFile(filepath.Join(directory, "host.history"), historyPath); err != nil {
		return historyFacts{}, err
	}
	if err := copyFile(filepath.Join(directory, "host.head"), anchorPath); err != nil {
		return historyFacts{}, err
	}
	controller, err := control.OpenWithAnchor(historyPath, anchorPath)
	if err != nil {
		return historyFacts{}, fmt.Errorf("replay retained History and head: %w", err)
	}
	state, bindings := controller.SnapshotWithSandboxBindings()
	events := controller.Events()
	if err := controller.Close(); err != nil {
		return historyFacts{}, err
	}
	expectedEvents := []string{
		"rule.bindings.cutover", "operation.prepared", "operation.phase", "operation.phase",
		"rule.bindings.cutover", "operation.phase", "operation.phase",
	}
	if len(events) != len(expectedEvents) || state.History.Sequence != 7 || len(bindings) != 1 || len(state.Operations) != 1 {
		return historyFacts{}, errors.New("retained History has an unexpected final shape")
	}
	for index, event := range events {
		if event.Sequence != uint64(index+1) || event.Operation != expectedEvents[index] {
			return historyFacts{}, fmt.Errorf("unexpected History event %d: %+v", index+1, event)
		}
	}
	var firstCutover, secondCutover cutoverEvent
	if err := decodeStrict(events[0].Data, &firstCutover); err != nil {
		return historyFacts{}, err
	}
	if err := decodeStrict(events[4].Data, &secondCutover); err != nil {
		return historyFacts{}, err
	}
	if firstCutover.SemanticVersion != 1 || secondCutover.SemanticVersion != 1 ||
		firstCutover.Certificate.Requirement.ID != "vm-restore-v1" ||
		secondCutover.Certificate.Requirement.ID != "vm-restore-v2" ||
		len(firstCutover.Bindings) != 1 || len(secondCutover.Bindings) != 1 {
		return historyFacts{}, errors.New("retained cutover events are inconsistent")
	}
	firstBinding, secondBinding := firstCutover.Bindings[0], secondCutover.Bindings[0]
	if firstBinding.Generation != 1 || secondBinding.Generation != 2 ||
		firstBinding.SandboxID != secondBinding.SandboxID || firstBinding.Domain != secondBinding.Domain ||
		firstBinding.HostInstanceID == secondBinding.HostInstanceID ||
		!bindingEqual(secondBinding, bindings[0]) {
		return historyFacts{}, errors.New("retained History does not contain two fresh sandbox generations")
	}
	var prepared prepareEvent
	if err := decodeStrict(events[1].Data, &prepared); err != nil {
		return historyFacts{}, err
	}
	if prepared.SemanticVersion != 1 {
		return historyFacts{}, errors.New("prepared Operation has an unsupported semantic version")
	}
	operation := prepared.Operation
	expectedOperationID := deriveOperationID(firstBinding.Domain, guest.CallID)
	if operation.ID != expectedOperationID || operation.Domain != firstBinding.Domain || operation.Kind != guest.Kind ||
		operation.Method != "POST" || !operation.RequestStored || len(operation.RequestHeaders) != 0 ||
		string(operation.RequestBody) != string(guest.Body) || operation.RequestHash != gatewayRequestHash(operation) {
		return historyFacts{}, fmt.Errorf("prepared Operation differs from the guest contract: %+v", operation)
	}
	target, err := url.Parse(operation.Target)
	if err != nil || target.Scheme != "http" || target.Path != "/v1/charge" || target.User != nil || target.Fragment != "" {
		return historyFacts{}, fmt.Errorf("prepared Operation has an invalid provider target %q", operation.Target)
	}
	host, _, err := net.SplitHostPort(target.Host)
	if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() {
		return historyFacts{}, fmt.Errorf("prepared Operation target is not a host loopback service: %q", operation.Target)
	}
	phases := make([]phaseEvent, 0, 4)
	for _, index := range []int{2, 3, 5, 6} {
		var phase phaseEvent
		if err := decodeStrict(events[index].Data, &phase); err != nil {
			return historyFacts{}, err
		}
		if phase.SemanticVersion != 1 || phase.ID != operation.ID {
			return historyFacts{}, errors.New("Operation phase event uses inconsistent identity")
		}
		phases = append(phases, phase)
	}
	expectedPhases := []kernel.Phase{kernel.Dispatched, kernel.Unknown, kernel.Dispatched, kernel.Succeeded}
	for index, phase := range phases {
		if phase.Update.Phase != expectedPhases[index] {
			return historyFacts{}, fmt.Errorf("Operation phase %d is %q, want %q", index, phase.Update.Phase, expectedPhases[index])
		}
	}
	if phases[0].Update.DispatchGeneration != 1 || phases[0].Update.DispatchOwner == "" ||
		phases[2].Update.DispatchGeneration != 2 || phases[2].Update.DispatchOwner != phases[0].Update.DispatchOwner {
		return historyFacts{}, fmt.Errorf(
			"Operation dispatch generations are inconsistent: first=%+v second=%+v",
			phases[0].Update, phases[2].Update,
		)
	}
	final, ok := state.Operations[operation.ID]
	if !ok || final.Phase != kernel.Succeeded || final.Target != operation.Target || final.RequestHash != operation.RequestHash ||
		final.ResultHash == "" || final.RemoteReference == "" || final.DispatchGeneration != 2 ||
		final.StatusCode != 200 ||
		final.DispatchOwner != phases[0].Update.DispatchOwner || state.Rule == nil || state.Rule.Version != 2 ||
		state.Requirement == nil || state.Requirement.ID != "vm-restore-v2" {
		return historyFacts{}, fmt.Errorf("unexpected replayed final State: %+v", state)
	}
	var receipt operationReceipt
	if err := decodeStrict(final.ResultBody, &receipt); err != nil || receipt.Schema != 1 ||
		receipt.OperationID != final.ID || receipt.Outcome != string(kernel.Succeeded) ||
		receipt.ResultHash != final.ResultHash || receipt.RemoteReference != final.RemoteReference {
		return historyFacts{}, fmt.Errorf("final Operation has an invalid provider receipt: %+v: %v", receipt, err)
	}
	return historyFacts{
		State: state, Events: events, FirstBinding: firstBinding, SecondBinding: secondBinding, Operation: final,
	}, nil
}

func checkPayment(path string, operation kernel.Operation) (paymentRecord, error) {
	file, err := os.Open(path)
	if err != nil {
		return paymentRecord{}, err
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	var records []paymentRecord
	for scanner.Scan() {
		var record paymentRecord
		if err := decodeStrict(scanner.Bytes(), &record); err != nil {
			return paymentRecord{}, err
		}
		records = append(records, record)
	}
	if err := scanner.Err(); err != nil {
		return paymentRecord{}, err
	}
	if len(records) != 1 {
		return paymentRecord{}, fmt.Errorf("payment History has %d commits, want 1", len(records))
	}
	record := records[0]
	if record.OperationID != operation.ID || record.ResultHash != operation.ResultHash ||
		record.RemoteReference != operation.RemoteReference || record.Path != "/v1/charge" ||
		record.RequestHash != paymentRequestHash("POST", record.Path, operation.RequestBody) ||
		record.ResultHash != paymentResultHash(operation.ID) ||
		record.RemoteReference != "payment/"+operation.ID || !validDigest(record.ResultHash) {
		return paymentRecord{}, fmt.Errorf("payment commit differs from final Operation: %+v", record)
	}
	return record, nil
}

func crossCheckBindings(supervisor supervisorFacts, retained historyFacts) error {
	if !bindingEqual(supervisor.FirstBinding, retained.FirstBinding) ||
		!bindingEqual(supervisor.SecondBinding, retained.SecondBinding) {
		return errors.New("host supervisor trace differs from durable sandbox bindings")
	}
	return nil
}

func crossCheckNetwork(
	qemu qemuCommandFile,
	supervisor supervisorFacts,
	retained historyFacts,
	metadata metadataFacts,
	guest guestFacts,
) error {
	options, err := qemuOptions(qemu.Arguments)
	if err != nil {
		return err
	}
	endpointHost, endpointPort, err := net.SplitHostPort(supervisor.FirstAddress)
	if err != nil || net.ParseIP(endpointHost) == nil || !net.ParseIP(endpointHost).IsLoopback() {
		return fmt.Errorf("sandbox endpoint is not a loopback address: %q", supervisor.FirstAddress)
	}
	metadataHost, metadataPort, err := net.SplitHostPort(metadata.Address)
	if err != nil || net.ParseIP(metadataHost) == nil || !net.ParseIP(metadataHost).IsLoopback() {
		return fmt.Errorf("guest metadata endpoint is not a loopback address: %q", metadata.Address)
	}
	wantedNetdev := "user,id=opnet,restrict=on," +
		"guestfwd=tcp:10.0.2.100:8000-cmd:/usr/bin/nc " + metadataHost + " " + metadataPort + "," +
		"guestfwd=tcp:10.0.2.100:8787-cmd:/usr/bin/nc " + endpointHost + " " + endpointPort
	if options["-netdev"] != wantedNetdev {
		return errors.New("QEMU network differs from the two recorded host endpoints")
	}
	providerTarget, err := url.Parse(retained.Operation.Target)
	if err != nil {
		return err
	}
	providerHost, providerPort, err := net.SplitHostPort(providerTarget.Host)
	if err != nil {
		return err
	}
	providerForward := "/usr/bin/nc " + providerHost + " " + providerPort
	if strings.Contains(options["-netdev"], providerForward) {
		return errors.New("QEMU network forwards directly to the provider")
	}
	canaryHost, canaryPort, err := net.SplitHostPort(metadata.DirectCanaryAddress)
	if err != nil || strconv.Itoa(guest.DirectCanaryPort) != canaryPort ||
		canaryHost != "127.0.0.1" || canaryPort == providerPort ||
		canaryPort == endpointPort || canaryPort == metadataPort {
		return errors.New("direct-host canary is not a distinct recorded loopback service")
	}
	return nil
}

func checkSerial(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	text := string(data)
	markers := []string{
		"SAFE_CHANGE_VM_READY kernel=", "SAFE_CHANGE_VM_DIRECT_BYPASS_BLOCKED",
		"SAFE_CHANGE_VM_FIRST_UNKNOWN", "SAFE_CHANGE_VM_DIRECT_BYPASS_BLOCKED",
		"SAFE_CHANGE_VM_RESTORED_SUCCEEDED",
	}
	position := 0
	for _, marker := range markers {
		index := strings.Index(text[position:], marker)
		if index == -1 {
			return "", fmt.Errorf("serial console omits ordered marker %q", marker)
		}
		position += index + len(marker)
	}
	if strings.Count(text, "SAFE_CHANGE_VM_READY kernel=") != 1 ||
		strings.Count(text, "SAFE_CHANGE_VM_DIRECT_BYPASS_BLOCKED") != 2 ||
		strings.Count(text, "SAFE_CHANGE_VM_FIRST_UNKNOWN") != 1 ||
		strings.Count(text, "SAFE_CHANGE_VM_RESTORED_SUCCEEDED") != 1 ||
		strings.Contains(text, "SAFE_CHANGE_VM_DIRECT_BYPASS_REACHABLE") ||
		strings.Contains(text, "SAFE_CHANGE_VM_UNEXPECTED") {
		return "", errors.New("serial console contains unexpected guest markers")
	}
	start := strings.Index(text, "SAFE_CHANGE_VM_READY kernel=") + len("SAFE_CHANGE_VM_READY kernel=")
	end := strings.IndexAny(text[start:], "\r\n ")
	if end <= 0 {
		return "", errors.New("serial console lacks a guest kernel version")
	}
	return text[start : start+end], nil
}

func checkSnapshot(path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	text := string(data)
	if strings.Count(text, "before_operation") != 1 || !strings.Contains(text, "Snapshot list:") {
		return errors.New("retained QEMU snapshot list is invalid")
	}
	return nil
}

func crossCheckResult(
	result resultFile,
	provenance provenanceFile,
	retained historyFacts,
	guestKernel string,
	providers []providerFact,
) error {
	if result.EvidenceSchema != 2 || result.Accelerator != provenance.Accelerator || result.Accelerator != "kvm" ||
		result.BaseImageSHA256 != expectedBaseImageSHA || !result.FullLinuxGuest || result.GuestKernel != guestKernel ||
		result.DirectHostCanaryFromGuest != "blocked_before_and_after_restore" ||
		!result.EndpointReboundWhileVMPaused || result.FirstNetworkResult != string(kernel.Unknown) ||
		!result.HistoryOutsideGuestRestoreDomain || !result.HostOwnedRestrictedNetwork ||
		result.InjectedGuestBearerToken || result.InjectedGuestProviderTarget ||
		!result.OldSandboxGenerationRejected || !result.PaymentOutsideGuestRestoreDomain ||
		result.RemoteCommits != 1 || result.RemoteDeliveries != len(providers) ||
		result.RestoredOperation != string(kernel.Succeeded) || result.RuleAndSandboxCutovers != 2 ||
		!result.RunnerCompleted || !result.SnapshotSavedBeforeOperation || !result.WholeVMRestored ||
		result.HostHistorySequence != retained.State.History.Sequence ||
		len(result.HostBoundSandboxGenerations) != 2 || result.HostBoundSandboxGenerations[0] != 1 ||
		result.HostBoundSandboxGenerations[1] != 2 {
		return fmt.Errorf("result.json differs from independently recomputed facts: %+v", result)
	}
	return nil
}

func readTrace(path string) ([]traceRecord, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	buffer := make([]byte, 64<<10)
	scanner.Buffer(buffer, 4<<20)
	var records []traceRecord
	var lastTime int64
	for scanner.Scan() {
		var record traceRecord
		if err := decodeStrict(scanner.Bytes(), &record); err != nil {
			return nil, err
		}
		if record.Sequence != uint64(len(records)+1) || record.TimeNS <= 0 || record.TimeNS < lastTime {
			return nil, fmt.Errorf("trace record %d has invalid sequence or time", len(records)+1)
		}
		lastTime = record.TimeNS
		records = append(records, record)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	if len(records) == 0 {
		return nil, errors.New("evidence trace is empty")
	}
	return records, nil
}

func readStrictJSON(path string, target any) error {
	_, err := readStrictJSONBytes(path, target)
	return err
}

func readStrictJSONBytes(path string, target any) ([]byte, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(data) > 4<<20 {
		return nil, fmt.Errorf("JSON evidence %q exceeds 4 MiB", filepath.Base(path))
	}
	if err := decodeStrict(data, target); err != nil {
		return nil, fmt.Errorf("decode %s: %w", filepath.Base(path), err)
	}
	return data, nil
}

func decodeStrict(data []byte, target any) error {
	if err := rejectDuplicateJSONKeys(data); err != nil {
		return err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("multiple JSON values")
		}
		return err
	}
	return nil
}

func rejectDuplicateJSONKeys(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	var consumeValue func() error
	consumeValue = func() error {
		token, err := decoder.Token()
		if err != nil {
			return err
		}
		delimiter, composite := token.(json.Delim)
		if !composite {
			return nil
		}
		switch delimiter {
		case '{':
			seen := make(map[string]bool)
			for decoder.More() {
				keyToken, err := decoder.Token()
				if err != nil {
					return err
				}
				key, ok := keyToken.(string)
				if !ok {
					return errors.New("JSON object key is not a string")
				}
				if seen[key] {
					return fmt.Errorf("JSON object contains duplicate key %q", key)
				}
				seen[key] = true
				if err := consumeValue(); err != nil {
					return err
				}
			}
			end, err := decoder.Token()
			if err != nil || end != json.Delim('}') {
				return errors.New("JSON object has an invalid terminator")
			}
		case '[':
			for decoder.More() {
				if err := consumeValue(); err != nil {
					return err
				}
			}
			end, err := decoder.Token()
			if err != nil || end != json.Delim(']') {
				return errors.New("JSON array has an invalid terminator")
			}
		default:
			return errors.New("JSON value has an invalid delimiter")
		}
		return nil
	}
	if err := consumeValue(); err != nil {
		return err
	}
	if _, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("multiple JSON values")
		}
		return err
	}
	return nil
}

func copyFile(source, destination string) error {
	input, err := os.Open(source)
	if err != nil {
		return err
	}
	defer input.Close()
	output, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	if _, err := io.Copy(output, input); err != nil {
		_ = output.Close()
		return err
	}
	if err := output.Sync(); err != nil {
		_ = output.Close()
		return err
	}
	return output.Close()
}

func bindingEqual(left, right control.SandboxBinding) bool {
	if left.SandboxID != right.SandboxID || left.Generation != right.Generation ||
		left.HostInstanceID != right.HostInstanceID || left.Domain != right.Domain ||
		len(left.AllowedKinds) != len(right.AllowedKinds) {
		return false
	}
	for index := range left.AllowedKinds {
		if left.AllowedKinds[index] != right.AllowedKinds[index] {
			return false
		}
	}
	return true
}

func equalStrings(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}

func deriveOperationID(domain, callID string) string {
	hash := sha256.New()
	_, _ = hash.Write([]byte("operation-id-v1\x00"))
	_, _ = hash.Write([]byte(domain))
	_, _ = hash.Write([]byte{0})
	_, _ = hash.Write([]byte(callID))
	return "op-" + hex.EncodeToString(hash.Sum(nil))
}

func paymentRequestHash(method, path string, body []byte) string {
	hash := sha256.New()
	_, _ = io.WriteString(hash, method)
	_, _ = hash.Write([]byte{0})
	_, _ = io.WriteString(hash, path)
	_, _ = hash.Write([]byte{0})
	_, _ = hash.Write(body)
	return hex.EncodeToString(hash.Sum(nil))
}

func gatewayRequestHash(operation kernel.Operation) string {
	headers := [][2]string{
		{"accept-encoding", "identity"},
		{"idempotency-key", operation.ID},
		{"user-agent", "safe-change-runtime/1"},
		{"x-operation-id", operation.ID},
	}
	hash := sha256.New()
	_, _ = io.WriteString(hash, operation.Method)
	_, _ = hash.Write([]byte{0})
	_, _ = io.WriteString(hash, operation.Target)
	_, _ = hash.Write([]byte{0})
	for _, header := range headers {
		_, _ = io.WriteString(hash, header[0])
		_, _ = hash.Write([]byte{':'})
		_, _ = io.WriteString(hash, header[1])
		_, _ = hash.Write([]byte{0})
	}
	_, _ = hash.Write(operation.RequestBody)
	return hex.EncodeToString(hash.Sum(nil))
}

func paymentResultHash(operationID string) string {
	digest := sha256.Sum256([]byte("charged\x00" + operationID))
	return hex.EncodeToString(digest[:])
}

func hashFile(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func dataSHA256(data []byte) string {
	digest := sha256.Sum256(data)
	return hex.EncodeToString(digest[:])
}

func validDigest(value string) bool {
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size && hex.EncodeToString(decoded) == value
}
