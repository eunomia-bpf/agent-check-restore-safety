//go:build historyguard

package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"syscall"
	"time"
	"unicode"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/apiclient"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/firecracker"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/vmresume"
	"golang.org/x/sys/unix"
)

const historyLaunchManifestSchema = 1

type historyLaunchManifest struct {
	Schema           int                    `json:"schema"`
	CheckedState     kernel.State           `json:"checked_state"`
	Certificate      kernel.Certificate     `json:"certificate"`
	ActivatedHistory kernel.HistoryPoint    `json:"activated_history"`
	Binding          control.SandboxBinding `json:"binding"`
	EndpointPath     string                 `json:"endpoint_path"`
	ControlURL       string                 `json:"control_url"`
	ControlTokenPath string                 `json:"control_token_path"`
}

type historyProcessFact struct {
	PID              int    `json:"pid"`
	Executable       string `json:"executable"`
	Device           uint64 `json:"device"`
	Inode            uint64 `json:"inode"`
	ExecutableSHA256 string `json:"executable_sha256"`
	StartTimeTicks   uint64 `json:"start_time_ticks"`
}

type historyArtifactFact struct {
	Name   string `json:"name"`
	Device uint64 `json:"device"`
	Inode  uint64 `json:"inode"`
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256"`
	Seals  int    `json:"seals"`
}

type historyRuntimeFacts struct {
	Schema              int                          `json:"schema"`
	Process             historyProcessFact           `json:"process"`
	Artifacts           []historyArtifactFact        `json:"artifacts"`
	ConfigurationSHA256 string                       `json:"configuration_sha256"`
	Endpoint            vmresume.EndpointPublication `json:"endpoint"`
	FirecrackerState    firecracker.InstanceInfo     `json:"firecracker_state"`
}

func registerLaunchFlags(config *options) {
	flag.StringVar(&config.launchManifest, "launch-manifest", "", "private History launch manifest (required by protected build)")
}

func validateLaunchOptions(config options) error {
	if config.launchManifest == "" {
		return errors.New("protected Firecracker cell requires -launch-manifest")
	}
	return nil
}

func launchOptionPaths(config *options) []*string { return []*string{&config.launchManifest} }

