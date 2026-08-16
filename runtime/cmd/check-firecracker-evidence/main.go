// Command check-firecracker-evidence fail-closes on an incomplete or
// internally inconsistent Firecracker restore evidence directory. Retained
// snapshot and initramfs payloads are required and rehashed; JSON provenance
// alone is not accepted as evidence of the bytes actually loaded by Firecracker.
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const (
	gatePort                   = uint32(8000)
	officialFirecrackerVersion = "1.16.1"
	officialKernelVersion      = "6.1.155"
	officialFirecrackerSHA256  = "2fd0171309af7e24cf8dafc8a6f921c1434c49b5f9349bb996b7ed0a4deb8aa7"
	officialKernelSHA256       = "e20e46d0c36c55c0d1014eb20576171b3f3d922260d9f792017aeff53af3d4f2"
)

type artifact struct {
	Name   string `json:"name"`
	Size   int64  `json:"size"`
	Mode   uint32 `json:"mode"`
	SHA256 string `json:"sha256"`
}
type sealedArtifact struct {
	Artifact   artifact `json:"artifact"`
	ChildFD    int      `json:"child_fd"`
	LinuxSeals int      `json:"linux_seals"`
}
type socket struct {
	Name   string `json:"name"`
	Device uint64 `json:"device"`
	Inode  uint64 `json:"inode"`
	Mode   uint32 `json:"mode"`
	UID    uint32 `json:"uid"`
}
type process struct {
	Generation       uint64 `json:"generation"`
	ID               string `json:"id"`
	PID              int    `json:"pid"`
	Executable       string `json:"executable"`
	ExecutableSHA256 string `json:"executable_sha256"`
	Device           uint64 `json:"device"`
	Inode            uint64 `json:"inode"`
	Start            uint64 `json:"start_time_ticks"`
	StartedNS        int64  `json:"started_time_ns"`
	StoppedNS        int64  `json:"stopped_time_ns"`
	ExitConfirmed    bool   `json:"exit_confirmed"`
	Termination      string `json:"termination"`
	APISocket        socket `json:"api_socket"`
	Vsock            socket `json:"vsock_backend"`
}
type supervisorEvent struct {
	Schema         int                        `json:"schema"`
	Sequence       uint64                     `json:"sequence"`
	Event          string                     `json:"event"`
	TimeNS         int64                      `json:"time_ns"`
	ElapsedNS      int64                      `json:"elapsed_ns"`
	Generation     uint64                     `json:"generation"`
	InstanceID     string                     `json:"instance_id"`
	PID            int                        `json:"pid"`
	StartTimeTicks uint64                     `json:"start_time_ticks"`
	Details        map[string]json.RawMessage `json:"details"`
}
type apiCall struct {
	Sequence uint64          `json:"sequence"`
	TimeNS   int64           `json:"time_ns"`
	Method   string          `json:"method"`
	Path     string          `json:"path"`
	Request  json.RawMessage `json:"request"`
	Status   int             `json:"status"`
	Response json.RawMessage `json:"response"`
	Error    string          `json:"error"`
}
type audit struct {
	Event         string    `json:"event"`
	Time          time.Time `json:"time"`
	Generation    uint64    `json:"generation"`
	Port          uint32    `json:"port"`
	PID           int       `json:"pid"`
	SandboxPID    int       `json:"sandbox_peer_pid"`
	SandboxDevice uint64    `json:"sandbox_device"`
	SandboxInode  uint64    `json:"sandbox_inode"`
	GuestToHost   int64     `json:"guest_to_host_bytes"`
	HostToGuest   int64     `json:"host_to_guest_bytes"`
	Bytes         int       `json:"bytes"`
	Status        int       `json:"status"`
	Error         string    `json:"error"`
}

func main() {
	var directory string
	flag.StringVar(&directory, "evidence", "", "Firecracker evidence directory")
	flag.Parse()
	if directory == "" || flag.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "usage: check-firecracker-evidence -evidence DIR")
		os.Exit(2)
	}
	if err := check(directory); err != nil {
		fmt.Fprintf(os.Stderr, "Firecracker evidence rejected: %v\n", err)
		os.Exit(1)
	}
	_, _ = fmt.Fprintln(os.Stdout, `{"valid":true,"backend":"firecracker"}`)
}

