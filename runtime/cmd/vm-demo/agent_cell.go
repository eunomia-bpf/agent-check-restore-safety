package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"sync/atomic"
	"syscall"
	"time"
	"unicode"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/apiclient"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/vmresume"
)

const agentSnapshotName = "before_agent"

var agentSessionPattern = regexp.MustCompile(`^[0-9a-f]{32}$`)

type agentGuardManifest struct {
	Schema           int                    `json:"schema"`
	CheckedState     kernel.State           `json:"checked_state"`
	Certificate      kernel.Certificate     `json:"certificate"`
	ActivatedHistory kernel.HistoryPoint    `json:"activated_history"`
	Binding          control.SandboxBinding `json:"binding"`
	EndpointPath     string                 `json:"endpoint_path"`
	ControlURL       string                 `json:"control_url"`
	ControlTokenPath string                 `json:"control_token_path"`
}

type agentSeed struct {
	userData     string
	claudePath   string
	claudeSHA    string
	sessionID    string
	gate         atomic.Bool
	claudeServed atomic.Uint64
	gateServed   atomic.Uint64
}

type agentVMM struct {
	command      *exec.Cmd
	done         chan error
	qmp          *qmpClient
	log          *os.File
	logPath      string
	serial       string
	qmpPath      string
	qmpDirectory string
	pid          int
	finished     bool
}

func runAgentCell(ctx context.Context, configuration options, tools hostTools, output io.Writer) error {
	if err := validateAgentOptions(configuration); err != nil {
		return err
	}
	evidenceDirectory, err := filepath.Abs(configuration.agentEvidenceDirPath)
	if err != nil {
		return err
	}
	if err := requireEmptyPrivateDirectory(evidenceDirectory); err != nil {
		return err
	}
	machineConfig, err := agentMachineConfig(configuration)
	if err != nil {
		return err
	}
	if err := writePrivateFile(filepath.Join(evidenceDirectory, "machine-config.json"), append(machineConfig, '\n')); err != nil {
		return err
	}
	if err := writeExternalHostTools(filepath.Join(evidenceDirectory, "host-tools.json"), tools); err != nil {
		return err
	}
	if configuration.agentMode == "prepare" {
		return prepareAgentCheckpoint(ctx, configuration, tools, evidenceDirectory, machineConfig, output)
	}
	return runAgentLane(ctx, configuration, tools, evidenceDirectory, machineConfig, output)
}

func validateAgentOptions(configuration options) error {
	if configuration.agentMode != "prepare" && configuration.agentMode != "source" && configuration.agentMode != "restore" {
		return errors.New("-agent-mode must be prepare, source, or restore")
	}
	for label, value := range map[string]string{
		"overlay": configuration.agentOverlayPath, "evidence directory": configuration.agentEvidenceDirPath,
		"Claude SHA-256": configuration.agentClaudeSHA, "metadata address": configuration.agentMetadataAddress,
		"model address": configuration.agentModelAddress, "egress address": configuration.agentEgressAddress,
	} {
		if value == "" {
			return fmt.Errorf("full-Agent VM %s is required", label)
		}
	}
	if !validLowerDigest(configuration.agentClaudeSHA) {
		return errors.New("full-Agent VM Claude SHA-256 is invalid")
	}
	for label, address := range map[string]string{
		"metadata": configuration.agentMetadataAddress,
		"model":    configuration.agentModelAddress,
		"egress":   configuration.agentEgressAddress,
	} {
		tcp, err := net.ResolveTCPAddr("tcp", address)
		if err != nil || tcp.Port == 0 || tcp.IP == nil || !tcp.IP.IsLoopback() {
			return fmt.Errorf("full-Agent VM %s address must be explicit loopback TCP", label)
		}
	}
	if configuration.agentMode == "prepare" {
		if configuration.agentClaudePath == "" || configuration.agentSessionID != "" ||
			configuration.agentBarrierPath != "" || configuration.agentGuardManifestPath != "" {
			return errors.New("prepare mode requires only the Claude artifact, not lane inputs")
		}
		if _, err := os.Lstat(configuration.agentOverlayPath); !errors.Is(err, os.ErrNotExist) {
			return errors.New("prepare checkpoint path must not exist")
		}
		actual, err := fileSHA(configuration.agentClaudePath)
		if err != nil || actual != configuration.agentClaudeSHA {
			return errors.New("official Claude executable differs from its required hash")
		}
	} else {
		if !agentSessionPattern.MatchString(configuration.agentSessionID) {
			return errors.New("source/restore session identity must be 16-byte lowercase hexadecimal")
		}
		if configuration.agentSealedPath == "" || !validLowerDigest(configuration.agentSealedSHA) ||
			!validLowerDigest(configuration.agentPreopenSHA) {
			return errors.New("source/restore requires sealed and pre-open checkpoint hashes")
		}
		if configuration.agentSealedSHA != configuration.agentPreopenSHA {
			return errors.New("lane copy does not declare the sealed checkpoint hash")
		}
		if configuration.agentMode == "source" {
			if configuration.agentBarrierPath == "" || configuration.agentGuardManifestPath != "" {
				return errors.New("source mode requires one kill barrier and no guard manifest")
			}
		} else if configuration.agentBarrierPath != "" {
			return errors.New("restore mode does not accept a source kill barrier")
		}
	}
	return nil
}

