// Command firecracker-codex-shim preserves the ordinary Codex app-server
// stdio contract while moving one protected tool boundary between two exact
// Firecracker processes. Stdout belongs exclusively to the Codex JSONL stream;
// diagnostics and guest console output go to stderr.
package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentguest"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentwire"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/codexvm"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/firecracker"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repobundle"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repodelta"
	"golang.org/x/sys/unix"
)

const (
	runLimit              = 10 * time.Minute
	endpointDrainLimit    = 5 * time.Second
	repositoryExportLimit = 30 * time.Second
	guestCID              = uint32(3)
	guestMemoryMiB        = 1024
	firstGeneration       = uint64(1)
	restoredGeneration    = uint64(3)
	maxGuestBinaryBytes   = int64(64 << 20)
	unixSocketPathLimit   = 108
	resultSchema          = 1
	evidenceEventSchema   = 1
	guestPayloadDrive     = "/dev/vda"
	guestRepositoryDrive  = "/dev/vdb"
	bootKernelDescriptor  = "/proc/self/fd/4"
	bootInitrdDescriptor  = "/proc/self/fd/5"
	payloadDescriptor     = "/proc/self/fd/6"
	repositoryDescriptor  = "/proc/self/fd/7"
	bootArguments         = "console=ttyS0 reboot=k panic=1 pci=off rdinit=/init"
)

var immutableSeals = unix.F_SEAL_SEAL | unix.F_SEAL_SHRINK | unix.F_SEAL_GROW | unix.F_SEAL_WRITE

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

type sealedArtifact struct {
	file   *os.File
	record sealedArtifactRecord
}

type socketRecord struct {
	Path   string `json:"path"`
	Device uint64 `json:"device"`
	Inode  uint64 `json:"inode"`
	Mode   uint32 `json:"mode"`
	UID    uint32 `json:"uid"`
}

type processRecord struct {
	Generation       uint64                             `json:"generation"`
	ID               string                             `json:"id"`
	PID              int                                `json:"pid"`
	Executable       string                             `json:"executable"`
	ExecutableSHA256 string                             `json:"executable_sha256"`
	Device           uint64                             `json:"device"`
	Inode            uint64                             `json:"inode"`
	StartTimeTicks   uint64                             `json:"start_time_ticks"`
	VMMVersion       string                             `json:"vmm_version,omitempty"`
	StartedTimeNS    int64                              `json:"started_time_ns"`
	StoppedTimeNS    int64                              `json:"stopped_time_ns,omitempty"`
	Termination      firecracker.TerminationDisposition `json:"termination,omitempty"`
	APISocket        socketRecord                       `json:"api_socket"`
	VsockBackend     socketRecord                       `json:"vsock_backend"`
}

type resultRecord struct {
	Schema                  int                       `json:"schema"`
	Success                 bool                      `json:"success"`
	Error                   string                    `json:"error,omitempty"`
	SessionID               string                    `json:"session_id"`
	RunnerSHA256            string                    `json:"runner_sha256"`
	CodexSHA256             string                    `json:"codex_sha256"`
	ArgumentsSHA256         string                    `json:"arguments_sha256"`
	ArgumentsEncoding       string                    `json:"arguments_encoding"`
	ArgumentsCount          int                       `json:"arguments_count"`
	WorkspaceMapping        workspaceMappingRecord    `json:"workspace_mapping"`
	Artifacts               map[string]artifactRecord `json:"artifacts,omitempty"`
	SealedBootInputs        []sealedArtifactRecord    `json:"sealed_boot_inputs,omitempty"`
	SealedLoadInputs        []sealedArtifactRecord    `json:"sealed_load_inputs,omitempty"`
	Checkpoint              *codexvm.Checkpoint       `json:"checkpoint,omitempty"`
	RepositoryChange        *repositoryChangeRecord   `json:"repository_change,omitempty"`
	Processes               []processRecord           `json:"processes,omitempty"`
	G1SIGKILLConfirmed      bool                      `json:"g1_sigkill_confirmed"`
	SnapshotLoadedPaused    bool                      `json:"snapshot_loaded_paused"`
	RelayArmedBeforeResume  bool                      `json:"relay_armed_before_resume"`
	ToolReleasedAfterAttach bool                      `json:"tool_released_after_g3_attach"`
	CompletedTimeNS         int64                     `json:"completed_time_ns"`
}

type repositoryChangeRecord struct {
	BaseRoot       string `json:"base_root"`
	FinalRoot      string `json:"final_root"`
	OperationCount int    `json:"operation_count"`
}

type workspaceMappingRecord struct {
	Host  string `json:"host"`
	Guest string `json:"guest"`
}

// checkpointEvidence is the canonical object whose artifact hash crosses into
// the durable control-plane Cutover. It joins the exact transport boundary,
// VM snapshot, repository input, executable contract, and both VMM instances.
type checkpointEvidence struct {
	Schema             int                `json:"schema"`
	SessionID          string             `json:"session_id"`
	SourceInstanceID   string             `json:"source_instance_id"`
	RestoredInstanceID string             `json:"restored_instance_id"`
	CodexSHA256        string             `json:"codex_sha256"`
	ArgumentsSHA256    string             `json:"arguments_sha256"`
	RepositoryTreeRoot string             `json:"repository_tree_root"`
	RepositoryBundle   artifactRecord     `json:"repository_bundle"`
	SnapshotState      artifactRecord     `json:"snapshot_state"`
	SnapshotMemory     artifactRecord     `json:"snapshot_memory"`
	StreamCheckpoint   codexvm.Checkpoint `json:"stream_checkpoint"`
}

type eventRecord struct {
	Schema     int            `json:"schema"`
	Sequence   uint64         `json:"sequence"`
	Event      string         `json:"event"`
	TimeNS     int64          `json:"time_ns"`
	Generation uint64         `json:"generation,omitempty"`
	InstanceID string         `json:"instance_id,omitempty"`
	PID        int            `json:"pid,omitempty"`
	Details    map[string]any `json:"details,omitempty"`
}

type evidenceFile struct {
	mu       sync.Mutex
	file     *os.File
	failure  error
	failed   chan struct{}
	failOnce sync.Once
	closed   bool
}

type eventLog struct {
	file     *evidenceFile
	mu       sync.Mutex
	sequence uint64
}

type bridgeIORecord struct {
	Schema    int    `json:"schema"`
	Sequence  uint64 `json:"sequence"`
	Phase     string `json:"phase"`
	Direction string `json:"direction"`
	TimeNS    int64  `json:"time_ns"`
	Size      int    `json:"canonical_size"`
	SHA256    string `json:"canonical_sha256"`
}

type bridgeIOLog struct {
	file     *evidenceFile
	mu       sync.Mutex
	sequence uint64
}

type generation struct {
	number         uint64
	id             string
	apiPath        string
	basePath       string
	process        *firecracker.Process
	client         *firecracker.Client
	listener       *firecracker.VsockListener
	exportListener *firecracker.VsockListener
	relay          *firecracker.Relay
	apiTrace       *evidenceFile
	relayAudit     *evidenceFile
	apiSocket      socketRecord
	vsockBackend   socketRecord
	vmmVersion     string
	startedTimeNS  int64
	stoppedTimeNS  int64
	termination    firecracker.TerminationDisposition
	acceptCancel   context.CancelFunc
	acceptDone     chan struct{}
	stopping       atomic.Bool
	tracesClosed   bool
	relayAuditSafe bool
}

type runner struct {
	ctx            context.Context
	cancel         context.CancelFunc
	config         codexvm.Config
	input          io.Reader
	output         io.Writer
	logger         *log.Logger
	events         *eventLog
	result         resultRecord
	sessionID      string
	idG1           string
	idG3           string
	bridge         *codexvm.Bridge
	bridgeIO       *bridgeIOLog
	bridgeIOFile   *evidenceFile
	proxy          *firecracker.LoopbackProxy
	proxyAudit     *evidenceFile
	kernel         *sealedArtifact
	payload        *sealedArtifact
	repository     *sealedArtifact
	repositoryTree repobundle.Bundle
	guest          *sealedArtifact
	initramfs      *sealedArtifact
	snapshotState  *sealedArtifact
	snapshotMemory *sealedArtifact
	g1             *generation
	g3             *generation
}