func check(dir string) error {
	if !filepath.IsAbs(dir) || filepath.Clean(dir) != dir {
		return errors.New("evidence directory must be absolute and canonical")
	}
	info, err := os.Lstat(dir)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("evidence directory is not a real directory")
	}
	for _, name := range []string{"result.json", "assets.json", "firecracker-processes.json", "snapshot-provenance.json", "timeline.json", "guest-request.json", "guest-results.json", "firecracker-supervisor.jsonl", "firecracker-api-g1.jsonl", "firecracker-api-g3.jsonl", "firecracker-gate-g1.jsonl", "firecracker-gate-g3.jsonl", "firecracker-relay-g1.jsonl", "firecracker-relay-g3.jsonl", "snapshot.state", "snapshot.memory", "guest-initramfs.cpio"} {
		if _, err := os.Lstat(filepath.Join(dir, name)); err != nil {
			return fmt.Errorf("missing required evidence %s: %w", name, err)
		}
	}
	request, err := os.ReadFile(filepath.Join(dir, "guest-request.json"))
	if err != nil {
		return err
	}
	callID, err := strictRequest(request)
	if err != nil {
		return err
	}
	var assets struct {
		Schema             int              `json:"schema"`
		FirecrackerVersion string           `json:"firecracker_version"`
		SnapshotFormat     string           `json:"snapshot_format"`
		Firecracker        artifact         `json:"firecracker"`
		Kernel             artifact         `json:"kernel"`
		Guest              artifact         `json:"guest"`
		Initramfs          artifact         `json:"initramfs"`
		SealedBootInputs   []sealedArtifact `json:"sealed_boot_inputs"`
		KernelSource       string           `json:"kernel_source"`
	}
	if err := strictFile(filepath.Join(dir, "assets.json"), &assets); err != nil {
		return err
	}
	if err := requireObjectKeys(filepath.Join(dir, "assets.json"), "schema", "firecracker_version", "snapshot_format", "firecracker", "kernel", "guest", "initramfs", "sealed_boot_inputs", "kernel_source"); err != nil {
		return err
	}
	if assets.Schema != 1 || assets.FirecrackerVersion != officialFirecrackerVersion || assets.SnapshotFormat != "v10.0.0" || assets.KernelSource != "official-firecracker-ci-v1.15" || assets.Firecracker.SHA256 != officialFirecrackerSHA256 || assets.Kernel.SHA256 != officialKernelSHA256 {
		return errors.New("assets provenance is incomplete")
	}
	for _, a := range []artifact{assets.Firecracker, assets.Kernel, assets.Guest, assets.Initramfs} {
		if a.Name == "" || a.Size <= 0 || len(a.SHA256) != 64 || a.Mode == 0 {
			return errors.New("assets provenance has an invalid artifact")
		}
	}
	if err := checkSealed(assets.SealedBootInputs, []artifact{assets.Kernel, assets.Initramfs}); err != nil {
		return fmt.Errorf("sealed boot inputs: %w", err)
	}
	if err := checkPayload(filepath.Join(dir, "guest-initramfs.cpio"), assets.Initramfs); err != nil {
		return fmt.Errorf("initramfs payload: %w", err)
	}
	if err := checkInitramfs(filepath.Join(dir, "guest-initramfs.cpio"), assets.Guest, request); err != nil {
		return err
	}
	var processes struct {
		Schema    int       `json:"schema"`
		Processes []process `json:"processes"`
	}
	if err := strictFile(filepath.Join(dir, "firecracker-processes.json"), &processes); err != nil {
		return err
	}
	if processes.Schema != 1 || len(processes.Processes) != 2 {
		return errors.New("evidence must retain exactly two Firecracker processes")
	}
	g1, g3, err := checkProcesses(processes.Processes)
	if err != nil {
		return err
	}
	if g1.ExecutableSHA256 != assets.Firecracker.SHA256 || g3.ExecutableSHA256 != assets.Firecracker.SHA256 {
		return errors.New("process executable hash differs from pinned Firecracker artifact")
	}
	var timeline map[string]int64
	if err := strictFile(filepath.Join(dir, "timeline.json"), &timeline); err != nil {
		return err
	}
	for _, key := range []string{"snapshot_created_ns", "first_relay_armed_ns", "first_vm_resumed_ns", "first_vm_stopped_ns", "restore_loaded_paused_ns", "restored_relay_armed_ns", "restored_vm_resumed_ns", "run_completed_ns"} {
		if timeline[key] <= 0 {
			return fmt.Errorf("timeline lacks %s", key)
		}
	}
	if !(g1.StartedNS < timeline["snapshot_created_ns"] && timeline["snapshot_created_ns"] < timeline["first_relay_armed_ns"] && timeline["first_relay_armed_ns"] < timeline["first_vm_resumed_ns"] && timeline["first_vm_resumed_ns"] < g1.StoppedNS && g1.StartedNS < g1.StoppedNS && g3.StartedNS < g3.StoppedNS && g3.StoppedNS <= timeline["run_completed_ns"] && timeline["snapshot_created_ns"] < timeline["first_vm_stopped_ns"] && timeline["first_vm_stopped_ns"] < g3.StartedNS && g3.StartedNS <= timeline["restore_loaded_paused_ns"] && timeline["restore_loaded_paused_ns"] < timeline["restored_relay_armed_ns"] && timeline["restored_relay_armed_ns"] < timeline["restored_vm_resumed_ns"] && timeline["restored_vm_resumed_ns"] <= timeline["run_completed_ns"]) {
		return errors.New("Firecracker lifecycle timeline is out of order")
	}
	if g1.StoppedNS != timeline["first_vm_stopped_ns"] || g1.StoppedNS >= g3.StartedNS {
		return errors.New("original Firecracker did not stop before successor start")
	}
	var snapshots struct {
		Schema           int              `json:"schema"`
		StateBefore      artifact         `json:"state_before"`
		StateAfter       artifact         `json:"state_after"`
		MemoryBefore     artifact         `json:"memory_before"`
		MemoryAfter      artifact         `json:"memory_after"`
		LoadCount        int              `json:"load_count"`
		OriginalStopped  bool             `json:"original_stopped_before_successor_start"`
		OriginalResumed  bool             `json:"original_resumed_after_snapshot"`
		SealedLoadInputs []sealedArtifact `json:"sealed_load_inputs"`
	}
	if err := strictFile(filepath.Join(dir, "snapshot-provenance.json"), &snapshots); err != nil {
		return err
	}
	if err := requireObjectKeys(filepath.Join(dir, "snapshot-provenance.json"), "schema", "state_before", "state_after", "memory_before", "memory_after", "sealed_load_inputs", "load_count", "original_resumed_after_snapshot", "original_stopped_before_successor_start"); err != nil {
		return err
	}
	if snapshots.Schema != 1 || snapshots.LoadCount != 1 || !snapshots.OriginalStopped || !snapshots.OriginalResumed || snapshots.StateBefore != snapshots.StateAfter || snapshots.MemoryBefore != snapshots.MemoryAfter || snapshots.StateBefore.SHA256 == "" || snapshots.MemoryBefore.SHA256 == "" {
		return errors.New("snapshot provenance does not prove an unchanged single paused load")
	}
	if err := checkSealed(snapshots.SealedLoadInputs, []artifact{snapshots.StateBefore, snapshots.MemoryBefore}); err != nil {
		return fmt.Errorf("sealed load inputs: %w", err)
	}
	if err := checkPayload(filepath.Join(dir, "snapshot.state"), snapshots.StateBefore); err != nil {
		return fmt.Errorf("snapshot state payload: %w", err)
	}
	if err := checkPayload(filepath.Join(dir, "snapshot.memory"), snapshots.MemoryBefore); err != nil {
		return fmt.Errorf("snapshot memory payload: %w", err)
	}
	var result struct {
		Schema               int      `json:"schema"`
		Backend              string   `json:"backend"`
		Accelerator          string   `json:"accelerator"`
		MicroVMs             int      `json:"microvm_processes"`
		Distinct             bool     `json:"distinct_processes"`
		Network              int      `json:"network_interfaces"`
		Drives               int      `json:"root_block_devices"`
		Fields               []string `json:"guest_request_fields"`
		Loads                int      `json:"snapshot_loads"`
		RestoreBeforeResume  bool     `json:"restore_loaded_before_resume"`
		RelayPaused          bool     `json:"relay_armed_while_paused"`
		FirstReused          bool     `json:"first_operation_reused"`
		RestoredReused       bool     `json:"restored_operation_reused"`
		OperationID          string   `json:"operation_id"`
		NestedVirtualization bool     `json:"nested_virtualization"`
		FirecrackerVersion   string   `json:"firecracker_version"`
		GuestKernel          string   `json:"guest_kernel"`
		PIDs                 []int    `json:"firecracker_pids"`
		GuestCID             uint32   `json:"guest_cid"`
		CredentialFree       bool     `json:"guest_credential_free"`
		SandboxTransport     string   `json:"sandbox_transport"`
		DirectEffect         string   `json:"direct_effect"`
		DirectProbeHost      string   `json:"direct_probe_host"`
		SuccessorTermination string   `json:"successor_termination"`
		OperationCallID      string   `json:"operation_call_id"`
	}
	if err := strictFile(filepath.Join(dir, "result.json"), &result); err != nil {
		return err
	}
	if err := requireObjectKeys(filepath.Join(dir, "result.json"), "schema", "backend", "accelerator", "nested_virtualization", "firecracker_version", "guest_kernel", "microvm_processes", "distinct_processes", "firecracker_pids", "guest_cid", "network_interfaces", "root_block_devices", "guest_credential_free", "guest_request_fields", "sandbox_transport", "direct_effect", "direct_probe_host", "snapshot_loads", "successor_termination", "restore_loaded_before_resume", "relay_armed_while_paused", "first_operation_reused", "restored_operation_reused", "operation_id", "operation_call_id"); err != nil {
		return err
	}
	wantSuccessorTermination, err := successorTermination(g3)
	if err != nil {
		return err
	}
	if result.Schema != 1 || result.Backend != "firecracker" || result.Accelerator != "kvm" || result.FirecrackerVersion != officialFirecrackerVersion || result.GuestKernel != officialKernelVersion || result.MicroVMs != 2 || !result.Distinct || len(result.PIDs) != 2 || result.PIDs[0] != g1.PID || result.PIDs[1] != g3.PID || result.GuestCID != 3 || !result.CredentialFree || result.SandboxTransport != "generation-bound-vsock-to-host-unix-socket" || result.DirectEffect != "unreachable-no-guest-network-device" || result.DirectProbeHost == "" || result.SuccessorTermination != wantSuccessorTermination || result.OperationCallID != callID || result.Network != 0 || result.Drives != 0 || result.Loads != 1 || !result.RestoreBeforeResume || !result.RelayPaused || !result.RestoredReused || result.OperationID == "" || strings.Join(result.Fields, ",") != "call_id,kind,body" {
		return errors.New("result summary violates Firecracker safety contract")
	}
	if err := checkGuestResults(filepath.Join(dir, "guest-results.json"), result.OperationID, result.FirstReused); err != nil {
		return err
	}
	supervisor, err := readJSONL[supervisorEvent](filepath.Join(dir, "firecracker-supervisor.jsonl"))
	if err != nil {
		return err
	}
	if err := checkSupervisor(supervisor, g1, g3, snapshots, result.OperationID, result.FirstReused); err != nil {
		return err
	}
	g1api, err := readJSONL[apiCall](filepath.Join(dir, "firecracker-api-g1.jsonl"))
	if err != nil {
		return err
	}
	g3api, err := readJSONL[apiCall](filepath.Join(dir, "firecracker-api-g3.jsonl"))
	if err != nil {
		return err
	}
	if err := checkAPI(g1api, g3api, g1, g3); err != nil {
		return err
	}
	for _, spec := range []struct {
		file       string
		generation uint64
		pid        int
	}{{"firecracker-gate-g1.jsonl", 1, g1.PID}, {"firecracker-gate-g3.jsonl", 3, g3.PID}} {
		records, err := readJSONL[audit](filepath.Join(dir, spec.file))
		if err != nil {
			return err
		}
		if err := checkGate(records, spec.generation, spec.pid); err != nil {
			return fmt.Errorf("%s: %w", spec.file, err)
		}
	}
	for _, spec := range []struct {
		file                string
		generation          uint64
		pid                 int
		requireLostResponse bool
	}{{"firecracker-relay-g1.jsonl", 1, g1.PID, result.FirstReused}, {"firecracker-relay-g3.jsonl", 3, g3.PID, false}} {
		records, err := readJSONL[audit](filepath.Join(dir, spec.file))
		if err != nil {
			return err
		}
		if err := checkRelay(records, spec.generation, spec.pid, spec.requireLostResponse); err != nil {
			return fmt.Errorf("%s: %w", spec.file, err)
		}
	}
	return nil
}