func validLowerDigest(value string) bool {
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size && hex.EncodeToString(decoded) == value
}

func agentMachineConfig(configuration options) ([]byte, error) {
	value := struct {
		Schema          int               `json:"schema"`
		Machine         string            `json:"machine"`
		MemoryMiB       int               `json:"memory_mib"`
		CPUs            int               `json:"cpus"`
		Accelerator     string            `json:"accelerator"`
		Disk            string            `json:"disk"`
		Snapshot        string            `json:"snapshot"`
		Network         string            `json:"network"`
		GuestForwards   map[string]string `json:"guest_forwards"`
		ClaudeSHA256    string            `json:"claude_sha256"`
		BaseImageSHA256 string            `json:"base_image_sha256"`
	}{
		Schema: 1, Machine: "q35", MemoryMiB: 2048, CPUs: 2, Accelerator: configuration.accel,
		Disk: "complete-qcow2", Snapshot: agentSnapshotName, Network: "qemu-user-restrict-on",
		GuestForwards: map[string]string{
			"10.0.2.100:8000": configuration.agentMetadataAddress,
			"10.0.2.100:9000": configuration.agentModelAddress,
			"10.0.2.100:8788": configuration.agentEgressAddress,
		},
		ClaudeSHA256: configuration.agentClaudeSHA, BaseImageSHA256: configuration.imageSHA,
	}
	return json.Marshal(value)
}

func prepareAgentCheckpoint(
	ctx context.Context,
	configuration options,
	tools hostTools,
	evidenceDirectory string,
	machineConfig []byte,
	output io.Writer,
) error {
	overlay, err := filepath.Abs(configuration.agentOverlayPath)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(overlay), 0o700); err != nil {
		return err
	}
	if commandOutput, err := exec.CommandContext(
		ctx, tools.qemuImage.path, "convert", "-q", "-O", "qcow2", configuration.imagePath, overlay,
	).CombinedOutput(); err != nil {
		return fmt.Errorf("create complete Agent checkpoint: %w: %s", err, commandOutput)
	}
	if err := os.Chmod(overlay, 0o600); err != nil {
		return err
	}
	if commandOutput, err := exec.CommandContext(
		ctx, tools.qemuImage.path, "resize", overlay, "8G",
	).CombinedOutput(); err != nil {
		return fmt.Errorf("resize complete Agent checkpoint: %w: %s", err, commandOutput)
	}
	seed := &agentSeed{
		userData:   makeUserData(agentGuestScript(configuration.agentClaudeSHA)),
		claudePath: configuration.agentClaudePath, claudeSHA: configuration.agentClaudeSHA,
	}
	listener, server, err := startAgentSeed(configuration.agentMetadataAddress, seed)
	if err != nil {
		return err
	}
	defer listener.Close()
	defer shutdown(server)
	vmm, err := launchAgentVMM(ctx, configuration, tools, evidenceDirectory, overlay, false)
	if err != nil {
		return err
	}
	defer vmm.cleanup()
	if err := waitForText(ctx, vmm.serial, "SAFE_CHANGE_QEMU_AGENT_BASE_READY", 8*time.Minute); err != nil {
		return withQEMULog(err, vmm.logPath)
	}
	if seed.claudeServed.Load() != 1 {
		return fmt.Errorf("official Claude artifact was served %d times, want once", seed.claudeServed.Load())
	}
	if err := vmm.qmp.command("stop", nil); err != nil {
		return err
	}
	if err := vmm.qmp.requireStatus("paused"); err != nil {
		return err
	}
	if err := vmm.qmp.human("savevm " + agentSnapshotName); err != nil {
		return err
	}
	if err := vmm.qmp.command("quit", nil); err != nil {
		return err
	}
	if err := vmm.wait(30 * time.Second); err != nil {
		return err
	}
	if err := vmm.closeLog(); err != nil {
		return err
	}
	snapshotOutput, err := exec.CommandContext(ctx, tools.qemuImage.path, "snapshot", "-l", overlay).CombinedOutput()
	if err != nil || !strings.Contains(string(snapshotOutput), agentSnapshotName) {
		return fmt.Errorf("prepared Agent snapshot is absent: %w: %s", err, snapshotOutput)
	}
	if err := writePrivateFile(filepath.Join(evidenceDirectory, "snapshots.txt"), snapshotOutput); err != nil {
		return err
	}
	sealedSHA, err := fileSHA(overlay)
	if err != nil {
		return err
	}
	result := map[string]any{
		"schema": 1, "mode": "prepare", "full_linux_guest": true,
		"checkpoint_path": overlay, "checkpoint_sha256": sealedSHA,
		"checkpoint_size": fileSize(overlay), "snapshot": agentSnapshotName,
		"machine_config_sha256": dataSHA256(machineConfig),
		"claude_sha256":         configuration.agentClaudeSHA,
		"claude_served":         seed.claudeServed.Load(), "qemu_reaped": true,
	}
	if err := writeAgentResult(evidenceDirectory, result); err != nil {
		return err
	}
	result["event"] = "checkpoint-sealed"
	return writeExternalEvent(output, result)
}

