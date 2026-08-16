package control

import (
	"encoding/json"
	"errors"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/headanchor"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/history"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

func testSandboxBinding(id string, generation uint64, host, domain string, kinds ...string) SandboxBinding {
	return SandboxBinding{
		SandboxID: id, Generation: generation, HostInstanceID: host,
		Domain: domain, AllowedKinds: append([]string(nil), kinds...),
	}
}

func TestCutoverPublishesCanonicalBindingsInOneEvent(t *testing.T) {
	control, err := Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	certificate, err := control.Compile(requirement("invoice-v1"))
	if err != nil {
		t.Fatal(err)
	}
	input := []SandboxBinding{
		testSandboxBinding("sandbox-z", 1, "host-z-1", "warehouse", "tip", "charge"),
		testSandboxBinding("sandbox-a", 1, "host-a-1", "payments", "charge"),
	}
	if err := control.Cutover(certificate, input); err != nil {
		t.Fatal(err)
	}
	input[0].AllowedKinds[0] = "mutated"
	input[1].Domain = "mutated"

	events := control.Events()
	if len(events) != 1 || events[0].Operation != eventRuleBindingsCutover {
		t.Fatalf("cutover events = %+v", events)
	}
	var durable ruleBindingsCutoverEvent
	if err := decodeStrict(events[0].Data, &durable); err != nil {
		t.Fatal(err)
	}
	if durable.SemanticVersion != cutoverSemanticVersion || durable.Certificate.Rule.Version != 1 {
		t.Fatalf("durable cutover = %+v", durable)
	}
	if len(durable.Bindings) != 2 || durable.Bindings[0].SandboxID != "sandbox-a" ||
		durable.Bindings[1].SandboxID != "sandbox-z" ||
		strings.Join(durable.Bindings[1].AllowedKinds, ",") != "charge,tip" {
		t.Fatalf("bindings are not canonical: %+v", durable.Bindings)
	}
	state := control.Snapshot()
	if state.Rule == nil || state.Rule.Version != 1 || state.History.Sequence != 1 {
		t.Fatalf("published State = %+v", state)
	}
	bindings := control.SandboxBindings()
	if !sandboxBindingsEqual(bindings, durable.Bindings) {
		t.Fatalf("published bindings = %+v, durable = %+v", bindings, durable.Bindings)
	}
	bindings[0].AllowedKinds[0] = "mutated-output"
	if control.SandboxBindings()[0].AllowedKinds[0] != "charge" {
		t.Fatal("SandboxBindings returned aliased AllowedKinds")
	}

	payment := durable.Bindings[0]
	if err := control.ValidateSandbox(payment); !errors.Is(err, ErrSandboxNotAttached) {
		t.Fatalf("unattached binding validation = %v", err)
	}
	if err := control.AttachSandboxHost(payment); err != nil {
		t.Fatal(err)
	}
	if err := control.ValidateSandbox(payment); err != nil {
		t.Fatal(err)
	}
	prepared, err := control.PrepareWithRequestForSandbox(
		payment, "charge-1", "charge", "request-1",
		map[string]string{"Content-Type": "application/json"}, []byte(`{"amount":1}`),
	)
	if err != nil {
		t.Fatal(err)
	}
	if prepared.Domain != "payments" || prepared.Kind != "charge" || !prepared.RequestStored {
		t.Fatalf("sandbox-prepared Operation = %+v", prepared)
	}
}

func TestReopenIsClosedUntilFreshGenerationCutoverAndAttach(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.history")
	first, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	certificate, err := first.Compile(requirement("invoice-v1"))
	if err != nil {
		t.Fatal(err)
	}
	old := testSandboxBinding("vm", 1, "vm-host-1", "vm", "charge")
	if err := first.Cutover(certificate, []SandboxBinding{old}); err != nil {
		t.Fatal(err)
	}
	if err := first.AttachSandboxHost(old); err != nil {
		t.Fatal(err)
	}
	if err := first.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if err := reopened.ValidateSandbox(old); !errors.Is(err, ErrSandboxNotAttached) {
		t.Fatalf("replayed binding validation = %v", err)
	}
	if err := reopened.AttachSandboxHost(old); !errors.Is(err, ErrStaleSandboxBinding) {
		t.Fatalf("replayed host instance was attachable: %v", err)
	}
	certificate, err = reopened.Compile(requirement("invoice-v2"))
	if err != nil {
		t.Fatal(err)
	}
	if err := reopened.Cutover(certificate, []SandboxBinding{
		testSandboxBinding("vm", 2, old.HostInstanceID, "vm", "charge"),
	}); err == nil || !strings.Contains(err.Error(), "already used") {
		t.Fatalf("reused HostInstanceID error = %v", err)
	}
	if err := reopened.Cutover(certificate, []SandboxBinding{
		testSandboxBinding("vm", 3, "vm-host-3", "vm", "charge"),
	}); err == nil || !strings.Contains(err.Error(), "want 2") {
		t.Fatalf("skipped generation error = %v", err)
	}
	fresh := testSandboxBinding("vm", 2, "vm-host-2", "vm", "charge")
	if err := reopened.Cutover(certificate, []SandboxBinding{fresh}); err != nil {
		t.Fatal(err)
	}
	if err := reopened.ValidateSandbox(old); !errors.Is(err, ErrStaleSandboxBinding) {
		t.Fatalf("old binding after cutover = %v", err)
	}
	if err := reopened.ValidateSandbox(fresh); !errors.Is(err, ErrSandboxNotAttached) {
		t.Fatalf("fresh binding before attach = %v", err)
	}
	if err := reopened.AttachSandboxHost(fresh); err != nil {
		t.Fatal(err)
	}
	if err := reopened.ValidateSandbox(fresh); err != nil {
		t.Fatal(err)
	}
}

func TestAttachSandboxHostsIsCompleteAndAtomic(t *testing.T) {
	control, err := Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	certificate, err := control.Compile(requirement("atomic-host-attach"))
	if err != nil {
		t.Fatal(err)
	}
	first := testSandboxBinding("vm-a", 1, "vm-host-a", "vm-a", "charge")
	second := testSandboxBinding("vm-b", 1, "vm-host-b", "vm-b", "charge")
	if err := control.Cutover(certificate, []SandboxBinding{first, second}); err != nil {
		t.Fatal(err)
	}
	if err := control.AttachSandboxHosts([]SandboxBinding{first}); err == nil {
		t.Fatal("partial sandbox set was attached")
	}
	if err := control.ValidateSandbox(first); !errors.Is(err, ErrSandboxNotAttached) {
		t.Fatalf("partial failure attached first sandbox: %v", err)
	}
	forged := second
	forged.HostInstanceID = "forged-host"
	if err := control.AttachSandboxHosts([]SandboxBinding{first, forged}); !errors.Is(err, ErrStaleSandboxBinding) {
		t.Fatalf("forged sandbox error=%v", err)
	}
	if err := control.ValidateSandbox(first); !errors.Is(err, ErrSandboxNotAttached) {
		t.Fatalf("forged failure attached first sandbox: %v", err)
	}
	if err := control.ValidateSandbox(second); !errors.Is(err, ErrSandboxNotAttached) {
		t.Fatalf("forged failure attached second sandbox: %v", err)
	}
	if err := control.AttachSandboxHosts([]SandboxBinding{second, first}); err != nil {
		t.Fatal(err)
	}
	if err := control.ValidateSandbox(first); err != nil {
		t.Fatal(err)
	}
	if err := control.ValidateSandbox(second); err != nil {
		t.Fatal(err)
	}
}

func TestActivateFailsClosedWhileDurableSandboxBindingsAreActive(t *testing.T) {
	control, err := Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	certificate, err := control.Compile(requirement("invoice-v1"))
	if err != nil {
		t.Fatal(err)
	}
	binding := testSandboxBinding("vm", 1, "vm-host-1", "vm", "charge")
	if err := control.Cutover(certificate, []SandboxBinding{binding}); err != nil {
		t.Fatal(err)
	}
	certificate, err = control.Compile(requirement("invoice-v2"))
	if err != nil {
		t.Fatal(err)
	}
	eventCount := len(control.Events())
	if err := control.Activate(certificate); !errors.Is(err, ErrActiveSandboxBindings) {
		t.Fatalf("legacy Activate error = %v", err)
	}
	if len(control.Events()) != eventCount {
		t.Fatal("rejected legacy Activate appended an event")
	}
	if err := control.Cutover(certificate, []SandboxBinding{}); err != nil {
		t.Fatal(err)
	}
	if len(control.SandboxBindings()) != 0 {
		t.Fatal("empty complete set did not close durable bindings")
	}
	certificate, err = control.Compile(requirement("invoice-v3"))
	if err != nil {
		t.Fatal(err)
	}
	if err := control.Activate(certificate); err != nil {
		t.Fatalf("legacy Activate remained closed after empty cutover: %v", err)
	}
}

func TestCutoverRejectsOpenBoundOperationWithoutStoredRequest(t *testing.T) {
	control, err := Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	activate(t, control, "invoice-v1")
	if _, err := control.Prepare("legacy-charge", "payments", "charge", "legacy-request"); err != nil {
		t.Fatal(err)
	}
	certificate, err := control.Compile(requirement("invoice-v2"))
	if err != nil {
		t.Fatal(err)
	}
	eventCount := len(control.Events())
	err = control.Cutover(certificate, []SandboxBinding{
		testSandboxBinding("vm", 1, "vm-host-1", "payments", "charge"),
	})
	if err == nil || !strings.Contains(err.Error(), "without a stored request") {
		t.Fatalf("legacy open Operation cutover error = %v", err)
	}
	if len(control.Events()) != eventCount || len(control.SandboxBindings()) != 0 {
		t.Fatal("rejected legacy cutover changed durable state")
	}
}

func TestSandboxAttachmentCanBeConsumedOnlyOnce(t *testing.T) {
	control, err := Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	certificate, err := control.Compile(requirement("invoice-v1"))
	if err != nil {
		t.Fatal(err)
	}
	binding := testSandboxBinding("vm", 1, "vm-host-1", "payments", "charge")
	if err := control.Cutover(certificate, []SandboxBinding{binding}); err != nil {
		t.Fatal(err)
	}
	if err := control.AttachSandboxHost(binding); err != nil {
		t.Fatal(err)
	}
	if err := control.AttachSandboxHost(binding); !errors.Is(err, ErrSandboxAlreadyAttached) {
		t.Fatalf("duplicate attachment error = %v", err)
	}
	if err := control.DetachSandboxHost(binding); err != nil {
		t.Fatal(err)
	}
	if err := control.AttachSandboxHost(binding); !errors.Is(err, ErrStaleSandboxBinding) {
		t.Fatalf("consumed attachment was reusable: %v", err)
	}
	if err := control.ValidateSandbox(binding); !errors.Is(err, ErrSandboxNotAttached) {
		t.Fatalf("detached binding validation = %v", err)
	}
}

func TestActiveAdapterAndCutoverHaveOneOrder(t *testing.T) {
	control, err := Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	certificate, err := control.Compile(requirement("invoice-v1"))
	if err != nil {
		t.Fatal(err)
	}
	release, err := control.BeginAdapterDispatch("payments")
	if err != nil {
		t.Fatal(err)
	}
	binding := testSandboxBinding("vm", 1, "vm-host-1", "payments", "charge")
	if err := control.Cutover(certificate, []SandboxBinding{binding}); !errors.Is(err, ErrActiveAdapterDispatch) {
		release()
		t.Fatalf("cutover during adapter call error = %v", err)
	}
	release()
	if err := control.Cutover(certificate, []SandboxBinding{binding}); err != nil {
		t.Fatal(err)
	}
	if _, err := control.BeginAdapterDispatch("payments"); !errors.Is(err, ErrSandboxBindingRequired) {
		t.Fatalf("bound domain admitted bearer adapter: %v", err)
	}
	if _, _, err := control.OperationForAdapter("payments", "not-registered"); !errors.Is(err, ErrSandboxBindingRequired) {
		t.Fatalf("bound adapter reached absent Operation lookup: %v", err)
	}
	otherRelease, err := control.BeginAdapterDispatch("inventory")
	if err != nil {
		t.Fatalf("unbound domain was rejected: %v", err)
	}
	otherRelease()
}

func TestSandboxResponseLeaseOrdersCutover(t *testing.T) {
	control, err := Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	firstCertificate, err := control.Compile(requirement("invoice-v1"))
	if err != nil {
		t.Fatal(err)
	}
	first := testSandboxBinding("vm", 1, "vm-host-1", "payments", "charge")
	if err := control.Cutover(firstCertificate, []SandboxBinding{first}); err != nil {
		t.Fatal(err)
	}
	if err := control.AttachSandboxHost(first); err != nil {
		t.Fatal(err)
	}
	secondCertificate, err := control.Compile(requirement("invoice-v2"))
	if err != nil {
		t.Fatal(err)
	}
	second := testSandboxBinding("vm", 2, "vm-host-2", "payments", "charge")
	release, err := control.BeginSandboxResponse(first)
	if err != nil {
		t.Fatal(err)
	}
	started := make(chan struct{})
	completed := make(chan error, 1)
	go func() {
		close(started)
		completed <- control.Cutover(secondCertificate, []SandboxBinding{second})
	}()
	<-started
	select {
	case err := <-completed:
		release()
		t.Fatalf("cutover crossed a live response lease: %v", err)
	case <-time.After(50 * time.Millisecond):
	}
	release()
	if err := <-completed; err != nil {
		t.Fatal(err)
	}
	if err := control.ValidateSandbox(first); !errors.Is(err, ErrStaleSandboxBinding) {
		t.Fatalf("old binding after ordered cutover = %v", err)
	}
}

func replacementRequirement(id, kind string) kernel.Requirement {
	return kernel.Requirement{
		ID: id, Results: map[string]uint32{"invoice-paid": 1},
		Capacities: map[string]uint32{"spend": 1},
		Kinds: map[string]kernel.KindSpec{
			kind: {
				Costs: map[string]uint32{"spend": 1}, Produces: map[string]uint32{"invoice-paid": 1},
				RetrySafe: true,
			},
		},
	}
}

func twoChargeRequirement(id string) kernel.Requirement {
	requirement := requirement(id)
	requirement.Results["invoice-paid"] = 2
	requirement.Capacities["spend"] = 2
	return requirement
}

func TestSandboxOperationOwnerRejectsCrossSandboxAccess(t *testing.T) {
	control, err := Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	certificate, err := control.Compile(requirement("sandbox-owner"))
	if err != nil {
		t.Fatal(err)
	}
	first := testSandboxBinding("sandbox-a", 1, "host-a-1", "shared", "charge")
	second := testSandboxBinding("sandbox-b", 1, "host-b-1", "shared", "charge")
	if err := control.Cutover(certificate, []SandboxBinding{first, second}); err != nil {
		t.Fatal(err)
	}
	if err := control.AttachSandboxHosts([]SandboxBinding{first, second}); err != nil {
		t.Fatal(err)
	}
	headers := map[string]string{"Content-Type": "application/json"}
	body := []byte(`{"amount":1}`)
	if _, err := control.PrepareWithRequestForSandbox(
		first, "owned-operation", "charge", "request-hash", headers, body,
	); err != nil {
		t.Fatal(err)
	}
	beforeHead := control.Snapshot().History
	beforeEvents := len(control.Events())

	if _, _, err := control.OperationForSandbox(second, "owned-operation"); err == nil ||
		!strings.Contains(err.Error(), "belongs to sandbox") {
		t.Fatalf("cross-sandbox lookup error=%v", err)
	}
	if _, err := control.PrepareWithRequestForSandbox(
		second, "owned-operation", "charge", "request-hash", headers, body,
	); err == nil || !strings.Contains(err.Error(), "different work") {
		t.Fatalf("cross-sandbox prepare error=%v", err)
	}
	if err := control.MoveForSandbox(second, "owned-operation", kernel.OperationUpdate{
		Phase: kernel.Dispatched, DispatchOwner: "other", DispatchGeneration: 1,
	}); err == nil || !strings.Contains(err.Error(), "belongs to sandbox") {
		t.Fatalf("cross-sandbox move error=%v", err)
	}
	operation := control.Snapshot().Operations["owned-operation"]
	if operation.SandboxID != first.SandboxID || operation.Phase != kernel.Prepared ||
		len(control.Events()) != beforeEvents || control.Snapshot().History != beforeHead {
		t.Fatalf("rejected access changed operation or History: operation=%+v events=%d head=%+v",
			operation, len(control.Events()), control.Snapshot().History)
	}
}

func TestSandboxDomainIsStableAcrossGenerations(t *testing.T) {
	control, err := Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	certificate, err := control.Compile(requirement("stable-domain-v1"))
	if err != nil {
		t.Fatal(err)
	}
	first := testSandboxBinding("vm", 1, "host-1", "payments", "charge")
	if err := control.Cutover(certificate, []SandboxBinding{first}); err != nil {
		t.Fatal(err)
	}
	certificate, err = control.Compile(requirement("stable-domain-v2"))
	if err != nil {
		t.Fatal(err)
	}
	changed := testSandboxBinding("vm", 2, "host-2", "inventory", "charge")
	beforeHead := control.Snapshot().History
	beforeEvents := len(control.Events())
	if err := control.Cutover(certificate, []SandboxBinding{changed}); err == nil ||
		!strings.Contains(err.Error(), "changed stable domain") {
		t.Fatalf("changed sandbox domain error=%v", err)
	}
	bindings := control.SandboxBindings()
	if len(bindings) != 1 || !sandboxBindingEqual(bindings[0], first) ||
		len(control.Events()) != beforeEvents || control.Snapshot().History != beforeHead {
		t.Fatalf("rejected domain change changed state: bindings=%+v events=%d head=%+v",
			bindings, len(control.Events()), control.Snapshot().History)
	}
}

func TestAdapterAndSandboxOperationOwnersAreMutuallyExclusive(t *testing.T) {
	control, err := Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	requirementV1 := twoChargeRequirement("owner-types-v1")
	certificate, err := control.Compile(requirementV1)
	if err != nil {
		t.Fatal(err)
	}
	if err := control.Activate(certificate); err != nil {
		t.Fatal(err)
	}
	if _, err := control.PrepareWithRequest(
		"adapter-operation", "payments", "charge", "adapter-request", nil, []byte(`{"amount":1}`),
	); err != nil {
		t.Fatal(err)
	}

	certificate, err = control.Compile(twoChargeRequirement("owner-types-v2"))
	if err != nil {
		t.Fatal(err)
	}
	binding := testSandboxBinding("vm", 1, "host-1", "payments", "charge")
	if err := control.Cutover(certificate, []SandboxBinding{binding}); err != nil {
		t.Fatal(err)
	}
	if err := control.AttachSandboxHost(binding); err != nil {
		t.Fatal(err)
	}
	if _, _, err := control.OperationForSandbox(binding, "adapter-operation"); err == nil ||
		!strings.Contains(err.Error(), "belongs to sandbox") {
		t.Fatalf("sandbox lookup of adapter operation error=%v", err)
	}
	if _, err := control.PrepareWithRequestForSandbox(
		binding, "sandbox-operation", "charge", "sandbox-request", nil, []byte(`{"amount":2}`),
	); err != nil {
		t.Fatal(err)
	}

	certificate, err = control.Compile(twoChargeRequirement("owner-types-v3"))
	if err != nil {
		t.Fatal(err)
	}
	if err := control.Cutover(certificate, nil); err != nil {
		t.Fatal(err)
	}
	if _, exists, err := control.OperationForAdapter("payments", "adapter-operation"); err != nil || !exists {
		t.Fatalf("adapter could not recover its own operation: exists=%v err=%v", exists, err)
	}
	if _, _, err := control.OperationForAdapter("payments", "sandbox-operation"); err == nil ||
		!strings.Contains(err.Error(), "not an adapter") {
		t.Fatalf("adapter lookup of sandbox operation error=%v", err)
	}
}

func TestSandboxOperationOwnerSurvivesRestartAndGenerationChange(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.history")
	firstControl, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	certificate, err := firstControl.Compile(requirement("restart-owner-v1"))
	if err != nil {
		t.Fatal(err)
	}
	first := testSandboxBinding("sandbox-a", 1, "host-a-1", "shared", "charge")
	if err := firstControl.Cutover(certificate, []SandboxBinding{first}); err != nil {
		t.Fatal(err)
	}
	if err := firstControl.AttachSandboxHost(first); err != nil {
		t.Fatal(err)
	}
	if _, err := firstControl.PrepareWithRequestForSandbox(
		first, "owned-operation", "charge", "request-hash", nil, []byte(`{"amount":1}`),
	); err != nil {
		t.Fatal(err)
	}
	if err := firstControl.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	operation := reopened.Snapshot().Operations["owned-operation"]
	if operation.SandboxID != first.SandboxID {
		t.Fatalf("replayed operation owner=%q, want %q", operation.SandboxID, first.SandboxID)
	}
	certificate, err = reopened.Compile(requirement("restart-owner-v2"))
	if err != nil {
		t.Fatal(err)
	}
	replacement := testSandboxBinding("sandbox-a", 2, "host-a-2", "shared", "charge")
	other := testSandboxBinding("sandbox-b", 1, "host-b-1", "shared", "charge")
	if err := reopened.Cutover(certificate, []SandboxBinding{replacement, other}); err != nil {
		t.Fatal(err)
	}
	if err := reopened.AttachSandboxHosts([]SandboxBinding{replacement, other}); err != nil {
		t.Fatal(err)
	}
	if recovered, exists, err := reopened.OperationForSandbox(replacement, "owned-operation"); err != nil || !exists || recovered.SandboxID != replacement.SandboxID {
		t.Fatalf("replacement generation lookup=%+v exists=%v err=%v", recovered, exists, err)
	}
	if _, _, err := reopened.OperationForSandbox(other, "owned-operation"); err == nil ||
		!strings.Contains(err.Error(), "belongs to sandbox") {
		t.Fatalf("other sandbox lookup after restart error=%v", err)
	}
}

func TestLegacySandboxOperationOwnerReplay(t *testing.T) {
	t.Run("single owner is inferred", func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "runtime.history")
		first, err := Open(path)
		if err != nil {
			t.Fatal(err)
		}
		certificate, err := first.Compile(requirement("legacy-single"))
		if err != nil {
			t.Fatal(err)
		}
		binding := testSandboxBinding("sandbox-a", 1, "host-a-1", "shared", "charge")
		if err := first.Cutover(certificate, []SandboxBinding{binding}); err != nil {
			t.Fatal(err)
		}
		legacy, err := first.PrepareWithRequest(
			"legacy-operation", "shared", "charge", "legacy-request", nil, []byte(`{"amount":1}`),
		)
		if err != nil {
			t.Fatal(err)
		}
		if legacy.SandboxID != "" {
			t.Fatalf("legacy fixture unexpectedly had sandbox owner %q", legacy.SandboxID)
		}
		if err := first.Close(); err != nil {
			t.Fatal(err)
		}

		reopened, err := Open(path)
		if err != nil {
			t.Fatal(err)
		}
		defer reopened.Close()
		replayed := reopened.Snapshot().Operations[legacy.ID]
		if replayed.SandboxID != binding.SandboxID {
			t.Fatalf("inferred legacy owner=%q, want %q", replayed.SandboxID, binding.SandboxID)
		}
	})

	t.Run("multiple owners fail closed", func(t *testing.T) {
		path := filepath.Join(t.TempDir(), "runtime.history")
		first, err := Open(path)
		if err != nil {
			t.Fatal(err)
		}
		certificate, err := first.Compile(requirement("legacy-ambiguous"))
		if err != nil {
			t.Fatal(err)
		}
		bindings := []SandboxBinding{
			testSandboxBinding("sandbox-a", 1, "host-a-1", "shared", "charge"),
			testSandboxBinding("sandbox-b", 1, "host-b-1", "shared", "charge"),
		}
		if err := first.Cutover(certificate, bindings); err != nil {
			t.Fatal(err)
		}
		if _, err := first.PrepareWithRequest(
			"legacy-operation", "shared", "charge", "legacy-request", nil, []byte(`{"amount":1}`),
		); err != nil {
			t.Fatal(err)
		}
		if err := first.Close(); err != nil {
			t.Fatal(err)
		}

		reopened, err := Open(path)
		if reopened != nil {
			_ = reopened.Close()
		}
		if err == nil || !strings.Contains(err.Error(), "multiple sandbox owners") {
			t.Fatalf("ambiguous legacy replay error=%v", err)
		}
	})
}

