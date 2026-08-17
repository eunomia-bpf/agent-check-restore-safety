package vmresume

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

type guardFixture struct {
	t               *testing.T
	state           *kernel.State
	request         Request
	listener        net.Listener
	diskFile        *os.File
	continueCount   int
	bindingValid    bool
	endpointHealthy bool
}

func newGuardFixture(t *testing.T, decision kernel.Decision) *guardFixture {
	t.Helper()
	initial := kernel.Requirement{
		ID: "before", Results: map[string]uint32{"done": 1}, Capacities: map[string]uint32{"slot": 1},
		Kinds: map[string]kernel.KindSpec{"reserve": {Costs: map[string]uint32{"slot": 1}, Produces: map[string]uint32{"done": 1}, RetrySafe: true}},
	}
	state := kernel.NewState()
	first, err := kernel.Compile(state, initial, 1)
	if err != nil {
		t.Fatal(err)
	}
	if err := state.Activate(first); err != nil {
		t.Fatal(err)
	}
	checked := state.Clone()
	target := initial
	target.ID = "after"
	certificate, err := kernel.Compile(checked, target, 2)
	if err != nil {
		t.Fatal(err)
	}
	if decision == kernel.Impossible {
		certificate.Decision = kernel.Impossible
		certificate.Rule = nil
		certificate.Witness = &kernel.Witness{Reason: "test denial"}
		certificate.Digest = ""
		// A manually altered Certificate is deliberately not verified in the
		// denied path: decision rejection precedes Certificate consumption.
	} else if err := state.Activate(certificate); err != nil {
		t.Fatal(err)
	}
	activated := kernel.HistoryPoint{Sequence: 9, Hash: digest([]byte("cutover"))}
	state.History = activated

	directory := t.TempDir()
	checkpointPath := filepath.Join(directory, "guest.qcow2")
	if err := os.WriteFile(checkpointPath, []byte("sealed full VM checkpoint"), 0o600); err != nil {
		t.Fatal(err)
	}
	diskFile, err := os.Open(checkpointPath)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = diskFile.Close() })
	machineConfig, err := json.Marshal(map[string]any{"machine": "q35", "memory_mib": 1024, "cpus": 2})
	if err != nil {
		t.Fatal(err)
	}
	binding := control.SandboxBinding{SandboxID: "agent-vm", Generation: 2, HostInstanceID: "host-2", Domain: "agent", AllowedKinds: []string{"reserve"}}
	socketPath := filepath.Join(directory, "sandbox.sock")
	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(socketPath, 0o600); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = listener.Close() })
	endpoint, err := CaptureEndpoint(socketPath, binding)
	if err != nil {
		t.Fatal(err)
	}
	process, err := CaptureProcessIdentity(os.Getpid())
	if err != nil {
		t.Fatal(err)
	}
	disk, err := CaptureDiskIdentity(checkpointPath, digest([]byte("sealed full VM checkpoint")))
	if err != nil {
		t.Fatal(err)
	}
	fixture := &guardFixture{
		t: t, state: state, listener: listener, diskFile: diskFile,
		bindingValid: true, endpointHealthy: true,
	}
	fixture.request = Request{
		CheckedState: checked, Certificate: certificate, ActivatedHistory: activated,
		Checkpoint: Checkpoint{
			Path: checkpointPath, SHA256: digest([]byte("sealed full VM checkpoint")), SnapshotName: "before_agent",
			MachineConfig: machineConfig, MachineConfigSHA256: digest(machineConfig),
		},
		Process: process, Disk: disk, Endpoint: endpoint,
	}
	return fixture
}

func (fixture *guardFixture) guard(t *testing.T) *Guard {
	t.Helper()
	guard, err := New(Sources{
		CurrentState: func() (*kernel.State, error) { return fixture.state.Clone(), nil },
		ValidateBinding: func(binding control.SandboxBinding) error {
			if !fixture.bindingValid || !reflect.DeepEqual(binding, fixture.request.Endpoint.Binding) {
				return errors.New("stale binding")
			}
			return nil
		},
		ProbeEndpoint: func(context.Context, EndpointPublication) error {
			if !fixture.endpointHealthy {
				return errors.New("endpoint unavailable")
			}
			return nil
		},
		Continue: func(context.Context) error { fixture.continueCount++; return nil },
	})
	if err != nil {
		t.Fatal(err)
	}
	return guard
}

