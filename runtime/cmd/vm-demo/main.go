// Command vm-demo boots an unmodified Ubuntu cloud image behind a restricted
// QEMU user network, saves the running guest before an external Operation,
// restores it after the remote commit loses its response, and verifies that
// host History prevents a duplicate commit.
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	goruntime "runtime"
	"slices"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
	"unicode"

	controlapi "github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/payment"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/sandboxhost"
)

const (
	defaultImageURL  = "https://cloud-images.ubuntu.com/releases/noble/release-20260725/ubuntu-24.04-server-cloudimg-amd64.img"
	defaultImageSHA  = "d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac"
	defaultImageSize = 624105472
	maxImageBytes    = 2 << 30
)

type options struct {
	imagePath               string
	imageURL                string
	imageSHA                string
	accel                   string
	keep                    bool
	timeout                 time.Duration
	externalSandboxSocket   string
	externalRequestPath     string
	externalDirectProbe     string
	externalEvidenceDirPath string
}

type executableIdentity struct {
	device uint64
	inode  uint64
	sha256 string
}

type hostTool struct {
	name     string
	path     string
	version  string
	identity executableIdentity
}

type hostTools struct {
	qemuSystem hostTool
	qemuImage  hostTool
	netcat     hostTool
}

func main() {
	var configuration options
	flag.StringVar(&configuration.imagePath, "image", "", "verified Ubuntu cloud image path or default cache path")
	flag.StringVar(&configuration.imageURL, "image-url", defaultImageURL, "download URL used when the image is absent")
	flag.StringVar(&configuration.imageSHA, "image-sha256", defaultImageSHA, "required lowercase SHA-256 for the base image")
	flag.StringVar(&configuration.accel, "accel", "tcg", "QEMU accelerator: tcg or kvm")
	flag.BoolVar(&configuration.keep, "keep", false, "retain the VM evidence directory")
	flag.DurationVar(&configuration.timeout, "timeout", 12*time.Minute, "whole-demo timeout")
	flag.StringVar(&configuration.externalSandboxSocket, "external-sandbox-socket", "", "host-owned Unix socket for credential-free shared-control mode")
	flag.StringVar(&configuration.externalRequestPath, "external-request", "", "strict execute-request JSON for shared-control mode")
	flag.StringVar(&configuration.externalDirectProbe, "external-direct-probe", "", "effect URL that the restored guest must not reach directly")
	flag.StringVar(&configuration.externalEvidenceDirPath, "external-evidence-dir", "", "empty directory for sanitized shared-control VM evidence")
	flag.Parse()
	if err := run(configuration); err != nil {
		log.Printf("VM demo failed: %v", err)
		os.Exit(1)
	}
}