func runAgentLane(
	ctx context.Context,
	configuration options,
	tools hostTools,
	evidenceDirectory string,
	machineConfig []byte,
	output io.Writer,
) error {
	overlay, err := filepath.Abs(configuration.agentOverlayPath)
	if err != nil {
		return err
	}
	preopenSHA, err := fileSHA(overlay)
	if err != nil {
		return err
	}
	if preopenSHA != configuration.agentPreopenSHA {
		return fmt.Errorf("lane copy SHA-256 %s differs from sealed %s", preopenSHA, configuration.agentPreopenSHA)
	}
	diskIdentity, err := vmresume.CaptureDiskIdentity(overlay, preopenSHA)
	if err != nil {
		return err
	}
	copyEvidence := map[string]any{
		"schema": 1, "verified_before_qemu_open": true, "sha256": preopenSHA,
		"size": fileSize(overlay), "device": diskIdentity.Device, "inode": diskIdentity.Inode,
		"verified_time_ns": time.Now().UnixNano(),
	}
	if err := writeJSONPrivate(filepath.Join(evidenceDirectory, "copy-verification.json"), copyEvidence); err != nil {
		return err
	}
	seed := &agentSeed{
		userData:  makeUserData(agentGuestScript(configuration.agentClaudeSHA)),
		claudeSHA: configuration.agentClaudeSHA, sessionID: configuration.agentSessionID,
	}
	seed.gate.Store(true)
	listener, server, err := startAgentSeed(configuration.agentMetadataAddress, seed)
	if err != nil {
		return err
	}
	defer listener.Close()
	defer shutdown(server)
	vmm, err := launchAgentVMM(ctx, configuration, tools, evidenceDirectory, overlay, true)
	if err != nil {
		return err
	}
	defer vmm.cleanup()
	processIdentity, err := vmresume.CaptureProcessIdentity(vmm.pid)
	if err != nil {
		return err
	}
	if err := vmresume.VerifyProcessDisk(vmm.pid, diskIdentity); err != nil {
		return err
	}
	if err := writeJSONPrivate(filepath.Join(evidenceDirectory, "live-vm.json"), map[string]any{
		"schema": 1, "process": processIdentity, "disk": diskIdentity,
		"process_holds_disk": true, "captured_time_ns": time.Now().UnixNano(),
	}); err != nil {
		return err
	}
	if err := vmm.qmp.requireStatus("prelaunch"); err != nil {
		return err
	}
	loaded := map[string]any{
		"event": "snapshot-loaded-halted", "mode": configuration.agentMode,
		"session_id": configuration.agentSessionID, "qemu_pid": vmm.pid,
		"qemu_status": "prelaunch", "qemu_running": false,
		"observed_time_ns": time.Now().UnixNano(),
	}
	if err := writeExternalEvent(output, loaded); err != nil {
		return err
	}
	if configuration.agentMode == "source" {
		return runAgentSource(ctx, configuration, vmm, seed, evidenceDirectory, output)
	}
	return runAgentRestore(
		ctx, configuration, vmm, seed, evidenceDirectory, machineConfig,
		processIdentity, diskIdentity, output,
	)
}

func runAgentSource(
	ctx context.Context,
	configuration options,
	vmm *agentVMM,
	seed *agentSeed,
	evidenceDirectory string,
	output io.Writer,
) error {
	if err := vmm.qmp.command("cont", nil); err != nil {
		return err
	}
	marker := "SAFE_CHANGE_QEMU_AGENT_CLAUDE_STARTED session=" + configuration.agentSessionID
	if err := waitForText(ctx, vmm.serial, marker, 3*time.Minute); err != nil {
		return withQEMULog(err, vmm.logPath)
	}
	started := map[string]any{"event": "claude-started", "session_id": configuration.agentSessionID, "observed_time_ns": time.Now().UnixNano()}
	if err := writeExternalEvent(output, started); err != nil {
		return err
	}
	barrier, err := waitForAgentBarrier(ctx, configuration.agentBarrierPath)
	if err != nil {
		return err
	}
	if err := vmm.qmp.command("stop", nil); err != nil {
		return err
	}
	if err := vmm.qmp.requireStatus("paused"); err != nil {
		return err
	}
	barrier["qemu_paused_time_ns"] = time.Now().UnixNano()
	barrier["serial_size"] = fileSize(vmm.serial)
	if err := writeJSONPrivate(filepath.Join(evidenceDirectory, "source-barrier.json"), barrier); err != nil {
		return err
	}
	if err := vmm.qmp.command("quit", nil); err != nil {
		return err
	}
	if err := vmm.wait(30 * time.Second); err != nil {
		return err
	}
	if err := vmm.closeLog(); err != nil {
		return err
	}
	result := map[string]any{
		"schema": 1, "mode": "source", "session_id": configuration.agentSessionID,
		"snapshot_loaded_halted": true, "initial_qemu_status": "prelaunch", "claude_started": true,
		"external_barrier_acknowledged": true, "guest_gate_served": seed.gateServed.Load(),
		"qemu_reaped": true,
	}
	if err := writeAgentResult(evidenceDirectory, result); err != nil {
		return err
	}
	result["event"] = "source-stopped"
	return writeExternalEvent(output, result)
}