func checkProcesses(p []process) (process, process, error) {
	var one, three process
	for _, value := range p {
		if value.Generation == 1 {
			one = value
		}
		if value.Generation == 3 {
			three = value
		}
	}
	if one.Generation != 1 || three.Generation != 3 || one.PID <= 0 || three.PID <= 0 || one.PID == three.PID || one.ID == "" || three.ID == "" || one.ID == three.ID || one.StartedNS <= 0 || one.StoppedNS <= 0 || three.StartedNS <= 0 || three.StoppedNS <= 0 || !one.ExitConfirmed || !three.ExitConfirmed || one.Termination != "supervisor" || (three.Termination != "supervisor" && three.Termination != "already-exited") {
		return process{}, process{}, errors.New("process records lack distinct generation identities")
	}
	for _, value := range []process{one, three} {
		if value.Executable == "" || len(value.ExecutableSHA256) != 64 || value.Device == 0 || value.Inode == 0 || value.Start == 0 || !validSocket(value.APISocket) || !validSocket(value.Vsock) {
			return process{}, process{}, errors.New("process record is incomplete")
		}
	}
	if one.APISocket.Name == three.APISocket.Name || one.APISocket.Inode == three.APISocket.Inode || one.Vsock.Name == three.Vsock.Name || one.Vsock.Inode == three.Vsock.Inode {
		return process{}, process{}, errors.New("generations reused an API or vsock socket")
	}
	return one, three, nil
}