func run(configuration options) error {
	if configuration.accel != "tcg" && configuration.accel != "kvm" {
		return errors.New("-accel must be tcg or kvm")
	}
	if configuration.accel == "kvm" {
		kvm, err := os.OpenFile("/dev/kvm", os.O_RDWR, 0)
		if err != nil {
			return fmt.Errorf("KVM acceleration requires read/write access to /dev/kvm: %w", err)
		}
		info, statErr := kvm.Stat()
		closeErr := kvm.Close()
		if statErr != nil || closeErr != nil {
			return errors.Join(statErr, closeErr)
		}
		if info.Mode()&os.ModeCharDevice == 0 {
			return errors.New("/dev/kvm is not a character device")
		}
	}
	decodedSHA, shaErr := hex.DecodeString(configuration.imageSHA)
	if shaErr != nil || len(decodedSHA) != sha256.Size || hex.EncodeToString(decodedSHA) != configuration.imageSHA {
		return errors.New("-image-sha256 must be 64 lowercase hexadecimal characters")
	}
	qemuSystem, err := resolveHostTool("qemu-system-x86_64")
	if err != nil {
		return err
	}
	qemuImage, err := resolveHostTool("qemu-img")
	if err != nil {
		return err
	}
	netcat, err := resolveHostTool("nc")
	if err != nil {
		return err
	}
	tools := hostTools{qemuSystem: qemuSystem, qemuImage: qemuImage, netcat: netcat}
	if configuration.imagePath == "" {
		cache, err := os.UserCacheDir()
		if err != nil {
			return err
		}
		configuration.imagePath = filepath.Join(cache, "safe-change-runtime", "images", "ubuntu-24.04-20260725-amd64.img")
	}
	configuration.imagePath, _ = filepath.Abs(configuration.imagePath)
	ctx, cancel := context.WithTimeout(context.Background(), configuration.timeout)
	defer cancel()
	external, err := validateExternalOptions(configuration)
	if err != nil {
		return err
	}
	if err := ensureImage(ctx, configuration.imagePath, configuration.imageURL, configuration.imageSHA); err != nil {
		return err
	}
	if external {
		return runExternal(ctx, configuration, tools, os.Stdin, os.Stdout)
	}

	work, err := os.MkdirTemp("", "safe-change-vm-")
	if err != nil {
		return err
	}
	if configuration.keep {
		log.Printf("VM evidence directory: %s", work)
	} else {
		defer os.RemoveAll(work)
	}
	historyPath := filepath.Join(work, "host.history")
	anchorPath := filepath.Join(work, "host.head")
	paymentPath := filepath.Join(work, "payment.history")
	overlayPath := filepath.Join(work, "guest.qcow2")
	serialPath := filepath.Join(work, "guest.serial.log")
	qemuLogPath := filepath.Join(work, "qemu.log")
	qmpPath := filepath.Join(work, "qmp.sock")
	qmpTracePath := filepath.Join(work, "qmp-protocol.jsonl")
	supervisorTrace, err := openSyncedTrace(filepath.Join(work, "host-supervisor.jsonl"))
	if err != nil {
		return err
	}
	defer supervisorTrace.Close()
	providerTrace, err := openSyncedTrace(filepath.Join(work, "provider-deliveries.jsonl"))
	if err != nil {
		return err
	}
	defer providerTrace.Close()
	metadataTrace, err := openSyncedTrace(filepath.Join(work, "guest-network.jsonl"))
	if err != nil {
		return err
	}
	defer metadataTrace.Close()
	if err := writeSourceProvenance(work, configuration); err != nil {
		return err
	}

	paymentService, err := payment.Open(paymentPath, true)
	if err != nil {
		return err
	}
	defer paymentService.Close()
	paymentListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	paymentHandler := paymentService.Handler()
	paymentServer := &http.Server{
		Handler: http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
			if request.URL.Path == "/v1/charge" {
				if err := providerTrace.Record("provider-request-received", map[string]any{
					"method": request.Method, "path": request.URL.Path,
					"operation_id": request.Header.Get("X-Operation-ID"),
				}); err != nil {
					http.Error(writer, "provider evidence write failed", http.StatusInternalServerError)
					return
				}
			}
			paymentHandler.ServeHTTP(writer, request)
		}),
		ReadHeaderTimeout: 5 * time.Second,
	}
	go serve(paymentServer, paymentListener)
	defer shutdown(paymentServer)
	paymentTarget := "http://" + paymentListener.Addr().String() + "/v1/charge"
	var directCanaryReached atomic.Bool
	directCanaryListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	directCanaryServer := &http.Server{
		Handler: http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
			directCanaryReached.Store(true)
			writer.WriteHeader(http.StatusNoContent)
		}),
		ReadHeaderTimeout: 5 * time.Second,
	}
	go serve(directCanaryServer, directCanaryListener)
	defer shutdown(directCanaryServer)
	if err := metadataTrace.Record("direct-host-canary-listening", map[string]any{
		"address": directCanaryListener.Addr().String(),
	}); err != nil {
		return err
	}

	controller, err := control.OpenWithAnchor(historyPath, anchorPath)
	if err != nil {
		return err
	}
	defer controller.Close()
	requirement := vmRequirement("vm-restore-v1", paymentTarget)
	certificate, err := controller.Compile(requirement)
	if err != nil {
		return err
	}
	adminToken, err := randomToken()
	if err != nil {
		return err
	}
	firstHostID, err := randomToken()
	if err != nil {
		return err
	}
	firstBinding := control.SandboxBinding{
		SandboxID: "full-linux-vm", Generation: 1,
		HostInstanceID: "qemu-" + firstHostID, Domain: "full-linux-vm",
		AllowedKinds: []string{"vm-write"},
	}
	if err := controller.Cutover(certificate, []control.SandboxBinding{firstBinding}); err != nil {
		return err
	}
	if err := supervisorTrace.Record("rule-and-sandbox-cutover", map[string]any{
		"history_sequence": controller.Snapshot().History.Sequence, "binding": firstBinding,
	}); err != nil {
		return err
	}
	serverAPI, err := controlapi.New(controller, nil, controlapi.Credentials{
		AdminToken: adminToken,
	})
	if err != nil {
		return err
	}
	sandboxEndpoint, err := sandboxhost.Listen(
		controller, serverAPI, firstBinding, "127.0.0.1:0",
	)
	if err != nil {
		return err
	}
	defer func() {
		closeContext, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = sandboxEndpoint.Close(closeContext)
	}()
	if err := supervisorTrace.Record("sandbox-endpoint-bound", map[string]any{
		"binding": firstBinding, "address": sandboxEndpoint.Address(),
	}); err != nil {
		return err
	}
	sandboxPort, err := sandboxEndpoint.Port()
	if err != nil {
		return err
	}

	executeJSON, err := makeSandboxExecuteJSON(
		"vm/job-1/write", "vm-write", []byte(`{"job":"job-1","value":42}`),
	)
	if err != nil {
		return err
	}
	var gate atomic.Bool
	guestScript := makeGuestScript(
		base64.StdEncoding.EncodeToString(executeJSON),
		directCanaryListener.Addr().(*net.TCPAddr).Port,
	)
	if err := validateStandaloneGuestBoundary(executeJSON, guestScript, paymentTarget); err != nil {
		return err
	}
	if err := writePrivateFile(filepath.Join(work, "guest-operation.json"), append(executeJSON, '\n')); err != nil {
		return err
	}
	if err := writePrivateFile(filepath.Join(work, "guest-script.sh"), []byte(guestScript)); err != nil {
		return err
	}
	userData := makeUserData(guestScript)
	seedListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	seedServer := &http.Server{Handler: seedHandler(userData, &gate, &seedEvidence{
		trace: metadataTrace, address: seedListener.Addr().String(),
		guestScriptSHA256: dataSHA256([]byte(guestScript)), userDataSHA256: dataSHA256([]byte(userData)),
	}), ReadHeaderTimeout: 5 * time.Second}
	go serve(seedServer, seedListener)
	defer shutdown(seedServer)

	if output, err := exec.CommandContext(ctx, tools.qemuImage.path, "create", "-q", "-f", "qcow2", "-F", "qcow2", "-b", configuration.imagePath, overlayPath, "8G").CombinedOutput(); err != nil {
		return fmt.Errorf("create guest overlay: %w: %s", err, output)
	}
	qemuLog, err := os.OpenFile(qemuLogPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	defer qemuLog.Close()
	netdev := fmt.Sprintf(
		"user,id=opnet,restrict=on,guestfwd=tcp:10.0.2.100:8000-cmd:%s 127.0.0.1 %d,guestfwd=tcp:10.0.2.100:8787-cmd:%s 127.0.0.1 %d",
		tools.netcat.path,
		seedListener.Addr().(*net.TCPAddr).Port,
		tools.netcat.path,
		sandboxPort,
	)
	qemuArgs := []string{
		"-name", "safe-change-vm", "-machine", "q35", "-m", "1024", "-smp", "2",
		"-drive", "file=" + overlayPath + ",if=virtio,format=qcow2,cache=none",
		"-display", "none", "-serial", "file:" + serialPath, "-monitor", "none",
		"-qmp", "unix:" + qmpPath + ",server=on,wait=off", "-no-reboot", "-nic", "none",
		"-netdev", netdev, "-device", "virtio-net-pci,netdev=opnet",
		"-smbios", "type=1,serial=ds=nocloud;s=http://10.0.2.100:8000/",
	}
	if configuration.accel == "tcg" {
		qemuArgs = append(qemuArgs, "-accel", "tcg,thread=multi")
	} else {
		qemuArgs = append(qemuArgs, "-accel", "kvm")
	}
	if err := writeQEMUCommand(
		filepath.Join(work, "qemu-command.json"), qemuArgs, work, configuration.imagePath,
	); err != nil {
		return err
	}
	qemu := exec.CommandContext(ctx, tools.qemuSystem.path, qemuArgs...)
	qemu.Stdout, qemu.Stderr = qemuLog, qemuLog
	if err := qemu.Start(); err != nil {
		return err
	}
	qemuDone := make(chan error, 1)
	go func() { qemuDone <- qemu.Wait() }()
	finished := false
	defer func() {
		if !finished && qemu.Process != nil {
			_ = qemu.Process.Kill()
			<-qemuDone
		}
	}()
	qmp, err := dialQMPWithTrace(ctx, qmpPath, qmpTracePath)
	if err != nil {
		return withQEMULog(err, qemuLogPath)
	}
	defer qmp.Close()
	if err := waitForText(ctx, serialPath, "SAFE_CHANGE_VM_READY", 5*time.Minute); err != nil {
		return withQEMULog(err, qemuLogPath)
	}
	if err := qmp.command("stop", nil); err != nil {
		return err
	}
	if err := qmp.requireStatus("paused"); err != nil {
		return err
	}
	if err := supervisorTrace.Record("snapshot-save-paused", nil); err != nil {
		return err
	}
	if err := qmp.human("savevm before_operation"); err != nil {
		return err
	}
	if err := metadataTrace.Record("guest-operation-gate-opened", nil); err != nil {
		return err
	}
	gate.Store(true)
	if err := qmp.command("cont", nil); err != nil {
		return err
	}
	if err := waitForText(ctx, serialPath, "SAFE_CHANGE_VM_FIRST_UNKNOWN", 2*time.Minute); err != nil {
		return err
	}
	if err := supervisorTrace.Record("first-operation-unknown", map[string]any{
		"history_sequence": controller.Snapshot().History.Sequence,
	}); err != nil {
		return err
	}
	if err := qmp.command("stop", nil); err != nil {
		return err
	}
	if err := qmp.requireStatus("paused"); err != nil {
		return err
	}
	if err := supervisorTrace.Record("restore-pause-confirmed", nil); err != nil {
		return err
	}
	oldEndpointAddress := sandboxEndpoint.Address()
	closeContext, cancelClose := context.WithTimeout(ctx, 10*time.Second)
	if err := sandboxEndpoint.Close(closeContext); err != nil {
		cancelClose()
		return fmt.Errorf("close old sandbox endpoint while VM is paused: %w", err)
	}
	cancelClose()
	if err := requireTCPClosed(oldEndpointAddress); err != nil {
		return err
	}
	if err := supervisorTrace.Record("old-sandbox-endpoint-closed", map[string]any{
		"binding": firstBinding, "address": oldEndpointAddress,
	}); err != nil {
		return err
	}
	if err := qmp.human("loadvm before_operation"); err != nil {
		return err
	}
	if err := qmp.requireStatus("paused"); err != nil {
		return fmt.Errorf("restored VM was not kept paused for host cutover: %w", err)
	}
	if err := supervisorTrace.Record("snapshot-loaded-paused", nil); err != nil {
		return err
	}
	secondCertificate, err := controller.Compile(vmRequirement("vm-restore-v2", paymentTarget))
	if err != nil {
		return err
	}
	secondHostID, err := randomToken()
	if err != nil {
		return err
	}
	secondBinding := control.SandboxBinding{
		SandboxID: firstBinding.SandboxID, Generation: 2,
		HostInstanceID: "qemu-" + secondHostID, Domain: firstBinding.Domain,
		AllowedKinds: append([]string(nil), firstBinding.AllowedKinds...),
	}
	if err := controller.Cutover(secondCertificate, []control.SandboxBinding{secondBinding}); err != nil {
		return err
	}
	if err := supervisorTrace.Record("rule-and-sandbox-cutover", map[string]any{
		"history_sequence": controller.Snapshot().History.Sequence, "binding": secondBinding,
	}); err != nil {
		return err
	}
	if err := controller.ValidateSandbox(firstBinding); !errors.Is(err, control.ErrStaleSandboxBinding) {
		return fmt.Errorf("old sandbox generation was not fenced: %v", err)
	}
	if err := supervisorTrace.Record("old-sandbox-generation-rejected", map[string]any{
		"binding": firstBinding, "reason": control.ErrStaleSandboxBinding.Error(),
	}); err != nil {
		return err
	}
	sandboxEndpoint, err = sandboxhost.Listen(
		controller, serverAPI, secondBinding, oldEndpointAddress,
	)
	if err != nil {
		return fmt.Errorf("bind replacement sandbox endpoint while VM is paused: %w", err)
	}
	if sandboxEndpoint.Address() != oldEndpointAddress {
		return fmt.Errorf("replacement sandbox endpoint moved from %s to %s", oldEndpointAddress, sandboxEndpoint.Address())
	}
	if err := supervisorTrace.Record("sandbox-endpoint-bound", map[string]any{
		"binding": secondBinding, "address": sandboxEndpoint.Address(),
	}); err != nil {
		return err
	}
	if err := qmp.command("cont", nil); err != nil {
		return err
	}
	if err := waitForText(ctx, serialPath, "SAFE_CHANGE_VM_RESTORED_SUCCEEDED", 2*time.Minute); err != nil {
		return err
	}
	if err := supervisorTrace.Record("restored-operation-succeeded", map[string]any{
		"history_sequence": controller.Snapshot().History.Sequence,
	}); err != nil {
		return err
	}
	select {
	case err := <-qemuDone:
		finished = true
		if err != nil {
			return withQEMULog(err, qemuLogPath)
		}
	case <-time.After(90 * time.Second):
		return errors.New("guest did not power off after the restored Operation succeeded")
	case <-ctx.Done():
		return ctx.Err()
	}
	if err := qemuLog.Sync(); err != nil {
		return err
	}

	serial, err := os.ReadFile(serialPath)
	if err != nil {
		return err
	}
	serialText := string(serial)
	if strings.Contains(serialText, "SAFE_CHANGE_VM_DIRECT_BYPASS_REACHABLE") ||
		strings.Count(serialText, "SAFE_CHANGE_VM_DIRECT_BYPASS_BLOCKED") < 2 {
		return errors.New("guest direct-host isolation check failed")
	}
	if directCanaryReached.Load() {
		return errors.New("guest reached the unforwarded host canary")
	}
	guestKernel := markerField(serialText, "SAFE_CHANGE_VM_READY kernel=")
	if guestKernel == "" {
		return errors.New("guest kernel version is missing from serial evidence")
	}
	stats := paymentService.Stats()
	state := controller.Snapshot()
	if stats.Deliveries != 2 || providerTrace.Count() != 2 || stats.Commits != 1 || len(state.Operations) != 1 {
		return fmt.Errorf("unexpected final facts: payment=%+v operations=%d", stats, len(state.Operations))
	}
	for _, operation := range state.Operations {
		if operation.Phase != kernel.Succeeded || operation.Kind != "vm-write" || operation.Target != paymentTarget {
			return fmt.Errorf("unexpected final Operation: %+v", operation)
		}
	}
	snapshotOutput, err := exec.CommandContext(ctx, tools.qemuImage.path, "snapshot", "-l", overlayPath).CombinedOutput()
	if err != nil || !strings.Contains(string(snapshotOutput), "before_operation") {
		return fmt.Errorf("guest snapshot not present: %w: %s", err, snapshotOutput)
	}
	if err := writePrivateFile(filepath.Join(work, "snapshots.txt"), snapshotOutput); err != nil {
		return err
	}
	summary := map[string]any{
		"evidence_schema":                      2,
		"accelerator":                          configuration.accel,
		"base_image_sha256":                    configuration.imageSHA,
		"full_linux_guest":                     true,
		"guest_kernel":                         guestKernel,
		"host_owned_restricted_network":        true,
		"direct_host_canary_from_guest":        "blocked_before_and_after_restore",
		"injected_guest_provider_target":       false,
		"injected_guest_bearer_token":          false,
		"host_bound_sandbox_generations":       []uint64{1, 2},
		"old_sandbox_generation_rejected":      true,
		"endpoint_rebound_while_vm_paused":     true,
		"rule_and_sandbox_cutovers":            2,
		"runner_completed":                     true,
		"snapshot_saved_before_operation":      true,
		"first_network_result":                 kernel.Unknown,
		"whole_vm_restored":                    true,
		"restored_operation":                   kernel.Succeeded,
		"remote_deliveries":                    stats.Deliveries,
		"remote_commits":                       stats.Commits,
		"host_history_sequence":                state.History.Sequence,
		"history_outside_guest_restore_domain": true,
		"payment_outside_guest_restore_domain": true,
	}
	if configuration.keep {
		summary["evidence_directory"] = work
	}
	encoded, err := json.MarshalIndent(summary, "", "  ")
	if err != nil {
		return err
	}
	if err := writePrivateFile(filepath.Join(work, "result.json"), append(encoded, '\n')); err != nil {
		return err
	}
	if err := supervisorTrace.Close(); err != nil {
		return err
	}
	if err := providerTrace.Close(); err != nil {
		return err
	}
	if err := metadataTrace.Close(); err != nil {
		return err
	}
	if err := writeEvidenceManifest(work, []string{
		"guest-network.jsonl", "guest-operation.json", "guest-script.sh", "guest.qcow2", "guest.serial.log",
		"host.head", "host.history", "host-supervisor.jsonl", "payment.history",
		"provenance.json", "provider-deliveries.jsonl", "qemu-command.json", "qemu.log", "qmp-protocol.jsonl",
		"result.json", "snapshots.txt",
	}); err != nil {
		return err
	}
	fmt.Println(string(encoded))
	return nil
}