func TestReplacementBindingCanRecoverFrozenOldKindButCannotCreateIt(t *testing.T) {
	control, err := Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	certificate, err := control.Compile(replacementRequirement("old", "charge-old"))
	if err != nil {
		t.Fatal(err)
	}
	old := testSandboxBinding("vm", 1, "vm-host-1", "payments", "charge-old")
	if err := control.Cutover(certificate, []SandboxBinding{old}); err != nil {
		t.Fatal(err)
	}
	if err := control.AttachSandboxHost(old); err != nil {
		t.Fatal(err)
	}
	headers := map[string]string{"Content-Type": "application/json"}
	body := []byte(`{"amount":1}`)
	if _, err := control.PrepareWithRequestForSandbox(old, "payment-1", "charge-old", "request-1", headers, body); err != nil {
		t.Fatal(err)
	}

	certificate, err = control.Compile(replacementRequirement("new", "charge-new"))
	if err != nil {
		t.Fatal(err)
	}
	fresh := testSandboxBinding("vm", 2, "vm-host-2", "payments", "charge-new")
	if err := control.Cutover(certificate, []SandboxBinding{fresh}); err != nil {
		t.Fatal(err)
	}
	if err := control.AttachSandboxHost(fresh); err != nil {
		t.Fatal(err)
	}
	if _, _, err := control.OperationForSandbox(old, "payment-1"); !errors.Is(err, ErrStaleSandboxBinding) {
		t.Fatalf("old sandbox lookup error = %v", err)
	}
	if _, _, err := control.OperationForSandbox(old, "not-registered"); !errors.Is(err, ErrStaleSandboxBinding) {
		t.Fatalf("stale binding was not rejected before absent Operation lookup: %v", err)
	}
	operation, exists, err := control.OperationForSandbox(fresh, "payment-1")
	if err != nil || !exists || operation.Kind != "charge-old" {
		t.Fatalf("replacement old-kind lookup = %+v, %v, %v", operation, exists, err)
	}
	if _, err := control.PrepareWithRequestForSandbox(
		fresh, "payment-1", "charge-old", "request-1", headers, body,
	); err != nil {
		t.Fatalf("replacement could not recover frozen old kind: %v", err)
	}
	if _, err := control.PrepareWithRequestForSandbox(
		fresh, "payment-2", "charge-old", "request-2", headers, body,
	); err == nil || !strings.Contains(err.Error(), "not allowed") {
		t.Fatalf("replacement created removed kind: %v", err)
	}
	update := kernel.OperationUpdate{
		Phase: kernel.Dispatched, DispatchOwner: control.BootID(), DispatchGeneration: 1,
	}
	if err := control.MoveForSandbox(old, "payment-1", update); !errors.Is(err, ErrStaleSandboxBinding) {
		t.Fatalf("old sandbox dispatch error = %v", err)
	}
	if control.Snapshot().Operations["payment-1"].Phase != kernel.Prepared {
		t.Fatal("stale sandbox changed Operation before rejection")
	}
	if err := control.MoveForSandbox(fresh, "payment-1", update); err != nil {
		t.Fatalf("replacement could not mark old kind dispatched: %v", err)
	}
	if err := control.MoveForSandbox(fresh, "payment-1", kernel.OperationUpdate{Phase: kernel.Unknown}); err == nil {
		t.Fatal("sandbox-bound Move accepted a post-network transition")
	}
}

