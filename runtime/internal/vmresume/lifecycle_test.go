package vmresume

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

func lifecycleFixture(t *testing.T, decision kernel.Decision) (LifecycleRequest, *kernel.State) {
	t.Helper()
	checked := kernel.NewState()
	requirement := kernel.Requirement{
		ID: "lifecycle", Results: map[string]uint32{"done": 1}, Capacities: map[string]uint32{"slot": 1},
		Kinds: map[string]kernel.KindSpec{
			"finish": {Costs: map[string]uint32{"slot": 1}, Produces: map[string]uint32{"done": 1}, RetrySafe: true},
		},
	}
	certificate, err := kernel.Compile(checked, requirement, 1)
	if err != nil {
		t.Fatal(err)
	}
	if decision == kernel.Impossible {
		requirement.Results["done"] = 2
		certificate, err = kernel.Compile(checked, requirement, 1)
		if err != nil {
			t.Fatal(err)
		}
	}
	if certificate.Decision != decision {
		t.Fatalf("fixture decision=%q want %q", certificate.Decision, decision)
	}
	current := checked.Clone()
	activatedHistory := checked.History
	if decision == kernel.Activate {
		if err := current.Activate(certificate); err != nil {
			t.Fatal(err)
		}
		activatedHistory = current.History
	}
	binding := control.SandboxBinding{
		SandboxID: "sandbox", Generation: 1, HostInstanceID: "host", Domain: "domain",
		AllowedKinds: []string{"kind"},
	}
	return LifecycleRequest{
		CheckedState: checked, Certificate: certificate, ActivatedHistory: activatedHistory,
		Binding: binding, RuntimeFacts: json.RawMessage(`{"process":"exact"}`),
	}, current
}

func TestLifecycleGuardStartsOnceAfterTwoLiveValidations(t *testing.T) {
	request, current := lifecycleFixture(t, kernel.Activate)
	stateReads, bindingReads, runtimeReads, starts := 0, 0, 0, 0
	guard, err := NewLifecycleGuard(LifecycleSources{
		CurrentState: func() (*kernel.State, error) { stateReads++; return current.Clone(), nil },
		ValidateBinding: func(value control.SandboxBinding) error {
			bindingReads++
			if !reflect.DeepEqual(value, request.Binding) {
				return errors.New("binding differs")
			}
			return nil
		},
		ValidateRuntime: func(_ context.Context, facts json.RawMessage) error {
			runtimeReads++
			if string(facts) != string(request.RuntimeFacts) {
				return errors.New("facts differ")
			}
			return nil
		},
		Start: func(context.Context) error { starts++; return nil },
	})
	if err != nil {
		t.Fatal(err)
	}
	authorization, err := guard.Authorize(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	if err := guard.Start(context.Background(), authorization); err != nil {
		t.Fatal(err)
	}
	if stateReads != 2 || bindingReads != 2 || runtimeReads != 2 || starts != 1 {
		t.Fatalf("reads/start=%d/%d/%d/%d", stateReads, bindingReads, runtimeReads, starts)
	}
	if err := guard.Start(context.Background(), authorization); !errors.Is(err, ErrConsumed) {
		t.Fatalf("second start error=%v", err)
	}
}

func TestLifecycleGuardImpossibleNeverReadsOrStarts(t *testing.T) {
	request, _ := lifecycleFixture(t, kernel.Impossible)
	called := false
	guard, err := NewLifecycleGuard(LifecycleSources{
		CurrentState:    func() (*kernel.State, error) { called = true; return nil, nil },
		ValidateBinding: func(control.SandboxBinding) error { called = true; return nil },
		ValidateRuntime: func(context.Context, json.RawMessage) error { called = true; return nil },
		Start:           func(context.Context) error { called = true; return nil },
	})
	if err != nil {
		t.Fatal(err)
	}
	_, err = guard.Authorize(context.Background(), request)
	if !errors.Is(err, ErrDenied) {
		t.Fatalf("authorize error=%v", err)
	}
	if called {
		t.Fatal("impossible decision invoked a live callback")
	}
	if err := guard.Start(context.Background(), LifecycleAuthorization{}); !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("denied start error=%v", err)
	}
}

func TestLifecycleGuardRejectsNoncanonicalAndStaleFacts(t *testing.T) {
	request, current := lifecycleFixture(t, kernel.Activate)
	guard, err := NewLifecycleGuard(LifecycleSources{
		CurrentState:    func() (*kernel.State, error) { return current.Clone(), nil },
		ValidateBinding: func(control.SandboxBinding) error { return nil },
		ValidateRuntime: func(context.Context, json.RawMessage) error { return nil },
		Start:           func(context.Context) error { return nil },
	})
	if err != nil {
		t.Fatal(err)
	}
	request.RuntimeFacts = json.RawMessage(`{ "process": "exact" }`)
	if _, err := guard.Authorize(context.Background(), request); err == nil {
		t.Fatal("accepted noncanonical runtime facts")
	}
	request.RuntimeFacts = json.RawMessage(`{"process":"exact"}`)
	current.History.Sequence++
	if _, err := guard.Authorize(context.Background(), request); err == nil {
		t.Fatal("accepted stale activated History")
	}
}

func TestLifecycleGuardImpossibleStillVerifiesCertificate(t *testing.T) {
	request, _ := lifecycleFixture(t, kernel.Impossible)
	request.Certificate.Digest = "tampered"
	guard, err := NewLifecycleGuard(LifecycleSources{
		CurrentState:    func() (*kernel.State, error) { return nil, nil },
		ValidateBinding: func(control.SandboxBinding) error { return nil },
		ValidateRuntime: func(context.Context, json.RawMessage) error { return nil },
		Start:           func(context.Context) error { return nil },
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := guard.Authorize(context.Background(), request); err == nil || errors.Is(err, ErrDenied) {
		t.Fatalf("malformed impossible Certificate error=%v", err)
	}
}