type externalExecuteRequest struct {
	CallID string `json:"call_id"`
	Kind   string `json:"kind"`
	Body   []byte `json:"body"`
}

func validateExternalOptions(configuration options) (bool, error) {
	requested := configuration.externalSandboxSocket != "" ||
		configuration.externalRequestPath != "" ||
		configuration.externalDirectProbe != "" ||
		configuration.externalEvidenceDirPath != ""
	if !requested {
		return false, nil
	}
	if configuration.externalSandboxSocket == "" || configuration.externalRequestPath == "" ||
		configuration.externalDirectProbe == "" || configuration.externalEvidenceDirPath == "" {
		return false, errors.New("shared-control mode requires sandbox socket, request, direct probe, and evidence directory")
	}
	if configuration.keep {
		return false, errors.New("-keep cannot be combined with shared-control mode")
	}
	probe, err := url.Parse(configuration.externalDirectProbe)
	if err != nil || probe.Scheme != "http" || probe.Host == "" || probe.User != nil || probe.Fragment != "" {
		return false, errors.New("external direct probe must be an absolute plain HTTP URL")
	}
	if !filepath.IsAbs(configuration.externalSandboxSocket) ||
		filepath.Clean(configuration.externalSandboxSocket) != configuration.externalSandboxSocket {
		return false, errors.New("external sandbox socket path must be absolute and canonical")
	}
	for _, character := range configuration.externalSandboxSocket {
		if character == ',' || unicode.IsSpace(character) || unicode.IsControl(character) {
			return false, errors.New("external sandbox socket path is unsafe for QEMU guestfwd")
		}
	}
	return true, nil
}