func successorTermination(value process) (string, error) {
	switch value.Termination {
	case "supervisor":
		return "host-after-final-result", nil
	case "already-exited":
		return "already-exited-after-final-result", nil
	default:
		return "", errors.New("successor process termination is invalid")
	}
}
func validSocket(s socket) bool {
	return s.Name != "" && s.Device != 0 && s.Inode != 0 && s.Mode == 0o600
}

func checkSealed(items []sealedArtifact, want []artifact) error {
	if len(items) != len(want) {
		return errors.New("wrong sealed artifact count")
	}
	for index, item := range items {
		if item.ChildFD != index+4 || item.LinuxSeals != 15 || item.Artifact.Size != want[index].Size || item.Artifact.Mode != want[index].Mode || item.Artifact.SHA256 != want[index].SHA256 {
			return errors.New("sealed artifact does not match source or fd contract")
		}
	}
	return nil
}

func checkGuestResults(path, operationID string, firstReused bool) error {
	var results struct {
		Schema   int    `json:"schema"`
		First    Result `json:"first"`
		Restored Result `json:"restored"`
	}
	if err := strictFile(path, &results); err != nil {
		return err
	}
	if results.Schema != 1 {
		return errors.New("guest results schema is invalid")
	}
	first, err := checkGuestResult(results.First, firstReused)
	if err != nil {
		return err
	}
	restored, err := checkGuestResult(results.Restored, true)
	if err != nil {
		return err
	}
	if first.OperationID != operationID || restored.OperationID != operationID {
		return errors.New("guest results operation ID differs from summary")
	}
	if first.Phase != restored.Phase || first.StatusCode != restored.StatusCode ||
		!bytes.Equal(first.Body, restored.Body) || first.ResultHash != restored.ResultHash ||
		first.RecoveredByQuery != restored.RecoveredByQuery {
		return errors.New("restored guest result differs from the first durable outcome")
	}
	return nil
}

type Result struct {
	Event  string          `json:"event"`
	Status int             `json:"status"`
	Body   json.RawMessage `json:"body"`
}

type operationOutcome struct {
	OperationID      string `json:"operation_id"`
	Phase            string `json:"phase"`
	StatusCode       int    `json:"status_code"`
	Body             []byte `json:"body"`
	ResultHash       string `json:"result_hash"`
	Reused           bool   `json:"reused"`
	RecoveredByQuery bool   `json:"recovered_by_query"`
}

