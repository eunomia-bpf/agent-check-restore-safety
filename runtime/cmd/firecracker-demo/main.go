// Command firecracker-demo runs the shared-control VM protocol on two real
// Firecracker processes. The first process creates a paused snapshot before
// an external Operation. The second process loads that snapshot paused, binds
// a new host-owned vsock path, and resumes only after the new sandbox endpoint
// exists. The guest has no network interface and no control credential.
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/firecracker"
	"golang.org/x/sys/unix"
)

const (
	officialFirecrackerVersion = "1.16.1"
	officialFirecrackerSHA256  = "2fd0171309af7e24cf8dafc8a6f921c1434c49b5f9349bb996b7ed0a4deb8aa7"
	officialKernelSHA256       = "e20e46d0c36c55c0d1014eb20576171b3f3d922260d9f792017aeff53af3d4f2"
	officialKernelVersion      = "6.1.155"
	guestCID                   = uint32(3)
	operationPort              = uint32(8787)
	guestMemoryMiB             = 128
	maxRequestBytes            = 1 << 20
)

type options struct {
	accel            string
	timeout          time.Duration
	firecrackerPath  string
	firecrackerSHA   string
	hostInstanceIDG1 string
	hostInstanceIDG3 string
	kernelPath       string
	kernelSHA        string
	guestPath        string
	sandboxSocket    string
	requestPath      string
	directProbe      string
	evidenceDir      string
}

type generation struct {
	number         uint64
	id             string
	basePath       string
	apiPath        string
	process        *firecracker.Process
	client         *firecracker.Client
	gate           *firecracker.Gate
	relay          *firecracker.Relay
	logFile        *os.File
	apiTrace       *os.File
	gateTrace      *os.File
	relayTrace     *os.File
	startedNS      int64
	stoppedNS      int64
	exitConfirmed  bool
	termination    firecracker.TerminationDisposition
	socketsRemoved bool
	apiSocket      socketRecord
	vsockBackend   socketRecord
}

type socketRecord struct {
	Name   string `json:"name"`
	Device uint64 `json:"device"`
	Inode  uint64 `json:"inode"`
	Mode   uint32 `json:"mode"`
	UID    uint32 `json:"uid"`
}

type processRecord struct {
	Generation       uint64       `json:"generation"`
	ID               string       `json:"id"`
	PID              int          `json:"pid"`
	Executable       string       `json:"executable"`
	ExecutableSHA256 string       `json:"executable_sha256"`
	Device           uint64       `json:"device"`
	Inode            uint64       `json:"inode"`
	StartTimeTicks   uint64       `json:"start_time_ticks"`
	StartedTimeNS    int64        `json:"started_time_ns"`
	StoppedTimeNS    int64        `json:"stopped_time_ns"`
	ExitConfirmed    bool         `json:"exit_confirmed"`
	Termination      string       `json:"termination"`
	APISocket        socketRecord `json:"api_socket"`
	VsockBackend     socketRecord `json:"vsock_backend"`
}

type artifactRecord struct {
	Name   string `json:"name"`
	Size   int64  `json:"size"`
	Mode   uint32 `json:"mode"`
	SHA256 string `json:"sha256"`
}

type sealedArtifactRecord struct {
	Artifact   artifactRecord `json:"artifact"`
	ChildFD    int            `json:"child_fd"`
	LinuxSeals int            `json:"linux_seals"`
}

type outcomeProjection struct {
	Phase       string `json:"phase"`
	Reused      bool   `json:"reused"`
	OperationID string `json:"operation_id"`
}

type supervisorTrace struct {
	file     *os.File
	origin   time.Time
	sequence uint64
	failure  error
}

func main() {
	defaultFirecracker, defaultKernel := defaultAssets()
	var config options
	flag.StringVar(&config.accel, "accel", "kvm", "compatibility flag; Firecracker requires kvm")
	flag.DurationVar(&config.timeout, "timeout", 10*time.Minute, "whole-demo timeout")
	flag.StringVar(&config.firecrackerPath, "firecracker", defaultFirecracker, "pinned Firecracker executable")
	flag.StringVar(&config.firecrackerSHA, "firecracker-sha256", officialFirecrackerSHA256, "required Firecracker executable SHA-256")
	flag.StringVar(&config.hostInstanceIDG1, "host-instance-id-g1", "", "exact first-generation Firecracker instance ID (random by default)")
	flag.StringVar(&config.hostInstanceIDG3, "host-instance-id-g3", "", "exact restored-generation Firecracker instance ID (random by default)")
	flag.StringVar(&config.kernelPath, "kernel", defaultKernel, "pinned Firecracker guest kernel")
	flag.StringVar(&config.kernelSHA, "kernel-sha256", officialKernelSHA256, "required guest-kernel SHA-256")
	flag.StringVar(&config.guestPath, "guest", "", "static firecracker-guest executable")
	flag.StringVar(&config.sandboxSocket, "external-sandbox-socket", "", "host-owned credential-free sandbox Unix socket")
	flag.StringVar(&config.requestPath, "external-request", "", "strict three-field execute request")
	flag.StringVar(&config.directProbe, "external-direct-probe", "", "effect URL retained only to prove that no guest network path exists")
	flag.StringVar(&config.evidenceDir, "external-evidence-dir", "", "empty private evidence directory")
	flag.Parse()
	if err := run(config, os.Stdin, os.Stdout); err != nil {
		log.Printf("Firecracker demo failed: %v", err)
		os.Exit(1)
	}
}

func defaultAssets() (string, string) {
	cache, err := os.UserCacheDir()
	if err != nil {
		return "", ""
	}
	root := filepath.Join(cache, "safe-change-runtime", "firecracker")
	return filepath.Join(root, "v1.16.1", "release-v1.16.1-x86_64", "firecracker-v1.16.1-x86_64"),
		filepath.Join(root, "assets-v1.15", "vmlinux-6.1.155")
}