func runExternal(ctx context.Context, configuration options, tools hostTools, input io.Reader, output io.Writer) error {
	if err := requireExternalSandboxSocket(configuration.externalSandboxSocket); err != nil {
		return err
	}
	requestData, request, err := readExternalRequest(configuration.externalRequestPath)
	if err != nil {
		return err
	}
	evidenceDirectory, err := filepath.Abs(configuration.externalEvidenceDirPath)
	if err != nil {
		return err
	}
	if err := requireEmptyPrivateDirectory(evidenceDirectory); err != nil {
		return err
	}
	if err := writeExternalHostTools(
		filepath.Join(evidenceDirectory, "host-tools.json"), tools,
	); err != nil {
		return err
	}
	verifiedImagePath := filepath.Join(evidenceDirectory, "verified-base.img")
	imageEvidence, err := copyVerifiedImage(
		configuration.imagePath,
		verifiedImagePath,
		configuration.imageSHA,
	)
	if err != nil {
		return err
	}
	encodedImageEvidence, err := json.MarshalIndent(imageEvidence, "", "  ")
	if err != nil {
		return err
	}
	if err := writePrivateFile(
		filepath.Join(evidenceDirectory, "base-image-provenance.json"),
		append(encodedImageEvidence, '\n'),
	); err != nil {
		return err
	}
	overlayPath := filepath.Join(evidenceDirectory, "guest.qcow2")
	serialPath := filepath.Join(evidenceDirectory, "guest.serial.log")
	qemuLogPath := filepath.Join(evidenceDirectory, "qemu.log")
	qmpPath := filepath.Join(evidenceDirectory, "qmp.sock")
	if commandOutput, err := exec.CommandContext(
		ctx,
		tools.qemuImage.path,
		"create",
		"-q",
		"-f",
		"qcow2",
		"-F",
		"qcow2",
		"-b",
		verifiedImagePath,
		overlayPath,
		"8G",
	).CombinedOutput(); err != nil {
		return fmt.Errorf("create external guest overlay: %w: %s", err, commandOutput)
	}

	var gate atomic.Bool
	guestScript := makeExternalGuestScript(
		base64.StdEncoding.EncodeToString(requestData),
		base64.StdEncoding.EncodeToString([]byte(configuration.externalDirectProbe)),
	)
	if err := writePrivateFile(filepath.Join(evidenceDirectory, "guest-request.json"), requestData); err != nil {
		return fmt.Errorf("retain credential-free guest request: %w", err)
	}
	if err := writePrivateFile(filepath.Join(evidenceDirectory, "guest-script.sh"), []byte(guestScript)); err != nil {
		return fmt.Errorf("retain guest execution boundary: %w", err)
	}
	userData := makeUserData(guestScript)
	seedListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	seedServer := &http.Server{
		Handler: seedHandler(userData, &gate, nil), ReadHeaderTimeout: 5 * time.Second,
	}
	go serve(seedServer, seedListener)
	defer shutdown(seedServer)

	qemuLog, err := os.OpenFile(qemuLogPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	qemuLogClosed := false
	defer func() {
		if !qemuLogClosed {
			_ = qemuLog.Close()
		}
	}()
	netdev := fmt.Sprintf(
		"user,id=opnet,restrict=on,guestfwd=tcp:10.0.2.100:8000-cmd:%s 127.0.0.1 %d,guestfwd=tcp:10.0.2.100:8787-cmd:%s -U %s",
		tools.netcat.path,
		seedListener.Addr().(*net.TCPAddr).Port,
		tools.netcat.path,
		configuration.externalSandboxSocket,
	)
	qemuArgs := []string{
		"-name", "safe-change-shared-history-vm", "-machine", "q35", "-m", "1024", "-smp", "2",
		"-drive", "file=" + overlayPath + ",if=virtio,format=qcow2,cache=none",
		"-display", "none", "-serial", "file:" + serialPath, "-monitor", "none",
		"-qmp", "unix:" + qmpPath + ",server=on,wait=off", "-no-reboot", "-nic", "none",
		"-netdev", netdev, "-device", "virtio-net-pci,netdev=opnet",
		"-smbios", "type=1,serial=ds=nocloud;s=http://10.0.2.100:8000/",
	}
	if configuration.accel == "tcg" {
		qemuArgs = append(qemuArgs, "-accel", "tcg,thread=multi")
	} else {
		qemuArgs = append(qemuArgs, "-accel", "kvm")
	}
	if err := writeQEMUCommand(
		filepath.Join(evidenceDirectory, "qemu-command.json"),
		qemuArgs,
		evidenceDirectory,
		verifiedImagePath,
		configuration.externalSandboxSocket,
	); err != nil {
		return err
	}
	qemu := exec.CommandContext(ctx, tools.qemuSystem.path, qemuArgs...)
	qemu.Stdout, qemu.Stderr = qemuLog, qemuLog
	if err := qemu.Start(); err != nil {
		return err
	}
	qemuDone := make(chan error, 1)
	go func() { qemuDone <- qemu.Wait() }()
	finished := false
	defer func() {
		if !finished && qemu.Process != nil {
			_ = qemu.Process.Kill()
			<-qemuDone
		}
	}()
	if err := writeQEMUProcessCommand(
		filepath.Join(evidenceDirectory, "qemu-process-command.json"),
		qemu.Process.Pid,
		qemuArgs,
		tools.qemuSystem,
		evidenceDirectory,
		verifiedImagePath,
		configuration.externalSandboxSocket,
	); err != nil {
		select {
		case waitErr := <-qemuDone:
			finished = true
			return withQEMULog(
				fmt.Errorf("QEMU exited before process evidence (wait error %v): %w", waitErr, err),
				qemuLogPath,
			)
		default:
		}
		return withQEMULog(err, qemuLogPath)
	}

	qmp, err := dialQMPWithTrace(
		ctx,
		qmpPath,
		filepath.Join(evidenceDirectory, "qmp-protocol.jsonl"),
	)
	if err != nil {
		return withQEMULog(err, qemuLogPath)
	}
	defer qmp.Close()
	if err := waitForText(ctx, serialPath, "SAFE_CHANGE_VM_EXTERNAL_READY", 5*time.Minute); err != nil {
		return withQEMULog(err, qemuLogPath)
	}
	guestKernel := markerFieldFromLast(serialPath, "SAFE_CHANGE_VM_EXTERNAL_READY kernel=")
	if guestKernel == "" {
		return errors.New("shared-control guest kernel marker is missing")
	}
	if err := qmp.command("stop", nil); err != nil {
		return err
	}
	if err := qmp.requireStatus("paused"); err != nil {
		return err
	}
	if err := qmp.human("savevm before_purchase"); err != nil {
		return err
	}
	if err := writeExternalEvent(output, map[string]any{
		"event": "snapshot-ready", "guest_kernel": guestKernel,
	}); err != nil {
		return err
	}
	commands := bufio.NewScanner(input)
	if err := expectExternalCommand(ctx, commands, "start"); err != nil {
		return err
	}
	gate.Store(true)
	if err := qmp.command("cont", nil); err != nil {
		return err
	}
	if err := waitForText(ctx, serialPath, "SAFE_CHANGE_VM_FIRST_SUCCEEDED reused=false", 2*time.Minute); err != nil {
		return err
	}
	if err := writeExternalEvent(output, map[string]any{
		"event": "first-succeeded", "operation_call_id": request.CallID,
	}); err != nil {
		return err
	}
	if err := expectExternalCommand(ctx, commands, "pause"); err != nil {
		return err
	}
	if err := qmp.command("stop", nil); err != nil {
		return err
	}
	if err := qmp.requireStatus("paused"); err != nil {
		return err
	}
	if err := writeExternalEvent(output, map[string]any{
		"event": "paused-after-first", "operation_call_id": request.CallID,
	}); err != nil {
		return err
	}
	if err := expectExternalCommand(ctx, commands, "restore"); err != nil {
		return err
	}
	if err := qmp.human("loadvm before_purchase"); err != nil {
		return err
	}
	if err := qmp.requireStatus("paused"); err != nil {
		return err
	}
	if err := writeExternalEvent(output, map[string]any{
		"event": "restore-loaded-paused", "operation_call_id": request.CallID,
	}); err != nil {
		return err
	}
	if err := expectExternalCommand(ctx, commands, "resume"); err != nil {
		return err
	}
	if err := qmp.command("cont", nil); err != nil {
		return err
	}
	if err := waitForText(ctx, serialPath, "SAFE_CHANGE_VM_RESTORED_SUCCEEDED reused=true", 2*time.Minute); err != nil {
		return err
	}
	select {
	case err := <-qemuDone:
		finished = true
		if err != nil {
			return withQEMULog(err, qemuLogPath)
		}
	case <-time.After(90 * time.Second):
		return errors.New("shared-control guest did not power off after reused Operation")
	case <-ctx.Done():
		return ctx.Err()
	}
	if err := qemuLog.Sync(); err != nil {
		return err
	}
	if err := qemuLog.Close(); err != nil {
		return err
	}
	qemuLogClosed = true

	serial, err := os.ReadFile(serialPath)
	if err != nil {
		return err
	}
	serialText := string(serial)
	if strings.Contains(serialText, "SAFE_CHANGE_VM_DIRECT_EFFECT_REACHABLE") ||
		strings.Count(serialText, "SAFE_CHANGE_VM_DIRECT_EFFECT_BLOCKED") != 2 {
		return errors.New("shared-control guest direct-effect isolation check failed")
	}
	snapshotOutput, err := exec.CommandContext(ctx, tools.qemuImage.path, "snapshot", "-l", overlayPath).CombinedOutput()
	if err != nil || !strings.Contains(string(snapshotOutput), "before_purchase") {
		return fmt.Errorf("shared-control guest snapshot is absent: %w: %s", err, snapshotOutput)
	}
	if err := os.WriteFile(filepath.Join(evidenceDirectory, "snapshots.txt"), snapshotOutput, 0o600); err != nil {
		return err
	}
	projection := map[string]any{
		"schema":                       1,
		"accelerator":                  configuration.accel,
		"base_image_sha256":            configuration.imageSHA,
		"full_linux_guest":             true,
		"guest_kernel":                 guestKernel,
		"machine":                      "q35",
		"memory_mib":                   1024,
		"cpus":                         2,
		"implicit_nics_disabled":       true,
		"network_backend":              "qemu-user-restrict-on",
		"guest_forwards":               []string{"metadata-gate", "host-bound-sandbox"},
		"guest_credential_free":        true,
		"guest_request_fields":         []string{"call_id", "kind", "body"},
		"sandbox_transport":            "host-unix-socket",
		"direct_effect":                "blocked_before_and_after_restore",
		"snapshot":                     "before_purchase",
		"whole_vm_restored":            true,
		"cutover_while_paused":         true,
		"restore_loaded_before_resume": true,
		"first_operation_reused":       false,
		"restored_operation_reused":    true,
		"operation_call_id":            request.CallID,
		"operation_kind":               request.Kind,
		"qemu_pid":                     qemu.Process.Pid,
	}
	encodedProjection, err := json.MarshalIndent(projection, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(evidenceDirectory, "result.json"), append(encodedProjection, '\n'), 0o600); err != nil {
		return err
	}
	if err := removeExternalPrivateFiles(overlayPath, qmpPath, verifiedImagePath); err != nil {
		return err
	}
	completed := make(map[string]any, len(projection)+1)
	for key, value := range projection {
		completed[key] = value
	}
	completed["event"] = "completed"
	return writeExternalEvent(output, completed)
}

func readExternalRequest(path string) ([]byte, externalExecuteRequest, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, externalExecuteRequest{}, err
	}
	if len(data) > 1<<20 {
		return nil, externalExecuteRequest{}, errors.New("external VM request exceeds 1 MiB")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var request externalExecuteRequest
	if err := decoder.Decode(&request); err != nil {
		return nil, externalExecuteRequest{}, err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return nil, externalExecuteRequest{}, errors.New("external VM request has trailing JSON")
	}
	if request.CallID == "" || request.Kind == "" {
		return nil, externalExecuteRequest{}, errors.New("external VM request has an invalid call identity or kind")
	}
	return data, request, nil
}

func requireExternalSandboxSocket(path string) error {
	if len([]byte(path)) >= 108 {
		return errors.New("external sandbox socket path exceeds the Unix socket limit")
	}
	parent, err := os.Lstat(filepath.Dir(path))
	if err != nil || !parent.IsDir() || parent.Mode()&os.ModeSymlink != 0 || parent.Mode().Perm() != 0o700 {
		return errors.New("external sandbox socket parent must be a private real directory")
	}
	resolved, err := filepath.EvalSymlinks(filepath.Dir(path))
	if err != nil || resolved != filepath.Dir(path) {
		return errors.New("external sandbox socket parent must not traverse symlinks")
	}
	info, err := os.Lstat(path)
	if err != nil || info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0o600 {
		return errors.New("external sandbox endpoint must be a private Unix socket")
	}
	for _, item := range []struct {
		label string
		info  os.FileInfo
	}{{"parent", parent}, {"socket", info}} {
		stat, ok := item.info.Sys().(*syscall.Stat_t)
		if !ok || int(stat.Uid) != os.Geteuid() {
			return fmt.Errorf("external sandbox %s must be owned by the current uid", item.label)
		}
	}
	transport := &http.Transport{
		DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			return (&net.Dialer{}).DialContext(ctx, "unix", path)
		},
	}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 3 * time.Second}
	response, err := client.Get("http://sandbox/healthz")
	if err != nil {
		return fmt.Errorf("probe external sandbox endpoint: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("external sandbox endpoint health status is %d", response.StatusCode)
	}
	return nil
}

