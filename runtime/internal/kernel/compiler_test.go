package kernel

import (
	"errors"
	"fmt"
	"strings"
	"testing"
)

func invoiceRequirement(id string) Requirement {
	return Requirement{
		ID: id,
		Results: map[string]uint32{
			"invoice-paid": 1,
		},
		Capacities: map[string]uint32{
			"spend": 1,
		},
		Kinds: map[string]KindSpec{
			"charge-invoice": {
				Costs:     map[string]uint32{"spend": 1},
				Produces:  map[string]uint32{"invoice-paid": 1},
				RetrySafe: true,
			},
			"send-tip": {
				Costs:    map[string]uint32{"spend": 1},
				Produces: map[string]uint32{"tip-sent": 1},
			},
		},
	}
}

func activateInitial(t *testing.T, state *State, requirement Requirement) Certificate {
	t.Helper()
	certificate, err := Compile(state, requirement, 1)
	if err != nil {
		t.Fatal(err)
	}
	if certificate.Decision != Activate {
		t.Fatalf("unexpected decision: %+v", certificate)
	}
	if err := state.Activate(certificate); err != nil {
		t.Fatal(err)
	}
	return certificate
}

func TestPolicyCompliantOperationCanStillBeBlocked(t *testing.T) {
	state := NewState()
	requirement := invoiceRequirement("invoice-v1")
	certificate := activateInitial(t, state, requirement)
	if len(certificate.Rule.Allow) != 1 || certificate.Rule.Allow[0] != "charge-invoice" {
		t.Fatalf("unexpected maximal initial rule: %+v", certificate.Rule.Allow)
	}

	// A tip consumes no more than the declared capacity and is individually
	// well-formed, but allowing it would make invoice-paid impossible.
	_, err := state.Prepare("tip-1", "microservice", "send-tip", "request-tip")
	if err == nil || !strings.Contains(err.Error(), "without a completion") {
		t.Fatalf("expected non-stranding rejection, got %v", err)
	}
	if _, err := state.Prepare("charge-1", "microservice", "charge-invoice", "request-charge"); err != nil {
		t.Fatal(err)
	}
	if len(state.Rule.Allow) != 0 {
		t.Fatalf("active Rule view was not refreshed: %+v", state.Rule.Allow)
	}
}

func TestStableIdentityCannotBeRebound(t *testing.T) {
	state := NewState()
	activateInitial(t, state, invoiceRequirement("invoice-v1"))
	first, err := state.Prepare("charge-1", "agent", "charge-invoice", "request-a")
	if err != nil {
		t.Fatal(err)
	}
	second, err := state.Prepare("charge-1", "agent", "charge-invoice", "request-a")
	if err != nil {
		t.Fatal(err)
	}
	if first.ID != second.ID || len(state.Operations) != 1 {
		t.Fatalf("stable retry created another operation: %+v %+v", first, second)
	}
	if _, err := state.Prepare("charge-1", "agent", "charge-invoice", "request-b"); err == nil {
		t.Fatal("rebound operation identity was accepted")
	}
}

func TestUnknownOperationIsConsideredInEveryOutcome(t *testing.T) {
	state := NewState()
	activateInitial(t, state, invoiceRequirement("invoice-v1"))
	if _, err := state.Prepare("charge-1", "vm", "charge-invoice", "request-charge"); err != nil {
		t.Fatal(err)
	}
	if err := state.MoveOperation("charge-1", OperationUpdate{Phase: Dispatched, RemoteReference: "remote-7", DispatchOwner: "boot-a", DispatchGeneration: 1}); err != nil {
		t.Fatal(err)
	}
	if err := state.MoveOperation("charge-1", OperationUpdate{Phase: Unknown, RemoteReference: "remote-7"}); err != nil {
		t.Fatal(err)
	}

	next := invoiceRequirement("invoice-v2")
	certificate, err := Compile(state, next, 2)
	if err != nil {
		t.Fatal(err)
	}
	if certificate.Decision != Activate {
		t.Fatalf("both success and failure remain recoverable: %+v", certificate)
	}
	if len(certificate.Rule.Allow) != 0 {
		t.Fatalf("a duplicate charge was enabled while the first result is unknown: %+v", certificate.Rule.Allow)
	}
	if err := state.CanPrepare("charge-invoice"); err == nil {
		t.Fatal("a second charge was enabled under an unknown first outcome")
	}
}