func launchConfiguredCell(ctx context.Context, config options, inputs launchInputs) (launchResult, error) {
	manifest, err := readHistoryLaunchManifest(config.launchManifest)
	if err != nil {
		return launchResult{}, err
	}
	controlClient, err := openHistoryControlClient(manifest)
	if err != nil {
		return launchResult{}, err
	}
	endpoint, err := vmresume.CaptureEndpoint(manifest.EndpointPath, manifest.Binding)
	if err != nil {
		return launchResult{}, fmt.Errorf("capture protected endpoint: %w", err)
	}
	initialState, err := inputs.client.State(ctx)
	if err != nil {
		return launchResult{}, fmt.Errorf("read configured Firecracker state: %w", err)
	}
	if err := requireNotStarted(initialState, config.instanceID); err != nil {
		return launchResult{}, err
	}
	facts, err := captureHistoryRuntimeFacts(inputs, endpoint, initialState)
	if err != nil {
		return launchResult{}, err
	}
	encodedFacts, err := encodeCanonicalHistoryJSON(facts)
	if err != nil {
		return launchResult{}, err
	}
	request := vmresume.LifecycleRequest{
		CheckedState: &manifest.CheckedState, Certificate: manifest.Certificate,
		ActivatedHistory: manifest.ActivatedHistory, Binding: manifest.Binding,
		RuntimeFacts: encodedFacts,
	}
	stateReads := []kernel.State{}
	bindingReads := [][]control.SandboxBinding{}
	runtimeReads := []firecracker.InstanceInfo{}
	guard, err := vmresume.NewLifecycleGuard(vmresume.LifecycleSources{
		CurrentState: func() (*kernel.State, error) {
			state, readErr := controlClient.State(ctx)
			if readErr != nil {
				return nil, readErr
			}
			stateReads = append(stateReads, state)
			return &state, nil
		},
		ValidateBinding: func(binding control.SandboxBinding) error {
			bindings, readErr := controlClient.SandboxBindings(ctx)
			if readErr != nil {
				return readErr
			}
			bindingReads = append(bindingReads, bindings)
			if !reflect.DeepEqual(binding, manifest.Binding) || !containsHistoryBinding(bindings, binding) {
				return errors.New("protected sandbox binding is absent from live Control")
			}
			return nil
		},
		ValidateRuntime: func(probeContext context.Context, encoded json.RawMessage) error {
			var expected historyRuntimeFacts
			if err := decodeStrictHistoryJSON(encoded, &expected); err != nil {
				return err
			}
			state, validateErr := validateHistoryRuntimeFacts(probeContext, config, inputs, expected)
			if validateErr != nil {
				return validateErr
			}
			runtimeReads = append(runtimeReads, state)
			return nil
		},
		Start: func(startContext context.Context) error { return inputs.client.Start(startContext) },
	})
	if err != nil {
		return launchResult{}, err
	}
	evidence := map[string]any{
		"schema": 1, "guarded": true, "certificate_decision": manifest.Certificate.Decision,
		"certificate_digest": manifest.Certificate.Digest, "checked_history": manifest.Certificate.History,
		"activated_history": manifest.ActivatedHistory, "binding": manifest.Binding,
		"runtime_facts": facts, "configured_state_before_authorize": initialState,
	}
	authorization, authorizeErr := guard.Authorize(ctx, request)
	if errors.Is(authorizeErr, vmresume.ErrDenied) {
		startErr := guard.Start(ctx, vmresume.LifecycleAuthorization{})
		if !errors.Is(startErr, vmresume.ErrUnauthorized) {
			return launchResult{}, fmt.Errorf("denied History guard accepted InstanceStart: %v", startErr)
		}
		after, stateErr := inputs.client.State(ctx)
		if stateErr != nil {
			return launchResult{}, stateErr
		}
		if err := requireNotStarted(after, config.instanceID); err != nil {
			return launchResult{}, fmt.Errorf("denied replacement changed Firecracker state: %w", err)
		}
		evidence["decision"] = "impossible"
		evidence["authorization_issued"] = false
		evidence["instance_start_issued"] = false
		evidence["denied_start_error"] = startErr.Error()
		evidence["configured_state_after_denial"] = after
		evidence["live_states"] = stateReads
		evidence["live_binding_views"] = bindingReads
		evidence["runtime_state_reads"] = runtimeReads
		if err := writePrivateJSON(filepath.Join(inputs.evidenceDir, "launch-guard.json"), evidence); err != nil {
			return launchResult{}, err
		}
		return launchResult{Guarded: true, Decision: "impossible", Started: false}, nil
	}
	if authorizeErr != nil {
		return launchResult{}, authorizeErr
	}
	if err := guard.Start(ctx, authorization); err != nil {
		return launchResult{}, err
	}
	reuseErr := guard.Start(ctx, authorization)
	if !errors.Is(reuseErr, vmresume.ErrConsumed) {
		return launchResult{}, fmt.Errorf("consumed History launch permit was reusable: %v", reuseErr)
	}
	evidence["decision"] = "activate"
	evidence["authorization_issued"] = true
	evidence["authorization_consumed"] = true
	evidence["instance_start_issued"] = true
	evidence["reused_authorization_error"] = reuseErr.Error()
	evidence["live_states"] = stateReads
	evidence["live_binding_views"] = bindingReads
	evidence["runtime_state_reads"] = runtimeReads
	if err := writePrivateJSON(filepath.Join(inputs.evidenceDir, "launch-guard.json"), evidence); err != nil {
		return launchResult{}, err
	}
	return launchResult{Guarded: true, Decision: "activate", Started: true}, nil
}

func readHistoryLaunchManifest(path string) (historyLaunchManifest, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return historyLaunchManifest{}, err
	}
	var manifest historyLaunchManifest
	if err := decodeStrictHistoryJSON(data, &manifest); err != nil {
		return historyLaunchManifest{}, err
	}
	if manifest.Schema != historyLaunchManifestSchema || manifest.EndpointPath == "" ||
		manifest.ControlURL == "" || manifest.ControlTokenPath == "" ||
		manifest.ActivatedHistory.Sequence == 0 {
		return historyLaunchManifest{}, errors.New("History launch manifest is incomplete")
	}
	return manifest, nil
}