func runAgentRestore(
	ctx context.Context,
	configuration options,
	vmm *agentVMM,
	seed *agentSeed,
	evidenceDirectory string,
	machineConfig []byte,
	processIdentity vmresume.ProcessIdentity,
	diskIdentity vmresume.DiskIdentity,
	output io.Writer,
) error {
	guardEvidence := map[string]any{
		"schema": 1, "resume_attempted": true, "guarded": configuration.agentGuardManifestPath != "",
		"snapshot_loaded_halted": true, "initial_qemu_status": "prelaunch", "qemu_pid": vmm.pid,
	}
	if configuration.agentGuardManifestPath == "" {
		guardEvidence["decision"] = "native-unguarded"
		guardEvidence["qmp_cont_issued"] = true
		if err := vmm.qmp.command("cont", nil); err != nil {
			return err
		}
	} else {
		manifest, err := readAgentGuardManifest(configuration.agentGuardManifestPath)
		if err != nil {
			return err
		}
		endpoint, err := vmresume.CaptureEndpoint(manifest.EndpointPath, manifest.Binding)
		if err != nil {
			return err
		}
		process, err := vmresume.CaptureProcessIdentity(vmm.pid)
		if err != nil {
			return err
		}
		if process != processIdentity {
			return errors.New("QEMU process changed after its live launch attestation")
		}
		if err := vmresume.VerifyProcessDisk(vmm.pid, diskIdentity); err != nil {
			return err
		}
		controlClient, err := openAgentControlClient(manifest)
		if err != nil {
			return err
		}
		request := vmresume.Request{
			CheckedState: &manifest.CheckedState, Certificate: manifest.Certificate,
			ActivatedHistory: manifest.ActivatedHistory,
			Checkpoint: vmresume.Checkpoint{
				Path: configuration.agentSealedPath, SHA256: configuration.agentSealedSHA,
				SnapshotName: agentSnapshotName, MachineConfig: machineConfig,
				MachineConfigSHA256: dataSHA256(machineConfig),
			},
			Process: process, Disk: diskIdentity, Endpoint: endpoint,
		}
		stateReadTimes, bindingReadTimes, endpointProbeTimes := []int64{}, []int64{}, []int64{}
		liveStates := []kernel.State{}
		liveBindingViews := [][]control.SandboxBinding{}
		guard, err := vmresume.New(vmresume.Sources{
			CurrentState: func() (*kernel.State, error) {
				state, readErr := controlClient.State(ctx)
				if readErr != nil {
					return nil, readErr
				}
				stateReadTimes = append(stateReadTimes, time.Now().UnixNano())
				liveStates = append(liveStates, state)
				return &state, nil
			},
			ValidateBinding: func(binding control.SandboxBinding) error {
				bindings, readErr := controlClient.SandboxBindings(ctx)
				if readErr != nil {
					return readErr
				}
				bindingReadTimes = append(bindingReadTimes, time.Now().UnixNano())
				liveBindingViews = append(liveBindingViews, bindings)
				if !reflect.DeepEqual(binding, manifest.Binding) || !containsBinding(bindings, binding) {
					return errors.New("binding is absent from the active control view")
				}
				return nil
			},
			ProbeEndpoint: func(probeContext context.Context, publication vmresume.EndpointPublication) error {
				if probeErr := probeAgentEndpoint(probeContext, publication); probeErr != nil {
					return probeErr
				}
				endpointProbeTimes = append(endpointProbeTimes, time.Now().UnixNano())
				return nil
			},
			Continue: func(context.Context) error {
				guardEvidence["qmp_cont_requested_time_ns"] = time.Now().UnixNano()
				return vmm.qmp.command("cont", nil)
			},
		})
		if err != nil {
			return err
		}
		guardEvidence["authorize_started_time_ns"] = time.Now().UnixNano()
		authorization, authorizeErr := guard.Authorize(ctx, request)
		guardEvidence["certificate_decision"] = manifest.Certificate.Decision
		guardEvidence["certificate_digest"] = manifest.Certificate.Digest
		guardEvidence["checked_history"] = manifest.Certificate.History
		guardEvidence["activated_history"] = manifest.ActivatedHistory
		guardEvidence["checkpoint_sha256"] = configuration.agentSealedSHA
		guardEvidence["machine_config_sha256"] = dataSHA256(machineConfig)
		guardEvidence["process"] = process
		guardEvidence["disk"] = diskIdentity
		guardEvidence["endpoint"] = endpoint
		if errors.Is(authorizeErr, vmresume.ErrDenied) {
			resumeErr := guard.Resume(ctx, vmresume.Authorization{})
			if !errors.Is(resumeErr, vmresume.ErrUnauthorized) {
				return fmt.Errorf("denied guard accepted a resume attempt: %v", resumeErr)
			}
			guardEvidence["decision"] = "impossible"
			guardEvidence["authorization_issued"] = false
			guardEvidence["qmp_cont_issued"] = false
			guardEvidence["resume_error"] = resumeErr.Error()
			guardEvidence["live_state_read_times_ns"] = stateReadTimes
			guardEvidence["live_binding_read_times_ns"] = bindingReadTimes
			guardEvidence["endpoint_probe_times_ns"] = endpointProbeTimes
			guardEvidence["live_states"] = liveStates
			guardEvidence["live_binding_views"] = liveBindingViews
			if err := writeJSONPrivate(filepath.Join(evidenceDirectory, "resume-guard.json"), guardEvidence); err != nil {
				return err
			}
			if err := vmm.qmp.command("quit", nil); err != nil {
				return err
			}
			if err := vmm.wait(30 * time.Second); err != nil {
				return err
			}
			if err := vmm.closeLog(); err != nil {
				return err
			}
			result := map[string]any{
				"schema": 1, "mode": "restore", "session_id": configuration.agentSessionID,
				"decision": "impossible", "resume_denied": true, "qmp_cont_issued": false,
				"task_completed": false, "qemu_reaped": true,
			}
			if err := writeAgentResult(evidenceDirectory, result); err != nil {
				return err
			}
			result["event"] = "resume-denied"
			return writeExternalEvent(output, result)
		}
		if authorizeErr != nil {
			return authorizeErr
		}
		guardEvidence["authorization_issued"] = true
		guardEvidence["authorization_issued_time_ns"] = time.Now().UnixNano()
		guardEvidence["resume_started_time_ns"] = time.Now().UnixNano()
		if err := guard.Resume(ctx, authorization); err != nil {
			return err
		}
		guardEvidence["decision"] = "activate"
		guardEvidence["qmp_cont_issued"] = true
		guardEvidence["authorization_consumed"] = true
		guardEvidence["live_state_read_times_ns"] = stateReadTimes
		guardEvidence["live_binding_read_times_ns"] = bindingReadTimes
		guardEvidence["endpoint_probe_times_ns"] = endpointProbeTimes
		guardEvidence["live_states"] = liveStates
		guardEvidence["live_binding_views"] = liveBindingViews
		if err := writeJSONPrivate(filepath.Join(evidenceDirectory, "resume-guard.json"), guardEvidence); err != nil {
			return err
		}
	}
	marker := "SAFE_CHANGE_QEMU_AGENT_COMPLETE session=" + configuration.agentSessionID
	if err := waitForText(ctx, vmm.serial, marker, 4*time.Minute); err != nil {
		return withQEMULog(err, vmm.logPath)
	}
	if err := vmm.qmp.command("stop", nil); err != nil {
		return err
	}
	if err := vmm.qmp.requireStatus("paused"); err != nil {
		return err
	}
	if err := vmm.qmp.command("quit", nil); err != nil {
		return err
	}
	if err := vmm.wait(30 * time.Second); err != nil {
		return err
	}
	if err := vmm.closeLog(); err != nil {
		return err
	}
	decision := guardEvidence["decision"]
	result := map[string]any{
		"schema": 1, "mode": "restore", "session_id": configuration.agentSessionID,
		"decision": decision, "task_completed": true, "qmp_cont_issued": true,
		"guest_gate_served": seed.gateServed.Load(), "qemu_reaped": true,
	}
	if err := writeAgentResult(evidenceDirectory, result); err != nil {
		return err
	}
	result["event"] = "restore-completed"
	return writeExternalEvent(output, result)
}