func TestImpossibleChangeHasCheckableWitness(t *testing.T) {
	state := NewState()
	activateInitial(t, state, invoiceRequirement("invoice-v1"))
	if _, err := state.Prepare("tip-legacy", "agent", "send-tip", "request-tip"); err == nil {
		// The active rule correctly blocks this path, so construct the durable
		// fact as if it came from an older, less restrictive rule.
		t.Fatal("tip unexpectedly passed the active rule")
	}
	state.Operations["tip-legacy"] = Operation{
		ID:          "tip-legacy",
		Domain:      "agent",
		Kind:        "send-tip",
		RequestHash: "request-tip",
		RuleVersion: 0,
		Costs:       map[string]uint32{"spend": 1},
		Produces:    map[string]uint32{"tip-sent": 1},
		Phase:       Unknown,
	}

	certificate, err := Compile(state, invoiceRequirement("invoice-v2"), 2)
	if err != nil {
		t.Fatal(err)
	}
	if certificate.Decision != Impossible || certificate.Witness == nil {
		t.Fatalf("expected impossibility certificate, got %+v", certificate)
	}
	if err := VerifyCertificate(state, certificate); err != nil {
		t.Fatalf("independent recomputation rejected witness: %v", err)
	}
	if err := state.Activate(certificate); err == nil {
		t.Fatal("an impossible change was activated")
	}
}

func TestHiddenWorldPlansDoNotCountAsOneRuntimeRule(t *testing.T) {
	state := NewState()
	activateInitial(t, state, invoiceRequirement("invoice-v1"))
	state.Operations["legacy-charge"] = Operation{
		ID:          "legacy-charge",
		Domain:      "vm",
		Kind:        "charge-invoice",
		RequestHash: "legacy-request",
		RuleVersion: 0,
		Costs:       map[string]uint32{"spend": 1},
		Produces:    map[string]uint32{"invoice-paid": 1},
		RetrySafe:   false,
		Phase:       Unknown,
	}
	certificate, err := Compile(state, invoiceRequirement("invoice-v2"), 2)
	if err != nil {
		t.Fatal(err)
	}
	if certificate.Decision != Impossible || certificate.Witness == nil {
		t.Fatalf("indistinguishable remote outcomes were accepted: %+v", certificate)
	}
	if !strings.Contains(certificate.Witness.Reason, "no implemented safe recovery") {
		t.Fatalf("unexpected witness: %+v", certificate.Witness)
	}
}

func TestCertificateBindsFullHistoryProgress(t *testing.T) {
	state := NewState()
	activateInitial(t, state, invoiceRequirement("invoice-v1"))
	state.History = HistoryPoint{Sequence: 7, Hash: "history-seven"}
	certificate, err := Compile(state, invoiceRequirement("invoice-v2"), 2)
	if err != nil {
		t.Fatal(err)
	}

	// Dispatch progress changes the complete execution record even though no
	// authorization fact changed.
	state.History = HistoryPoint{Sequence: 8, Hash: "history-eight"}
	if err := VerifyCertificate(state, certificate); err == nil || !strings.Contains(err.Error(), "stale") {
		t.Fatalf("stale certificate was not rejected: %v", err)
	}
}

func TestCertificateTamperFails(t *testing.T) {
	state := NewState()
	certificate := activateInitial(t, state, invoiceRequirement("invoice-v1"))
	certificate.Requirement.Capacities["spend"] = 2
	if err := VerifyCertificate(state, certificate); err == nil {
		t.Fatal("tampered certificate was accepted")
	}
}

func TestOperationProgressRefreshesCurrentRule(t *testing.T) {
	state := NewState()
	activateInitial(t, state, invoiceRequirement("invoice-v1"))
	if _, err := state.Prepare("charge-1", "service", "charge-invoice", "request"); err != nil {
		t.Fatal(err)
	}
	if err := state.MoveOperation("charge-1", OperationUpdate{Phase: Succeeded, ResultHash: "result", RemoteReference: "remote"}); err == nil {
		t.Fatal("operation settled before dispatch")
	}
	if err := state.MoveOperation("charge-1", OperationUpdate{Phase: Dispatched, RemoteReference: "remote", DispatchOwner: "boot-a", DispatchGeneration: 1}); err != nil {
		t.Fatal(err)
	}
	if err := state.MoveOperation("charge-1", OperationUpdate{Phase: Failed, ResultHash: "failed-result", RemoteReference: "remote"}); err != nil {
		t.Fatal(err)
	}
	if len(state.Rule.Allow) != 1 || state.Rule.Allow[0] != "charge-invoice" {
		t.Fatalf("failed operation did not reopen the required action: %+v", state.Rule.Allow)
	}
}