func requireEmptyPrivateDirectory(path string) error {
	info, err := os.Stat(path)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode().Perm()&0o077 != 0 {
		return errors.New("external VM evidence directory must be private")
	}
	entries, err := os.ReadDir(path)
	if err != nil {
		return err
	}
	if len(entries) != 0 {
		return errors.New("external VM evidence directory must be empty")
	}
	return nil
}

func makeExternalGuestScript(encodedRequest, encodedDirectProbe string) string {
	return fmt.Sprintf(`#!/usr/bin/env bash
set -uo pipefail
log_marker() { printf '%%s\n' "$1" > /dev/ttyS0; }
log_marker "SAFE_CHANGE_VM_EXTERNAL_READY kernel=$(uname -r)"
until curl -fsS --connect-timeout 2 --max-time 3 http://10.0.2.100:8000/go >/dev/null; do sleep 1; done
direct_url=$(printf '%%s' '%s' | base64 -d)
if curl -fsS --connect-timeout 2 --max-time 3 "$direct_url" >/dev/null; then
  log_marker SAFE_CHANGE_VM_DIRECT_EFFECT_REACHABLE
  /sbin/poweroff -f
  exit 1
fi
log_marker SAFE_CHANGE_VM_DIRECT_EFFECT_BLOCKED
printf '%%s' '%s' | base64 -d > /run/safe-change-execute.json
status=$(curl -sS --max-time 45 -o /run/safe-change-response.json -w '%%{http_code}' \
  -X POST -H 'Content-Type: application/json' \
  --data-binary @/run/safe-change-execute.json http://10.0.2.100:8787/v1/execute) || status=transport-error
read -r phase reused < <(python3 -c 'import json; d=json.load(open("/run/safe-change-response.json")); print(d.get("phase", ""), str(bool(d.get("reused", False))).lower())' 2>/dev/null || true)
if [[ "$status" == 200 && "$phase" == succeeded && "$reused" == false ]]; then
  log_marker "SAFE_CHANGE_VM_FIRST_SUCCEEDED reused=false"
  sync
  while true; do sleep 60; done
fi
if [[ "$status" == 200 && "$phase" == succeeded && "$reused" == true ]]; then
  log_marker "SAFE_CHANGE_VM_RESTORED_SUCCEEDED reused=true"
  sync
  /sbin/poweroff -f
  exit 0
fi
log_marker "SAFE_CHANGE_VM_EXTERNAL_UNEXPECTED status=$status phase=$phase reused=$reused"
/sbin/poweroff -f
exit 1
`, encodedDirectProbe, encodedRequest)
}

func expectExternalCommand(ctx context.Context, scanner *bufio.Scanner, expected string) error {
	result := make(chan error, 1)
	go func() {
		if !scanner.Scan() {
			if err := scanner.Err(); err != nil {
				result <- err
				return
			}
			result <- fmt.Errorf("shared-control VM input closed while waiting for %q", expected)
			return
		}
		if strings.TrimSpace(scanner.Text()) != expected {
			result <- fmt.Errorf("shared-control VM expected %q command", expected)
			return
		}
		result <- nil
	}()
	select {
	case err := <-result:
		return err
	case <-ctx.Done():
		return ctx.Err()
	}
}

func writeExternalEvent(writer io.Writer, value map[string]any) error {
	return json.NewEncoder(writer).Encode(value)
}

func writeQEMUCommand(path string, arguments []string, evidenceDirectory, imagePath string, privatePaths ...string) error {
	redacted := redactQEMUArguments(arguments, evidenceDirectory, imagePath, privatePaths...)
	value := map[string]any{
		"schema":     1,
		"executable": "qemu-system-x86_64",
		"arguments":  redacted,
	}
	var encoded bytes.Buffer
	encoder := json.NewEncoder(&encoded)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(value); err != nil {
		return err
	}
	return writePrivateFile(path, encoded.Bytes())
}

func redactQEMUArguments(arguments []string, evidenceDirectory, imagePath string, privatePaths ...string) []string {
	redacted := make([]string, len(arguments))
	for index, argument := range arguments {
		argument = strings.ReplaceAll(argument, evidenceDirectory, "<vm-evidence>")
		argument = strings.ReplaceAll(argument, imagePath, "<verified-base-image>")
		for _, privatePath := range privatePaths {
			argument = strings.ReplaceAll(argument, privatePath, "<host-sandbox-socket>")
		}
		redacted[index] = argument
	}
	return redacted
}