func launchAgentVMM(
	ctx context.Context,
	configuration options,
	tools hostTools,
	evidenceDirectory, overlay string,
	loadSnapshot bool,
) (*agentVMM, error) {
	serialPath := filepath.Join(evidenceDirectory, "guest.serial.log")
	qemuLogPath := filepath.Join(evidenceDirectory, "qemu.log")
	qmpDirectory, err := os.MkdirTemp("/tmp", "safe-change-qmp-")
	if err != nil {
		return nil, err
	}
	if err := os.Chmod(qmpDirectory, 0o700); err != nil {
		_ = os.Remove(qmpDirectory)
		return nil, err
	}
	qmpPath := filepath.Join(qmpDirectory, "qmp.sock")
	metadataPort := mustTCPPort(configuration.agentMetadataAddress)
	modelPort := mustTCPPort(configuration.agentModelAddress)
	egressPort := mustTCPPort(configuration.agentEgressAddress)
	netdev := fmt.Sprintf(
		"user,id=agentnet,restrict=on,guestfwd=tcp:10.0.2.100:8000-cmd:%s 127.0.0.1 %d,guestfwd=tcp:10.0.2.100:9000-cmd:%s 127.0.0.1 %d,guestfwd=tcp:10.0.2.100:8788-cmd:%s 127.0.0.1 %d",
		tools.netcat.path, metadataPort, tools.netcat.path, modelPort, tools.netcat.path, egressPort,
	)
	arguments := []string{
		"-name", "safe-change-full-agent-vm", "-machine", "q35", "-m", "2048", "-smp", "2",
		"-drive", "file=" + overlay + ",if=virtio,format=qcow2,cache=none",
		"-display", "none", "-serial", "file:" + serialPath, "-monitor", "none",
		"-qmp", "unix:" + qmpPath + ",server=on,wait=off", "-no-reboot", "-nic", "none",
		"-netdev", netdev, "-device", "virtio-net-pci,netdev=agentnet",
		"-smbios", "type=1,serial=ds=nocloud;s=http://10.0.2.100:8000/",
	}
	if loadSnapshot {
		arguments = append(arguments, "-S", "-loadvm", agentSnapshotName)
	}
	if configuration.accel == "tcg" {
		arguments = append(arguments, "-accel", "tcg,thread=multi")
	} else {
		arguments = append(arguments, "-accel", "kvm")
	}
	if err := writeQEMUCommand(filepath.Join(evidenceDirectory, "qemu-command.json"), arguments, evidenceDirectory, configuration.imagePath, overlay, qmpDirectory); err != nil {
		_ = os.Remove(qmpDirectory)
		return nil, err
	}
	logFile, err := os.OpenFile(qemuLogPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return nil, err
	}
	command := agentQEMUCommand(ctx, tools.qemuSystem.path, arguments)
	command.Stdout, command.Stderr = logFile, logFile
	if err := command.Start(); err != nil {
		_ = logFile.Close()
		return nil, err
	}
	done := make(chan error, 1)
	go func() { done <- command.Wait() }()
	vmm := &agentVMM{command: command, done: done, log: logFile, logPath: qemuLogPath, serial: serialPath, qmpPath: qmpPath, qmpDirectory: qmpDirectory, pid: command.Process.Pid}
	if err := writeQEMUProcessCommand(
		filepath.Join(evidenceDirectory, "qemu-process-command.json"), command.Process.Pid,
		arguments, tools.qemuSystem, evidenceDirectory, configuration.imagePath, overlay, qmpDirectory,
	); err != nil {
		vmm.cleanup()
		return nil, err
	}
	dialContext, cancelDial := context.WithTimeout(ctx, 10*time.Second)
	defer cancelDial()
	qmp, err := dialQMPWithTrace(dialContext, qmpPath, filepath.Join(evidenceDirectory, "qmp-protocol.jsonl"))
	if err != nil {
		vmm.cleanup()
		return nil, withQEMULog(err, qemuLogPath)
	}
	vmm.qmp = qmp
	return vmm, nil
}