func TestSandboxDispatchMarkerMakesEarlierCutoverCertificateStale(t *testing.T) {
	control, err := Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	certificate, err := control.Compile(replacementRequirement("old", "charge"))
	if err != nil {
		t.Fatal(err)
	}
	old := testSandboxBinding("vm", 1, "vm-host-1", "payments", "charge")
	if err := control.Cutover(certificate, []SandboxBinding{old}); err != nil {
		t.Fatal(err)
	}
	if err := control.AttachSandboxHost(old); err != nil {
		t.Fatal(err)
	}
	if _, err := control.PrepareWithRequestForSandbox(
		old, "payment-1", "charge", "request-1", nil, []byte(`{"amount":1}`),
	); err != nil {
		t.Fatal(err)
	}
	earlier, err := control.Compile(replacementRequirement("new", "charge"))
	if err != nil {
		t.Fatal(err)
	}
	if err := control.MoveForSandbox(old, "payment-1", kernel.OperationUpdate{
		Phase: kernel.Dispatched, DispatchOwner: "gateway-boot", DispatchGeneration: 1,
	}); err != nil {
		t.Fatal(err)
	}
	fresh := testSandboxBinding("vm", 2, "vm-host-2", "payments", "charge")
	if err := control.Cutover(earlier, []SandboxBinding{fresh}); err == nil || !strings.Contains(err.Error(), "stale") {
		t.Fatalf("pre-dispatch Certificate survived durable dispatch marker: %v", err)
	}
	if err := control.ValidateSandbox(old); err != nil {
		t.Fatalf("failed cutover changed active binding: %v", err)
	}
	if control.Snapshot().Rule.Version != 1 {
		t.Fatal("failed cutover changed active Rule")
	}
}