func writeQEMUProcessCommand(
	path string,
	pid int,
	expectedArguments []string,
	expectedExecutable hostTool,
	evidenceDirectory, imagePath string,
	privatePaths ...string,
) error {
	data, err := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", pid))
	if err != nil {
		return fmt.Errorf("read live QEMU process command: %w", err)
	}
	fields := bytes.Split(data, []byte{0})
	if len(fields) > 0 && len(fields[len(fields)-1]) == 0 {
		fields = fields[:len(fields)-1]
	}
	if len(fields) != len(expectedArguments)+1 {
		return fmt.Errorf(
			"live QEMU process command has %d fields, want %d",
			len(fields), len(expectedArguments)+1,
		)
	}
	if string(fields[0]) != expectedExecutable.path {
		return fmt.Errorf(
			"live QEMU argv[0] is %q, want %q",
			fields[0], expectedExecutable.path,
		)
	}
	arguments := make([]string, len(fields)-1)
	for index, field := range fields[1:] {
		arguments[index] = string(field)
	}
	if !slices.Equal(arguments, expectedArguments) {
		return errors.New("live QEMU process command differs from the launched arguments")
	}
	processExecutable, err := os.Open(fmt.Sprintf("/proc/%d/exe", pid))
	if err != nil {
		return fmt.Errorf("read live QEMU executable: %w", err)
	}
	defer processExecutable.Close()
	processIdentity, err := identityForOpenExecutable(processExecutable)
	if err != nil {
		return err
	}
	if processIdentity != expectedExecutable.identity {
		return errors.New("live QEMU executable inode or bytes differ from the resolved host tool")
	}
	value := map[string]any{
		"schema":            1,
		"source":            "linux-proc-cmdline-and-exe-fd",
		"pid":               pid,
		"executable":        "qemu-system-x86_64",
		"executable_path":   expectedExecutable.path,
		"executable_sha256": processIdentity.sha256,
		"arguments": redactQEMUArguments(
			arguments, evidenceDirectory, imagePath, privatePaths...,
		),
	}
	var encoded bytes.Buffer
	encoder := json.NewEncoder(&encoded)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(value); err != nil {
		return err
	}
	return writePrivateFile(path, encoded.Bytes())
}

func markerFieldFromLast(path, marker string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return markerField(string(data), marker)
}

func removeExternalPrivateFiles(paths ...string) error {
	for _, path := range paths {
		if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
	}
	return nil
}

func resolveHostTool(name string) (hostTool, error) {
	path, err := exec.LookPath(name)
	if err != nil {
		return hostTool{}, fmt.Errorf("required host command %q: %w", name, err)
	}
	path, err = filepath.Abs(path)
	if err != nil {
		return hostTool{}, err
	}
	path, err = filepath.EvalSymlinks(path)
	if err != nil {
		return hostTool{}, fmt.Errorf("resolve host command %q: %w", name, err)
	}
	info, err := os.Lstat(path)
	if err != nil {
		return hostTool{}, err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0o111 == 0 {
		return hostTool{}, fmt.Errorf("host command %q is not a regular executable", name)
	}
	executable, err := os.Open(path)
	if err != nil {
		return hostTool{}, err
	}
	identity, identityErr := identityForOpenExecutable(executable)
	closeErr := executable.Close()
	if identityErr != nil || closeErr != nil {
		return hostTool{}, errors.Join(identityErr, closeErr)
	}
	version, err := hostToolVersion(path, name)
	if err != nil {
		return hostTool{}, err
	}
	return hostTool{name: name, path: path, version: version, identity: identity}, nil
}

func hostToolVersion(path, name string) (string, error) {
	arguments := []string{"--version"}
	if name == "nc" {
		arguments = []string{"-h"}
	}
	output, commandErr := exec.Command(path, arguments...).CombinedOutput()
	line := strings.TrimSpace(string(output))
	if index := strings.IndexByte(line, '\n'); index >= 0 {
		line = line[:index]
	}
	if line == "" {
		return "", fmt.Errorf("host command %q returned no version: %w", name, commandErr)
	}
	if commandErr != nil && name != "nc" {
		return "", fmt.Errorf("host command %q version: %w: %s", name, commandErr, line)
	}
	return line, nil
}

func writeExternalHostTools(path string, tools hostTools) error {
	values := map[string]hostTool{
		"qemu-system-x86_64": tools.qemuSystem,
		"qemu-img":           tools.qemuImage,
		"nc":                 tools.netcat,
	}
	records := make(map[string]map[string]string, len(values))
	for name, tool := range values {
		records[name] = map[string]string{
			"path": tool.path, "sha256": tool.identity.sha256, "version": tool.version,
		}
	}
	encoded, err := json.MarshalIndent(map[string]any{
		"schema": 1,
		"tools":  records,
	}, "", "  ")
	if err != nil {
		return err
	}
	return writePrivateFile(path, append(encoded, '\n'))
}

func copyVerifiedImage(sourcePath, destinationPath, expectedSHA string) (map[string]any, error) {
	source, err := os.Open(sourcePath)
	if err != nil {
		return nil, err
	}
	defer source.Close()
	before, err := source.Stat()
	if err != nil {
		return nil, err
	}
	if !before.Mode().IsRegular() {
		return nil, errors.New("verified base-image source is not a regular file")
	}
	destination, err := os.OpenFile(
		destinationPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600,
	)
	if err != nil {
		return nil, err
	}
	complete := false
	defer func() {
		_ = destination.Close()
		if !complete {
			_ = os.Remove(destinationPath)
		}
	}()
	hash := sha256.New()
	written, err := io.Copy(
		io.MultiWriter(destination, hash),
		io.LimitReader(source, maxImageBytes+1),
	)
	if err != nil {
		return nil, err
	}
	if written > maxImageBytes {
		return nil, fmt.Errorf("verified base-image copy exceeds %d bytes", maxImageBytes)
	}
	actualSHA := hex.EncodeToString(hash.Sum(nil))
	if actualSHA != expectedSHA {
		return nil, fmt.Errorf("private base-image copy has SHA-256 %s, want %s", actualSHA, expectedSHA)
	}
	if expectedSHA == defaultImageSHA && written != defaultImageSize {
		return nil, fmt.Errorf("private base-image copy has %d bytes, want %d", written, defaultImageSize)
	}
	after, err := source.Stat()
	if err != nil {
		return nil, err
	}
	if !os.SameFile(before, after) || before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) {
		return nil, errors.New("base-image source changed while it was copied")
	}
	if err := destination.Sync(); err != nil {
		return nil, err
	}
	if err := destination.Close(); err != nil {
		return nil, err
	}
	privateSHA, err := fileSHA(destinationPath)
	if err != nil {
		return nil, err
	}
	info, err := os.Lstat(destinationPath)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm() != 0o600 || privateSHA != expectedSHA {
		return nil, errors.New("private base-image copy failed its post-copy verification")
	}
	complete = true
	return map[string]any{
		"schema":               1,
		"bytes":                written,
		"sha256":               privateSHA,
		"private_backing_copy": true,
		"file_mode":            "0600",
	}, nil
}

func serve(server *http.Server, listener net.Listener) {
	if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Printf("HTTP server failed: %v", err)
	}
}

func shutdown(server *http.Server) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = server.Shutdown(ctx)
}

func randomToken() (string, error) {
	data := make([]byte, 32)
	if _, err := rand.Read(data); err != nil {
		return "", err
	}
	return hex.EncodeToString(data), nil
}

func vmRequirement(id, target string) kernel.Requirement {
	return kernel.Requirement{
		ID: id, Results: map[string]uint32{"written": 1},
		Capacities: map[string]uint32{"slot": 1},
		Kinds: map[string]kernel.KindSpec{
			"vm-write": {
				Costs: map[string]uint32{"slot": 1}, Produces: map[string]uint32{"written": 1},
				RetrySafe: true, Target: target, Method: http.MethodPost,
				ResponseClassifier: gateway.ResponseReceiptV1,
			},
		},
	}
}

type sandboxExecutePayload struct {
	CallID string `json:"call_id"`
	Kind   string `json:"kind"`
	Body   []byte `json:"body,omitempty"`
}

func makeSandboxExecuteJSON(callID, kind string, body []byte) ([]byte, error) {
	return json.Marshal(sandboxExecutePayload{CallID: callID, Kind: kind, Body: body})
}

func validateStandaloneGuestBoundary(requestData []byte, script, providerTarget string) error {
	decoder := json.NewDecoder(bytes.NewReader(requestData))
	decoder.DisallowUnknownFields()
	var request sandboxExecutePayload
	if err := decoder.Decode(&request); err != nil {
		return fmt.Errorf("validate sandbox guest request: %w", err)
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return errors.New("sandbox guest request contains trailing JSON")
	}
	if request.CallID == "" || request.Kind == "" {
		return errors.New("sandbox guest request is missing logical identity")
	}
	for _, forbidden := range []string{
		"Authorization:", "Bearer ", providerTarget,
		base64.StdEncoding.EncodeToString([]byte(providerTarget)), "/v1/charge",
	} {
		if forbidden != "" && strings.Contains(script, forbidden) {
			return fmt.Errorf("sandbox guest script contains host-owned provider data %q", forbidden)
		}
	}
	if bytes.Contains(request.Body, []byte(providerTarget)) {
		return errors.New("sandbox guest payload contains the provider target")
	}
	return nil
}