func agentQEMUCommand(ctx context.Context, executable string, arguments []string) *exec.Cmd {
	command := exec.CommandContext(ctx, executable, arguments...)
	command.SysProcAttr = &syscall.SysProcAttr{Pdeathsig: syscall.SIGKILL}
	return command
}

func (vmm *agentVMM) wait(timeout time.Duration) error {
	if vmm.finished {
		return nil
	}
	select {
	case err := <-vmm.done:
		vmm.finished = true
		if err != nil {
			return withQEMULog(err, vmm.logPath)
		}
		return nil
	case <-time.After(timeout):
		return errors.New("QEMU did not exit after the supervisor command")
	}
}

func (vmm *agentVMM) closeLog() error {
	if vmm.log == nil {
		return nil
	}
	err := errors.Join(vmm.log.Sync(), vmm.log.Close())
	vmm.log = nil
	return err
}

func (vmm *agentVMM) cleanup() {
	if vmm.qmp != nil {
		_ = vmm.qmp.Close()
		vmm.qmp = nil
	}
	if !vmm.finished && vmm.command != nil && vmm.command.Process != nil {
		_ = vmm.command.Process.Kill()
		<-vmm.done
		vmm.finished = true
	}
	_ = vmm.closeLog()
	if vmm.qmpDirectory != "" {
		_ = os.Remove(vmm.qmpPath)
		_ = os.Remove(vmm.qmpDirectory)
		vmm.qmpDirectory = ""
	}
}

func startAgentSeed(address string, seed *agentSeed) (net.Listener, *http.Server, error) {
	listener, err := net.Listen("tcp", address)
	if err != nil {
		return nil, nil, err
	}
	server := &http.Server{Handler: seed.handler(), ReadHeaderTimeout: 5 * time.Second}
	go serve(server, listener)
	return listener, server, nil
}

func (seed *agentSeed) handler() http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/meta-data":
			writer.Header().Set("Content-Type", "text/plain")
			_, _ = io.WriteString(writer, "instance-id: safe-change-agent-vm-1\nlocal-hostname: safe-change-agent-vm\n")
		case "/user-data":
			writer.Header().Set("Content-Type", "text/plain")
			_, _ = io.WriteString(writer, seed.userData)
		case "/vendor-data":
			writer.Header().Set("Content-Type", "text/plain")
			_, _ = io.WriteString(writer, "#cloud-config\n{}\n")
		case "/agent/claude":
			if seed.claudePath == "" {
				http.NotFound(writer, request)
				return
			}
			seed.claudeServed.Add(1)
			writer.Header().Set("Content-Type", "application/octet-stream")
			writer.Header().Set("X-Content-SHA256", seed.claudeSHA)
			http.ServeFile(writer, request, seed.claudePath)
		case "/agent/gate":
			if !seed.gate.Load() {
				http.Error(writer, "not yet", http.StatusServiceUnavailable)
				return
			}
			seed.gateServed.Add(1)
			_, _ = io.WriteString(writer, "go\n")
		case "/agent/config":
			if !seed.gate.Load() || !agentSessionPattern.MatchString(seed.sessionID) {
				http.Error(writer, "not ready", http.StatusServiceUnavailable)
				return
			}
			writer.Header().Set("Content-Type", "text/plain")
			_, _ = io.WriteString(writer, seed.sessionID+"\n")
		default:
			http.NotFound(writer, request)
		}
	})
}