func TestCutoverReplayRejectsUnknownSemanticVersionWithoutAdvancingAnchor(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.history")
	control, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	activate(t, control, "invoice-v1")
	wantHead := control.Snapshot().History
	if err := control.Close(); err != nil {
		t.Fatal(err)
	}
	record, err := history.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := record.Append(eventRuleBindingsCutover, map[string]any{
		"semantic_version": cutoverSemanticVersion + 1,
		"certificate":      kernel.Certificate{},
		"bindings":         []SandboxBinding{},
	}); err != nil {
		t.Fatal(err)
	}
	if err := record.Close(); err != nil {
		t.Fatal(err)
	}
	if reopened, err := Open(path); err == nil || !strings.Contains(err.Error(), "cutover semantic version") {
		if reopened != nil {
			_ = reopened.Close()
		}
		t.Fatalf("unknown cutover version error = %v", err)
	}
	anchor, err := headanchor.Open(path + ".head-anchor")
	if err != nil {
		t.Fatal(err)
	}
	defer anchor.Close()
	point, err := anchor.Current()
	if err != nil {
		t.Fatal(err)
	}
	if point.Sequence != wantHead.Sequence || point.Hash != wantHead.Hash {
		t.Fatalf("invalid cutover advanced anchor to %+v, want %+v", point, wantHead)
	}
}