func openHistoryControlClient(manifest historyLaunchManifest) (*apiclient.Client, error) {
	parsed, err := url.Parse(manifest.ControlURL)
	if err != nil || parsed.Scheme != "http" || parsed.Hostname() != "127.0.0.1" ||
		parsed.Port() == "" || parsed.Path != "" || parsed.RawQuery != "" ||
		parsed.Fragment != "" || parsed.User != nil {
		return nil, errors.New("History launch Control URL must be an explicit loopback HTTP origin")
	}
	path := manifest.ControlTokenPath
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return nil, errors.New("History launch token path must be absolute and canonical")
	}
	pathInfo, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	stat, ok := pathInfo.Sys().(*syscall.Stat_t)
	if !pathInfo.Mode().IsRegular() || pathInfo.Mode().Perm() != 0o600 || !ok ||
		int(stat.Uid) != os.Geteuid() || stat.Nlink != 1 {
		return nil, errors.New("History launch token must be a private current-user file with one link")
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	openInfo, err := file.Stat()
	if err != nil || !os.SameFile(pathInfo, openInfo) {
		return nil, errors.New("History launch token changed while opening")
	}
	data, err := io.ReadAll(io.LimitReader(file, 4097))
	if err != nil || len(data) > 4096 {
		return nil, errors.New("History launch token is unreadable or oversized")
	}
	token := strings.TrimSuffix(string(data), "\n")
	if len(token) < 32 || strings.IndexFunc(token, func(value rune) bool {
		return unicode.IsSpace(value) || unicode.IsControl(value)
	}) >= 0 || token+"\n" != string(data) {
		return nil, errors.New("History launch token is not one canonical line")
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	transport.DialContext = (&net.Dialer{Timeout: 3 * time.Second}).DialContext
	return apiclient.New(manifest.ControlURL, token, &http.Client{Transport: transport, Timeout: 5 * time.Second})
}

func captureHistoryRuntimeFacts(inputs launchInputs, endpoint vmresume.EndpointPublication, state firecracker.InstanceInfo) (historyRuntimeFacts, error) {
	artifacts := make([]historyArtifactFact, 0, len(inputs.artifactFiles))
	for name, file := range inputs.artifactFiles {
		record, ok := inputs.artifacts[name]
		if !ok {
			return historyRuntimeFacts{}, fmt.Errorf("protected artifact %q has no record", name)
		}
		fact, err := captureHistoryArtifact(name, file, record)
		if err != nil {
			return historyRuntimeFacts{}, err
		}
		artifacts = append(artifacts, fact)
	}
	sort.Slice(artifacts, func(i, j int) bool { return artifacts[i].Name < artifacts[j].Name })
	configurationHash := sha256.Sum256(inputs.configuration)
	identity := inputs.process.Identity()
	return historyRuntimeFacts{
		Schema: 1,
		Process: historyProcessFact{
			PID: identity.PID, Executable: identity.Executable, Device: identity.Device,
			Inode: identity.Inode, ExecutableSHA256: identity.ExecutableSHA256,
			StartTimeTicks: identity.StartTimeTicks,
		},
		Artifacts: artifacts, ConfigurationSHA256: hex.EncodeToString(configurationHash[:]),
		Endpoint: endpoint, FirecrackerState: state,
	}, nil
}

func captureHistoryArtifact(name string, file *os.File, record artifactRecord) (historyArtifactFact, error) {
	if file == nil || record.Name != name || record.Size <= 0 || len(record.SHA256) != 64 {
		return historyArtifactFact{}, fmt.Errorf("protected artifact %q metadata is incomplete", name)
	}
	info, err := file.Stat()
	if err != nil {
		return historyArtifactFact{}, err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || info.Size() != record.Size {
		return historyArtifactFact{}, fmt.Errorf("protected artifact %q identity differs", name)
	}
	seals, err := unix.FcntlInt(file.Fd(), unix.F_GET_SEALS, 0)
	wanted := unix.F_SEAL_SEAL | unix.F_SEAL_SHRINK | unix.F_SEAL_GROW | unix.F_SEAL_WRITE
	if err != nil || seals != wanted {
		return historyArtifactFact{}, fmt.Errorf("protected artifact %q is not fully sealed", name)
	}
	return historyArtifactFact{
		Name: name, Device: uint64(stat.Dev), Inode: stat.Ino, Size: info.Size(),
		SHA256: record.SHA256, Seals: seals,
	}, nil
}

func validateHistoryRuntimeFacts(ctx context.Context, config options, inputs launchInputs, expected historyRuntimeFacts) (firecracker.InstanceInfo, error) {
	if expected.Schema != 1 {
		return firecracker.InstanceInfo{}, errors.New("protected runtime facts schema differs")
	}
	if err := inputs.process.VerifyIdentity(); err != nil {
		return firecracker.InstanceInfo{}, err
	}
	actual, err := captureHistoryRuntimeFacts(inputs, expected.Endpoint, expected.FirecrackerState)
	if err != nil {
		return firecracker.InstanceInfo{}, err
	}
	actual.Endpoint, err = vmresume.CaptureEndpoint(expected.Endpoint.Path, expected.Endpoint.Binding)
	if err != nil {
		return firecracker.InstanceInfo{}, err
	}
	state, err := inputs.client.State(ctx)
	if err != nil {
		return firecracker.InstanceInfo{}, err
	}
	if err := requireNotStarted(state, config.instanceID); err != nil {
		return firecracker.InstanceInfo{}, err
	}
	actual.FirecrackerState = state
	if !reflect.DeepEqual(actual, expected) {
		return firecracker.InstanceInfo{}, errors.New("protected Firecracker runtime facts changed")
	}
	for _, artifact := range expected.Artifacts {
		if !processHasHistoryArtifact(inputs.process.PID(), artifact) {
			return firecracker.InstanceInfo{}, fmt.Errorf("Firecracker process no longer holds artifact %q", artifact.Name)
		}
	}
	if err := probeHistoryEndpoint(ctx, expected.Endpoint); err != nil {
		return firecracker.InstanceInfo{}, err
	}
	return state, nil
}

func processHasHistoryArtifact(pid int, artifact historyArtifactFact) bool {
	entries, err := os.ReadDir(filepath.Join("/proc", fmt.Sprint(pid), "fd"))
	if err != nil {
		return false
	}
	for _, entry := range entries {
		info, err := os.Stat(filepath.Join("/proc", fmt.Sprint(pid), "fd", entry.Name()))
		if err != nil || info.Size() != artifact.Size {
			continue
		}
		stat, ok := info.Sys().(*syscall.Stat_t)
		if ok && uint64(stat.Dev) == artifact.Device && stat.Ino == artifact.Inode {
			return true
		}
	}
	return false
}

func requireNotStarted(state firecracker.InstanceInfo, instanceID string) error {
	if state.State != firecracker.StateNotStarted || state.ID != instanceID ||
		state.AppName != "Firecracker" || state.VMMVersion != officialFirecrackerVersion {
		return fmt.Errorf("Firecracker state is %+v, require configured Not started instance %q", state, instanceID)
	}
	return nil
}

func probeHistoryEndpoint(ctx context.Context, endpoint vmresume.EndpointPublication) error {
	connection, err := (&net.Dialer{}).DialContext(ctx, "unix", endpoint.Path)
	if err != nil {
		return err
	}
	defer connection.Close()
	deadline := time.Now().Add(3 * time.Second)
	if value, ok := ctx.Deadline(); ok && value.Before(deadline) {
		deadline = value
	}
	_ = connection.SetDeadline(deadline)
	if _, err := io.WriteString(connection, "GET /healthz HTTP/1.1\r\nHost: sandbox\r\nConnection: close\r\n\r\n"); err != nil {
		return err
	}
	response := make([]byte, 128)
	count, err := connection.Read(response)
	if err != nil && !errors.Is(err, io.EOF) {
		return err
	}
	if !bytes.HasPrefix(response[:count], []byte("HTTP/1.1 200")) {
		return errors.New("protected sandbox endpoint health probe failed")
	}
	return nil
}

func containsHistoryBinding(bindings []control.SandboxBinding, expected control.SandboxBinding) bool {
	for _, binding := range bindings {
		if reflect.DeepEqual(binding, expected) {
			return true
		}
	}
	return false
}

func decodeStrictHistoryJSON(data []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return errors.New("History launch JSON contains trailing data")
	}
	return nil
}

func encodeCanonicalHistoryJSON(value any) ([]byte, error) {
	encoded, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	decoder := json.NewDecoder(bytes.NewReader(encoded))
	decoder.UseNumber()
	var generic any
	if err := decoder.Decode(&generic); err != nil {
		return nil, err
	}
	return json.Marshal(generic)
}