func agentGuestScript(claudeSHA string) string {
	return fmt.Sprintf(`#!/usr/bin/env bash
set -euo pipefail
log_marker() { printf '%%s\n' "$1" > /dev/ttyS0; }
install -d -m 0755 /opt/claude
curl -fsS --connect-timeout 2 --max-time 300 http://10.0.2.100:8000/agent/claude -o /opt/claude/claude
printf '%%s  %%s\n' '%s' /opt/claude/claude | sha256sum -c -
chmod 0755 /opt/claude/claude
version=$(/opt/claude/claude --version | tr '\r\n' ' ')
log_marker "SAFE_CHANGE_QEMU_AGENT_BASE_READY kernel=$(uname -r) claude_sha256=%s claude_version=$version"
until curl -fsS --connect-timeout 2 --max-time 3 http://10.0.2.100:8000/agent/gate >/dev/null; do sleep 1; done
session=$(curl -fsS --connect-timeout 2 --max-time 3 http://10.0.2.100:8000/agent/config | tr -d '\r\n')
if [[ ! "$session" =~ ^[0-9a-f]{32}$ ]]; then
  log_marker SAFE_CHANGE_QEMU_AGENT_BAD_SESSION
  while true; do sleep 60; done
fi
uuid="${session:0:8}-${session:8:4}-${session:12:4}-${session:16:4}-${session:20:12}"
install -d -o ubuntu -g ubuntu -m 0700 /run/claude-config /run/claude-workspace
printf '{"mcpServers":{}}\n' > /run/claude-mcp.json
chown ubuntu:ubuntu /run/claude-mcp.json
if ! curl -fsS --connect-timeout 2 --max-time 10 http://10.0.2.100:9000/health | grep -qx '{"status":"ok"}'; then
  log_marker "SAFE_CHANGE_QEMU_AGENT_MODEL_UNREACHABLE session=$session"
  while true; do sleep 60; done
fi
log_marker "SAFE_CHANGE_QEMU_AGENT_MODEL_READY session=$session"
cd /run/claude-workspace
log_marker "SAFE_CHANGE_QEMU_AGENT_CLAUDE_STARTED session=$session"
set +e
runuser -u ubuntu -- env -i \
  HOME=/home/ubuntu PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 LC_ALL=C.UTF-8 SHELL=/bin/bash \
  ANTHROPIC_BASE_URL=http://10.0.2.100:9000 ANTHROPIC_API_KEY=fixture-credential ANTHROPIC_MODEL=claude-fixture-1 \
  CLAUDE_CONFIG_DIR=/run/claude-config CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 CLAUDE_CODE_SKIP_PROMPT_HISTORY=1 \
  DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 NO_PROXY=10.0.2.100 no_proxy=10.0.2.100 \
  SAFE_CHANGE_CALL_ID="$session" SAFE_CHANGE_EGRESS_URL=http://10.0.2.100:8788/v1/reserve \
  /opt/claude/claude --bare --print \
  'Use the Bash tool once to submit the fixed reservation to the local HTTP endpoint. Finish with DONE.' \
  --output-format stream-json --verbose --no-session-persistence \
  --strict-mcp-config --mcp-config /run/claude-mcp.json --allowedTools Bash \
  --permission-mode dontAsk --model claude-fixture-1 --max-turns 3 --no-chrome \
  --disable-slash-commands --prompt-suggestions false --session-id "$uuid" \
  2>&1 | tee /run/claude-stream.jsonl /dev/ttyS0
status=${PIPESTATUS[0]}
set -e
if [[ "$status" != 0 ]] || ! grep -q 'DONE' /run/claude-stream.jsonl; then
  log_marker "SAFE_CHANGE_QEMU_AGENT_FAILED session=$session status=$status version=$version"
  while true; do sleep 60; done
fi
sync
log_marker "SAFE_CHANGE_QEMU_AGENT_COMPLETE session=$session"
while true; do sleep 60; done
`, claudeSHA, claudeSHA)
}

func readAgentGuardManifest(path string) (agentGuardManifest, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return agentGuardManifest{}, err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var manifest agentGuardManifest
	if err := decoder.Decode(&manifest); err != nil {
		return agentGuardManifest{}, err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return agentGuardManifest{}, errors.New("resume guard manifest has trailing JSON")
	}
	if manifest.Schema != 2 || manifest.EndpointPath == "" || manifest.ControlURL == "" ||
		manifest.ControlTokenPath == "" || manifest.ActivatedHistory.Sequence == 0 {
		return agentGuardManifest{}, errors.New("resume guard manifest is incomplete")
	}
	return manifest, nil
}