func TestSandboxBindingValidationRejectsAmbiguousValues(t *testing.T) {
	tests := []struct {
		name     string
		bindings []SandboxBinding
	}{
		{name: "empty id", bindings: []SandboxBinding{testSandboxBinding("", 1, "host", "vm", "charge")}},
		{name: "zero generation", bindings: []SandboxBinding{testSandboxBinding("vm", 0, "host", "vm", "charge")}},
		{name: "control character", bindings: []SandboxBinding{testSandboxBinding("vm\n", 1, "host", "vm", "charge")}},
		{name: "duplicate kind", bindings: []SandboxBinding{testSandboxBinding("vm", 1, "host", "vm", "charge", "charge")}},
		{name: "duplicate sandbox", bindings: []SandboxBinding{
			testSandboxBinding("vm", 1, "host-1", "vm", "charge"),
			testSandboxBinding("vm", 1, "host-2", "vm", "charge"),
		}},
		{name: "shared host", bindings: []SandboxBinding{
			testSandboxBinding("vm-a", 1, "host", "a", "charge"),
			testSandboxBinding("vm-b", 1, "host", "b", "charge"),
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if _, err := canonicalSandboxBindings(test.bindings); err == nil {
				t.Fatalf("accepted bindings: %+v", test.bindings)
			}
		})
	}
}

func TestReplayRejectsNoncanonicalCutoverBindings(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.history")
	control, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	certificate, err := control.Compile(requirement("invoice-v1"))
	if err != nil {
		t.Fatal(err)
	}
	if err := control.Close(); err != nil {
		t.Fatal(err)
	}
	record, err := history.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	data, err := json.Marshal(ruleBindingsCutoverEvent{
		SemanticVersion: cutoverSemanticVersion,
		Certificate:     certificate,
		Bindings: []SandboxBinding{
			testSandboxBinding("z", 1, "host-z", "z", "tip", "charge"),
			testSandboxBinding("a", 1, "host-a", "a", "charge"),
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := record.AppendJSON(eventRuleBindingsCutover, data); err != nil {
		t.Fatal(err)
	}
	if err := record.Close(); err != nil {
		t.Fatal(err)
	}
	if reopened, err := Open(path); err == nil || !strings.Contains(err.Error(), "canonical order") {
		if reopened != nil {
			_ = reopened.Close()
		}
		t.Fatalf("noncanonical replay error = %v", err)
	}
}