func run(config options, input io.Reader, output io.Writer) (returnErr error) {
	if runtime.GOOS != "linux" || runtime.GOARCH != "amd64" {
		return errors.New("the pinned Firecracker backend currently requires Linux amd64")
	}
	if config.accel != "kvm" {
		return errors.New("Firecracker is KVM-only; -accel must be kvm")
	}
	if config.timeout <= 0 {
		return errors.New("timeout must be positive")
	}
	if config.hostInstanceIDG1 != "" && config.hostInstanceIDG1 == config.hostInstanceIDG3 {
		return errors.New("first and restored Firecracker instance IDs must differ")
	}
	for label, value := range map[string]string{
		"Firecracker executable": config.firecrackerPath,
		"guest kernel":           config.kernelPath,
		"guest executable":       config.guestPath,
		"sandbox socket":         config.sandboxSocket,
		"guest request":          config.requestPath,
		"direct probe":           config.directProbe,
		"evidence directory":     config.evidenceDir,
	} {
		if value == "" {
			return fmt.Errorf("%s is required", label)
		}
	}
	probe, err := url.Parse(config.directProbe)
	if err != nil || probe.Scheme != "http" || probe.Host == "" || probe.User != nil || probe.Fragment != "" {
		return errors.New("external direct probe must be an absolute plain HTTP URL")
	}
	if err := requireKVM(); err != nil {
		return err
	}
	for _, pointer := range []*string{&config.firecrackerPath, &config.kernelPath, &config.guestPath, &config.sandboxSocket, &config.requestPath, &config.evidenceDir} {
		absolute, err := filepath.Abs(*pointer)
		if err != nil {
			return err
		}
		*pointer = filepath.Clean(absolute)
	}
	if err := requireEmptyPrivateDirectory(config.evidenceDir); err != nil {
		return err
	}
	firecrackerArtifact, err := verifyArtifact("firecracker-v1.16.1-x86_64", config.firecrackerPath, config.firecrackerSHA, true)
	if err != nil {
		return err
	}
	kernelArtifact, err := verifyArtifact("vmlinux-"+officialKernelVersion, config.kernelPath, config.kernelSHA, false)
	if err != nil {
		return err
	}
	guestArtifact, err := verifyArtifact("firecracker-guest", config.guestPath, "", true)
	if err != nil {
		return err
	}
	request, err := os.ReadFile(config.requestPath)
	if err != nil {
		return err
	}
	if len(request) == 0 || len(request) > maxRequestBytes {
		return errors.New("guest request must contain 1 byte to 1 MiB")
	}
	if err := writePrivateFile(filepath.Join(config.evidenceDir, "guest-request.json"), request, 0o400); err != nil {
		return err
	}
	guestBinary, err := os.ReadFile(config.guestPath)
	if err != nil {
		return err
	}
	guestDigest := sha256.Sum256(guestBinary)
	if hex.EncodeToString(guestDigest[:]) != guestArtifact.SHA256 {
		return errors.New("guest executable changed after verification")
	}
	initramfsPath := filepath.Join(config.evidenceDir, "guest-initramfs.cpio")
	initramfs, err := os.OpenFile(initramfsPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	buildErr := firecracker.BuildInitramfs(initramfs, guestBinary, request)
	syncErr := initramfs.Sync()
	closeErr := initramfs.Close()
	if buildErr != nil || syncErr != nil || closeErr != nil {
		return errors.Join(buildErr, syncErr, closeErr)
	}
	if err := os.Chmod(initramfsPath, 0o400); err != nil {
		return err
	}
	initramfsArtifact, err := artifactForPath("guest-initramfs.cpio", initramfsPath)
	if err != nil {
		return err
	}
	sealedKernel, sealedKernelRecord, err := sealArtifact("sealed-kernel", config.kernelPath, 4)
	if err != nil {
		return err
	}
	defer sealedKernel.Close()
	sealedInitramfs, sealedInitramfsRecord, err := sealArtifact("sealed-initramfs", initramfsPath, 5)
	if err != nil {
		return err
	}
	defer sealedInitramfs.Close()
	if sealedKernelRecord.Artifact.SHA256 != kernelArtifact.SHA256 ||
		sealedInitramfsRecord.Artifact.SHA256 != initramfsArtifact.SHA256 {
		return errors.New("sealed boot inputs differ from their verified sources")
	}
	if err := writeJSON(filepath.Join(config.evidenceDir, "assets.json"), map[string]any{
		"schema":              1,
		"firecracker_version": officialFirecrackerVersion,
		"snapshot_format":     "v10.0.0",
		"firecracker":         firecrackerArtifact,
		"kernel":              kernelArtifact,
		"guest":               guestArtifact,
		"initramfs":           initramfsArtifact,
		"sealed_boot_inputs":  []sealedArtifactRecord{sealedKernelRecord, sealedInitramfsRecord},
		"kernel_source":       "official-firecracker-ci-v1.15",
	}); err != nil {
		return err
	}

	ctx, cancel := context.WithTimeout(context.Background(), config.timeout)
	defer cancel()
	supervisor, err := openSupervisorTrace(filepath.Join(config.evidenceDir, "firecracker-supervisor.jsonl"))
	if err != nil {
		return err
	}
	defer func() { returnErr = errors.Join(returnErr, supervisor.Close()) }()
	if err := supervisor.Record("run-started", nil, nil); err != nil {
		return err
	}
	commands := bufio.NewScanner(input)
	commands.Buffer(make([]byte, 1024), 64<<10)
	timeline := map[string]int64{"run_start_ns": time.Now().UnixNano()}
	var firstGeneration, restoredGeneration *generation
	defer func() {
		cleanupErr := errors.Join(cleanupGeneration(firstGeneration), cleanupGeneration(restoredGeneration))
		returnErr = errors.Join(returnErr, cleanupErr)
	}()

	firstGeneration, err = startGeneration(ctx, config, 1, config.hostInstanceIDG1, []*os.File{sealedKernel, sealedInitramfs})
	if err != nil {
		return err
	}
	if err := requireProcessArtifact(firstGeneration, config.firecrackerPath, firecrackerArtifact.SHA256); err != nil {
		return err
	}
	if err := supervisor.Record("process-started", firstGeneration, nil); err != nil {
		return err
	}
	if err := requireInstanceState(ctx, firstGeneration, firecracker.StateNotStarted); err != nil {
		return err
	}
	if err := firstGeneration.client.Configure(ctx,
		firecracker.MachineConfig{VCPUCount: 1, MemSizeMiB: guestMemoryMiB, SMT: false, TrackDirtyPages: false},
		firecracker.BootSource{
			KernelImagePath: "/proc/self/fd/4",
			InitrdPath:      "/proc/self/fd/5",
			BootArgs:        "console=ttyS0 reboot=k panic=1 pci=off rdinit=/init",
		},
		firecracker.VsockDevice{GuestCID: guestCID, UDSPath: firstGeneration.basePath},
	); err != nil {
		return err
	}
	firstGeneration.vsockBackend, err = captureSocket(firstGeneration.basePath)
	if err != nil {
		return fmt.Errorf("capture first vsock backend: %w", err)
	}
	if err := firstGeneration.client.Start(ctx); err != nil {
		return err
	}
	if err := firstGeneration.gate.WaitReady(ctx); err != nil {
		return fmt.Errorf("wait for first guest READY: %w", err)
	}
	if err := supervisor.Record("guest-ready", firstGeneration, nil); err != nil {
		return err
	}
	timeline["first_guest_ready_ns"] = time.Now().UnixNano()
	if err := firstGeneration.client.Pause(ctx); err != nil {
		return err
	}
	if err := requireInstanceState(ctx, firstGeneration, firecracker.StatePaused); err != nil {
		return err
	}
	snapshotStatePath := filepath.Join(config.evidenceDir, "snapshot.state")
	snapshotMemoryPath := filepath.Join(config.evidenceDir, "snapshot.memory")
	if err := firstGeneration.client.CreateFullSnapshot(ctx, snapshotStatePath, snapshotMemoryPath); err != nil {
		return err
	}
	if err := syncPaths(snapshotStatePath, snapshotMemoryPath); err != nil {
		return err
	}
	if err := os.Chmod(snapshotStatePath, 0o400); err != nil {
		return err
	}
	if err := os.Chmod(snapshotMemoryPath, 0o400); err != nil {
		return err
	}
	snapshotStateBefore, err := artifactForPath("snapshot.state", snapshotStatePath)
	if err != nil {
		return err
	}
	snapshotMemoryBefore, err := artifactForPath("snapshot.memory", snapshotMemoryPath)
	if err != nil {
		return err
	}
	sealedSnapshotState, sealedSnapshotStateRecord, err := sealArtifact("sealed-snapshot-state", snapshotStatePath, 4)
	if err != nil {
		return err
	}
	defer sealedSnapshotState.Close()
	sealedSnapshotMemory, sealedSnapshotMemoryRecord, err := sealArtifact("sealed-snapshot-memory", snapshotMemoryPath, 5)
	if err != nil {
		return err
	}
	defer sealedSnapshotMemory.Close()
	if sealedSnapshotStateRecord.Artifact.SHA256 != snapshotStateBefore.SHA256 ||
		sealedSnapshotMemoryRecord.Artifact.SHA256 != snapshotMemoryBefore.SHA256 {
		return errors.New("sealed snapshot inputs differ from the paused snapshot")
	}
	timeline["snapshot_created_ns"] = time.Now().UnixNano()
	if err := supervisor.Record("snapshot-created-paused", firstGeneration, map[string]any{
		"state_sha256": snapshotStateBefore.SHA256, "memory_sha256": snapshotMemoryBefore.SHA256,
	}); err != nil {
		return err
	}
	firstGeneration.relay, err = armOperationRelay(firstGeneration, config.sandboxSocket)
	if err != nil {
		return err
	}
	if err := verifySocketRecord(firstGeneration.basePath, firstGeneration.vsockBackend); err != nil {
		return err
	}
	timeline["first_relay_armed_ns"] = time.Now().UnixNano()
	if err := supervisor.Record("relay-armed-paused", firstGeneration, nil); err != nil {
		return err
	}
	if err := emit(output, map[string]any{
		"event": "snapshot-ready", "guest_kernel": officialKernelVersion,
		"firecracker_version": officialFirecrackerVersion,
	}); err != nil {
		return err
	}
	if err := expectCommand(ctx, commands, "start"); err != nil {
		return err
	}
	if err := verifySocketRecord(firstGeneration.basePath, firstGeneration.vsockBackend); err != nil {
		return err
	}
	if err := firstGeneration.gate.Allow(); err != nil {
		return err
	}
	if err := firstGeneration.client.Resume(ctx); err != nil {
		return err
	}
	timeline["first_vm_resumed_ns"] = time.Now().UnixNano()
	if err := supervisor.Record("vm-resumed", firstGeneration, nil); err != nil {
		return err
	}
	firstResult, err := firstGeneration.gate.WaitResult(ctx)
	if err != nil {
		return fmt.Errorf("wait for first guest result: %w", err)
	}
	firstOutcome, err := requireOutcome(firstResult)
	if err != nil {
		return err
	}
	timeline["first_operation_succeeded_ns"] = time.Now().UnixNano()
	if err := supervisor.Record("operation-result", firstGeneration, map[string]any{
		"operation_id": firstOutcome.OperationID, "reused": firstOutcome.Reused,
	}); err != nil {
		return err
	}
	if err := emit(output, map[string]any{
		"event": "first-succeeded", "operation_call_id": requestCallID(request),
	}); err != nil {
		return err
	}
	if err := expectCommand(ctx, commands, "pause"); err != nil {
		return err
	}
	if err := firstGeneration.client.Pause(ctx); err != nil {
		return err
	}
	if err := requireInstanceState(ctx, firstGeneration, firecracker.StatePaused); err != nil {
		return err
	}
	timeline["first_vm_paused_ns"] = time.Now().UnixNano()
	if err := supervisor.Record("vm-paused", firstGeneration, nil); err != nil {
		return err
	}
	if err := firstGeneration.relay.Close(); err != nil {
		return err
	}
	firstGeneration.relay = nil
	if err := firstGeneration.gate.Close(); err != nil {
		return err
	}
	firstGeneration.gate = nil
	if err := stopGeneration(ctx, firstGeneration); err != nil {
		return err
	}
	if firstGeneration.termination != firecracker.TerminationBySupervisor {
		return errors.New("first Firecracker exited before supervisor termination")
	}
	timeline["first_vm_stopped_ns"] = firstGeneration.stoppedNS
	if err := supervisor.Record("process-stopped", firstGeneration, map[string]any{"exit_confirmed": firstGeneration.exitConfirmed, "termination": firstGeneration.termination}); err != nil {
		return err
	}
	if err := emit(output, map[string]any{
		"event": "paused-after-first", "operation_call_id": requestCallID(request),
	}); err != nil {
		return err
	}
	if err := expectCommand(ctx, commands, "restore"); err != nil {
		return err
	}
	restoredGeneration, err = startGeneration(ctx, config, 3, config.hostInstanceIDG3, []*os.File{sealedSnapshotState, sealedSnapshotMemory})
	if err != nil {
		return err
	}
	if err := requireProcessArtifact(restoredGeneration, config.firecrackerPath, firecrackerArtifact.SHA256); err != nil {
		return err
	}
	if err := supervisor.Record("process-started", restoredGeneration, nil); err != nil {
		return err
	}
	if err := requireInstanceState(ctx, restoredGeneration, firecracker.StateNotStarted); err != nil {
		return err
	}
	if err := restoredGeneration.client.LoadSnapshotPaused(ctx, firecracker.LoadSnapshotConfig{
		SnapshotPath:  "/proc/self/fd/4",
		MemoryBackend: firecracker.MemoryBackend{BackendType: "File", BackendPath: "/proc/self/fd/5"},
		VsockOverride: &firecracker.VsockOverride{UDSPath: restoredGeneration.basePath},
		Resume:        false,
	}); err != nil {
		return err
	}
	restoredGeneration.vsockBackend, err = captureSocket(restoredGeneration.basePath)
	if err != nil {
		return fmt.Errorf("capture restored vsock backend: %w", err)
	}
	if err := requireInstanceState(ctx, restoredGeneration, firecracker.StatePaused); err != nil {
		return err
	}
	timeline["restore_loaded_paused_ns"] = time.Now().UnixNano()
	if err := supervisor.Record("snapshot-loaded-paused", restoredGeneration, map[string]any{
		"state_sha256":  sealedSnapshotStateRecord.Artifact.SHA256,
		"memory_sha256": sealedSnapshotMemoryRecord.Artifact.SHA256,
	}); err != nil {
		return err
	}
	if err := emit(output, map[string]any{
		"event": "restore-loaded-paused", "operation_call_id": requestCallID(request),
	}); err != nil {
		return err
	}
	if err := expectCommand(ctx, commands, "resume"); err != nil {
		return err
	}
	restoredGeneration.relay, err = armOperationRelay(restoredGeneration, config.sandboxSocket)
	if err != nil {
		return err
	}
	if err := verifySocketRecord(restoredGeneration.basePath, restoredGeneration.vsockBackend); err != nil {
		return err
	}
	timeline["restored_relay_armed_ns"] = time.Now().UnixNano()
	if err := supervisor.Record("relay-armed-paused", restoredGeneration, nil); err != nil {
		return err
	}
	if err := restoredGeneration.gate.Allow(); err != nil {
		return err
	}
	if err := restoredGeneration.client.Resume(ctx); err != nil {
		return err
	}
	timeline["restored_vm_resumed_ns"] = time.Now().UnixNano()
	if err := supervisor.Record("vm-resumed", restoredGeneration, nil); err != nil {
		return err
	}
	restoredResult, err := restoredGeneration.gate.WaitResult(ctx)
	if err != nil {
		return fmt.Errorf("wait for restored guest result: %w", err)
	}
	restoredOutcome, err := requireOutcome(restoredResult)
	if err != nil {
		return err
	}
	if !restoredOutcome.Reused {
		return errors.New("restored guest did not reuse the durable Operation outcome")
	}
	if firstOutcome.OperationID == "" || restoredOutcome.OperationID != firstOutcome.OperationID {
		return errors.New("restored guest did not reuse the first stable Operation identity")
	}
	if err := writeJSON(filepath.Join(config.evidenceDir, "guest-results.json"), map[string]any{
		"schema":   1,
		"first":    firstResult,
		"restored": restoredResult,
	}); err != nil {
		return err
	}
	timeline["restored_operation_succeeded_ns"] = time.Now().UnixNano()
	if err := supervisor.Record("operation-result", restoredGeneration, map[string]any{
		"operation_id": restoredOutcome.OperationID, "reused": restoredOutcome.Reused,
	}); err != nil {
		return err
	}
	// Record whether the supervisor stopped the exact pidfd-bound successor or
	// observed that it had already exited after the final RESULT crossed the gate.
	if err := stopGeneration(ctx, restoredGeneration); err != nil {
		return err
	}
	timeline["restored_vm_stopped_ns"] = restoredGeneration.stoppedNS
	if err := supervisor.Record("process-stopped", restoredGeneration, map[string]any{"exit_confirmed": restoredGeneration.exitConfirmed, "termination": restoredGeneration.termination}); err != nil {
		return err
	}
	if err := restoredGeneration.relay.Close(); err != nil {
		return err
	}
	restoredGeneration.relay = nil
	if err := restoredGeneration.gate.Close(); err != nil {
		return err
	}
	restoredGeneration.gate = nil
	snapshotStateAfter, err := artifactForPath("snapshot.state", snapshotStatePath)
	if err != nil {
		return err
	}
	snapshotMemoryAfter, err := artifactForPath("snapshot.memory", snapshotMemoryPath)
	if err != nil {
		return err
	}
	if snapshotStateBefore != snapshotStateAfter || snapshotMemoryBefore != snapshotMemoryAfter {
		return errors.New("Firecracker snapshot artifacts changed during restore")
	}
	if err := syncGenerationEvidence(firstGeneration, restoredGeneration); err != nil {
		return err
	}
	if err := writeJSON(filepath.Join(config.evidenceDir, "snapshot-provenance.json"), map[string]any{
		"schema": 1, "state_before": snapshotStateBefore, "state_after": snapshotStateAfter,
		"memory_before": snapshotMemoryBefore, "memory_after": snapshotMemoryAfter,
		"sealed_load_inputs": []sealedArtifactRecord{sealedSnapshotStateRecord, sealedSnapshotMemoryRecord},
		"load_count":         1, "original_resumed_after_snapshot": true,
		"original_stopped_before_successor_start": firstGeneration.stoppedNS <= restoredGeneration.startedNS,
	}); err != nil {
		return err
	}
	if err := writeJSON(filepath.Join(config.evidenceDir, "firecracker-processes.json"), map[string]any{
		"schema":    1,
		"processes": []processRecord{recordProcess(firstGeneration), recordProcess(restoredGeneration)},
	}); err != nil {
		return err
	}
	successorTermination, err := terminationSummary(restoredGeneration.termination)
	if err != nil {
		return err
	}
	result := map[string]any{
		"schema":                       1,
		"backend":                      "firecracker",
		"accelerator":                  "kvm",
		"nested_virtualization":        hostReportsHypervisor(),
		"firecracker_version":          officialFirecrackerVersion,
		"guest_kernel":                 officialKernelVersion,
		"microvm_processes":            2,
		"distinct_processes":           firstGeneration.process.PID() != restoredGeneration.process.PID(),
		"firecracker_pids":             []int{firstGeneration.process.PID(), restoredGeneration.process.PID()},
		"guest_cid":                    guestCID,
		"network_interfaces":           0,
		"root_block_devices":           0,
		"guest_credential_free":        true,
		"guest_request_fields":         []string{"call_id", "kind", "body"},
		"sandbox_transport":            "generation-bound-vsock-to-host-unix-socket",
		"direct_effect":                "unreachable-no-guest-network-device",
		"direct_probe_host":            probe.Host,
		"snapshot_loads":               1,
		"successor_termination":        successorTermination,
		"restore_loaded_before_resume": true,
		"relay_armed_while_paused":     timeline["first_relay_armed_ns"] < timeline["first_vm_resumed_ns"] && timeline["restored_relay_armed_ns"] < timeline["restored_vm_resumed_ns"],
		"first_operation_reused":       firstOutcome.Reused,
		"restored_operation_reused":    restoredOutcome.Reused,
		"operation_id":                 firstOutcome.OperationID,
		"operation_call_id":            requestCallID(request),
	}
	if err := writeJSON(filepath.Join(config.evidenceDir, "result.json"), result); err != nil {
		return err
	}
	timeline["run_completed_ns"] = time.Now().UnixNano()
	if err := supervisor.Record("run-completed", nil, nil); err != nil {
		return err
	}
	if err := writeJSON(filepath.Join(config.evidenceDir, "timeline.json"), timeline); err != nil {
		return err
	}
	completed := make(map[string]any, len(result)+1)
	for key, value := range result {
		completed[key] = value
	}
	completed["event"] = "completed"
	return emit(output, completed)
}

func startGeneration(ctx context.Context, config options, number uint64, instanceID string, inheritedFiles []*os.File) (*generation, error) {
	var err error
	label := fmt.Sprintf("g%d", number)
	if instanceID == "" {
		token, err := randomHex(8)
		if err != nil {
			return nil, err
		}
		instanceID = "safe-change-" + label + "-" + token
	}
	generation := &generation{
		number:   number,
		id:       instanceID,
		basePath: filepath.Join(config.evidenceDir, "vsock-"+label),
		apiPath:  filepath.Join(config.evidenceDir, "api-"+label+".sock"),
	}
	open := func(name string) (*os.File, error) {
		return os.OpenFile(filepath.Join(config.evidenceDir, name), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	}
	if generation.logFile, err = open("firecracker-" + label + ".log"); err != nil {
		return nil, err
	}
	if generation.apiTrace, err = open("firecracker-api-" + label + ".jsonl"); err != nil {
		_ = generation.logFile.Close()
		return nil, err
	}
	if generation.gateTrace, err = open("firecracker-gate-" + label + ".jsonl"); err != nil {
		_ = generation.logFile.Close()
		_ = generation.apiTrace.Close()
		return nil, err
	}
	if generation.relayTrace, err = open("firecracker-relay-" + label + ".jsonl"); err != nil {
		_ = generation.logFile.Close()
		_ = generation.apiTrace.Close()
		_ = generation.gateTrace.Close()
		return nil, err
	}
	generation.process, err = firecracker.StartProcess(ctx, firecracker.ProcessConfig{
		Binary:             config.firecrackerPath,
		ExecutableSHA256:   config.firecrackerSHA,
		APISocket:          generation.apiPath,
		ID:                 generation.id,
		Env:                []string{"PATH=/usr/bin:/bin", "LANG=C"},
		Dir:                config.evidenceDir,
		Stdout:             generation.logFile,
		Stderr:             generation.logFile,
		StartupTimeout:     10 * time.Second,
		TerminationTimeout: 5 * time.Second,
		InheritedFiles:     inheritedFiles,
	})
	if err != nil {
		_ = cleanupGeneration(generation)
		return nil, err
	}
	generation.startedNS = time.Now().UnixNano()
	generation.apiSocket, err = captureSocket(generation.apiPath)
	if err != nil {
		_ = cleanupGeneration(generation)
		return nil, err
	}
	generation.client, err = firecracker.NewClient(firecracker.ClientConfig{
		SocketPath: generation.apiPath, ExpectedPeerPID: generation.process.PID(), Timeout: 10 * time.Second,
		MaxResponseBytes: 1 << 20, Trace: generation.apiTrace,
	})
	if err != nil {
		_ = cleanupGeneration(generation)
		return nil, err
	}
	generation.gate, err = firecracker.ArmGate(firecracker.GateConfig{
		Generation: number, BasePath: generation.basePath,
		FirecrackerPID: generation.process.PID(), VerifyProcess: generation.process.VerifyIdentity, AuditLog: generation.gateTrace,
		DrainTimeout: 5 * time.Second,
	})
	if err != nil {
		_ = cleanupGeneration(generation)
		return nil, err
	}
	return generation, nil
}

func armOperationRelay(generation *generation, sandboxSocket string) (*firecracker.Relay, error) {
	return firecracker.Arm(firecracker.RelayConfig{
		Generation:     generation.number,
		BasePath:       generation.basePath,
		Port:           operationPort,
		FirecrackerPID: generation.process.PID(),
		VerifyProcess:  generation.process.VerifyIdentity,
		SandboxSocket:  sandboxSocket,
		AuditLog:       generation.relayTrace,
		DrainTimeout:   5 * time.Second,
	})
}

func stopGeneration(ctx context.Context, generation *generation) error {
	if generation == nil || generation.process == nil {
		return nil
	}
	var errs []error
	if generation.client != nil {
		errs = append(errs, generation.client.Close())
		generation.client = nil
	}
	if generation.stoppedNS == 0 {
		disposition, err := generation.process.TerminateWithDisposition(ctx)
		if err != nil {
			errs = append(errs, err)
			return errors.Join(errs...)
		}
		generation.termination = disposition
		generation.stoppedNS = time.Now().UnixNano()
		generation.exitConfirmed = true
	}
	if !generation.socketsRemoved {
		if err := removeGenerationSockets(generation); err != nil {
			errs = append(errs, err)
			return errors.Join(errs...)
		}
		generation.socketsRemoved = true
	}
	return errors.Join(errs...)
}

func terminationSummary(disposition firecracker.TerminationDisposition) (string, error) {
	switch disposition {
	case firecracker.TerminationBySupervisor:
		return "host-after-final-result", nil
	case firecracker.TerminationAlreadyExited:
		return "already-exited-after-final-result", nil
	default:
		return "", errors.New("successor termination disposition is missing")
	}
}

func cleanupGeneration(generation *generation) error {
	if generation == nil {
		return nil
	}
	var errs []error
	if generation.relay != nil {
		errs = append(errs, generation.relay.Close())
		generation.relay = nil
	}
	if generation.gate != nil {
		errs = append(errs, generation.gate.Close())
		generation.gate = nil
	}
	if generation.process != nil {
		errs = append(errs, stopGeneration(context.Background(), generation))
	}
	for _, file := range []*os.File{generation.apiTrace, generation.gateTrace, generation.relayTrace, generation.logFile} {
		if file != nil {
			errs = append(errs, file.Sync(), file.Close())
		}
	}
	generation.apiTrace, generation.gateTrace, generation.relayTrace, generation.logFile = nil, nil, nil, nil
	return errors.Join(errs...)
}

func syncGenerationEvidence(generations ...*generation) error {
	var errs []error
	for _, generation := range generations {
		if generation == nil {
			continue
		}
		for _, file := range []*os.File{generation.apiTrace, generation.gateTrace, generation.relayTrace, generation.logFile} {
			if file != nil {
				errs = append(errs, file.Sync())
			}
		}
	}
	return errors.Join(errs...)
}

func requireInstanceState(ctx context.Context, generation *generation, want firecracker.VMState) error {
	if generation == nil || generation.client == nil || generation.process == nil {
		return errors.New("Firecracker generation has no live API client")
	}
	if err := generation.process.VerifyIdentity(); err != nil {
		return err
	}
	info, err := generation.client.State(ctx)
	if err != nil {
		return err
	}
	if info.VMMVersion != officialFirecrackerVersion {
		return fmt.Errorf("Firecracker API version is %q, want %q", info.VMMVersion, officialFirecrackerVersion)
	}
	if info.ID != generation.id {
		return fmt.Errorf("Firecracker API instance id is %q, want %q", info.ID, generation.id)
	}
	if info.State != want {
		return fmt.Errorf("Firecracker state is %q, want %q", info.State, want)
	}
	return nil
}

func requireProcessArtifact(generation *generation, expectedPath, expectedSHA256 string) error {
	if generation == nil || generation.process == nil {
		return errors.New("Firecracker generation has no process")
	}
	identity := generation.process.Identity()
	if identity.Executable != expectedPath || identity.ExecutableSHA256 != expectedSHA256 {
		return errors.New("started Firecracker process differs from the verified executable")
	}
	return generation.process.VerifyIdentity()
}

func requireOutcome(result firecracker.Result) (outcomeProjection, error) {
	if result.Event != "RESULT" || result.Status != 200 {
		return outcomeProjection{}, fmt.Errorf("guest Operation returned event %q HTTP %d", result.Event, result.Status)
	}
	var outcome outcomeProjection
	decoder := json.NewDecoder(bytes.NewReader(result.Body))
	if err := decoder.Decode(&outcome); err != nil {
		return outcomeProjection{}, err
	}
	if outcome.Phase != "succeeded" {
		return outcomeProjection{}, fmt.Errorf("guest Operation outcome is phase=%q reused=%v", outcome.Phase, outcome.Reused)
	}
	return outcome, nil
}

func expectCommand(ctx context.Context, scanner *bufio.Scanner, expected string) error {
	result := make(chan error, 1)
	go func() {
		if !scanner.Scan() {
			if err := scanner.Err(); err != nil {
				result <- err
				return
			}
			result <- fmt.Errorf("input closed while waiting for %q", expected)
			return
		}
		if strings.TrimSpace(scanner.Text()) != expected {
			result <- fmt.Errorf("expected %q command", expected)
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

func emit(writer io.Writer, value map[string]any) error {
	encoder := json.NewEncoder(writer)
	encoder.SetEscapeHTML(false)
	return encoder.Encode(value)
}

func requestCallID(request []byte) string {
	var value struct {
		CallID string `json:"call_id"`
	}
	_ = json.Unmarshal(request, &value)
	return value.CallID
}

func requireKVM() error {
	device, err := os.OpenFile("/dev/kvm", os.O_RDWR, 0)
	if err != nil {
		return fmt.Errorf("Firecracker requires read/write access to /dev/kvm: %w", err)
	}
	info, statErr := device.Stat()
	closeErr := device.Close()
	if statErr != nil || closeErr != nil {
		return errors.Join(statErr, closeErr)
	}
	if info.Mode()&os.ModeCharDevice == 0 {
		return errors.New("/dev/kvm is not a character device")
	}
	return nil
}

func hostReportsHypervisor() bool {
	data, err := os.ReadFile("/proc/cpuinfo")
	if err != nil {
		return false
	}
	for _, line := range strings.Split(string(data), "\n") {
		if !strings.HasPrefix(line, "flags") {
			continue
		}
		for _, field := range strings.Fields(line) {
			if field == "hypervisor" {
				return true
			}
		}
	}
	return false
}

func requireEmptyPrivateDirectory(path string) error {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return errors.New("evidence directory must be absolute and canonical")
	}
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || info.Mode().Perm() != 0o700 {
		return errors.New("evidence directory must be a real current-user 0700 directory")
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil || resolved != path {
		return errors.New("evidence directory must not traverse symlinks")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(stat.Uid) != os.Geteuid() {
		return errors.New("evidence directory must be owned by the current user")
	}
	entries, err := os.ReadDir(path)
	if err != nil {
		return err
	}
	if len(entries) != 0 {
		return errors.New("evidence directory must be empty")
	}
	return nil
}

func verifyArtifact(name, path, expectedSHA string, executable bool) (artifactRecord, error) {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return artifactRecord{}, fmt.Errorf("%s path must be absolute and canonical", name)
	}
	info, err := os.Lstat(path)
	if err != nil {
		return artifactRecord{}, err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return artifactRecord{}, fmt.Errorf("%s must be a regular non-symlink file", name)
	}
	if executable && info.Mode().Perm()&0o111 == 0 {
		return artifactRecord{}, fmt.Errorf("%s is not executable", name)
	}
	record, err := artifactForPath(name, path)
	if err != nil {
		return artifactRecord{}, err
	}
	if expectedSHA != "" && record.SHA256 != expectedSHA {
		return artifactRecord{}, fmt.Errorf("%s SHA-256 is %s, want %s", name, record.SHA256, expectedSHA)
	}
	return record, nil
}

func artifactForPath(name, path string) (artifactRecord, error) {
	file, err := os.Open(path)
	if err != nil {
		return artifactRecord{}, err
	}
	record, recordErr := artifactForOpenFile(name, file)
	closeErr := file.Close()
	if recordErr != nil || closeErr != nil {
		return artifactRecord{}, errors.Join(recordErr, closeErr)
	}
	return record, nil
}

func artifactForOpenFile(name string, file *os.File) (artifactRecord, error) {
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return artifactRecord{}, err
	}
	digest := sha256.New()
	if _, err := io.Copy(digest, file); err != nil {
		return artifactRecord{}, err
	}
	info, err := file.Stat()
	if err != nil {
		return artifactRecord{}, err
	}
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return artifactRecord{}, err
	}
	return artifactRecord{Name: name, Size: info.Size(), Mode: uint32(info.Mode().Perm()), SHA256: hex.EncodeToString(digest.Sum(nil))}, nil
}

func sealArtifact(name, sourcePath string, childFD int) (*os.File, sealedArtifactRecord, error) {
	sourceDescriptor, err := unix.Open(sourcePath, unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return nil, sealedArtifactRecord{}, fmt.Errorf("open %s for sealing: %w", name, err)
	}
	source := os.NewFile(uintptr(sourceDescriptor), sourcePath)
	if source == nil {
		_ = unix.Close(sourceDescriptor)
		return nil, sealedArtifactRecord{}, errors.New("wrap sealed-artifact source descriptor")
	}
	defer source.Close()
	descriptor, err := unix.MemfdCreate(name, unix.MFD_CLOEXEC|unix.MFD_ALLOW_SEALING)
	if err != nil {
		return nil, sealedArtifactRecord{}, fmt.Errorf("create sealed %s memfd: %w", name, err)
	}
	sealed := os.NewFile(uintptr(descriptor), name)
	if sealed == nil {
		_ = unix.Close(descriptor)
		return nil, sealedArtifactRecord{}, errors.New("wrap sealed-artifact memfd")
	}
	fail := func(err error) (*os.File, sealedArtifactRecord, error) {
		_ = sealed.Close()
		return nil, sealedArtifactRecord{}, err
	}
	if _, err := io.Copy(sealed, source); err != nil {
		return fail(fmt.Errorf("copy %s into sealed memfd: %w", name, err))
	}
	if err := sealed.Sync(); err != nil {
		return fail(fmt.Errorf("sync sealed %s: %w", name, err))
	}
	if err := sealed.Chmod(0o400); err != nil {
		return fail(fmt.Errorf("protect sealed %s: %w", name, err))
	}
	seals := unix.F_SEAL_SEAL | unix.F_SEAL_SHRINK | unix.F_SEAL_GROW | unix.F_SEAL_WRITE
	if _, err := unix.FcntlInt(sealed.Fd(), unix.F_ADD_SEALS, seals); err != nil {
		return fail(fmt.Errorf("seal immutable %s: %w", name, err))
	}
	actualSeals, err := unix.FcntlInt(sealed.Fd(), unix.F_GET_SEALS, 0)
	if err != nil || actualSeals != seals {
		return fail(fmt.Errorf("verify immutable %s seals: got %d, want %d: %w", name, actualSeals, seals, err))
	}
	record, err := artifactForOpenFile(name, sealed)
	if err != nil {
		return fail(err)
	}
	return sealed, sealedArtifactRecord{Artifact: record, ChildFD: childFD, LinuxSeals: actualSeals}, nil
}

func syncPaths(paths ...string) error {
	var errs []error
	for _, path := range paths {
		file, err := os.OpenFile(path, os.O_RDWR, 0)
		if err != nil {
			errs = append(errs, err)
			continue
		}
		errs = append(errs, file.Sync(), file.Close())
	}
	return errors.Join(errs...)
}

func captureSocket(path string) (socketRecord, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return socketRecord{}, err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || info.Mode()&os.ModeSymlink != 0 || info.Mode()&os.ModeSocket == 0 || int(stat.Uid) != os.Geteuid() {
		return socketRecord{}, errors.New("Firecracker path is not a current-user Unix socket")
	}
	if info.Mode().Perm() != 0o600 {
		if err := unix.Fchmodat(unix.AT_FDCWD, path, 0o600, unix.AT_SYMLINK_NOFOLLOW); err != nil {
			return socketRecord{}, fmt.Errorf("protect Firecracker Unix socket: %w", err)
		}
		protected, err := os.Lstat(path)
		if err != nil || !os.SameFile(info, protected) || protected.Mode().Perm() != 0o600 {
			return socketRecord{}, errors.New("Firecracker Unix socket changed while protecting it")
		}
		info = protected
		stat, ok = info.Sys().(*syscall.Stat_t)
		if !ok {
			return socketRecord{}, errors.New("Firecracker Unix socket has no Linux identity")
		}
	}
	return socketRecord{Name: filepath.Base(path), Device: uint64(stat.Dev), Inode: stat.Ino, Mode: uint32(info.Mode().Perm()), UID: stat.Uid}, nil
}

func verifySocketRecord(path string, expected socketRecord) error {
	current, err := captureSocket(path)
	if err != nil {
		return err
	}
	if current != expected {
		return fmt.Errorf("Firecracker socket %s changed after capture", expected.Name)
	}
	return nil
}

func removeGenerationSockets(generation *generation) error {
	var errs []error
	for _, item := range []struct {
		path   string
		record socketRecord
	}{
		{generation.apiPath, generation.apiSocket},
		{generation.basePath, generation.vsockBackend},
	} {
		if item.record.Inode == 0 {
			continue
		}
		info, err := os.Lstat(item.path)
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			errs = append(errs, err)
			continue
		}
		stat, ok := info.Sys().(*syscall.Stat_t)
		if !ok || uint64(stat.Dev) != item.record.Device || stat.Ino != item.record.Inode || info.Mode()&os.ModeSocket == 0 {
			errs = append(errs, fmt.Errorf("refuse to remove replaced Firecracker socket %s", item.record.Name))
			continue
		}
		errs = append(errs, os.Remove(item.path))
	}
	return errors.Join(errs...)
}

func recordProcess(generation *generation) processRecord {
	identity := generation.process.Identity()
	return processRecord{
		Generation: generation.number, ID: generation.id, PID: identity.PID,
		Executable: filepath.Base(identity.Executable), ExecutableSHA256: identity.ExecutableSHA256,
		Device: identity.Device, Inode: identity.Inode, StartTimeTicks: identity.StartTimeTicks,
		StartedTimeNS: generation.startedNS, StoppedTimeNS: generation.stoppedNS,
		ExitConfirmed: generation.exitConfirmed, Termination: string(generation.termination),
		APISocket: generation.apiSocket, VsockBackend: generation.vsockBackend,
	}
}

func writePrivateFile(path string, data []byte, mode os.FileMode) error {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	writeErr := writeAll(file, data)
	syncErr := file.Sync()
	closeErr := file.Close()
	return errors.Join(writeErr, syncErr, closeErr)
}

func writeJSON(path string, value any) error {
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(value); err != nil {
		return err
	}
	return writePrivateFile(path, buffer.Bytes(), 0o600)
}

func openSupervisorTrace(path string) (*supervisorTrace, error) {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, err
	}
	return &supervisorTrace{file: file, origin: time.Now()}, nil
}

func (trace *supervisorTrace) Record(event string, generation *generation, details map[string]any) error {
	if trace == nil || trace.file == nil {
		return errors.New("Firecracker supervisor trace is closed")
	}
	if trace.failure != nil {
		return trace.failure
	}
	if event == "" {
		return errors.New("Firecracker supervisor event is empty")
	}
	trace.sequence++
	record := struct {
		Schema         int            `json:"schema"`
		Sequence       uint64         `json:"sequence"`
		Event          string         `json:"event"`
		TimeNS         int64          `json:"time_ns"`
		ElapsedNS      int64          `json:"elapsed_ns"`
		Generation     uint64         `json:"generation,omitempty"`
		InstanceID     string         `json:"instance_id,omitempty"`
		PID            int            `json:"pid,omitempty"`
		StartTimeTicks uint64         `json:"start_time_ticks,omitempty"`
		Details        map[string]any `json:"details,omitempty"`
	}{
		Schema: 1, Sequence: trace.sequence, Event: event,
		TimeNS: time.Now().UnixNano(), ElapsedNS: time.Since(trace.origin).Nanoseconds(),
		Details: details,
	}
	if generation != nil && generation.process != nil {
		identity := generation.process.Identity()
		record.Generation = generation.number
		record.InstanceID = generation.id
		record.PID = identity.PID
		record.StartTimeTicks = identity.StartTimeTicks
	}
	encoded, err := json.Marshal(record)
	if err == nil {
		encoded = append(encoded, '\n')
		err = writeAll(trace.file, encoded)
	}
	if err == nil {
		err = trace.file.Sync()
	}
	if err != nil {
		trace.failure = fmt.Errorf("write durable Firecracker supervisor trace: %w", err)
		return trace.failure
	}
	return nil
}

func (trace *supervisorTrace) Close() error {
	if trace == nil || trace.file == nil {
		return nil
	}
	err := errors.Join(trace.failure, trace.file.Sync(), trace.file.Close())
	trace.file = nil
	return err
}

func writeAll(writer io.Writer, data []byte) error {
	for len(data) > 0 {
		written, err := writer.Write(data)
		if err != nil {
			return err
		}
		if written <= 0 || written > len(data) {
			return io.ErrShortWrite
		}
		data = data[written:]
	}
	return nil
}

func randomHex(bytesCount int) (string, error) {
	value := make([]byte, bytesCount)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return hex.EncodeToString(value), nil
}