func checkGuestResult(result Result, reused bool) (operationOutcome, error) {
	if result.Event != "RESULT" || result.Status != 200 || len(result.Body) == 0 || !json.Valid(result.Body) {
		return operationOutcome{}, errors.New("guest result is incomplete")
	}
	var outcome operationOutcome
	dec := json.NewDecoder(bytes.NewReader(result.Body))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&outcome); err != nil {
		return operationOutcome{}, errors.New("guest result body is not a strict outcome")
	}
	if dec.Decode(&struct{}{}) != io.EOF {
		return operationOutcome{}, errors.New("guest result body has trailing JSON")
	}
	if outcome.Phase != "succeeded" || outcome.StatusCode != 200 || len(outcome.Body) == 0 ||
		outcome.ResultHash == "" || outcome.Reused != reused || outcome.RecoveredByQuery ||
		outcome.OperationID == "" {
		return operationOutcome{}, errors.New("guest result reuse contract is invalid")
	}
	return outcome, nil
}

func checkSupervisor(records []supervisorEvent, g1, g3 process, snapshots struct {
	Schema           int              `json:"schema"`
	StateBefore      artifact         `json:"state_before"`
	StateAfter       artifact         `json:"state_after"`
	MemoryBefore     artifact         `json:"memory_before"`
	MemoryAfter      artifact         `json:"memory_after"`
	LoadCount        int              `json:"load_count"`
	OriginalStopped  bool             `json:"original_stopped_before_successor_start"`
	OriginalResumed  bool             `json:"original_resumed_after_snapshot"`
	SealedLoadInputs []sealedArtifact `json:"sealed_load_inputs"`
}, operationID string, firstReused bool) error {
	want := []struct {
		event      string
		generation uint64
	}{{"run-started", 0}, {"process-started", 1}, {"guest-ready", 1}, {"snapshot-created-paused", 1}, {"relay-armed-paused", 1}, {"vm-resumed", 1}, {"operation-result", 1}, {"vm-paused", 1}, {"process-stopped", 1}, {"process-started", 3}, {"snapshot-loaded-paused", 3}, {"relay-armed-paused", 3}, {"vm-resumed", 3}, {"operation-result", 3}, {"process-stopped", 3}, {"run-completed", 0}}
	if len(records) != len(want) {
		return errors.New("supervisor trace event count differs")
	}
	var lastTime, lastElapsed int64
	for index, record := range records {
		expected := want[index]
		if record.Schema != 1 || record.Sequence != uint64(index+1) || record.Event != expected.event || record.TimeNS <= lastTime || record.ElapsedNS <= lastElapsed || record.Generation != expected.generation {
			return errors.New("supervisor trace sequence or timing differs")
		}
		lastTime, lastElapsed = record.TimeNS, record.ElapsedNS
		if expected.generation == 0 {
			if record.InstanceID != "" || record.PID != 0 || record.StartTimeTicks != 0 {
				return errors.New("global supervisor event is process-bound")
			}
			continue
		}
		p := g1
		if expected.generation == 3 {
			p = g3
		}
		if record.InstanceID != p.ID || record.PID != p.PID || record.StartTimeTicks != p.Start {
			return errors.New("supervisor event process binding differs")
		}
		if record.Event == "snapshot-created-paused" {
			if detailString(record.Details, "state_sha256") != snapshots.StateBefore.SHA256 || detailString(record.Details, "memory_sha256") != snapshots.MemoryBefore.SHA256 {
				return errors.New("supervisor snapshot create hash differs")
			}
		}
		if record.Event == "snapshot-loaded-paused" {
			if detailString(record.Details, "state_sha256") != snapshots.StateBefore.SHA256 || detailString(record.Details, "memory_sha256") != snapshots.MemoryBefore.SHA256 {
				return errors.New("supervisor snapshot load hash differs")
			}
		}
		if record.Event == "process-stopped" && (!detailBool(record.Details, "exit_confirmed") || detailString(record.Details, "termination") != p.Termination) {
			return errors.New("supervisor stop lacks matching exit confirmation")
		}
		if record.Event == "operation-result" {
			expectedReused := firstReused
			if expected.generation == 3 {
				expectedReused = true
			}
			if detailString(record.Details, "operation_id") != operationID || detailBool(record.Details, "reused") != expectedReused {
				return errors.New("supervisor operation result differs")
			}
		}
	}
	return nil
}
func detailString(details map[string]json.RawMessage, key string) string {
	var v string
	_ = json.Unmarshal(details[key], &v)
	return v
}
func detailBool(details map[string]json.RawMessage, key string) bool {
	var v bool
	_ = json.Unmarshal(details[key], &v)
	return v
}