func main() {
	logger := log.New(os.Stderr, "firecracker-codex-shim: ", log.Ldate|log.Ltime|log.Lmicroseconds|log.LUTC)
	config, err := codexvm.LoadConfig(os.Args[1:], os.LookupEnv)
	if err != nil {
		logger.Printf("configuration failed: %v", err)
		os.Exit(1)
	}
	signalContext, stopSignals := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stopSignals()
	ctx, cancel := context.WithTimeout(signalContext, runLimit)
	defer cancel()
	if err := run(ctx, config, os.Stdin, os.Stdout, logger); err != nil {
		logger.Printf("failed: %v", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, config codexvm.Config, input io.Reader, output io.Writer, logger *log.Logger) error {
	if ctx == nil || input == nil || output == nil || logger == nil {
		return errors.New("Firecracker Codex shim requires context, input, output, and logger")
	}
	if runtime.GOOS != "linux" {
		return errors.New("Firecracker Codex shim requires Linux")
	}

	oldUmask := syscall.Umask(0o077)
	defer syscall.Umask(oldUmask)
	eventsFile, err := openEvidenceFile(filepath.Join(config.EvidenceDir, "events.jsonl"))
	if err != nil {
		return fmt.Errorf("open events evidence: %w", err)
	}
	events := &eventLog{file: eventsFile}

	sessionID, idG1, idG3, setupErr := generateRunIDs(rand.Reader)
	argumentsHash, hashErr := argumentsDigest(config.Arguments)
	setupErr = errors.Join(setupErr, hashErr)
	record := resultRecord{
		Schema: resultSchema, SessionID: sessionID, RunnerSHA256: config.RunnerSHA256, CodexSHA256: config.CodexSHA256,
		ArgumentsSHA256: argumentsHash, ArgumentsEncoding: "compact-json-array",
		ArgumentsCount:   len(config.Arguments),
		WorkspaceMapping: workspaceMappingRecord{Host: config.Workspace, Guest: agentguest.WorkspaceDirectory},
		Artifacts:        make(map[string]artifactRecord),
	}

	var executeErr error
	var active *runner
	if setupErr == nil {
		runContext, cancel := context.WithCancel(ctx)
		active = &runner{
			ctx: runContext, cancel: cancel, config: config, input: input, output: output,
			logger: logger, events: events, result: record, sessionID: sessionID, idG1: idG1, idG3: idG3,
		}
		executeErr = active.execute()
		cleanupErr := active.cleanup()
		cancel()
		executeErr = errors.Join(executeErr, cleanupErr)
		record = active.result
		record.Processes = active.processRecords()
	} else {
		executeErr = setupErr
	}

	finishEvent := "run-completed"
	if executeErr != nil {
		finishEvent = "run-failed"
	}
	eventErr := events.Record(finishEvent, nil, map[string]any{"error": errorString(executeErr)})
	closeEventsErr := events.Close()
	var eventsArtifactErr error
	if eventErr == nil && closeEventsErr == nil {
		var eventsArtifact artifactRecord
		eventsArtifact, eventsArtifactErr = artifactForPath(
			"events.jsonl", filepath.Join(config.EvidenceDir, "events.jsonl"), 0o600,
		)
		if eventsArtifactErr == nil {
			record.Artifacts["events"] = eventsArtifact
		}
	}
	executeErr = errors.Join(executeErr, eventErr, closeEventsErr, eventsArtifactErr)
	record.Success = executeErr == nil
	record.Error = errorString(executeErr)
	record.CompletedTimeNS = time.Now().UnixNano()
	resultErr := writePrivateJSON(filepath.Join(config.EvidenceDir, "result.json"), record)
	return errors.Join(executeErr, resultErr)
}

func (r *runner) execute() error {
	if err := validateRuntimePaths(r.config.EvidenceDir, r.config.GuestModelPort); err != nil {
		return err
	}
	runnerArtifact, err := retainSelfExecutable(
		filepath.Join(r.config.EvidenceDir, "runner"), r.config.RunnerSHA256,
	)
	if err != nil {
		return err
	}
	r.result.Artifacts["runner"] = runnerArtifact
	if err := r.events.Record("run-started", nil, map[string]any{
		"session_id": r.sessionID, "g1_id": r.idG1, "g3_id": r.idG3,
		"runner_sha256": r.config.RunnerSHA256, "codex_sha256": r.config.CodexSHA256, "arguments_sha256": r.result.ArgumentsSHA256,
		"workspace_mapping": r.result.WorkspaceMapping,
	}); err != nil {
		return err
	}

	if r.kernel, err = sealPath("kernel", r.config.Kernel, r.config.KernelSHA256, 4, 0); err != nil {
		return err
	}
	if r.payload, err = sealPath("payload", r.config.Payload, r.config.PayloadSHA256, 6, 0); err != nil {
		return err
	}
	if r.repository, err = sealPath("repository", r.config.Repository, r.config.RepositorySHA256, 7, int64(agentguest.MaxRepositoryBytes)); err != nil {
		return err
	}
	if r.repositoryTree, err = decodeSealedRepository(r.repository); err != nil {
		return err
	}
	if r.guest, err = sealPath("guest", r.config.Guest, r.config.GuestSHA256, 0, maxGuestBinaryBytes); err != nil {
		return err
	}
	guestBytes, err := readSealedArtifact(r.guest, maxGuestBinaryBytes)
	if err != nil {
		return fmt.Errorf("read sealed guest: %w", err)
	}
	guestConfig, err := buildGuestConfig(r.config, r.sessionID, r.repository, r.repositoryTree)
	if err != nil {
		return err
	}
	configJSON, err := json.Marshal(guestConfig)
	if err != nil {
		return fmt.Errorf("encode guest config: %w", err)
	}
	if _, err := agentguest.DecodeConfig(bytes.NewReader(configJSON)); err != nil {
		return fmt.Errorf("round-trip strict guest config: %w", err)
	}
	guestConfigArtifact, err := persistBytesArtifact(
		"guest-config.json", filepath.Join(r.config.EvidenceDir, "guest-config.json"), configJSON,
	)
	if err != nil {
		return err
	}
	r.result.Artifacts["guest_config"] = guestConfigArtifact
	if r.initramfs, err = buildRuntimeInitramfs(guestBytes, configJSON); err != nil {
		return err
	}
	initramfsArtifact, err := persistOpenArtifact(
		"guest-initramfs.cpio", filepath.Join(r.config.EvidenceDir, "guest-initramfs.cpio"),
		r.initramfs.file, r.initramfs.record.Artifact,
	)
	if err != nil {
		return err
	}
	r.result.Artifacts["kernel"] = r.kernel.record.Artifact
	r.result.Artifacts["payload"] = r.payload.record.Artifact
	repositoryArtifact, err := persistOpenArtifact(
		"repository.bundle", filepath.Join(r.config.EvidenceDir, "repository.bundle"),
		r.repository.file, r.repository.record.Artifact,
	)
	if err != nil {
		return err
	}
	r.result.Artifacts["repository"] = repositoryArtifact
	r.result.Artifacts["guest"] = r.guest.record.Artifact
	r.result.Artifacts["initramfs"] = initramfsArtifact
	r.result.SealedBootInputs = []sealedArtifactRecord{r.kernel.record, r.initramfs.record, r.payload.record, r.repository.record}
	if err := r.events.Record("artifacts-sealed", nil, map[string]any{
		"kernel": r.kernel.record, "payload": r.payload.record,
		"repository": r.repository.record, "repository_tree_root": r.repositoryTree.TreeRoot.String(),
		"guest": r.guest.record, "initramfs": r.initramfs.record,
	}); err != nil {
		return err
	}

	if err := r.startProxy(); err != nil {
		return err
	}
	if r.bridgeIOFile, err = openEvidenceFile(filepath.Join(r.config.EvidenceDir, "bridge-io.jsonl")); err != nil {
		return fmt.Errorf("open bridge I/O evidence: %w", err)
	}
	r.watchEvidence(r.bridgeIOFile, "bridge I/O audit")
	r.bridgeIO = &bridgeIOLog{file: r.bridgeIOFile}
	if r.bridge, err = codexvm.NewAuditedWorkspaceBridge(
		r.sessionID, r.input, r.output, r.logger, r.config.Workspace, agentguest.WorkspaceDirectory,
		r.bridgeIO.Record,
	); err != nil {
		return fmt.Errorf("create Codex bridge: %w", err)
	}
	r.bridge.StartInput(r.ctx)

	r.g1 = newGeneration(r.config.EvidenceDir, firstGeneration, r.idG1)
	if err := r.startGeneration(r.g1, []*os.File{r.kernel.file, r.initramfs.file, r.payload.file, r.repository.file}); err != nil {
		return err
	}
	firecrackerArtifact, err := artifactForProcess(r.g1.process)
	if err != nil {
		return err
	}
	r.result.Artifacts["firecracker"] = firecrackerArtifact
	if err := r.events.Record("process-started", r.g1, nil); err != nil {
		return err
	}
	if err := r.configureFirstGeneration(); err != nil {
		return err
	}
	if err := r.armEndpoints(r.g1); err != nil {
		return err
	}
	if err := r.events.Record("endpoints-armed-before-start", r.g1, map[string]any{
		"stream_port": agentguest.DefaultStreamPort, "export_port": agentguest.DefaultExportPort, "model_port": r.config.GuestModelPort,
	}); err != nil {
		return err
	}
	if err := r.g1.client.Start(r.ctx); err != nil {
		return fmt.Errorf("start g1 VM: %w", err)
	}
	if err := r.requireState(r.g1, firecracker.StateRunning); err != nil {
		return err
	}
	if err := r.bridge.WaitAttached(r.ctx, firstGeneration); err != nil {
		return fmt.Errorf("wait for g1 attach: %w", err)
	}
	if err := r.events.Record("bridge-attached", r.g1, nil); err != nil {
		return err
	}
	checkpoint, err := r.bridge.WaitCheckpoint(r.ctx)
	if err != nil {
		return fmt.Errorf("wait for protected tool checkpoint: %w", err)
	}
	r.result.Checkpoint = &checkpoint
	if err := r.events.Record("tool-call-observed-checkpoint-quiescent", r.g1, map[string]any{
		"host_barrier": checkpoint.HostBarrier, "guest_barrier": checkpoint.GuestBarrier,
	}); err != nil {
		return err
	}
	if err := r.closeModelRelay(r.g1); err != nil {
		return fmt.Errorf("quiesce g1 model path before snapshot: %w", err)
	}
	idleContext, idleCancel := context.WithTimeout(r.ctx, endpointDrainLimit)
	idleErr := r.proxy.WaitIdle(idleContext)
	idleCancel()
	if idleErr != nil {
		return fmt.Errorf("wait for g1 model proxy quiescence: %w", idleErr)
	}
	if err := r.events.Record("model-path-quiescent", r.g1, nil); err != nil {
		return err
	}
	if err := r.g1.client.Pause(r.ctx); err != nil {
		return fmt.Errorf("pause g1 VM: %w", err)
	}
	if err := r.requireState(r.g1, firecracker.StatePaused); err != nil {
		return err
	}
	if err := r.events.Record("vm-paused", r.g1, nil); err != nil {
		return err
	}

	snapshotStatePath := filepath.Join(r.config.EvidenceDir, "snapshot.state")
	snapshotMemoryPath := filepath.Join(r.config.EvidenceDir, "snapshot.memory")
	if err := requireAbsent(snapshotStatePath, snapshotMemoryPath); err != nil {
		return err
	}
	if err := r.g1.client.CreateFullSnapshot(r.ctx, snapshotStatePath, snapshotMemoryPath); err != nil {
		return fmt.Errorf("create full snapshot: %w", err)
	}
	stateBefore, err := finalizeSnapshotFile("snapshot.state", snapshotStatePath)
	if err != nil {
		return err
	}
	memoryBefore, err := finalizeSnapshotFile("snapshot.memory", snapshotMemoryPath)
	if err != nil {
		return err
	}
	r.result.Artifacts["snapshot_state"] = stateBefore
	r.result.Artifacts["snapshot_memory"] = memoryBefore
	if err := r.events.Record("snapshot-created-paused", r.g1, map[string]any{
		"state": stateBefore, "memory": memoryBefore,
	}); err != nil {
		return err
	}

	if err := r.killFirstGeneration(); err != nil {
		return err
	}
	if r.snapshotState, err = sealPath("snapshot-state", snapshotStatePath, stateBefore.SHA256, 4, 0); err != nil {
		return err
	}
	if r.snapshotMemory, err = sealPath("snapshot-memory", snapshotMemoryPath, memoryBefore.SHA256, 5, 0); err != nil {
		return err
	}
	r.result.SealedLoadInputs = []sealedArtifactRecord{r.snapshotState.record, r.snapshotMemory.record, r.payload.record, r.repository.record}
	if err := r.events.Record("snapshot-load-inputs-sealed", nil, map[string]any{
		"state": r.snapshotState.record, "memory": r.snapshotMemory.record,
		"payload": r.payload.record, "repository": r.repository.record,
	}); err != nil {
		return err
	}
	if err := r.bridge.AdvanceGeneration(restoredGeneration, checkpoint); err != nil {
		return fmt.Errorf("advance bridge generation: %w", err)
	}
	if err := r.events.Record("bridge-generation-advanced", nil, map[string]any{"generation": restoredGeneration}); err != nil {
		return err
	}

	r.g3 = newGeneration(r.config.EvidenceDir, restoredGeneration, r.idG3)
	if err := r.startGeneration(r.g3, []*os.File{r.snapshotState.file, r.snapshotMemory.file, r.payload.file, r.repository.file}); err != nil {
		return err
	}
	if err := r.events.Record("process-started", r.g3, nil); err != nil {
		return err
	}
	if err := r.g3.client.LoadSnapshotPaused(r.ctx, firecracker.LoadSnapshotConfig{
		SnapshotPath:  bootKernelDescriptor,
		MemoryBackend: firecracker.MemoryBackend{BackendType: "File", BackendPath: bootInitrdDescriptor},
		VsockOverride: &firecracker.VsockOverride{UDSPath: r.g3.basePath}, Resume: false,
	}); err != nil {
		return fmt.Errorf("load g3 snapshot paused: %w", err)
	}
	if r.g3.vsockBackend, err = captureSocket(r.g3.basePath); err != nil {
		return fmt.Errorf("capture g3 vsock backend: %w", err)
	}
	if err := r.requireState(r.g3, firecracker.StatePaused); err != nil {
		return err
	}
	checkpointArtifact, err := r.persistCheckpointEvidence(checkpoint)
	if err != nil {
		return err
	}
	r.result.Artifacts["checkpoint"] = checkpointArtifact
	r.result.SnapshotLoadedPaused = true
	if err := r.events.Record("snapshot-loaded-paused", r.g3, map[string]any{
		"state_sha256":  r.snapshotState.record.Artifact.SHA256,
		"memory_sha256": r.snapshotMemory.record.Artifact.SHA256,
		"checkpoint":    checkpointArtifact,
	}); err != nil {
		return err
	}
	if err := r.armEndpoints(r.g3); err != nil {
		return err
	}
	r.result.RelayArmedBeforeResume = true
	if err := r.events.Record("endpoints-armed-while-paused", r.g3, map[string]any{
		"stream_port": agentguest.DefaultStreamPort, "export_port": agentguest.DefaultExportPort, "model_port": r.config.GuestModelPort,
	}); err != nil {
		return err
	}
	if err := r.g3.client.Resume(r.ctx); err != nil {
		return fmt.Errorf("resume g3 VM: %w", err)
	}
	if err := r.requireState(r.g3, firecracker.StateRunning); err != nil {
		return err
	}
	if err := r.events.Record("vm-resumed", r.g3, nil); err != nil {
		return err
	}
	if err := r.bridge.WaitAttached(r.ctx, restoredGeneration); err != nil {
		return fmt.Errorf("wait for g3 attach: %w", err)
	}
	if err := r.events.Record("bridge-attached", r.g3, nil); err != nil {
		return err
	}
	if err := r.events.Record("tool-call-release-authorized", r.g3, nil); err != nil {
		return err
	}
	if err := r.bridge.ReleaseToolCall(); err != nil {
		return fmt.Errorf("release protected tool call: %w", err)
	}
	r.result.ToolReleasedAfterAttach = true
	if err := r.events.Record("tool-call-delivered-after-attach", r.g3, nil); err != nil {
		return err
	}

	if waitErr := r.bridge.Wait(r.ctx); waitErr != nil {
		return fmt.Errorf("Codex bridge stopped: %w", waitErr)
	}
	if err := r.events.Record("codex-session-completed", r.g3, nil); err != nil {
		return err
	}
	if err := r.bridge.ShutdownGuest(); err != nil {
		return fmt.Errorf("request stable guest repository export: %w", err)
	}
	return r.receiveFinalRepository()
}

func (r *runner) persistCheckpointEvidence(stream codexvm.Checkpoint) (artifactRecord, error) {
	if r.g1 == nil || r.g3 == nil {
		return artifactRecord{}, errors.New("checkpoint evidence requires both VM instances")
	}
	evidence := checkpointEvidence{
		Schema: 1, SessionID: r.sessionID,
		SourceInstanceID: r.g1.id, RestoredInstanceID: r.g3.id,
		CodexSHA256: r.result.CodexSHA256, ArgumentsSHA256: r.result.ArgumentsSHA256,
		RepositoryTreeRoot: r.repositoryTree.TreeRoot.String(),
		RepositoryBundle:   r.result.Artifacts["repository"],
		SnapshotState:      r.result.Artifacts["snapshot_state"],
		SnapshotMemory:     r.result.Artifacts["snapshot_memory"],
		StreamCheckpoint:   stream,
	}
	encoded, err := json.Marshal(evidence)
	if err != nil {
		return artifactRecord{}, fmt.Errorf("encode checkpoint evidence: %w", err)
	}
	return persistBytesArtifact("checkpoint.json", filepath.Join(r.config.EvidenceDir, "checkpoint.json"), encoded)
}

func (r *runner) startProxy() error {
	var err error
	r.proxyAudit, err = openEvidenceFile(filepath.Join(r.config.EvidenceDir, "model-proxy.jsonl"))
	if err != nil {
		return fmt.Errorf("open model proxy audit: %w", err)
	}
	r.watchEvidence(r.proxyAudit, "model proxy audit")
	r.proxy, err = firecracker.StartLoopbackProxy(firecracker.LoopbackProxyConfig{
		SocketPath:    filepath.Join(r.config.EvidenceDir, "model-proxy.sock"),
		TargetAddress: r.config.HostModelTarget, AuditLog: r.proxyAudit,
		DialTimeout: 5 * time.Second, DrainTimeout: endpointDrainLimit,
	})
	if err != nil {
		return fmt.Errorf("start fixed loopback model proxy: %w", err)
	}
	return r.events.Record("model-proxy-started", nil, map[string]any{
		"target": r.proxy.TargetAddress(), "socket": r.proxy.SocketPath(),
	})
}

func newGeneration(directory string, number uint64, id string) *generation {
	label := fmt.Sprintf("g%d", number)
	return &generation{
		number: number, id: id,
		apiPath:        filepath.Join(directory, "api-"+label+".sock"),
		basePath:       filepath.Join(directory, "vsock-"+label),
		relayAuditSafe: true,
	}
}

func (r *runner) startGeneration(g *generation, inherited []*os.File) error {
	if g == nil {
		return errors.New("start nil Firecracker generation")
	}
	var err error
	label := fmt.Sprintf("g%d", g.number)
	if g.apiTrace, err = openEvidenceFile(filepath.Join(r.config.EvidenceDir, "firecracker-api-"+label+".jsonl")); err != nil {
		return err
	}
	r.watchEvidence(g.apiTrace, label+" API trace")
	if g.relayAudit, err = openEvidenceFile(filepath.Join(r.config.EvidenceDir, "firecracker-relay-"+label+".jsonl")); err != nil {
		return err
	}
	r.watchEvidence(g.relayAudit, label+" relay audit")
	g.process, err = firecracker.StartProcess(r.ctx, firecracker.ProcessConfig{
		Binary: r.config.Firecracker, ExecutableSHA256: r.config.FirecrackerSHA256,
		APISocket: g.apiPath, ID: g.id,
		Env: []string{"PATH=/usr/bin:/bin", "LANG=C", "LC_ALL=C"}, Dir: r.config.EvidenceDir,
		Stdout: os.Stderr, Stderr: os.Stderr,
		StartupTimeout: 10 * time.Second, TerminationTimeout: 5 * time.Second,
		InheritedFiles: inherited,
	})
	if err != nil {
		if record, captureErr := captureSocket(g.apiPath); captureErr == nil {
			g.apiSocket = record
		}
		return fmt.Errorf("start Firecracker %s: %w", label, err)
	}
	g.startedTimeNS = time.Now().UnixNano()
	go r.watchGenerationProcess(g)
	if g.apiSocket, err = captureSocket(g.apiPath); err != nil {
		return fmt.Errorf("capture %s API socket: %w", label, err)
	}
	g.client, err = firecracker.NewClient(firecracker.ClientConfig{
		SocketPath: g.apiPath, ExpectedPeerPID: g.process.PID(), Timeout: 10 * time.Second,
		MaxResponseBytes: 1 << 20, Trace: g.apiTrace,
	})
	if err != nil {
		return fmt.Errorf("create %s API client: %w", label, err)
	}
	if err := r.requireState(g, firecracker.StateNotStarted); err != nil {
		return err
	}
	identity := g.process.Identity()
	if identity.ExecutableSHA256 != r.config.FirecrackerSHA256 {
		return errors.New("started Firecracker hash differs from configured hash")
	}
	return nil
}

func (r *runner) watchGenerationProcess(g *generation) {
	if g == nil || g.process == nil {
		return
	}
	select {
	case <-g.process.Done():
	case <-r.ctx.Done():
		return
	}
	if g.stopping.Load() || r.ctx.Err() != nil {
		return
	}
	waitErr := g.process.WaitContext(context.Background())
	if g.stopping.Load() || r.ctx.Err() != nil {
		return
	}
	if waitErr == nil {
		waitErr = errors.New("process exited with status zero")
	}
	r.failBridge(fmt.Errorf("g%d Firecracker exited unexpectedly: %w", g.number, waitErr))
}

func (r *runner) configureFirstGeneration() error {
	err := r.g1.client.Configure(r.ctx,
		firecracker.MachineConfig{VCPUCount: 1, MemSizeMiB: guestMemoryMiB, SMT: false, TrackDirtyPages: false},
		firecracker.BootSource{KernelImagePath: bootKernelDescriptor, InitrdPath: bootInitrdDescriptor, BootArgs: bootArguments},
		firecracker.VsockDevice{GuestCID: guestCID, UDSPath: r.g1.basePath},
	)
	if err != nil {
		return fmt.Errorf("configure g1 VM: %w", err)
	}
	if err := r.g1.client.ConfigureDrive(r.ctx, firecracker.Drive{
		DriveID: "payload", PathOnHost: payloadDescriptor, IsRootDevice: false, IsReadOnly: true,
	}); err != nil {
		return fmt.Errorf("configure read-only payload drive: %w", err)
	}
	if err := r.g1.client.ConfigureDrive(r.ctx, firecracker.Drive{
		DriveID: "repository", PathOnHost: repositoryDescriptor, IsRootDevice: false, IsReadOnly: true,
	}); err != nil {
		return fmt.Errorf("configure read-only repository drive: %w", err)
	}
	var captureErr error
	r.g1.vsockBackend, captureErr = captureSocket(r.g1.basePath)
	if captureErr != nil {
		return fmt.Errorf("capture g1 vsock backend: %w", captureErr)
	}
	return nil
}

func (r *runner) armEndpoints(g *generation) error {
	var err error
	g.relay, err = firecracker.Arm(firecracker.RelayConfig{
		Generation: g.number, BasePath: g.basePath, Port: r.config.GuestModelPort,
		FirecrackerPID: g.process.PID(), VerifyProcess: g.process.VerifyIdentity,
		SandboxSocket: r.proxy.SocketPath(), AuditLog: g.relayAudit, DrainTimeout: endpointDrainLimit,
	})
	if err != nil {
		return fmt.Errorf("arm g%d model relay: %w", g.number, err)
	}
	g.relayAuditSafe = false
	g.listener, err = firecracker.ArmVsockListener(firecracker.VsockListenerConfig{
		BasePath: g.basePath, Port: agentguest.DefaultStreamPort,
		FirecrackerPID: g.process.PID(), VerifyProcess: g.process.VerifyIdentity,
	})
	if err != nil {
		return fmt.Errorf("arm g%d Codex stream listener: %w", g.number, err)
	}
	g.exportListener, err = firecracker.ArmVsockListener(firecracker.VsockListenerConfig{
		BasePath: g.basePath, Port: agentguest.DefaultExportPort,
		FirecrackerPID: g.process.PID(), VerifyProcess: g.process.VerifyIdentity,
	})
	if err != nil {
		return fmt.Errorf("arm g%d repository export listener: %w", g.number, err)
	}
	acceptContext, cancel := context.WithCancel(r.ctx)
	g.acceptCancel = cancel
	g.acceptDone = make(chan struct{})
	go r.acceptConnections(acceptContext, g, g.listener)
	return nil
}

func (r *runner) acceptConnections(ctx context.Context, g *generation, listener *firecracker.VsockListener) {
	defer close(g.acceptDone)
	for {
		connection, err := listener.Accept(ctx)
		if err != nil {
			if ctx.Err() != nil || g.stopping.Load() || errors.Is(err, net.ErrClosed) || errors.Is(err, os.ErrClosed) {
				return
			}
			r.failBridge(fmt.Errorf("accept g%d authenticated stream: %w", g.number, err))
			return
		}
		err = r.bridge.ServeConnection(ctx, connection)
		if errors.Is(err, codexvm.ErrDisconnected) {
			if g.stopping.Load() || ctx.Err() != nil {
				return
			}
			r.logger.Printf("g%d Codex stream disconnected; waiting for authenticated reconnect", g.number)
			continue
		}
		if ctx.Err() != nil || g.stopping.Load() {
			return
		}
		if err == nil {
			err = errors.New("Codex stream ended without a disconnect result")
		}
		r.failBridge(fmt.Errorf("serve g%d Codex stream: %w", g.number, err))
		return
	}
}

func (r *runner) failBridge(err error) {
	if err == nil {
		return
	}
	r.cancel()
	r.bridge.Fail(err)
}

func (r *runner) requireState(g *generation, want firecracker.VMState) error {
	if g == nil || g.process == nil || g.client == nil {
		return errors.New("Firecracker generation lacks a live process and client")
	}
	if err := g.process.VerifyIdentity(); err != nil {
		return fmt.Errorf("verify g%d process identity: %w", g.number, err)
	}
	info, err := g.client.State(r.ctx)
	if err != nil {
		return fmt.Errorf("read g%d state: %w", g.number, err)
	}
	if info.ID != g.id {
		return fmt.Errorf("g%d API instance ID is %q, require %q", g.number, info.ID, g.id)
	}
	if info.State != want {
		return fmt.Errorf("g%d state is %q, require %q", g.number, info.State, want)
	}
	g.vmmVersion = info.VMMVersion
	return nil
}

func (r *runner) killFirstGeneration() error {
	r.g1.stopping.Store(true)
	disposition, err := r.g1.process.Kill(r.ctx)
	if err != nil {
		return fmt.Errorf("SIGKILL exact g1 Firecracker process: %w", err)
	}
	r.g1.termination = disposition
	r.g1.stoppedTimeNS = time.Now().UnixNano()
	if disposition != firecracker.TerminationBySupervisor {
		return fmt.Errorf("g1 Firecracker termination is %q, require supervisor SIGKILL", disposition)
	}
	r.result.G1SIGKILLConfirmed = true
	if err := r.events.Record("g1-sigkill-confirmed", r.g1, map[string]any{"disposition": disposition}); err != nil {
		return err
	}
	return r.finishStoppedGeneration(r.g1)
}

func (r *runner) finishStoppedGeneration(g *generation) error {
	var errs []error
	errs = append(errs, r.closeEndpoints(g))
	if g.client != nil {
		errs = append(errs, g.client.Close())
		g.client = nil
	}
	errs = append(errs, removeGenerationSockets(g), r.closeGenerationTraces(g))
	return errors.Join(errs...)
}

func (r *runner) closeEndpoints(g *generation) error {
	if g == nil {
		return nil
	}
	g.stopping.Store(true)
	if g.acceptCancel != nil {
		g.acceptCancel()
		g.acceptCancel = nil
	}
	var errs []error
	if g.listener != nil {
		errs = append(errs, g.listener.Close())
		g.listener = nil
	}
	if g.exportListener != nil {
		errs = append(errs, g.exportListener.Close())
		g.exportListener = nil
	}
	if g.relay != nil {
		errs = append(errs, r.closeModelRelay(g))
	}
	if g.acceptDone != nil {
		select {
		case <-g.acceptDone:
		case <-time.After(endpointDrainLimit):
			errs = append(errs, fmt.Errorf("g%d Codex accept loop did not stop", g.number))
		}
		g.acceptDone = nil
	}
	return errors.Join(errs...)
}

func (r *runner) cleanup() error {
	var errs []error
	for _, g := range []*generation{r.g3, r.g1} {
		if g == nil {
			continue
		}
		errs = append(errs, r.closeEndpoints(g))
		if g.client != nil {
			errs = append(errs, g.client.Close())
			g.client = nil
		}
		if g.process != nil && g.stoppedTimeNS == 0 {
			disposition, err := g.process.TerminateWithDisposition(r.ctx)
			if err != nil {
				errs = append(errs, fmt.Errorf("terminate g%d Firecracker: %w", g.number, err))
			} else {
				g.termination = disposition
				g.stoppedTimeNS = time.Now().UnixNano()
			}
		}
		errs = append(errs, removeGenerationSockets(g), r.closeGenerationTraces(g))
	}
	proxyAuditSafe := r.proxy == nil
	if r.proxy != nil {
		proxy := r.proxy
		errs = append(errs, proxy.Close())
		waitContext, waitCancel := context.WithTimeout(context.Background(), endpointDrainLimit)
		waitErr := proxy.Wait(waitContext)
		waitCancel()
		errs = append(errs, waitErr)
		proxyAuditSafe = !errors.Is(waitErr, context.DeadlineExceeded)
		r.proxy = nil
	}
	if r.proxyAudit != nil {
		// StartProxy may fail before a proxy owns this file. If a live proxy
		// timed out above, intentionally retain the descriptor until process
		// exit rather than race a late handler audit write.
		if !proxyAuditSafe {
			errs = append(errs, errors.New("model proxy handlers did not stop before audit cleanup"))
		} else {
			errs = append(errs, r.closeAndRetainEvidence(
				&r.proxyAudit, "model_proxy", "model-proxy.jsonl",
			))
		}
	}
	if r.bridgeIOFile != nil {
		bridgeInputSafe := r.bridge == nil
		if r.bridge != nil {
			waitContext, waitCancel := context.WithTimeout(context.Background(), endpointDrainLimit)
			waitErr := r.bridge.WaitInput(waitContext)
			waitCancel()
			errs = append(errs, waitErr)
			bridgeInputSafe = !errors.Is(waitErr, context.DeadlineExceeded)
		}
		if !bridgeInputSafe {
			errs = append(errs, errors.New("Codex bridge input did not stop before I/O audit cleanup"))
		} else {
			errs = append(errs, r.closeAndRetainEvidence(
				&r.bridgeIOFile, "bridge_io", "bridge-io.jsonl",
			))
			r.bridgeIO = nil
		}
	}
	for _, artifact := range []*sealedArtifact{
		r.snapshotMemory, r.snapshotState, r.initramfs, r.guest, r.repository, r.payload, r.kernel,
	} {
		if artifact != nil && artifact.file != nil {
			errs = append(errs, artifact.file.Close())
			artifact.file = nil
		}
	}
	return errors.Join(errs...)
}

func (r *runner) closeModelRelay(g *generation) error {
	if g == nil || g.relay == nil {
		return nil
	}
	relay := g.relay
	closeErr := relay.Close()
	waitContext, waitCancel := context.WithTimeout(context.Background(), endpointDrainLimit)
	waitErr := relay.Wait(waitContext)
	waitCancel()
	if !errors.Is(waitErr, context.DeadlineExceeded) {
		g.relayAuditSafe = true
		g.relay = nil
	}
	return errors.Join(closeErr, waitErr)
}

func (r *runner) closeGenerationTraces(g *generation) error {
	if g == nil || g.tracesClosed {
		return nil
	}
	label := fmt.Sprintf("g%d", g.number)
	var errs []error
	if g.apiTrace != nil {
		errs = append(errs, r.closeAndRetainEvidence(
			&g.apiTrace, "firecracker_api_"+label, "firecracker-api-"+label+".jsonl",
		))
	}
	if g.relayAudit != nil {
		if !g.relayAuditSafe {
			errs = append(errs, fmt.Errorf("%s relay handlers did not stop before audit cleanup", label))
		} else {
			errs = append(errs, r.closeAndRetainEvidence(
				&g.relayAudit, "firecracker_relay_"+label, "firecracker-relay-"+label+".jsonl",
			))
		}
	}
	g.tracesClosed = g.apiTrace == nil && g.relayAudit == nil
	return errors.Join(errs...)
}

func (r *runner) closeAndRetainEvidence(file **evidenceFile, key, name string) error {
	if file == nil || *file == nil {
		return nil
	}
	closeErr := (*file).Close()
	*file = nil
	if closeErr != nil {
		return closeErr
	}
	record, err := artifactForPath(name, filepath.Join(r.config.EvidenceDir, name), 0o600)
	if err != nil {
		return err
	}
	r.result.Artifacts[key] = record
	return nil
}

func (r *runner) processRecords() []processRecord {
	records := make([]processRecord, 0, 2)
	for _, g := range []*generation{r.g1, r.g3} {
		if g == nil || g.process == nil {
			continue
		}
		identity := g.process.Identity()
		records = append(records, processRecord{
			Generation: g.number, ID: g.id, PID: identity.PID,
			Executable: identity.Executable, ExecutableSHA256: identity.ExecutableSHA256,
			Device: identity.Device, Inode: identity.Inode, StartTimeTicks: identity.StartTimeTicks,
			VMMVersion: g.vmmVersion, StartedTimeNS: g.startedTimeNS, StoppedTimeNS: g.stoppedTimeNS,
			Termination: g.termination, APISocket: g.apiSocket, VsockBackend: g.vsockBackend,
		})
	}
	return records
}

func (r *runner) watchEvidence(file *evidenceFile, label string) {
	if file == nil {
		return
	}
	go func() {
		select {
		case <-file.Failed():
			err := file.Failure()
			if err == nil {
				err = errors.New("unknown evidence failure")
			}
			r.cancel()
			if r.bridge != nil {
				r.bridge.Fail(fmt.Errorf("%s: %w", label, err))
			}
		case <-r.ctx.Done():
		}
	}()
}

func (audit *bridgeIOLog) Record(phase, direction string, line []byte) error {
	if audit == nil || audit.file == nil {
		return errors.New("bridge I/O audit is unavailable")
	}
	if direction != codexvm.DirectionClientToServer && direction != codexvm.DirectionServerToClient {
		return fmt.Errorf("bridge I/O audit direction %q is invalid", direction)
	}
	if phase != codexvm.PhaseObserved && phase != codexvm.PhaseAuthorized && phase != codexvm.PhaseDelivered {
		return fmt.Errorf("bridge I/O audit phase %q is invalid", phase)
	}
	if direction == codexvm.DirectionClientToServer && phase != codexvm.PhaseObserved {
		return errors.New("client-to-server bridge I/O must use observed phase")
	}
	if direction == codexvm.DirectionServerToClient && phase == codexvm.PhaseObserved {
		return errors.New("server-to-client bridge I/O must use authorized or delivered phase")
	}
	canonical, err := agentwire.CanonicalJSONObject(line)
	if err != nil {
		return fmt.Errorf("canonicalize bridge I/O: %w", err)
	}
	digest := sha256.Sum256(canonical)
	audit.mu.Lock()
	defer audit.mu.Unlock()
	audit.sequence++
	record := bridgeIORecord{
		Schema: evidenceEventSchema, Sequence: audit.sequence, Phase: phase, Direction: direction,
		TimeNS: time.Now().UnixNano(), Size: len(canonical), SHA256: hex.EncodeToString(digest[:]),
	}
	encoded, err := json.Marshal(record)
	if err != nil {
		return fmt.Errorf("encode bridge I/O audit: %w", err)
	}
	if _, err := audit.file.Write(append(encoded, '\n')); err != nil {
		return fmt.Errorf("write bridge I/O audit: %w", err)
	}
	return nil
}

func buildGuestConfig(config codexvm.Config, sessionID string, repository *sealedArtifact, tree repobundle.Bundle) (agentguest.Config, error) {
	if repository == nil || repository.file == nil || tree.Schema != repobundle.Schema {
		return agentguest.Config{}, errors.New("verified repository is unavailable for guest config")
	}
	guestConfig := agentguest.Config{
		Schema: agentguest.ConfigSchema, SessionID: sessionID, CodexSHA256: config.CodexSHA256,
		Arguments: append([]string(nil), config.Arguments...), StreamPort: agentguest.DefaultStreamPort,
		ModelPort: config.GuestModelPort, PayloadDrive: guestPayloadDrive,
		RepositoryDrive: guestRepositoryDrive, RepositorySize: uint64(repository.record.Artifact.Size),
		RepositorySHA256: repository.record.Artifact.SHA256, RepositoryTreeRoot: tree.TreeRoot.String(),
	}
	if err := guestConfig.Validate(); err != nil {
		return agentguest.Config{}, fmt.Errorf("validate strict guest config: %w", err)
	}
	return guestConfig, nil
}

func buildRuntimeInitramfs(guest, configJSON []byte) (*sealedArtifact, error) {
	file, err := newMemfd("codex-runtime-initramfs")
	if err != nil {
		return nil, err
	}
	if err := firecracker.BuildRuntimeInitramfs(file, guest, configJSON); err != nil {
		_ = file.Close()
		return nil, fmt.Errorf("build runtime initramfs: %w", err)
	}
	return finalizeMemfd("runtime-initramfs", file, 5)
}

func sealPath(name, path, expectedSHA256 string, childFD int, maxSize int64) (*sealedArtifact, error) {
	initial, err := os.Lstat(path)
	if err != nil {
		return nil, fmt.Errorf("inspect %s source: %w", name, err)
	}
	if initial.Mode()&os.ModeSymlink != 0 || !initial.Mode().IsRegular() || initial.Size() <= 0 {
		return nil, fmt.Errorf("%s source must be a non-empty direct regular file", name)
	}
	if maxSize > 0 && initial.Size() > maxSize {
		return nil, fmt.Errorf("%s source is %d bytes, limit %d", name, initial.Size(), maxSize)
	}
	descriptor, err := unix.Open(path, unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return nil, fmt.Errorf("open %s source: %w", name, err)
	}
	source := os.NewFile(uintptr(descriptor), path)
	if source == nil {
		_ = unix.Close(descriptor)
		return nil, fmt.Errorf("wrap %s source descriptor", name)
	}
	defer source.Close()
	opened, err := source.Stat()
	if err != nil {
		return nil, fmt.Errorf("stat %s source: %w", name, err)
	}
	if !opened.Mode().IsRegular() || !os.SameFile(initial, opened) {
		return nil, fmt.Errorf("%s source changed while opening", name)
	}

	sealed, err := newMemfd("sealed-" + name)
	if err != nil {
		return nil, err
	}
	fail := func(failure error) (*sealedArtifact, error) {
		_ = sealed.Close()
		return nil, failure
	}
	digest := sha256.New()
	written, err := io.CopyN(io.MultiWriter(sealed, digest), source, opened.Size())
	if err != nil {
		return fail(fmt.Errorf("copy %s into sealed memfd: copied %d of %d: %w", name, written, opened.Size(), err))
	}
	if written != opened.Size() {
		return fail(fmt.Errorf("copy %s into sealed memfd: copied %d of %d", name, written, opened.Size()))
	}
	var extra [1]byte
	if count, readErr := source.Read(extra[:]); count != 0 || !errors.Is(readErr, io.EOF) {
		return fail(fmt.Errorf("%s source size changed while sealing", name))
	}
	current, err := os.Lstat(path)
	if err != nil {
		return fail(fmt.Errorf("reinspect %s source: %w", name, err))
	}
	if !os.SameFile(initial, current) {
		return fail(fmt.Errorf("%s source path changed while sealing", name))
	}
	actualHash := hex.EncodeToString(digest.Sum(nil))
	if expectedSHA256 != "" && actualHash != expectedSHA256 {
		return fail(fmt.Errorf("%s SHA-256 is %s, require %s", name, actualHash, expectedSHA256))
	}
	result, err := finalizeMemfd(name, sealed, childFD)
	if err != nil {
		return nil, err
	}
	if result.record.Artifact.SHA256 != actualHash || result.record.Artifact.Size != opened.Size() {
		_ = result.file.Close()
		return nil, fmt.Errorf("sealed %s differs from streamed source", name)
	}
	return result, nil
}

func newMemfd(name string) (*os.File, error) {
	descriptor, err := unix.MemfdCreate(name, unix.MFD_CLOEXEC|unix.MFD_ALLOW_SEALING)
	if err != nil {
		return nil, fmt.Errorf("create %s memfd: %w", name, err)
	}
	file := os.NewFile(uintptr(descriptor), name)
	if file == nil {
		_ = unix.Close(descriptor)
		return nil, fmt.Errorf("wrap %s memfd", name)
	}
	return file, nil
}

func finalizeMemfd(name string, file *os.File, childFD int) (*sealedArtifact, error) {
	if file == nil {
		return nil, fmt.Errorf("finalize nil %s memfd", name)
	}
	fail := func(failure error) (*sealedArtifact, error) {
		_ = file.Close()
		return nil, failure
	}
	if err := file.Sync(); err != nil {
		return fail(fmt.Errorf("sync %s memfd: %w", name, err))
	}
	if err := file.Chmod(0o400); err != nil {
		return fail(fmt.Errorf("protect %s memfd: %w", name, err))
	}
	if _, err := unix.FcntlInt(file.Fd(), unix.F_ADD_SEALS, immutableSeals); err != nil {
		return fail(fmt.Errorf("seal immutable %s memfd: %w", name, err))
	}
	actualSeals, err := unix.FcntlInt(file.Fd(), unix.F_GET_SEALS, 0)
	if err != nil {
		return fail(fmt.Errorf("verify %s memfd seals: got %d, require %d: %w", name, actualSeals, immutableSeals, err))
	}
	if actualSeals != immutableSeals {
		return fail(fmt.Errorf("verify %s memfd seals: got %d, require %d", name, actualSeals, immutableSeals))
	}
	record, err := artifactForOpenFile(name, file)
	if err != nil {
		return fail(err)
	}
	if record.Size <= 0 {
		return fail(fmt.Errorf("sealed %s memfd is empty", name))
	}
	return &sealedArtifact{file: file, record: sealedArtifactRecord{
		Artifact: record, ChildFD: childFD, LinuxSeals: actualSeals,
	}}, nil
}

func readSealedArtifact(artifact *sealedArtifact, maxBytes int64) ([]byte, error) {
	if artifact == nil || artifact.file == nil || maxBytes <= 0 {
		return nil, errors.New("invalid sealed artifact read")
	}
	if artifact.record.Artifact.Size > maxBytes {
		return nil, fmt.Errorf("sealed artifact exceeds %d bytes", maxBytes)
	}
	if _, err := artifact.file.Seek(0, io.SeekStart); err != nil {
		return nil, err
	}
	data, err := io.ReadAll(io.LimitReader(artifact.file, maxBytes+1))
	if err != nil {
		return nil, err
	}
	if int64(len(data)) != artifact.record.Artifact.Size {
		return nil, errors.New("sealed artifact size differs from its record")
	}
	if _, err := artifact.file.Seek(0, io.SeekStart); err != nil {
		return nil, err
	}
	return data, nil
}

func decodeSealedRepository(artifact *sealedArtifact) (repobundle.Bundle, error) {
	if artifact == nil || artifact.file == nil || artifact.record.Artifact.Name != "repository" {
		return repobundle.Bundle{}, errors.New("sealed repository artifact is unavailable")
	}
	size := artifact.record.Artifact.Size
	if size <= 0 || uint64(size) > agentguest.MaxRepositoryBytes || size%512 != 0 {
		return repobundle.Bundle{}, fmt.Errorf("sealed repository size %d is not a bounded block image", size)
	}
	bundle, err := repobundle.Decode(io.NewSectionReader(artifact.file, 0, size), repobundle.DefaultLimits())
	if err != nil {
		return repobundle.Bundle{}, fmt.Errorf("decode sealed repository: %w", err)
	}
	return bundle, nil
}

func (r *runner) receiveFinalRepository() error {
	if r.g3 == nil || r.g3.exportListener == nil {
		return errors.New("restored repository export listener is unavailable")
	}
	exportContext, cancel := context.WithTimeout(r.ctx, repositoryExportLimit)
	defer cancel()
	connection, err := r.g3.exportListener.Accept(exportContext)
	if err != nil {
		return fmt.Errorf("accept final repository export: %w", err)
	}
	if deadline, ok := exportContext.Deadline(); ok {
		_ = connection.SetDeadline(deadline)
	}
	finalPath := filepath.Join(r.config.EvidenceDir, "repository-final.bundle")
	finalBundle, finalArtifact, receiveErr := receiveRepositoryBundle(connection, finalPath)
	closeErr := connection.Close()
	if err := errors.Join(receiveErr, closeErr); err != nil {
		return err
	}
	delta, err := repodelta.Compute(r.repositoryTree, finalBundle, repodelta.DefaultLimits())
	if err != nil {
		return fmt.Errorf("derive repository delta: %w", err)
	}
	deltaArtifact, err := persistRepositoryDelta(
		filepath.Join(r.config.EvidenceDir, "repository.delta"), r.repositoryTree, finalBundle, delta,
	)
	if err != nil {
		return err
	}
	r.result.Artifacts["repository_final"] = finalArtifact
	r.result.Artifacts["repository_delta"] = deltaArtifact
	r.result.RepositoryChange = &repositoryChangeRecord{
		BaseRoot: r.repositoryTree.TreeRoot.String(), FinalRoot: finalBundle.TreeRoot.String(),
		OperationCount: len(delta.Operations),
	}
	return r.events.Record("repository-exported", r.g3, map[string]any{
		"base_root": r.repositoryTree.TreeRoot.String(), "final_root": finalBundle.TreeRoot.String(),
		"operation_count": len(delta.Operations), "final_bundle": finalArtifact, "delta": deltaArtifact,
	})
}

func receiveRepositoryBundle(reader io.Reader, path string) (repobundle.Bundle, artifactRecord, error) {
	if reader == nil {
		return repobundle.Bundle{}, artifactRecord{}, errors.New("final repository reader is nil")
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return repobundle.Bundle{}, artifactRecord{}, fmt.Errorf("create final repository evidence: %w", err)
	}
	fail := func(failure error) (repobundle.Bundle, artifactRecord, error) {
		closeErr := file.Close()
		removeErr := os.Remove(path)
		return repobundle.Bundle{}, artifactRecord{}, errors.Join(failure, closeErr, removeErr)
	}
	bundle, decodeErr := repobundle.Decode(io.TeeReader(reader, file), repobundle.DefaultLimits())
	if decodeErr != nil {
		return fail(fmt.Errorf("decode final repository export: %w", decodeErr))
	}
	if err := file.Sync(); err != nil {
		return fail(err)
	}
	if err := file.Close(); err != nil {
		_ = os.Remove(path)
		return repobundle.Bundle{}, artifactRecord{}, err
	}
	record, err := artifactForPath("repository-final.bundle", path, 0o600)
	if err != nil {
		return repobundle.Bundle{}, artifactRecord{}, err
	}
	return bundle, record, nil
}

func persistRepositoryDelta(path string, base, final repobundle.Bundle, delta repodelta.Delta) (artifactRecord, error) {
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return artifactRecord{}, fmt.Errorf("create repository delta evidence: %w", err)
	}
	fail := func(failure error) (artifactRecord, error) {
		closeErr := file.Close()
		removeErr := os.Remove(path)
		return artifactRecord{}, errors.Join(failure, closeErr, removeErr)
	}
	if err := repodelta.Encode(file, delta, repodelta.DefaultLimits()); err != nil {
		return fail(fmt.Errorf("encode repository delta: %w", err))
	}
	if err := file.Sync(); err != nil {
		return fail(err)
	}
	if err := file.Close(); err != nil {
		_ = os.Remove(path)
		return artifactRecord{}, err
	}
	check, err := os.Open(path)
	if err != nil {
		return artifactRecord{}, err
	}
	decoded, decodeErr := repodelta.Decode(check, repodelta.DefaultLimits())
	closeErr := check.Close()
	if err := errors.Join(decodeErr, closeErr); err != nil {
		return artifactRecord{}, err
	}
	applied, err := repodelta.Apply(base, decoded, repodelta.DefaultLimits())
	if err != nil || applied.TreeRoot != final.TreeRoot {
		return artifactRecord{}, errors.Join(errors.New("repository delta does not reconstruct the exported tree"), err)
	}
	return artifactForPath("repository.delta", path, 0o600)
}

func artifactForOpenFile(name string, file *os.File) (artifactRecord, error) {
	if file == nil {
		return artifactRecord{}, errors.New("artifact file is nil")
	}
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
	return artifactRecord{
		Name: name, Size: info.Size(), Mode: uint32(info.Mode().Perm()),
		SHA256: hex.EncodeToString(digest.Sum(nil)),
	}, nil
}

func artifactForProcess(process *firecracker.Process) (artifactRecord, error) {
	if process == nil {
		return artifactRecord{}, errors.New("Firecracker process is nil")
	}
	if err := process.VerifyIdentity(); err != nil {
		return artifactRecord{}, fmt.Errorf("verify Firecracker before recording executable: %w", err)
	}
	identity := process.Identity()
	file, err := os.Open(fmt.Sprintf("/proc/%d/exe", identity.PID))
	if err != nil {
		return artifactRecord{}, fmt.Errorf("open exact Firecracker executable: %w", err)
	}
	info, statErr := file.Stat()
	if statErr != nil {
		_ = file.Close()
		return artifactRecord{}, fmt.Errorf("stat exact Firecracker executable: %w", statErr)
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || uint64(stat.Dev) != identity.Device || stat.Ino != identity.Inode {
		_ = file.Close()
		return artifactRecord{}, errors.New("Firecracker executable identity changed while recording")
	}
	record, recordErr := artifactForOpenFile("firecracker", file)
	closeErr := file.Close()
	if recordErr != nil || closeErr != nil {
		return artifactRecord{}, errors.Join(recordErr, closeErr)
	}
	if record.SHA256 != identity.ExecutableSHA256 {
		return artifactRecord{}, errors.New("recorded Firecracker executable hash differs from process identity")
	}
	return record, nil
}

func retainSelfExecutable(path, expectedSHA256 string) (artifactRecord, error) {
	file, err := os.Open("/proc/self/exe")
	if err != nil {
		return artifactRecord{}, fmt.Errorf("open running shim executable: %w", err)
	}
	info, statErr := file.Stat()
	if statErr != nil || !info.Mode().IsRegular() || info.Size() <= 0 || info.Mode().Perm()&0o111 == 0 {
		_ = file.Close()
		if statErr != nil {
			return artifactRecord{}, fmt.Errorf("stat running shim executable: %w", statErr)
		}
		return artifactRecord{}, errors.New("running shim executable is not a non-empty executable regular file")
	}
	source, recordErr := artifactForOpenFile("runner", file)
	if recordErr == nil && source.SHA256 != expectedSHA256 {
		recordErr = fmt.Errorf("running shim SHA-256 is %s, require %s", source.SHA256, expectedSHA256)
	}
	var retained artifactRecord
	if recordErr == nil {
		retained, recordErr = persistOpenArtifact("runner", path, file, source)
	}
	closeErr := file.Close()
	if recordErr != nil || closeErr != nil {
		return artifactRecord{}, errors.Join(recordErr, closeErr)
	}
	return retained, nil
}

func bytesArtifact(name string, data []byte, mode os.FileMode) artifactRecord {
	digest := sha256.Sum256(data)
	return artifactRecord{Name: name, Size: int64(len(data)), Mode: uint32(mode.Perm()), SHA256: hex.EncodeToString(digest[:])}
}

func persistBytesArtifact(name, path string, data []byte) (artifactRecord, error) {
	expected := bytesArtifact(name, data, 0o600)
	return persistReaderArtifact(name, path, bytes.NewReader(data), expected)
}

func persistOpenArtifact(name, path string, source *os.File, expected artifactRecord) (artifactRecord, error) {
	if source == nil {
		return artifactRecord{}, fmt.Errorf("persist %s from nil source", name)
	}
	if _, err := source.Seek(0, io.SeekStart); err != nil {
		return artifactRecord{}, fmt.Errorf("rewind %s source: %w", name, err)
	}
	record, err := persistReaderArtifact(name, path, source, expected)
	_, seekErr := source.Seek(0, io.SeekStart)
	return record, errors.Join(err, seekErr)
}

func persistReaderArtifact(name, path string, source io.Reader, expected artifactRecord) (artifactRecord, error) {
	if source == nil || expected.Size <= 0 || expected.SHA256 == "" {
		return artifactRecord{}, fmt.Errorf("persist %s requires a non-empty bound source", name)
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return artifactRecord{}, fmt.Errorf("create retained %s: %w", name, err)
	}
	written, copyErr := io.CopyN(file, source, expected.Size)
	if copyErr == nil && written != expected.Size {
		copyErr = io.ErrShortWrite
	}
	if copyErr == nil {
		var extra [1]byte
		if count, readErr := source.Read(extra[:]); count != 0 || !errors.Is(readErr, io.EOF) {
			copyErr = fmt.Errorf("%s source size changed while retaining", name)
		}
	}
	syncErr := file.Sync()
	closeErr := file.Close()
	if copyErr != nil || syncErr != nil || closeErr != nil {
		var copyFailure error
		if copyErr != nil {
			copyFailure = fmt.Errorf("retain %s: copied %d of %d: %w", name, written, expected.Size, copyErr)
		}
		return artifactRecord{}, errors.Join(copyFailure, syncErr, closeErr)
	}
	record, err := artifactForPath(name, path, 0o600)
	if err != nil {
		return artifactRecord{}, err
	}
	if record.Size != expected.Size || record.SHA256 != expected.SHA256 {
		return artifactRecord{}, fmt.Errorf("retained %s differs from the VM input", name)
	}
	return record, nil
}

func artifactForPath(name, path string, requiredMode os.FileMode) (artifactRecord, error) {
	initial, err := os.Lstat(path)
	if err != nil {
		return artifactRecord{}, fmt.Errorf("inspect retained %s: %w", name, err)
	}
	if initial.Mode()&os.ModeSymlink != 0 || !initial.Mode().IsRegular() || initial.Size() <= 0 || initial.Mode().Perm() != requiredMode.Perm() {
		return artifactRecord{}, fmt.Errorf("retained %s must be a non-empty direct %04o regular file", name, requiredMode.Perm())
	}
	descriptor, err := unix.Open(path, unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return artifactRecord{}, fmt.Errorf("open retained %s: %w", name, err)
	}
	file := os.NewFile(uintptr(descriptor), path)
	if file == nil {
		_ = unix.Close(descriptor)
		return artifactRecord{}, fmt.Errorf("wrap retained %s descriptor", name)
	}
	opened, statErr := file.Stat()
	if statErr != nil || !os.SameFile(initial, opened) || opened.Mode().Perm() != requiredMode.Perm() {
		_ = file.Close()
		if statErr != nil {
			return artifactRecord{}, fmt.Errorf("stat retained %s: %w", name, statErr)
		}
		return artifactRecord{}, fmt.Errorf("retained %s changed while opening", name)
	}
	record, recordErr := artifactForOpenFile(name, file)
	closeErr := file.Close()
	current, pathErr := os.Lstat(path)
	if pathErr == nil && (!os.SameFile(initial, current) || current.Mode().Perm() != requiredMode.Perm()) {
		pathErr = fmt.Errorf("retained %s path identity or mode changed", name)
	}
	if recordErr != nil || closeErr != nil || pathErr != nil {
		return artifactRecord{}, errors.Join(recordErr, closeErr, pathErr)
	}
	return record, nil
}

func finalizeSnapshotFile(name, path string) (artifactRecord, error) {
	initial, err := os.Lstat(path)
	if err != nil {
		return artifactRecord{}, fmt.Errorf("inspect %s: %w", name, err)
	}
	if initial.Mode()&os.ModeSymlink != 0 || !initial.Mode().IsRegular() || initial.Size() <= 0 {
		return artifactRecord{}, fmt.Errorf("%s must be a non-empty direct regular file", name)
	}
	descriptor, err := unix.Open(path, unix.O_RDWR|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return artifactRecord{}, fmt.Errorf("open %s: %w", name, err)
	}
	file := os.NewFile(uintptr(descriptor), path)
	if file == nil {
		_ = unix.Close(descriptor)
		return artifactRecord{}, fmt.Errorf("wrap %s descriptor", name)
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil {
		return artifactRecord{}, fmt.Errorf("stat %s: %w", name, err)
	}
	if !os.SameFile(initial, opened) {
		return artifactRecord{}, fmt.Errorf("%s changed while opening", name)
	}
	if err := file.Chmod(0o600); err != nil {
		return artifactRecord{}, fmt.Errorf("protect %s: %w", name, err)
	}
	if err := file.Sync(); err != nil {
		return artifactRecord{}, fmt.Errorf("fsync %s: %w", name, err)
	}
	record, err := artifactForOpenFile(name, file)
	if err != nil {
		return artifactRecord{}, err
	}
	current, err := os.Lstat(path)
	if err != nil {
		return artifactRecord{}, fmt.Errorf("reinspect %s: %w", name, err)
	}
	if !os.SameFile(initial, current) || current.Mode().Perm() != 0o600 {
		return artifactRecord{}, fmt.Errorf("%s changed while finalizing", name)
	}
	return record, nil
}

func argumentsDigest(arguments []string) (string, error) {
	encoded, err := json.Marshal(arguments)
	if err != nil {
		return "", fmt.Errorf("encode exact guest arguments: %w", err)
	}
	digest := sha256.Sum256(encoded)
	return hex.EncodeToString(digest[:]), nil
}

func generateRunIDs(reader io.Reader) (string, string, string, error) {
	session, err := randomHex(reader, agentguest.SessionIDHexBytes)
	if err != nil {
		return "", "", "", err
	}
	idG1, err := randomHex(reader, 16)
	if err != nil {
		return "", "", "", err
	}
	for attempts := 0; attempts < 8; attempts++ {
		idG3, err := randomHex(reader, 16)
		if err != nil {
			return "", "", "", err
		}
		if idG3 != idG1 {
			return session, idG1, idG3, nil
		}
	}
	return "", "", "", errors.New("could not generate distinct Firecracker VM IDs")
}

func randomHex(reader io.Reader, bytesCount int) (string, error) {
	if reader == nil || bytesCount <= 0 {
		return "", errors.New("random hex requires a reader and positive size")
	}
	buffer := make([]byte, bytesCount)
	if _, err := io.ReadFull(reader, buffer); err != nil {
		return "", fmt.Errorf("read random bytes: %w", err)
	}
	return hex.EncodeToString(buffer), nil
}

func validateRuntimePaths(directory string, modelPort uint32) error {
	paths := []string{
		filepath.Join(directory, "model-proxy.sock"),
		filepath.Join(directory, "api-g1.sock"), filepath.Join(directory, "api-g3.sock"),
		filepath.Join(directory, "vsock-g1") + "_" + fmt.Sprint(agentguest.DefaultStreamPort),
		filepath.Join(directory, "vsock-g1") + "_" + fmt.Sprint(agentguest.DefaultExportPort),
		filepath.Join(directory, "vsock-g1") + "_" + fmt.Sprint(modelPort),
		filepath.Join(directory, "vsock-g3") + "_" + fmt.Sprint(agentguest.DefaultStreamPort),
		filepath.Join(directory, "vsock-g3") + "_" + fmt.Sprint(agentguest.DefaultExportPort),
		filepath.Join(directory, "vsock-g3") + "_" + fmt.Sprint(modelPort),
	}
	for _, path := range paths {
		if len([]byte(path)) >= unixSocketPathLimit {
			return fmt.Errorf("runtime Unix socket path is too long: %q", path)
		}
	}
	return nil
}

func requireAbsent(paths ...string) error {
	for _, path := range paths {
		_, err := os.Lstat(path)
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			return fmt.Errorf("inspect future evidence path %q: %w", path, err)
		}
		return fmt.Errorf("refusing to overwrite existing evidence path %q", path)
	}
	return nil
}

func captureSocket(path string) (socketRecord, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return socketRecord{}, err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || info.Mode()&os.ModeSymlink != 0 || info.Mode()&os.ModeSocket == 0 || stat.Uid != uint32(os.Geteuid()) {
		return socketRecord{}, errors.New("Firecracker path is not a current-user direct Unix socket")
	}
	if info.Mode().Perm() != 0o600 {
		if err := unix.Fchmodat(unix.AT_FDCWD, path, 0o600, unix.AT_SYMLINK_NOFOLLOW); err != nil {
			return socketRecord{}, fmt.Errorf("protect Firecracker Unix socket: %w", err)
		}
		updated, err := os.Lstat(path)
		if err != nil || !os.SameFile(info, updated) || updated.Mode().Perm() != 0o600 {
			return socketRecord{}, errors.New("Firecracker Unix socket changed while protecting")
		}
		info = updated
		stat, ok = info.Sys().(*syscall.Stat_t)
		if !ok {
			return socketRecord{}, errors.New("Firecracker Unix socket lacks Linux identity")
		}
	}
	return socketRecord{Path: path, Device: uint64(stat.Dev), Inode: stat.Ino, Mode: uint32(info.Mode().Perm()), UID: stat.Uid}, nil
}

func removeGenerationSockets(g *generation) error {
	if g == nil {
		return nil
	}
	return errors.Join(
		captureExistingSocket(g.apiPath, &g.apiSocket),
		captureExistingSocket(g.basePath, &g.vsockBackend),
		removeOwnedSocket(g.apiSocket),
		removeOwnedSocket(g.vsockBackend),
	)
}

func captureExistingSocket(path string, record *socketRecord) error {
	if record == nil || record.Path != "" {
		return nil
	}
	if _, err := os.Lstat(path); errors.Is(err, os.ErrNotExist) {
		return nil
	} else if err != nil {
		return err
	}
	captured, err := captureSocket(path)
	if err != nil {
		return err
	}
	*record = captured
	return nil
}

func removeOwnedSocket(record socketRecord) error {
	if record.Path == "" || record.Inode == 0 {
		return nil
	}
	info, err := os.Lstat(record.Path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || info.Mode()&os.ModeSymlink != 0 || info.Mode()&os.ModeSocket == 0 ||
		uint64(stat.Dev) != record.Device || stat.Ino != record.Inode {
		return fmt.Errorf("refuse to remove replaced Firecracker socket %q", record.Path)
	}
	return os.Remove(record.Path)
}

func openEvidenceFile(path string) (*evidenceFile, error) {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, err
	}
	info, err := file.Stat()
	if err != nil {
		_ = file.Close()
		return nil, fmt.Errorf("stat new evidence file: %w", err)
	}
	if !info.Mode().IsRegular() || info.Mode().Perm() != 0o600 {
		_ = file.Close()
		return nil, errors.New("new evidence file is not a regular 0600 file")
	}
	return &evidenceFile{file: file, failed: make(chan struct{})}, nil
}

func (file *evidenceFile) Write(data []byte) (int, error) {
	if file == nil {
		return 0, errors.New("evidence file is nil")
	}
	file.mu.Lock()
	defer file.mu.Unlock()
	if file.failure != nil {
		return 0, file.failure
	}
	if file.closed || file.file == nil {
		return 0, file.setFailureLocked(errors.New("evidence file is closed"))
	}
	written, err := file.file.Write(data)
	if err == nil && written != len(data) {
		err = io.ErrShortWrite
	}
	if err == nil {
		err = file.file.Sync()
	}
	if err != nil {
		return written, file.setFailureLocked(fmt.Errorf("durably write evidence: %w", err))
	}
	return written, nil
}

func (file *evidenceFile) setFailureLocked(err error) error {
	if err != nil && file.failure == nil {
		file.failure = err
		file.failOnce.Do(func() { close(file.failed) })
	}
	return file.failure
}

func (file *evidenceFile) Failure() error {
	if file == nil {
		return nil
	}
	file.mu.Lock()
	defer file.mu.Unlock()
	return file.failure
}

func (file *evidenceFile) Failed() <-chan struct{} {
	if file == nil {
		closed := make(chan struct{})
		close(closed)
		return closed
	}
	return file.failed
}

func (file *evidenceFile) Close() error {
	if file == nil {
		return nil
	}
	file.mu.Lock()
	defer file.mu.Unlock()
	if file.closed {
		return file.failure
	}
	file.closed = true
	var err error
	if file.file != nil {
		err = errors.Join(file.file.Sync(), file.file.Close())
		file.file = nil
	}
	if err != nil {
		file.setFailureLocked(fmt.Errorf("close evidence: %w", err))
	}
	return file.failure
}

func (events *eventLog) Record(event string, g *generation, details map[string]any) error {
	if events == nil || events.file == nil || event == "" {
		return errors.New("invalid evidence event")
	}
	events.mu.Lock()
	defer events.mu.Unlock()
	events.sequence++
	record := eventRecord{
		Schema: evidenceEventSchema, Sequence: events.sequence, Event: event,
		TimeNS: time.Now().UnixNano(), Details: details,
	}
	if g != nil {
		record.Generation = g.number
		record.InstanceID = g.id
		if g.process != nil {
			record.PID = g.process.PID()
		}
	}
	encoded, err := json.Marshal(record)
	if err != nil {
		return err
	}
	_, err = events.file.Write(append(encoded, '\n'))
	return err
}

func (events *eventLog) Close() error {
	if events == nil {
		return nil
	}
	return events.file.Close()
}

func writePrivateJSON(path string, value any) error {
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(value); err != nil {
		return err
	}
	file, err := openEvidenceFile(path)
	if err != nil {
		return err
	}
	_, writeErr := file.Write(buffer.Bytes())
	return errors.Join(writeErr, file.Close())
}

func errorString(err error) string {
	if err == nil {
		return ""
	}
	return strings.TrimSpace(err.Error())
}
