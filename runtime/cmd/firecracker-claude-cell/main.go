//go:build linux

// Command firecracker-claude-cell runs one disposable Claude Code microVM.
// The host model endpoint and MCP authority remain outside the VM. stdin may
// contain "kill" to destroy the exact pidfd-bound VMM while an Operation is
// in flight; otherwise the command waits for Claude's authenticated result.
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
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentguest"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentwire"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/firecracker"
	"golang.org/x/sys/unix"
)

const (
	officialFirecrackerVersion = "1.16.1"
	officialFirecrackerSHA256  = "2fd0171309af7e24cf8dafc8a6f921c1434c49b5f9349bb996b7ed0a4deb8aa7"
	officialKernelSHA256       = "e20e46d0c36c55c0d1014eb20576171b3f3d922260d9f792017aeff53af3d4f2"
	officialKernelVersion      = "6.1.155"
	guestCID                   = uint32(3)
	guestMemoryMiB             = 1024
	bootArguments              = "console=ttyS0 reboot=k panic=1 pci=off rdinit=/init"
	maxGuestBytes              = int64(64 << 20)
	maxPayloadBytes            = int64(1 << 30)
	endpointTimeout            = 5 * time.Second
)

type options struct {
	timeout           time.Duration
	generation        uint64
	instanceID        string
	sessionID         string
	firecrackerPath   string
	firecrackerSHA256 string
	kernelPath        string
	kernelSHA256      string
	guestPath         string
	payloadPath       string
	payloadSHA256     string
	claudeSHA256      string
	relaySHA256       string
	modelTarget       string
	mcpHostSocket     string
	profile           string
	egressTarget      string
	busyBoxSHA256     string
	bashSHA256        string
	evidenceDir       string
	launchManifest    string
}

type artifactRecord struct {
	Name   string `json:"name"`
	Size   int64  `json:"size"`
	Mode   uint32 `json:"mode"`
	SHA256 string `json:"sha256"`
}

type processRecord struct {
	Generation       uint64                             `json:"generation"`
	InstanceID       string                             `json:"instance_id"`
	PID              int                                `json:"pid"`
	Executable       string                             `json:"executable"`
	ExecutableSHA256 string                             `json:"executable_sha256"`
	StartTimeTicks   uint64                             `json:"start_time_ticks"`
	StartedTimeNS    int64                              `json:"started_time_ns"`
	StoppedTimeNS    int64                              `json:"stopped_time_ns"`
	Termination      firecracker.TerminationDisposition `json:"termination"`
}

type cellResult struct {
	Schema             int                       `json:"schema"`
	Valid              bool                      `json:"valid"`
	Backend            string                    `json:"backend"`
	FirecrackerVersion string                    `json:"firecracker_version"`
	KernelVersion      string                    `json:"kernel_version"`
	Generation         uint64                    `json:"generation"`
	SessionID          string                    `json:"session_id"`
	Disposition        string                    `json:"disposition"`
	ToolProfile        string                    `json:"tool_profile"`
	NetworkInterfaces  int                       `json:"network_interfaces"`
	RootBlockDevices   int                       `json:"root_block_devices"`
	ReadOnlyPayload    bool                      `json:"read_only_payload"`
	LaunchGuarded      bool                      `json:"launch_guarded"`
	LaunchDecision     string                    `json:"launch_decision"`
	InstanceStarted    bool                      `json:"instance_started"`
	GuestResult        *firecracker.Result       `json:"guest_result,omitempty"`
	Process            processRecord             `json:"process"`
	Artifacts          map[string]artifactRecord `json:"artifacts"`
}

type sealedArtifact struct {
	file   *os.File
	record artifactRecord
}

type launchInputs struct {
	client        *firecracker.Client
	process       *firecracker.Process
	artifacts     map[string]artifactRecord
	artifactFiles map[string]*os.File
	configuration json.RawMessage
	evidenceDir   string
}

type launchResult struct {
	Guarded  bool
	Decision string
	Started  bool
}