func checkAPI(one, three []apiCall, g1, g3 process) error {
	want1 := []string{"GET /", "PUT /machine-config", "PUT /boot-source", "PUT /vsock", "PUT /actions", "PATCH /vm", "GET /", "PUT /snapshot/create", "PATCH /vm", "PATCH /vm", "GET /"}
	want3 := []string{"GET /", "PUT /snapshot/load", "GET /", "PATCH /vm"}
	if err := exactCalls(one, want1); err != nil {
		return fmt.Errorf("g1 API trace: %w", err)
	}
	if err := exactCalls(three, want3); err != nil {
		return fmt.Errorf("g3 API trace: %w", err)
	}
	if err := expectObject(one[1].Request, map[string]any{"vcpu_count": float64(1), "mem_size_mib": float64(128), "smt": false, "track_dirty_pages": false}); err != nil {
		return err
	}
	var boot map[string]any
	if json.Unmarshal(one[2].Request, &boot) != nil || len(boot) != 3 || boot["kernel_image_path"] != "/proc/self/fd/4" || boot["initrd_path"] != "/proc/self/fd/5" || boot["boot_args"] == "" {
		return errors.New("boot-source payload is not exact")
	}
	var g1vsock map[string]any
	_ = json.Unmarshal(one[3].Request, &g1vsock)
	if len(g1vsock) != 2 || g1vsock["guest_cid"] != float64(3) {
		return errors.New("vsock setup payload is not exact")
	}
	g1path, _ := g1vsock["uds_path"].(string)
	var load map[string]any
	if err := json.Unmarshal(three[1].Request, &load); err != nil {
		return errors.New("invalid snapshot load payload")
	}
	if len(load) != 4 || load["resume_vm"] != false || load["snapshot_path"] != "/proc/self/fd/4" {
		return errors.New("snapshot load must have resume_vm=false")
	}
	override, ok := load["vsock_override"].(map[string]any)
	if !ok || len(override) != 1 {
		return errors.New("snapshot load lacks strict vsock override")
	}
	g3path, _ := override["uds_path"].(string)
	if g1path == "" || g3path == "" || g1path == g3path || filepath.Base(g1path) != g1.Vsock.Name || filepath.Base(g3path) != g3.Vsock.Name {
		return errors.New("snapshot load did not switch to successor vsock path")
	}
	var snapshot map[string]any
	if json.Unmarshal(one[7].Request, &snapshot) != nil || len(snapshot) != 3 || snapshot["snapshot_type"] != "Full" || filepath.Base(fmt.Sprint(snapshot["snapshot_path"])) != "snapshot.state" || filepath.Base(fmt.Sprint(snapshot["mem_file_path"])) != "snapshot.memory" {
		return errors.New("snapshot create payload is not exact")
	}
	mem, ok := load["mem_backend"].(map[string]any)
	if !ok || len(mem) != 2 || mem["backend_type"] != "File" || mem["backend_path"] != "/proc/self/fd/5" {
		return errors.New("snapshot load memory backend is not exact")
	}
	if err := expectObject(one[4].Request, map[string]any{"action_type": "InstanceStart"}); err != nil {
		return err
	}
	if err := expectObject(one[5].Request, map[string]any{"state": "Paused"}); err != nil {
		return err
	}
	if err := expectObject(one[8].Request, map[string]any{"state": "Resumed"}); err != nil {
		return err
	}
	if err := expectObject(one[9].Request, map[string]any{"state": "Paused"}); err != nil {
		return err
	}
	if err := expectObject(three[3].Request, map[string]any{"state": "Resumed"}); err != nil {
		return err
	}
	for _, item := range []struct {
		call    apiCall
		process process
		state   string
	}{{one[0], g1, "Not started"}, {one[6], g1, "Paused"}, {one[10], g1, "Paused"}, {three[0], g3, "Not started"}, {three[2], g3, "Paused"}} {
		if err := checkState(item.call, item.process, item.state); err != nil {
			return err
		}
	}
	return nil
}
func exactCalls(c []apiCall, want []string) error {
	if len(c) != len(want) {
		return fmt.Errorf("calls=%d want=%d", len(c), len(want))
	}
	var last int64
	for i, v := range c {
		if v.Sequence != uint64(i+1) || v.TimeNS <= last || v.Error != "" {
			return errors.New("non-monotonic or failed API call")
		}
		last = v.TimeNS
		parts := strings.SplitN(want[i], " ", 2)
		if v.Method != parts[0] || v.Path != parts[1] || v.Status != map[bool]int{true: 200, false: 204}[v.Method == "GET"] {
			return fmt.Errorf("unexpected API call %s %s", v.Method, v.Path)
		}
	}
	return nil
}
func checkState(c apiCall, p process, want string) error {
	var x struct {
		AppName    string `json:"app_name"`
		ID         string `json:"id"`
		State      string `json:"state"`
		VMMVersion string `json:"vmm_version"`
	}
	if err := strictRaw(c.Response, &x); err != nil || x.AppName != "Firecracker" || x.ID != p.ID || x.State != want || x.VMMVersion != officialFirecrackerVersion {
		return errors.New("API GET / response is not the exact Firecracker instance state")
	}
	return nil
}
func expectObject(raw json.RawMessage, want map[string]any) error {
	var got map[string]any
	if json.Unmarshal(raw, &got) != nil || len(got) != len(want) {
		return errors.New("API request payload is not exact")
	}
	for k, v := range want {
		if got[k] != v {
			return errors.New("API request payload differs")
		}
	}
	return nil
}
func checkGate(a []audit, generation uint64, pid int) error {
	if len(a) < 4 {
		return errors.New("gate event count is too small")
	}
	allowCount := 0
	goCount := 0
	accepted := false
	ready := false
	resultCount := 0
	for index, v := range a {
		if v.Time.IsZero() {
			return errors.New("gate audit lacks time")
		}
		if v.Error != "" {
			return errors.New("gate recorded error")
		}
		if v.Generation != generation || v.Port != gatePort {
			return errors.New("gate audit has wrong generation or port")
		}
		switch v.Event {
		case "accept":
			if v.PID != pid {
				return errors.New("gate accepted wrong peer PID")
			}
			accepted, ready = true, false
		case "ready":
			if !accepted || ready {
				return errors.New("gate ready is not attached to an accepted connection")
			}
			ready = true
		case "allow":
			allowCount++
			if allowCount != 1 {
				return errors.New("gate allowed more than once")
			}
		case "go":
			if allowCount != 1 || !accepted || !ready || v.Bytes != len(fmt.Sprintf("GO %d\n", generation)) {
				return errors.New("gate go is not attached to an allowed ready connection")
			}
			goCount++
			ready = false
		case "result":
			if index != len(a)-1 || !accepted || index == 0 || a[index-1].Event != "accept" || v.Status != 200 || v.Bytes <= 0 {
				return errors.New("gate result lacks a final accepted successful response")
			}
			resultCount++
		default:
			return errors.New("gate has an unknown event")
		}
		if resultCount > 1 {
			return errors.New("gate has multiple results")
		}
	}
	if allowCount != 1 || goCount == 0 || resultCount != 1 {
		return errors.New("gate did not complete an allowed request")
	}
	return nil
}
func checkRelay(a []audit, generation uint64, pid int, requireLostResponse bool) error {
	if len(a) < 2 || len(a)%2 != 0 {
		return errors.New("relay event count differs")
	}
	var sandboxDevice, sandboxInode uint64
	var sandboxPID int
	lostResponse := false
	for index, v := range a {
		if v.Time.IsZero() {
			return errors.New("relay audit lacks time")
		}
		if v.Error != "" {
			return errors.New("relay recorded error")
		}
		if v.Generation != generation || v.Port != 8787 {
			return errors.New("relay audit has wrong generation")
		}
		if v.SandboxDevice == 0 || v.SandboxInode == 0 {
			return errors.New("relay audit lacks pinned sandbox identity")
		}
		if index == 0 {
			sandboxDevice, sandboxInode = v.SandboxDevice, v.SandboxInode
		} else if v.SandboxDevice != sandboxDevice || v.SandboxInode != sandboxInode {
			return errors.New("relay sandbox identity changed")
		}
		if (index%2 == 0 && v.Event != "accept") || (index%2 == 1 && v.Event != "bytes") {
			return errors.New("relay events are out of order or unknown")
		}
		if v.Event == "accept" {
			if v.PID != pid {
				return errors.New("relay accepted wrong peer PID")
			}
		}
		if v.Event == "bytes" {
			if v.SandboxPID <= 0 || v.SandboxPID == pid || v.GuestToHost <= 0 || v.HostToGuest < 0 {
				return errors.New("relay did not forward bytes")
			}
			if index != len(a)-1 && v.HostToGuest == 0 {
				lostResponse = true
			}
			if sandboxPID == 0 {
				sandboxPID = v.SandboxPID
			} else if v.SandboxPID != sandboxPID {
				return errors.New("relay sandbox peer PID changed")
			}
			if index == len(a)-1 && v.HostToGuest == 0 {
				return errors.New("relay final response was not delivered")
			}
		}
	}
	if requireLostResponse && !lostResponse {
		return errors.New("reused first result lacks a prior lost relay response")
	}
	return nil
}