func openAgentControlClient(manifest agentGuardManifest) (*apiclient.Client, error) {
	parsed, err := url.Parse(manifest.ControlURL)
	if err != nil || parsed.Scheme != "http" || parsed.Hostname() != "127.0.0.1" ||
		parsed.Port() == "" || parsed.Path != "" || parsed.RawQuery != "" || parsed.Fragment != "" || parsed.User != nil {
		return nil, errors.New("resume guard Control URL must be an explicit loopback HTTP origin")
	}
	if manifest.ControlTokenPath == "" || !filepath.IsAbs(manifest.ControlTokenPath) ||
		filepath.Clean(manifest.ControlTokenPath) != manifest.ControlTokenPath {
		return nil, errors.New("resume guard Control token path must be absolute and canonical")
	}
	pathInfo, err := os.Lstat(manifest.ControlTokenPath)
	if err != nil {
		return nil, err
	}
	stat, ok := pathInfo.Sys().(*syscall.Stat_t)
	if !pathInfo.Mode().IsRegular() || pathInfo.Mode().Perm() != 0o600 || !ok ||
		int(stat.Uid) != os.Geteuid() || stat.Nlink != 1 {
		return nil, errors.New("resume guard Control token must be a private current-user file with one link")
	}
	file, err := os.Open(manifest.ControlTokenPath)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	openInfo, err := file.Stat()
	if err != nil || !os.SameFile(pathInfo, openInfo) {
		return nil, errors.New("resume guard Control token changed while opening")
	}
	data, err := io.ReadAll(io.LimitReader(file, 4097))
	if err != nil || len(data) > 4096 {
		return nil, errors.New("resume guard Control token is unreadable or oversized")
	}
	token := strings.TrimSuffix(string(data), "\n")
	if len(token) < 32 || strings.IndexFunc(token, func(value rune) bool {
		return unicode.IsSpace(value) || unicode.IsControl(value)
	}) >= 0 || token+"\n" != string(data) {
		return nil, errors.New("resume guard Control token is not one canonical line")
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	transport.DialContext = (&net.Dialer{Timeout: 3 * time.Second}).DialContext
	client := &http.Client{Transport: transport, Timeout: 5 * time.Second}
	return apiclient.New(manifest.ControlURL, token, client)
}

func containsBinding(bindings []control.SandboxBinding, expected control.SandboxBinding) bool {
	for _, binding := range bindings {
		if reflect.DeepEqual(binding, expected) {
			return true
		}
	}
	return false
}

func probeAgentEndpoint(ctx context.Context, endpoint vmresume.EndpointPublication) error {
	dialer := net.Dialer{}
	connection, err := dialer.DialContext(ctx, "unix", endpoint.Path)
	if err != nil {
		return err
	}
	defer connection.Close()
	if deadline, ok := ctx.Deadline(); ok {
		_ = connection.SetDeadline(deadline)
	} else {
		_ = connection.SetDeadline(time.Now().Add(3 * time.Second))
	}
	if _, err := io.WriteString(connection, "GET /healthz HTTP/1.1\r\nHost: sandbox\r\nConnection: close\r\n\r\n"); err != nil {
		return err
	}
	response := make([]byte, 128)
	count, err := connection.Read(response)
	if err != nil && !errors.Is(err, io.EOF) {
		return err
	}
	if !bytes.HasPrefix(response[:count], []byte("HTTP/1.1 200")) {
		return errors.New("sandbox endpoint health probe did not return HTTP 200")
	}
	return nil
}

func waitForAgentBarrier(ctx context.Context, path string) (map[string]any, error) {
	path, err := filepath.Abs(path)
	if err != nil {
		return nil, err
	}
	ticker := time.NewTicker(50 * time.Millisecond)
	defer ticker.Stop()
	for {
		info, err := os.Lstat(path)
		if err == nil {
			if !info.Mode().IsRegular() || info.Mode().Perm()&0o077 != 0 {
				return nil, errors.New("source barrier must be a private regular file")
			}
			data, err := os.ReadFile(path)
			if err != nil {
				return nil, err
			}
			var value map[string]any
			if err := json.Unmarshal(data, &value); err != nil || value["external_fact_observed"] != true {
				return nil, errors.New("source barrier does not acknowledge an external fact")
			}
			value["barrier_path_basename"] = filepath.Base(path)
			value["barrier_observed_time_ns"] = time.Now().UnixNano()
			return value, nil
		}
		if !errors.Is(err, os.ErrNotExist) {
			return nil, err
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-ticker.C:
		}
	}
}

func mustTCPPort(address string) int {
	tcp, err := net.ResolveTCPAddr("tcp", address)
	if err != nil {
		panic(err)
	}
	return tcp.Port
}

func writeAgentResult(directory string, value map[string]any) error {
	return writeJSONPrivate(filepath.Join(directory, "result.json"), value)
}

func writeJSONPrivate(path string, value any) error {
	encoded, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	return writePrivateFile(path, append(encoded, '\n'))
}

func fileSize(path string) int64 {
	info, err := os.Stat(path)
	if err != nil {
		return -1
	}
	return info.Size()
}