func TestMultiResultOperationCanBeOnlyCompletion(t *testing.T) {
	state := NewState()
	requirement := Requirement{
		ID:         "provision-v1",
		Results:    map[string]uint32{"vm-ready": 1, "service-ready": 1},
		Capacities: map[string]uint32{"slot": 1},
		Kinds: map[string]KindSpec{
			"provision-stack": {
				Costs:     map[string]uint32{"slot": 1},
				Produces:  map[string]uint32{"vm-ready": 1, "service-ready": 1},
				RetrySafe: true,
			},
		},
	}
	certificate := activateInitial(t, state, requirement)
	if len(certificate.Rule.Allow) != 1 || certificate.Rule.Allow[0] != "provision-stack" {
		t.Fatalf("unexpected rule: %+v", certificate.Rule)
	}
}

func boundedRequirement(resultCount, kindCount int, requiredUnits uint32) Requirement {
	results := make(map[string]uint32, resultCount)
	produces := make(map[string]uint32, resultCount)
	for index := 0; index < resultCount; index++ {
		name := fmt.Sprintf("result-%02d", index)
		count := uint32(1)
		if index == 0 {
			count = requiredUnits
		}
		results[name] = count
		produces[name] = count
	}
	kinds := make(map[string]KindSpec, kindCount)
	for index := 0; index < kindCount; index++ {
		kinds[fmt.Sprintf("kind-%02d", index)] = KindSpec{
			Produces:  cloneMap(produces),
			RetrySafe: true,
		}
	}
	return Requirement{ID: "bounded", Results: results, Kinds: kinds}
}

func addOpenOperations(state *State, count int) {
	for index := 0; index < count; index++ {
		id := fmt.Sprintf("open-%02d", index)
		state.Operations[id] = Operation{
			ID:          id,
			Domain:      "test",
			Kind:        "finish",
			RequestHash: id,
			Produces:    map[string]uint32{"done": 1},
			RetrySafe:   true,
			Phase:       Unknown,
		}
	}
}

func openRequirement(kindCount int) Requirement {
	kinds := make(map[string]KindSpec, kindCount)
	for index := 0; index < kindCount; index++ {
		kinds[fmt.Sprintf("finish-%02d", index)] = KindSpec{
			Produces:  map[string]uint32{"done": 1},
			RetrySafe: true,
		}
	}
	return Requirement{
		ID:      "open-worlds",
		Results: map[string]uint32{"done": 1},
		Kinds:   kinds,
	}
}

func TestRequirementResourceBoundsAcceptBoundary(t *testing.T) {
	state := NewState()
	requirement := boundedRequirement(MaxRequirementResults, 1, 1)
	requirement.Capacities = map[string]uint32{"largest": MaxModelValue}
	spec := requirement.Kinds["kind-00"]
	spec.Costs = map[string]uint32{"largest": MaxModelValue}
	requirement.Kinds["kind-00"] = spec
	certificate, err := Compile(state, requirement, 1)
	if err != nil {
		t.Fatalf("boundary requirement was rejected: %v", err)
	}
	if certificate.Decision != Activate {
		t.Fatalf("boundary requirement did not produce an activation: %+v", certificate)
	}

	deep := boundedRequirement(1, 1, MaxRequiredUnits)
	deepSpec := deep.Kinds["kind-00"]
	deepSpec.Produces["result-00"] = 1
	deep.Kinds["kind-00"] = deepSpec
	if _, err := Compile(NewState(), deep, 1); err != nil {
		t.Fatalf("maximum bounded deficit was rejected: %v", err)
	}
}