func main() {
	defaultFirecracker, defaultKernel := defaultAssets()
	var config options
	flag.DurationVar(&config.timeout, "timeout", 3*time.Minute, "whole-cell timeout")
	flag.Uint64Var(&config.generation, "generation", 0, "positive VM generation")
	flag.StringVar(&config.instanceID, "instance-id", "", "unique Firecracker instance ID (random by default)")
	flag.StringVar(&config.sessionID, "session-id", "", "16-byte lowercase hex Claude session (random by default)")
	flag.StringVar(&config.firecrackerPath, "firecracker", defaultFirecracker, "pinned Firecracker executable")
	flag.StringVar(&config.firecrackerSHA256, "firecracker-sha256", officialFirecrackerSHA256, "required Firecracker SHA-256")
	flag.StringVar(&config.kernelPath, "kernel", defaultKernel, "pinned guest kernel")
	flag.StringVar(&config.kernelSHA256, "kernel-sha256", officialKernelSHA256, "required kernel SHA-256")
	flag.StringVar(&config.guestPath, "guest", "", "static firecracker-claude-guest executable")
	flag.StringVar(&config.payloadPath, "payload", "", "immutable Claude SquashFS payload")
	flag.StringVar(&config.payloadSHA256, "payload-sha256", "", "required payload SHA-256")
	flag.StringVar(&config.claudeSHA256, "claude-sha256", "", "required Claude executable SHA-256")
	flag.StringVar(&config.relaySHA256, "relay-sha256", "", "required MCP relay SHA-256")
	flag.StringVar(&config.modelTarget, "model-target", "", "fixed numeric host loopback model address")
	flag.StringVar(&config.mcpHostSocket, "mcp-host-socket", "", "host MCP Unix socket")
	flag.StringVar(&config.profile, "profile", "mcp", "fixed guest tool profile: mcp or http")
	flag.StringVar(&config.egressTarget, "egress-target", "", "fixed numeric host loopback HTTP egress address")
	flag.StringVar(&config.busyBoxSHA256, "busybox-sha256", "", "required HTTP-profile BusyBox SHA-256")
	flag.StringVar(&config.bashSHA256, "bash-sha256", "", "required HTTP-profile Bash wrapper SHA-256")
	flag.StringVar(&config.evidenceDir, "evidence-dir", "", "empty private evidence directory")
	registerLaunchFlags(&config)
	flag.Parse()
	if err := run(config, os.Stdin, os.Stdout); err != nil {
		log.Printf("Firecracker Claude cell failed: %v", err)
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
		return errors.New("Firecracker Claude cell requires Linux amd64")
	}
	if input == nil || output == nil || config.timeout <= 0 || config.generation == 0 {
		return errors.New("Firecracker Claude cell requires streams, timeout, and a positive generation")
	}
	for label, value := range map[string]string{
		"guest": config.guestPath, "payload": config.payloadPath, "payload SHA-256": config.payloadSHA256,
		"Claude SHA-256": config.claudeSHA256, "relay SHA-256": config.relaySHA256,
		"model target": config.modelTarget, "evidence directory": config.evidenceDir,
	} {
		if value == "" {
			return fmt.Errorf("%s is required", label)
		}
	}
	if config.profile != "mcp" && config.profile != agentguest.ClaudeHTTPProfile {
		return errors.New("Claude cell profile must be mcp or http")
	}
	if config.profile == "mcp" && config.mcpHostSocket == "" {
		return errors.New("MCP host socket is required for the mcp profile")
	}
	if config.profile == agentguest.ClaudeHTTPProfile && (config.egressTarget == "" || config.busyBoxSHA256 == "" || config.bashSHA256 == "") {
		return errors.New("HTTP profile requires egress target, BusyBox, and Bash SHA-256")
	}
	if err := validateLaunchOptions(config); err != nil {
		return err
	}
	if err := requireKVM(); err != nil {
		return err
	}
	paths := []*string{&config.firecrackerPath, &config.kernelPath, &config.guestPath, &config.payloadPath, &config.evidenceDir}
	if config.mcpHostSocket != "" {
		paths = append(paths, &config.mcpHostSocket)
	}
	paths = append(paths, launchOptionPaths(&config)...)
	for _, pointer := range paths {
		absolute, err := filepath.Abs(*pointer)
		if err != nil {
			return err
		}
		*pointer = filepath.Clean(absolute)
	}
	if err := requireEmptyPrivateDirectory(config.evidenceDir); err != nil {
		return err
	}
	if config.sessionID == "" {
		random, err := randomHex(16)
		if err != nil {
			return err
		}
		config.sessionID = random
	}
	if config.instanceID == "" {
		random, err := randomHex(8)
		if err != nil {
			return err
		}
		config.instanceID = fmt.Sprintf("claude-g%d-%s", config.generation, random)
	}
	guestConfig := agentguest.ClaudeConfig{
		Schema: agentguest.ClaudeConfigSchema, SessionID: config.sessionID,
		ClaudeSHA256: config.claudeSHA256, RelaySHA256: config.relaySHA256,
		ModelPort: parseTargetPort(config.modelTarget), PayloadDrive: "/dev/vda",
	}
	if config.profile == agentguest.ClaudeHTTPProfile {
		guestConfig.Schema = agentguest.ClaudeHTTPConfigSchema
		guestConfig.Profile = agentguest.ClaudeHTTPProfile
		guestConfig.EgressPort = agentguest.DefaultClaudeHTTPPort
		guestConfig.BusyBoxSHA256 = config.busyBoxSHA256
		guestConfig.BashSHA256 = config.bashSHA256
	}
	if err := guestConfig.Validate(); err != nil {
		return fmt.Errorf("validate Claude guest config: %w", err)
	}
	configJSON, err := json.Marshal(guestConfig)
	if err != nil {
		return err
	}
	if err := writePrivateFile(filepath.Join(config.evidenceDir, "guest-config.json"), append(configJSON, '\n')); err != nil {
		return err
	}

	artifacts := make(map[string]artifactRecord)
	guestBytes, guestRecord, err := readArtifact("firecracker-claude-guest", config.guestPath, "", maxGuestBytes, true)
	if err != nil {
		return err
	}
	artifacts["guest"] = guestRecord
	initramfs, err := newMemfd("claude-initramfs")
	if err != nil {
		return err
	}
	if err := firecracker.BuildRuntimeInitramfs(initramfs, guestBytes, configJSON); err != nil {
		_ = initramfs.Close()
		return err
	}
	initramfsArtifact, err := finalizeMemfd("initramfs", initramfs)
	if err != nil {
		return err
	}
	defer initramfsArtifact.file.Close()
	artifacts["initramfs"] = initramfsArtifact.record
	kernel, err := sealPath("kernel", config.kernelPath, config.kernelSHA256, 128<<20)
	if err != nil {
		return err
	}
	defer kernel.file.Close()
	artifacts["kernel"] = kernel.record
	payload, err := sealPath("payload", config.payloadPath, config.payloadSHA256, maxPayloadBytes)
	if err != nil {
		return err
	}
	defer payload.file.Close()
	artifacts["payload"] = payload.record

	ctx, cancel := context.WithTimeout(context.Background(), config.timeout)
	defer cancel()
	logFile, err := os.OpenFile(filepath.Join(config.evidenceDir, "firecracker.log"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer func() { returnErr = errors.Join(returnErr, logFile.Sync(), logFile.Close()) }()
	apiTrace, err := os.OpenFile(filepath.Join(config.evidenceDir, "firecracker-api.jsonl"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer func() { returnErr = errors.Join(returnErr, apiTrace.Sync(), apiTrace.Close()) }()
	modelAudit, err := createEvidenceFile(config.evidenceDir, "model-relay.jsonl")
	if err != nil {
		return err
	}
	defer func() { returnErr = errors.Join(returnErr, modelAudit.Sync(), modelAudit.Close()) }()
	operationRelayName := "mcp-relay.jsonl"
	if config.profile == agentguest.ClaudeHTTPProfile {
		operationRelayName = "egress-relay.jsonl"
	}
	operationAudit, err := createEvidenceFile(config.evidenceDir, operationRelayName)
	if err != nil {
		return err
	}
	defer func() { returnErr = errors.Join(returnErr, operationAudit.Sync(), operationAudit.Close()) }()
	gateAudit, err := createEvidenceFile(config.evidenceDir, "gate.jsonl")
	if err != nil {
		return err
	}
	defer func() { returnErr = errors.Join(returnErr, gateAudit.Sync(), gateAudit.Close()) }()
	proxyAudit, err := createEvidenceFile(config.evidenceDir, "model-proxy.jsonl")
	if err != nil {
		return err
	}
	defer func() { returnErr = errors.Join(returnErr, proxyAudit.Sync(), proxyAudit.Close()) }()

	proxy, err := firecracker.StartLoopbackProxy(firecracker.LoopbackProxyConfig{
		SocketPath: filepath.Join(config.evidenceDir, "model-proxy.sock"), TargetAddress: config.modelTarget,
		AuditLog: proxyAudit, DialTimeout: endpointTimeout, DrainTimeout: endpointTimeout,
	})
	if err != nil {
		return err
	}
	defer func() { returnErr = errors.Join(returnErr, proxy.Close()) }()

	operationSocket := config.mcpHostSocket
	operationPort := agentguest.DefaultMCPPort
	var egressProxy *firecracker.LoopbackProxy
	if config.profile == agentguest.ClaudeHTTPProfile {
		egressProxyAudit, err := createEvidenceFile(config.evidenceDir, "egress-proxy.jsonl")
		if err != nil {
			return err
		}
		defer func() { returnErr = errors.Join(returnErr, egressProxyAudit.Sync(), egressProxyAudit.Close()) }()
		egressProxy, err = firecracker.StartLoopbackProxy(firecracker.LoopbackProxyConfig{
			SocketPath: filepath.Join(config.evidenceDir, "egress-proxy.sock"), TargetAddress: config.egressTarget,
			AuditLog: egressProxyAudit, DialTimeout: endpointTimeout, DrainTimeout: endpointTimeout,
		})
		if err != nil {
			return err
		}
		defer func() { returnErr = errors.Join(returnErr, egressProxy.Close()) }()
		operationSocket = egressProxy.SocketPath()
		operationPort = guestConfig.EgressPort
	}

	apiPath := filepath.Join(config.evidenceDir, "api.sock")
	basePath := filepath.Join(config.evidenceDir, "vsock")
	process, err := firecracker.StartProcess(ctx, firecracker.ProcessConfig{
		Binary: config.firecrackerPath, ExecutableSHA256: config.firecrackerSHA256,
		APISocket: apiPath, ID: config.instanceID, Env: []string{"PATH=/usr/bin:/bin", "LANG=C", "LC_ALL=C"},
		Dir: config.evidenceDir, Stdout: logFile, Stderr: logFile,
		StartupTimeout: 10 * time.Second, TerminationTimeout: endpointTimeout,
		InheritedFiles: []*os.File{kernel.file, initramfsArtifact.file, payload.file},
	})
	if err != nil {
		return err
	}
	startedTimeNS := time.Now().UnixNano()
	var stoppedTimeNS int64
	var termination firecracker.TerminationDisposition
	defer func() {
		if stoppedTimeNS == 0 {
			disposition, stopErr := process.TerminateWithDisposition(context.Background())
			termination, stoppedTimeNS = disposition, time.Now().UnixNano()
			returnErr = errors.Join(returnErr, stopErr)
		}
	}()
	client, err := firecracker.NewClient(firecracker.ClientConfig{
		SocketPath: apiPath, ExpectedPeerPID: process.PID(), Timeout: 10 * time.Second,
		MaxResponseBytes: 1 << 20, Trace: apiTrace,
	})
	if err != nil {
		return err
	}
	defer client.Close()
	gate, err := firecracker.ArmGate(firecracker.GateConfig{
		Generation: config.generation, BasePath: basePath, FirecrackerPID: process.PID(),
		VerifyProcess: process.VerifyIdentity, AuditLog: gateAudit, DrainTimeout: endpointTimeout,
	})
	if err != nil {
		return err
	}
	defer gate.Close()
	modelRelay, err := firecracker.Arm(firecracker.RelayConfig{
		Generation: config.generation, BasePath: basePath, Port: guestConfig.ModelPort,
		FirecrackerPID: process.PID(), VerifyProcess: process.VerifyIdentity,
		SandboxSocket: proxy.SocketPath(), AuditLog: modelAudit, DrainTimeout: endpointTimeout,
	})
	if err != nil {
		return err
	}
	defer modelRelay.Close()
	operationRelay, err := firecracker.Arm(firecracker.RelayConfig{
		Generation: config.generation, BasePath: basePath, Port: operationPort,
		FirecrackerPID: process.PID(), VerifyProcess: process.VerifyIdentity,
		SandboxSocket: operationSocket, AuditLog: operationAudit, DrainTimeout: endpointTimeout,
	})
	if err != nil {
		return err
	}
	defer operationRelay.Abort()

	machine := firecracker.MachineConfig{VCPUCount: 1, MemSizeMiB: guestMemoryMiB, SMT: false, TrackDirtyPages: false}
	boot := firecracker.BootSource{KernelImagePath: "/proc/self/fd/4", InitrdPath: "/proc/self/fd/5", BootArgs: bootArguments}
	vsock := firecracker.VsockDevice{GuestCID: guestCID, UDSPath: basePath}
	drive := firecracker.Drive{DriveID: "payload", PathOnHost: "/proc/self/fd/6", IsRootDevice: false, IsReadOnly: true}
	machineDescription, err := json.Marshal(struct {
		Schema      int                       `json:"schema"`
		Machine     firecracker.MachineConfig `json:"machine"`
		Boot        firecracker.BootSource    `json:"boot"`
		Vsock       firecracker.VsockDevice   `json:"vsock"`
		Drive       firecracker.Drive         `json:"drive"`
		ToolProfile string                    `json:"tool_profile"`
	}{1, machine, boot, vsock, drive, config.profile})
	if err != nil {
		return err
	}
	if err := writePrivateFile(filepath.Join(config.evidenceDir, "machine-config.json"), append(machineDescription, '\n')); err != nil {
		return err
	}
	if err := client.Configure(ctx, machine, boot, vsock); err != nil {
		return err
	}
	if err := client.ConfigureDrive(ctx, drive); err != nil {
		return err
	}
	launch, err := launchConfiguredCell(ctx, config, launchInputs{
		client: client, process: process, artifacts: artifacts,
		artifactFiles: map[string]*os.File{
			"kernel": kernel.file, "initramfs": initramfsArtifact.file, "payload": payload.file,
		},
		configuration: machineDescription, evidenceDir: config.evidenceDir,
	})
	if err != nil {
		return err
	}
	if !launch.Started {
		termination, err = process.TerminateWithDisposition(ctx)
		stoppedTimeNS = time.Now().UnixNano()
		if err != nil {
			return err
		}
		identity := process.Identity()
		result := cellResult{
			Schema: 1, Valid: true, Backend: "firecracker-kvm", FirecrackerVersion: officialFirecrackerVersion,
			KernelVersion: officialKernelVersion, Generation: config.generation, SessionID: config.sessionID,
			Disposition: "launch-denied", ToolProfile: config.profile, NetworkInterfaces: 0, RootBlockDevices: 0, ReadOnlyPayload: true,
			LaunchGuarded: launch.Guarded, LaunchDecision: launch.Decision, InstanceStarted: false, Artifacts: artifacts,
			Process: processRecord{Generation: config.generation, InstanceID: config.instanceID, PID: identity.PID,
				Executable: identity.Executable, ExecutableSHA256: identity.ExecutableSHA256, StartTimeTicks: identity.StartTimeTicks,
				StartedTimeNS: startedTimeNS, StoppedTimeNS: stoppedTimeNS, Termination: termination},
		}
		if err := writePrivateJSON(filepath.Join(config.evidenceDir, "result.json"), result); err != nil {
			return err
		}
		return emit(output, map[string]any{
			"event": "launch-denied", "generation": config.generation, "decision": launch.Decision,
			"instance_started": false, "vmm_pid": process.PID(),
		})
	}
	if err := gate.WaitReady(ctx); err != nil {
		return fmt.Errorf("wait for Claude guest READY: %w", err)
	}
	if err := gate.Allow(); err != nil {
		return err
	}
	if err := emit(output, map[string]any{"event": "ready", "generation": config.generation, "instance_id": config.instanceID, "vmm_pid": process.PID()}); err != nil {
		return err
	}

	commands := make(chan string, 1)
	go readCommands(input, commands)
	guestResult := make(chan resultOrError, 1)
	go func() {
		result, err := gate.WaitResult(ctx)
		guestResult <- resultOrError{result: result, err: err}
	}()
	disposition := ""
	var authenticated *firecracker.Result
	select {
	case command := <-commands:
		if command != "kill" {
			return fmt.Errorf("unknown cell command %q", command)
		}
		termination, err = process.Kill(ctx)
		stoppedTimeNS = time.Now().UnixNano()
		if err != nil || termination != firecracker.TerminationBySupervisor {
			return errors.Join(err, fmt.Errorf("source VMM termination is %q", termination))
		}
		disposition = "vmm-sigkill"
	case completed := <-guestResult:
		if completed.err != nil {
			return completed.err
		}
		if err := validateGuestResult(completed.result); err != nil {
			return err
		}
		authenticated = &completed.result
		termination, err = process.TerminateWithDisposition(ctx)
		stoppedTimeNS = time.Now().UnixNano()
		if err != nil {
			return err
		}
		disposition = "completed"
	case <-process.Done():
		return fmt.Errorf("Firecracker exited before a cell outcome: %w", process.WaitContext(context.Background()))
	case <-ctx.Done():
		return ctx.Err()
	}

	identity := process.Identity()
	result := cellResult{
		Schema: 1, Valid: true, Backend: "firecracker-kvm", FirecrackerVersion: officialFirecrackerVersion,
		KernelVersion: officialKernelVersion, Generation: config.generation, SessionID: config.sessionID,
		Disposition: disposition, ToolProfile: config.profile, NetworkInterfaces: 0, RootBlockDevices: 0, ReadOnlyPayload: true,
		LaunchGuarded: launch.Guarded, LaunchDecision: launch.Decision, InstanceStarted: true,
		GuestResult: authenticated, Artifacts: artifacts,
		Process: processRecord{Generation: config.generation, InstanceID: config.instanceID, PID: identity.PID,
			Executable: identity.Executable, ExecutableSHA256: identity.ExecutableSHA256, StartTimeTicks: identity.StartTimeTicks,
			StartedTimeNS: startedTimeNS, StoppedTimeNS: stoppedTimeNS, Termination: termination},
	}
	if err := writePrivateJSON(filepath.Join(config.evidenceDir, "result.json"), result); err != nil {
		return err
	}
	return emit(output, map[string]any{"event": "completed", "generation": config.generation, "disposition": disposition, "vmm_pid": process.PID()})
}

type resultOrError struct {
	result firecracker.Result
	err    error
}

func readCommands(reader io.Reader, output chan<- string) {
	scanner := bufio.NewScanner(reader)
	if scanner.Scan() {
		output <- strings.TrimSpace(scanner.Text())
	}
}

func validateGuestResult(result firecracker.Result) error {
	if result.Event != "RESULT" || result.Status != 200 || len(result.Body) == 0 {
		return errors.New("Claude guest returned a non-success result")
	}
	canonical, err := agentwire.CanonicalJSONObject(result.Body)
	if err != nil {
		return fmt.Errorf("validate Claude guest result body: %w", err)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(canonical, &fields); err != nil {
		return err
	}
	for _, name := range []string{"result", "stream", "stream_bytes", "stream_sha256"} {
		if _, ok := fields[name]; !ok {
			return fmt.Errorf("Claude guest result body omits %q", name)
		}
	}
	if len(fields) != 4 {
		return errors.New("Claude guest result body contains an unknown field")
	}
	var body struct {
		Result       string `json:"result"`
		Stream       string `json:"stream"`
		StreamBytes  int    `json:"stream_bytes"`
		StreamSHA256 string `json:"stream_sha256"`
	}
	if err := json.Unmarshal(canonical, &body); err != nil {
		return err
	}
	digest := sha256.Sum256([]byte(body.Stream))
	if body.Result != "DONE" || body.Stream == "" || body.StreamBytes != len(body.Stream) || body.StreamSHA256 != hex.EncodeToString(digest[:]) {
		return errors.New("Claude guest result body is internally inconsistent")
	}
	return nil
}

func parseTargetPort(target string) uint32 {
	index := strings.LastIndexByte(target, ':')
	if index < 0 {
		return 0
	}
	var port uint64
	for _, value := range []byte(target[index+1:]) {
		if value < '0' || value > '9' {
			return 0
		}
		port = port*10 + uint64(value-'0')
		if port > 65535 {
			return 0
		}
	}
	return uint32(port)
}

func requireKVM() error {
	file, err := os.OpenFile("/dev/kvm", os.O_RDWR|unix.O_CLOEXEC, 0)
	if err != nil {
		return fmt.Errorf("open /dev/kvm read/write: %w", err)
	}
	return file.Close()
}

func requireEmptyPrivateDirectory(path string) error {
	info, err := os.Lstat(path)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() || info.Mode().Perm() != 0o700 {
		return errors.New("evidence directory must be a direct 0700 directory")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != uint32(os.Geteuid()) {
		return errors.New("evidence directory must be owned by the current user")
	}
	entries, err := os.ReadDir(path)
	if err != nil || len(entries) != 0 {
		return errors.New("evidence directory must be empty")
	}
	return nil
}

func readArtifact(name, path, expected string, maximum int64, executable bool) ([]byte, artifactRecord, error) {
	info, err := os.Lstat(path)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Size() <= 0 || info.Size() > maximum || (executable && info.Mode()&0o111 == 0) {
		if err != nil {
			return nil, artifactRecord{}, fmt.Errorf("inspect %s %q: %w", name, path, err)
		}
		return nil, artifactRecord{}, fmt.Errorf("%s %q must be a bounded direct regular file: mode=%s size=%d limit=%d executable=%t", name, path, info.Mode(), info.Size(), maximum, executable)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, artifactRecord{}, err
	}
	digest := sha256.Sum256(data)
	hash := hex.EncodeToString(digest[:])
	if expected != "" && hash != expected {
		return nil, artifactRecord{}, fmt.Errorf("%s SHA-256 is %s, require %s", name, hash, expected)
	}
	return data, artifactRecord{Name: name, Size: int64(len(data)), Mode: uint32(info.Mode().Perm()), SHA256: hash}, nil
}

func sealPath(name, path, expected string, maximum int64) (*sealedArtifact, error) {
	data, record, err := readArtifact(name, path, expected, maximum, false)
	if err != nil {
		return nil, err
	}
	file, err := newMemfd("sealed-" + name)
	if err != nil {
		return nil, err
	}
	if _, err := file.Write(data); err != nil {
		_ = file.Close()
		return nil, err
	}
	sealed, err := finalizeMemfd(name, file)
	if err != nil {
		return nil, err
	}
	if sealed.record.SHA256 != record.SHA256 || sealed.record.Size != record.Size {
		_ = sealed.file.Close()
		return nil, fmt.Errorf("sealed %s differs from source", name)
	}
	return sealed, nil
}

func newMemfd(name string) (*os.File, error) {
	descriptor, err := unix.MemfdCreate(name, unix.MFD_CLOEXEC|unix.MFD_ALLOW_SEALING)
	if err != nil {
		return nil, err
	}
	file := os.NewFile(uintptr(descriptor), name)
	if file == nil {
		_ = unix.Close(descriptor)
		return nil, errors.New("wrap memfd")
	}
	return file, nil
}

func finalizeMemfd(name string, file *os.File) (*sealedArtifact, error) {
	fail := func(err error) (*sealedArtifact, error) { _ = file.Close(); return nil, err }
	if err := file.Sync(); err != nil {
		return fail(err)
	}
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return fail(err)
	}
	digest := sha256.New()
	size, err := io.Copy(digest, file)
	if err != nil || size <= 0 {
		return fail(errors.Join(err, errors.New("sealed artifact is empty")))
	}
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return fail(err)
	}
	seals := unix.F_SEAL_SEAL | unix.F_SEAL_SHRINK | unix.F_SEAL_GROW | unix.F_SEAL_WRITE
	if _, err := unix.FcntlInt(file.Fd(), unix.F_ADD_SEALS, seals); err != nil {
		return fail(err)
	}
	return &sealedArtifact{file: file, record: artifactRecord{Name: name, Size: size, Mode: 0o400, SHA256: hex.EncodeToString(digest.Sum(nil))}}, nil
}

func createEvidenceFile(directory, name string) (*os.File, error) {
	return os.OpenFile(filepath.Join(directory, name), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
}

func writePrivateFile(path string, data []byte) error {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	written, writeErr := file.Write(data)
	if writeErr == nil && written != len(data) {
		writeErr = io.ErrShortWrite
	}
	return errors.Join(writeErr, file.Sync(), file.Close())
}

func writePrivateJSON(path string, value any) error {
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(value); err != nil {
		return err
	}
	return writePrivateFile(path, buffer.Bytes())
}

func emit(writer io.Writer, value any) error {
	data, err := json.Marshal(value)
	if err != nil {
		return err
	}
	data = append(data, '\n')
	written, err := writer.Write(data)
	if err == nil && written != len(data) {
		err = io.ErrShortWrite
	}
	return err
}

func randomHex(bytesCount int) (string, error) {
	if bytesCount <= 0 {
		return "", errors.New("random identity length must be positive")
	}
	data := make([]byte, bytesCount)
	if _, err := io.ReadFull(rand.Reader, data); err != nil {
		return "", fmt.Errorf("read random identity: %w", err)
	}
	return hex.EncodeToString(data), nil
}