type syncedTrace struct {
	mu       sync.Mutex
	file     *os.File
	sequence uint64
	closed   bool
}

func openSyncedTrace(path string) (*syncedTrace, error) {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, err
	}
	return &syncedTrace{file: file}, nil
}

func (trace *syncedTrace) Record(event string, details map[string]any) error {
	if trace == nil {
		return errors.New("host trace is nil")
	}
	trace.mu.Lock()
	defer trace.mu.Unlock()
	if trace.closed {
		return errors.New("host supervisor trace is closed")
	}
	if event == "" {
		return errors.New("host supervisor trace event is empty")
	}
	trace.sequence++
	record := map[string]any{
		"sequence": trace.sequence, "time_ns": time.Now().UnixNano(), "event": event,
	}
	if len(details) != 0 {
		record["details"] = details
	}
	if err := json.NewEncoder(trace.file).Encode(record); err != nil {
		return err
	}
	return trace.file.Sync()
}

func (trace *syncedTrace) Close() error {
	if trace == nil {
		return nil
	}
	trace.mu.Lock()
	defer trace.mu.Unlock()
	if trace.closed {
		return nil
	}
	trace.closed = true
	return trace.file.Close()
}

func (trace *syncedTrace) Count() uint64 {
	if trace == nil {
		return 0
	}
	trace.mu.Lock()
	defer trace.mu.Unlock()
	return trace.sequence
}

func writeEvidenceManifest(directory string, names []string) error {
	owned := append([]string(nil), names...)
	sort.Strings(owned)
	var manifest strings.Builder
	for index, name := range owned {
		if name == "" || filepath.Base(name) != name || name == "SHA256SUMS" ||
			(index > 0 && owned[index-1] == name) {
			return fmt.Errorf("invalid evidence manifest name %q", name)
		}
		digest, err := fileSHA(filepath.Join(directory, name))
		if err != nil {
			return err
		}
		fmt.Fprintf(&manifest, "%s  %s\n", digest, name)
	}
	if err := writePrivateFile(filepath.Join(directory, "SHA256SUMS"), []byte(manifest.String())); err != nil {
		return err
	}
	directoryFile, err := os.Open(directory)
	if err != nil {
		return err
	}
	syncErr := directoryFile.Sync()
	closeErr := directoryFile.Close()
	return errors.Join(syncErr, closeErr)
}

func writePrivateFile(path string, data []byte) error {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	if _, err := file.Write(data); err != nil {
		_ = file.Close()
		return err
	}
	if err := file.Sync(); err != nil {
		_ = file.Close()
		return err
	}
	return file.Close()
}

func writeSourceProvenance(directory string, configuration options) error {
	selectedSourcePaths := []string{
		"Makefile", "README.md", "runtime/README.md", "runtime/go.mod", "runtime/go.sum",
		"runtime/cmd/check-vm-evidence", "runtime/cmd/vm-demo",
		"runtime/internal/api", "runtime/internal/certcheck", "runtime/internal/control",
		"runtime/internal/gateway", "runtime/internal/headanchor", "runtime/internal/history",
		"runtime/internal/kernel", "runtime/internal/payment", "runtime/internal/sandboxhost",
		"runtime/internal/vmevidence",
	}
	reproductionCommand := fmt.Sprintf("make runtime-vm-demo VM_ACCEL=%s", configuration.accel)
	if configuration.keep {
		reproductionCommand += " VM_DEMO_ARGS=-keep"
	}
	provenance := map[string]any{
		"schema": 1, "recorded_at": time.Now().UTC().Format(time.RFC3339Nano),
		"public_entrypoint": "make runtime-vm-demo", "runner_arguments": os.Args[1:],
		"reproduction_command":  reproductionCommand,
		"accelerator":           configuration.accel,
		"go_version":            goruntime.Version(),
		"selected_source_paths": selectedSourcePaths,
	}
	if unameOutput, err := exec.Command("uname", "-srmo").CombinedOutput(); err == nil {
		provenance["host_uname"] = strings.TrimSpace(string(unameOutput))
	}
	tools := make([]map[string]any, 0, 3)
	for _, name := range []string{"qemu-system-x86_64", "qemu-img", "nc"} {
		record := map[string]any{"name": name}
		path, err := exec.LookPath(name)
		if err != nil {
			record["error"] = err.Error()
		} else {
			record["path"] = path
			if digest, digestErr := fileSHA(path); digestErr == nil {
				record["sha256"] = digest
			} else {
				record["error"] = digestErr.Error()
			}
		}
		tools = append(tools, record)
	}
	provenance["host_tools"] = tools
	if configuration.accel == "kvm" {
		device, err := os.OpenFile("/dev/kvm", os.O_RDWR, 0)
		provenance["kvm_device_read_write"] = err == nil
		if err != nil {
			provenance["kvm_device_error"] = err.Error()
		} else {
			_ = device.Close()
		}
	}
	rootOutput, rootErr := exec.Command("git", "rev-parse", "--show-toplevel").CombinedOutput()
	if rootErr != nil {
		provenance["source_state"] = "git-unavailable"
		provenance["source_error"] = strings.TrimSpace(string(rootOutput))
	} else {
		root := strings.TrimSpace(string(rootOutput))
		revisionOutput, revisionErr := exec.Command("git", "-C", root, "rev-parse", "HEAD").CombinedOutput()
		statusArguments := []string{"-C", root, "status", "--porcelain", "--untracked-files=all", "--"}
		statusArguments = append(statusArguments, selectedSourcePaths...)
		statusOutput, statusErr := exec.Command("git", statusArguments...).CombinedOutput()
		if revisionErr != nil || statusErr != nil {
			provenance["source_state"] = "git-inspection-failed"
			provenance["source_error"] = strings.TrimSpace(string(append(revisionOutput, statusOutput...)))
		} else {
			status := strings.TrimSpace(string(statusOutput))
			provenance["source_state"] = "git"
			provenance["git_revision"] = strings.TrimSpace(string(revisionOutput))
			provenance["selected_source_clean"] = status == ""
			if status != "" {
				provenance["selected_source_status"] = strings.Split(status, "\n")
			}
		}
	}
	encoded, err := json.MarshalIndent(provenance, "", "  ")
	if err != nil {
		return err
	}
	return writePrivateFile(filepath.Join(directory, "provenance.json"), append(encoded, '\n'))
}

func requireTCPClosed(address string) error {
	connection, err := net.DialTimeout("tcp", address, 250*time.Millisecond)
	if err != nil {
		return nil
	}
	_ = connection.Close()
	return fmt.Errorf("old sandbox endpoint %s remained reachable while VM was paused", address)
}