func TestRequirementResourceBoundsRejectExcess(t *testing.T) {
	tests := []struct {
		name        string
		requirement Requirement
	}{
		{
			name:        "result dimensions",
			requirement: boundedRequirement(MaxRequirementResults+1, 1, 1),
		},
		{
			name:        "required units",
			requirement: boundedRequirement(1, 1, MaxRequiredUnits+1),
		},
		{
			name: "numeric value",
			requirement: Requirement{
				ID:         "too-large",
				Results:    map[string]uint32{"done": 1},
				Capacities: map[string]uint32{"resource": MaxModelValue + 1},
				Kinds: map[string]KindSpec{
					"finish": {Costs: map[string]uint32{"resource": 1}, Produces: map[string]uint32{"done": 1}, RetrySafe: true},
				},
			},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			certificate, err := Compile(NewState(), test.requirement, 1)
			if !errors.Is(err, ErrResourceLimit) {
				t.Fatalf("expected resource-limit error, got certificate=%+v error=%v", certificate, err)
			}
			if certificate.Decision != "" || certificate.Digest != "" {
				t.Fatalf("resource exhaustion produced a certificate: %+v", certificate)
			}
		})
	}
}

func TestOpenOperationBoundAndCompletionBudget(t *testing.T) {
	boundary := NewState()
	addOpenOperations(boundary, MaxOpenOperations)
	certificate, err := Compile(boundary, openRequirement(1), 1)
	if err != nil || certificate.Decision != Activate {
		t.Fatalf("open-operation boundary failed: certificate=%+v error=%v", certificate, err)
	}

	over := NewState()
	addOpenOperations(over, MaxOpenOperations+1)
	first := over.Operations["open-00"]
	first.RetrySafe = false // Must not mask the model-size error as Impossible.
	over.Operations[first.ID] = first
	certificate, err = Compile(over, openRequirement(1), 1)
	if !errors.Is(err, ErrResourceLimit) || certificate.Decision != "" {
		t.Fatalf("open-operation excess was not a resource error: certificate=%+v error=%v", certificate, err)
	}

	wide := NewState()
	addOpenOperations(wide, 10)
	certificate, err = Compile(wide, openRequirement(MaxRequirementKinds), 1)
	if !errors.Is(err, ErrResourceLimit) || certificate.Decision != "" {
		t.Fatalf("completion-check excess was not a resource error: certificate=%+v error=%v", certificate, err)
	}
}

func TestResourceLimitCannotValidateAsImpossibleCertificate(t *testing.T) {
	state := NewState()
	oversized := boundedRequirement(MaxRequirementResults+1, 1, 1)
	certificate := Certificate{
		Schema:      CertificateSchema,
		Decision:    Impossible,
		History:     state.History,
		Requirement: oversized,
		Witness:     &Witness{Reason: "forged semantic impossibility"},
	}
	digest, err := certificateDigest(certificate)
	if err != nil {
		t.Fatal(err)
	}
	certificate.Digest = digest
	if err := VerifyCertificate(state, certificate); !errors.Is(err, ErrResourceLimit) {
		t.Fatalf("oversized impossible certificate did not fail as a resource error: %v", err)
	}
}

func TestAggregateCounterOverflowIsResourceError(t *testing.T) {
	facts := facts{
		used:    map[string]uint32{"resource": ^uint32(0)},
		results: map[string]uint32{"done": ^uint32(0)},
	}
	if err := addSuccess(&facts, map[string]uint32{"resource": 1}, nil); !errors.Is(err, ErrResourceLimit) {
		t.Fatalf("resource counter overflow was not typed: %v", err)
	}
	if err := addSuccess(&facts, nil, map[string]uint32{"done": 1}); !errors.Is(err, ErrResourceLimit) {
		t.Fatalf("result counter overflow was not typed: %v", err)
	}
}

func TestUnsupportedHTTPClassifierCannotBecomeACompletion(t *testing.T) {
	requirement := invoiceRequirement("unsupported-adapter")
	spec := requirement.Kinds["charge-invoice"]
	spec.Target = "https://payments.invalid/charge"
	spec.Method = "POST"
	spec.ResponseClassifier = "status-is-truth"
	requirement.Kinds["charge-invoice"] = spec
	certificate, err := Compile(NewState(), requirement, 1)
	if err == nil || certificate.Decision != "" {
		t.Fatalf("unsupported classifier produced certificate=%+v error=%v", certificate, err)
	}
}