func strictRequest(data []byte) (string, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	tok, err := dec.Token()
	if err != nil {
		return "", errors.New("guest request is not JSON")
	}
	if d, ok := tok.(json.Delim); !ok || d != '{' {
		return "", errors.New("guest request must be object")
	}
	seen := map[string]bool{}
	for dec.More() {
		t, e := dec.Token()
		if e != nil {
			return "", e
		}
		k, ok := t.(string)
		if !ok || seen[k] || (k != "call_id" && k != "kind" && k != "body") {
			return "", errors.New("guest request must have exactly call_id, kind, body")
		}
		seen[k] = true
		var value any
		if dec.Decode(&value) != nil {
			return "", errors.New("invalid guest request value")
		}
		if k != "body" {
			if s, ok := value.(string); !ok || strings.TrimSpace(s) == "" {
				return "", errors.New("guest request has empty identity")
			}
		} else if _, ok := value.(string); !ok {
			return "", errors.New("guest request body must be string")
		}
	}
	tok, err = dec.Token()
	if err != nil {
		return "", err
	}
	if d, ok := tok.(json.Delim); !ok || d != '}' || len(seen) != 3 {
		return "", errors.New("guest request fields incomplete")
	}
	if _, err = dec.Token(); !errors.Is(err, io.EOF) {
		return "", errors.New("guest request has trailing value")
	}
	var request struct {
		CallID string `json:"call_id"`
	}
	if err := json.Unmarshal(data, &request); err != nil {
		return "", err
	}
	return request.CallID, nil
}
func strictRaw(data []byte, target any) error {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if err := dec.Decode(target); err != nil {
		return err
	}
	if dec.Decode(&struct{}{}) != io.EOF {
		return errors.New("trailing JSON")
	}
	return nil
}
func strictFile(path string, target any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if err := dec.Decode(target); err != nil {
		return fmt.Errorf("decode %s: %w", filepath.Base(path), err)
	}
	if dec.Decode(&struct{}{}) != io.EOF {
		return fmt.Errorf("%s has trailing JSON", filepath.Base(path))
	}
	return nil
}
func requireObjectKeys(path string, keys ...string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var object map[string]json.RawMessage
	if err := json.Unmarshal(data, &object); err != nil {
		return err
	}
	if len(object) != len(keys) {
		return fmt.Errorf("%s does not have the exact schema fields", filepath.Base(path))
	}
	for _, key := range keys {
		if _, ok := object[key]; !ok {
			return fmt.Errorf("%s lacks %s", filepath.Base(path), key)
		}
	}
	return nil
}
func readJSONL[T any](path string) ([]T, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(data) == 0 || data[len(data)-1] != '\n' {
		return nil, fmt.Errorf("%s is not complete JSONL", filepath.Base(path))
	}
	lines := strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
	out := make([]T, 0, len(lines))
	for _, line := range lines {
		var x T
		dec := json.NewDecoder(strings.NewReader(line))
		dec.DisallowUnknownFields()
		if err := dec.Decode(&x); err != nil {
			return nil, fmt.Errorf("%s: %w", filepath.Base(path), err)
		}
		if dec.Decode(&struct{}{}) != io.EOF {
			return nil, fmt.Errorf("%s has trailing JSON", filepath.Base(path))
		}
		out = append(out, x)
	}
	return out, nil
}