func ensureImage(ctx context.Context, path, source, expected string) error {
	if info, err := os.Lstat(path); err == nil {
		if !info.Mode().IsRegular() || (expected == defaultImageSHA && info.Size() != defaultImageSize) {
			return fmt.Errorf("cached image %q is not the expected regular file", path)
		}
		actual, err := fileSHA(path)
		if err != nil {
			return err
		}
		if actual != expected {
			return fmt.Errorf("cached image %q has SHA-256 %s, want %s", path, actual, expected)
		}
		log.Printf("using verified VM image %s", path)
		return nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if source == "" {
		return fmt.Errorf("VM image %q is absent and -image-url is empty", path)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	temporary := fmt.Sprintf("%s.partial-%d", path, os.Getpid())
	file, err := os.OpenFile(temporary, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = file.Close()
		if !ok {
			_ = os.Remove(temporary)
		}
	}()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, source, nil)
	if err != nil {
		return err
	}
	response, err := (&http.Client{Timeout: 20 * time.Minute}).Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("download VM image: HTTP %d", response.StatusCode)
	}
	if response.ContentLength > maxImageBytes {
		return fmt.Errorf("VM image is %d bytes, limit is %d", response.ContentLength, maxImageBytes)
	}
	log.Printf("downloading verified VM image from %s", source)
	hash := sha256.New()
	written, err := io.Copy(io.MultiWriter(file, hash), io.LimitReader(response.Body, maxImageBytes+1))
	if err != nil {
		return err
	}
	if written > maxImageBytes {
		return fmt.Errorf("VM image exceeds the %d-byte limit", maxImageBytes)
	}
	actual := hex.EncodeToString(hash.Sum(nil))
	if actual != expected {
		return fmt.Errorf("downloaded VM image has SHA-256 %s, want %s", actual, expected)
	}
	if err := file.Sync(); err != nil {
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	if err := os.Rename(temporary, path); err != nil {
		return err
	}
	directory, err := os.Open(filepath.Dir(path))
	if err != nil {
		return err
	}
	syncErr := directory.Sync()
	closeErr := directory.Close()
	if syncErr != nil || closeErr != nil {
		return errors.Join(syncErr, closeErr)
	}
	ok = true
	return nil
}

func fileSHA(path string) (string, error) {
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

func identityForOpenExecutable(file *os.File) (executableIdentity, error) {
	info, err := file.Stat()
	if err != nil {
		return executableIdentity{}, err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || !info.Mode().IsRegular() {
		return executableIdentity{}, errors.New("executable does not have a regular Linux inode")
	}
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return executableIdentity{}, err
	}
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return executableIdentity{}, err
	}
	return executableIdentity{
		device: uint64(stat.Dev),
		inode:  stat.Ino,
		sha256: hex.EncodeToString(hash.Sum(nil)),
	}, nil
}

func dataSHA256(data []byte) string {
	digest := sha256.Sum256(data)
	return hex.EncodeToString(digest[:])
}

func makeUserData(script string) string {
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

func makeGuestScript(encodedRequest string, directCanaryPort int) string {
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

type seedEvidence struct {
	trace             *syncedTrace
	address           string
	guestScriptSHA256 string
	userDataSHA256    string
}

func seedHandler(userData string, gate *atomic.Bool, evidence *seedEvidence) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/meta-data":
			writer.Header().Set("Content-Type", "text/plain")
			_, _ = io.WriteString(writer, "instance-id: safe-change-vm-1\nlocal-hostname: safe-change-vm\n")
		case "/user-data":
			if evidence != nil {
				if err := evidence.trace.Record("guest-user-data-served", map[string]any{
					"method": request.Method, "path": request.URL.Path, "address": evidence.address,
					"guest_script_sha256": evidence.guestScriptSHA256,
					"user_data_sha256":    evidence.userDataSHA256,
				}); err != nil {
					http.Error(writer, "guest metadata evidence write failed", http.StatusInternalServerError)
					return
				}
			}
			writer.Header().Set("Content-Type", "text/plain")
			_, _ = io.WriteString(writer, userData)
		case "/vendor-data":
			writer.Header().Set("Content-Type", "text/plain")
			_, _ = io.WriteString(writer, "#cloud-config\n{}\n")
		case "/go":
			if !gate.Load() {
				http.Error(writer, "not yet", http.StatusServiceUnavailable)
				return
			}
			if evidence != nil {
				if err := evidence.trace.Record("guest-operation-gate-served", nil); err != nil {
					http.Error(writer, "guest gate evidence write failed", http.StatusInternalServerError)
					return
				}
			}
			_, _ = io.WriteString(writer, "go\n")
		default:
			http.NotFound(writer, request)
		}
	})
}

func markerField(text, marker string) string {
	start := strings.Index(text, marker)
	if start == -1 {
		return ""
	}
	value := text[start+len(marker):]
	if end := strings.IndexAny(value, "\r\n "); end != -1 {
		value = value[:end]
	}
	return value
}

func waitForText(ctx context.Context, path, marker string, timeout time.Duration) error {
	deadline := time.NewTimer(timeout)
	defer deadline.Stop()
	ticker := time.NewTicker(200 * time.Millisecond)
	defer ticker.Stop()
	for {
		data, err := os.ReadFile(path)
		if err == nil && strings.Contains(string(data), marker) {
			log.Printf("guest marker: %s", marker)
			return nil
		}
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-deadline.C:
			return fmt.Errorf("timed out waiting for guest marker %q", marker)
		case <-ticker.C:
		}
	}
}

func withQEMULog(cause error, path string) error {
	data, _ := os.ReadFile(path)
	if len(data) > 8192 {
		data = data[len(data)-8192:]
	}
	return fmt.Errorf("%w; QEMU log: %s", cause, data)
}

type qmpClient struct {
	connection net.Conn
	decoder    *json.Decoder
	encoder    *json.Encoder
	trace      *os.File
	traceSeq   uint64
	nextID     uint64
}

func dialQMP(ctx context.Context, path string) (*qmpClient, error) {
	return dialQMPWithTrace(ctx, path, "")
}

func dialQMPWithTrace(ctx context.Context, path, tracePath string) (*qmpClient, error) {
	var connection net.Conn
	var err error
	for connection == nil {
		connection, err = (&net.Dialer{}).DialContext(ctx, "unix", path)
		if err == nil {
			break
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(100 * time.Millisecond):
		}
	}
	client := &qmpClient{
		connection: connection,
		decoder:    json.NewDecoder(connection),
		encoder:    json.NewEncoder(connection),
	}
	if tracePath != "" {
		client.trace, err = os.OpenFile(
			tracePath,
			os.O_CREATE|os.O_EXCL|os.O_WRONLY,
			0o600,
		)
		if err != nil {
			connection.Close()
			return nil, err
		}
	}
	var greeting map[string]json.RawMessage
	if err := client.decoder.Decode(&greeting); err != nil {
		client.Close()
		return nil, err
	}
	if err := client.record("server_to_client", greeting); err != nil {
		client.Close()
		return nil, err
	}
	if _, ok := greeting["QMP"]; !ok {
		client.Close()
		return nil, errors.New("QMP greeting is missing")
	}
	if err := client.command("qmp_capabilities", nil); err != nil {
		client.Close()
		return nil, err
	}
	return client, nil
}

func (q *qmpClient) Close() error {
	connectionErr := q.connection.Close()
	var traceErr error
	if q.trace != nil {
		traceErr = q.trace.Close()
		q.trace = nil
	}
	return errors.Join(connectionErr, traceErr)
}

func (q *qmpClient) record(direction string, payload any) error {
	if q.trace == nil {
		return nil
	}
	q.traceSeq++
	record := map[string]any{
		"sequence":  q.traceSeq,
		"time_ns":   time.Now().UnixNano(),
		"direction": direction,
		"payload":   payload,
	}
	if err := json.NewEncoder(q.trace).Encode(record); err != nil {
		return err
	}
	return q.trace.Sync()
}

func (q *qmpClient) command(name string, arguments any) error {
	_, err := q.commandResult(name, arguments)
	return err
}

func (q *qmpClient) requireStatus(expected string) error {
	data, err := q.commandResult("query-status", nil)
	if err != nil {
		return err
	}
	var status struct {
		Running bool   `json:"running"`
		Status  string `json:"status"`
	}
	if err := json.Unmarshal(data, &status); err != nil {
		return err
	}
	if status.Status != expected || (expected == "paused" && status.Running) {
		return fmt.Errorf("QEMU status is %q (running=%t), want %q", status.Status, status.Running, expected)
	}
	return nil
}

func (q *qmpClient) commandResult(name string, arguments any) (json.RawMessage, error) {
	q.nextID++
	id := fmt.Sprintf("command-%d", q.nextID)
	request := map[string]any{"execute": name, "id": id}
	if arguments != nil {
		request["arguments"] = arguments
	}
	if err := q.record("client_to_server", request); err != nil {
		return nil, err
	}
	if err := q.encoder.Encode(request); err != nil {
		return nil, err
	}
	for {
		var raw map[string]json.RawMessage
		if err := q.decoder.Decode(&raw); err != nil {
			return nil, err
		}
		if err := q.record("server_to_client", raw); err != nil {
			return nil, err
		}
		var response struct {
			ID     string          `json:"id"`
			Return json.RawMessage `json:"return"`
			Error  *struct {
				Class string `json:"class"`
				Desc  string `json:"desc"`
			} `json:"error"`
		}
		encoded, err := json.Marshal(raw)
		if err != nil {
			return nil, err
		}
		if err := json.Unmarshal(encoded, &response); err != nil {
			return nil, err
		}
		if response.ID != id {
			continue
		}
		if response.Error != nil {
			return nil, fmt.Errorf("QMP %s: %s: %s", name, response.Error.Class, response.Error.Desc)
		}
		return response.Return, nil
	}
}

func (q *qmpClient) human(command string) error {
	result, err := q.commandResult("human-monitor-command", map[string]string{"command-line": command})
	if err != nil {
		return err
	}
	var output string
	if err := json.Unmarshal(result, &output); err != nil {
		return fmt.Errorf("decode HMP %q response: %w", command, err)
	}
	if strings.TrimSpace(output) != "" {
		return fmt.Errorf("HMP %q failed: %s", command, strings.TrimSpace(output))
	}
	return nil
}