func TestGuardBindsAndConsumesOneResume(t *testing.T) {
	fixture := newGuardFixture(t, kernel.Activate)
	guard := fixture.guard(t)
	authorization, err := guard.Authorize(context.Background(), fixture.request)
	if err != nil {
		t.Fatal(err)
	}
	if err := guard.Resume(context.Background(), authorization); err != nil {
		t.Fatal(err)
	}
	if fixture.continueCount != 1 {
		t.Fatalf("Continue calls = %d, want 1", fixture.continueCount)
	}
	if err := guard.Resume(context.Background(), authorization); !errors.Is(err, ErrConsumed) {
		t.Fatalf("second resume error = %v, want consumed", err)
	}
}

func TestGuardDeniesImpossibleDecisionAndResumeAttempt(t *testing.T) {
	fixture := newGuardFixture(t, kernel.Impossible)
	guard := fixture.guard(t)
	if _, err := guard.Authorize(context.Background(), fixture.request); !errors.Is(err, ErrDenied) {
		t.Fatalf("authorize error = %v, want denied", err)
	}
	if err := guard.Resume(context.Background(), Authorization{}); !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("resume error = %v, want unauthorized", err)
	}
	if fixture.continueCount != 0 {
		t.Fatalf("denied resume issued %d Continue calls", fixture.continueCount)
	}
}

func TestGuardRechecksCheckpointAndBindingBeforeResume(t *testing.T) {
	for _, test := range []struct {
		name   string
		mutate func(*guardFixture)
	}{
		{name: "checkpoint", mutate: func(f *guardFixture) { _ = os.WriteFile(f.request.Checkpoint.Path, []byte("changed"), 0o600) }},
		{name: "binding", mutate: func(f *guardFixture) { f.bindingValid = false }},
		{name: "endpoint", mutate: func(f *guardFixture) { f.endpointHealthy = false }},
		{name: "open disk", mutate: func(f *guardFixture) { _ = f.diskFile.Close() }},
		{name: "History", mutate: func(f *guardFixture) { f.state.History.Sequence++ }},
	} {
		t.Run(test.name, func(t *testing.T) {
			fixture := newGuardFixture(t, kernel.Activate)
			guard := fixture.guard(t)
			authorization, err := guard.Authorize(context.Background(), fixture.request)
			if err != nil {
				t.Fatal(err)
			}
			test.mutate(fixture)
			if err := guard.Resume(context.Background(), authorization); err == nil {
				t.Fatal("changed host fact did not fail closed")
			}
			if fixture.continueCount != 0 {
				t.Fatalf("changed host fact issued %d Continue calls", fixture.continueCount)
			}
		})
	}
}

func TestGuardRejectsForgedAuthorization(t *testing.T) {
	fixture := newGuardFixture(t, kernel.Activate)
	guard := fixture.guard(t)
	if _, err := guard.Authorize(context.Background(), fixture.request); err != nil {
		t.Fatal(err)
	}
	if err := guard.Resume(context.Background(), Authorization{}); !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("forged authorization error = %v", err)
	}
	if fixture.continueCount != 0 {
		t.Fatal("forged authorization reached Continue")
	}
}

func TestDeniedAuthorizationRevokesOlderPermit(t *testing.T) {
	fixture := newGuardFixture(t, kernel.Activate)
	guard := fixture.guard(t)
	prior, err := guard.Authorize(context.Background(), fixture.request)
	if err != nil {
		t.Fatal(err)
	}
	denied := fixture.request
	denied.Certificate.Decision = kernel.Impossible
	if _, err := guard.Authorize(context.Background(), denied); !errors.Is(err, ErrDenied) {
		t.Fatalf("denied authorize error = %v", err)
	}
	if err := guard.Resume(context.Background(), prior); !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("revoked permit error = %v, want unauthorized", err)
	}
	if fixture.continueCount != 0 {
		t.Fatal("revoked permit reached Continue")
	}
}

func digest(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}