func checkPayload(path string, want artifact) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 || info.Mode().Perm() != os.FileMode(want.Mode) || info.Size() != want.Size {
		return errors.New("file type, mode, or size differs from provenance")
	}
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()
	digest := sha256.New()
	if _, err := io.Copy(digest, file); err != nil {
		return err
	}
	if fmt.Sprintf("%x", digest.Sum(nil)) != want.SHA256 {
		return errors.New("streamed SHA-256 differs from provenance")
	}
	return nil
}

type newcEntry struct {
	name string
	mode uint32
	data []byte
}

func checkInitramfs(path string, guest artifact, request []byte) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	entries, err := parseNewc(data)
	if err != nil {
		return fmt.Errorf("invalid retained initramfs: %w", err)
	}
	want := []struct {
		name string
		mode uint32
	}{
		{"dev", 0040755}, {"dev/console", 0020600}, {"init", 0100555},
		{"proc", 0040555}, {"request.json", 0100444}, {"run", 0040755},
		{"sys", 0040555}, {"tmp", 0041777},
	}
	if len(entries) != len(want) {
		return errors.New("initramfs has an unexpected entry count")
	}
	for index, expected := range want {
		entry := entries[index]
		if entry.name != expected.name || entry.mode != expected.mode {
			return errors.New("initramfs entries or modes differ from deterministic layout")
		}
		if expected.name != "init" && expected.name != "request.json" && len(entry.data) != 0 {
			return errors.New("initramfs metadata entry has unexpected data")
		}
		if expected.name == "init" && (int64(len(entry.data)) != guest.Size || fmt.Sprintf("%x", sha256.Sum256(entry.data)) != guest.SHA256) {
			return errors.New("initramfs init bytes differ from guest artifact")
		}
		if expected.name == "request.json" && !bytes.Equal(entry.data, request) {
			return errors.New("initramfs request.json differs from retained guest request")
		}
	}
	return nil
}

func parseNewc(data []byte) ([]newcEntry, error) {
	const headerSize = 110
	offset := 0
	entries := []newcEntry{}
	for {
		if offset+headerSize > len(data) || string(data[offset:offset+6]) != "070701" {
			return nil, errors.New("missing newc header")
		}
		field := func(start int) (uint32, error) {
			value, err := strconv.ParseUint(string(data[offset+start:offset+start+8]), 16, 32)
			return uint32(value), err
		}
		mode, err := field(14)
		if err != nil {
			return nil, errors.New("invalid newc mode")
		}
		size, err := field(54)
		if err != nil {
			return nil, errors.New("invalid newc size")
		}
		nameSize, err := field(94)
		if err != nil || nameSize == 0 {
			return nil, errors.New("invalid newc name size")
		}
		offset += headerSize
		if int(nameSize) > len(data)-offset || data[offset+int(nameSize)-1] != 0 {
			return nil, errors.New("invalid newc name")
		}
		name := string(data[offset : offset+int(nameSize)-1])
		offset = (offset + int(nameSize) + 3) &^ 3
		if int(size) > len(data)-offset {
			return nil, errors.New("truncated newc entry")
		}
		payload := append([]byte(nil), data[offset:offset+int(size)]...)
		offset = (offset + int(size) + 3) &^ 3
		if name == "TRAILER!!!" {
			if size != 0 || offset > len(data) {
				return nil, errors.New("invalid newc trailer")
			}
			for _, value := range data[offset:] {
				if value != 0 {
					return nil, errors.New("newc has non-zero trailing data")
				}
			}
			return entries, nil
		}
		entries = append(entries, newcEntry{name: name, mode: mode, data: payload})
	}
}
