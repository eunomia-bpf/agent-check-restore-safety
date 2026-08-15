package certcheck_test

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"go/parser"
	"go/token"
	"math/rand"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/certcheck"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

func requirement(id string, required, capacity uint32) kernel.Requirement {
	return kernel.Requirement{
		ID:         id,
		Results:    map[string]uint32{"done": required},
		Capacities: map[string]uint32{"slot": capacity},
		Kinds: map[string]kernel.KindSpec{
			"finish": {
				Costs:     map[string]uint32{"slot": 1},
				Produces:  map[string]uint32{"done": 1},
				RetrySafe: true,
			},
			"waste": {
				Costs:     map[string]uint32{"slot": 1},
				Produces:  map[string]uint32{"wasted": 1},
				RetrySafe: true,
			},
		},
	}
}

func mustJSON(t *testing.T, value any) []byte {
	t.Helper()
	encoded, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return encoded
}

type projectedFacts struct {
	Used               map[string]uint64 `json:"used"`
	Results            map[string]uint32 `json:"results"`
	UndeclaredResource string            `json:"undeclared_resource,omitempty"`
}

type projectedOperation struct {
	ID        string            `json:"id"`
	Costs     map[string]uint32 `json:"costs"`
	Produces  map[string]uint32 `json:"produces"`
	RetrySafe bool              `json:"retry_safe"`
	Queryable bool              `json:"queryable,omitempty"`
}

type projectedState struct {
	Schema         int                           `json:"schema"`
	History        kernel.HistoryPoint           `json:"history"`
	FromRule       uint64                        `json:"from_rule"`
	Settled        projectedFacts                `json:"settled"`
	OpenOperations map[string]projectedOperation `json:"open_operations"`
}

func projectedStateJSON(t *testing.T, state *kernel.State, target kernel.Requirement) []byte {
	t.Helper()
	fromRule := uint64(0)
	if state.Rule != nil {
		fromRule = state.Rule.Version
	}
	projection := projectedState{
		Schema: certcheck.StateSchema, History: state.History, FromRule: fromRule,
		Settled:        projectedFacts{Used: make(map[string]uint64), Results: make(map[string]uint32)},
		OpenOperations: make(map[string]projectedOperation),
	}
	ids := make([]string, 0, len(state.Operations))
	for id := range state.Operations {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	addSettled := func(operation kernel.Operation) {
		for resource, amount := range operation.Costs {
			if _, declared := target.Capacities[resource]; !declared {
				if amount != 0 && (projection.Settled.UndeclaredResource == "" || resource < projection.Settled.UndeclaredResource) {
					projection.Settled.UndeclaredResource = resource
				}
				continue
			}
			projection.Settled.Used[resource] += uint64(amount)
		}
		for result, amount := range operation.Produces {
			need, required := target.Results[result]
			if !required || projection.Settled.Results[result] >= need {
				continue
			}
			if amount >= need-projection.Settled.Results[result] {
				projection.Settled.Results[result] = need
			} else {
				projection.Settled.Results[result] += amount
			}
		}
	}
	for _, id := range ids {
		operation := state.Operations[id]
		switch operation.Phase {
		case kernel.Succeeded:
			addSettled(operation)
		case kernel.Prepared:
			if !operation.RetrySafe && !operation.Queryable {
				continue
			}
			fallthrough
		case kernel.Dispatched, kernel.Unknown:
			projection.OpenOperations[id] = projectedOperation{
				ID: operation.ID, Costs: operation.Costs,
				Produces: operation.Produces, RetrySafe: operation.RetrySafe,
				Queryable: operation.Queryable,
			}
		case kernel.Failed, kernel.Cancelled:
		default:
			t.Fatalf("invalid phase in test State: %q", operation.Phase)
		}
	}
	return mustJSON(t, projection)
}

func check(t *testing.T, state *kernel.State, certificate kernel.Certificate) certcheck.Verdict {
	t.Helper()
	verdict, err := certcheck.CheckJSON(projectedStateJSON(t, state, certificate.Requirement), mustJSON(t, certificate))
	if err != nil {
		t.Fatal(err)
	}
	return verdict
}

func resign(t *testing.T, value *kernel.Certificate) {
	t.Helper()
	value.Digest = ""
	encoded := mustJSON(t, value)
	digest := sha256.Sum256(encoded)
	value.Digest = hex.EncodeToString(digest[:])
}

func TestAcceptsCompilerActivationAndImpossibility(t *testing.T) {
	state := kernel.NewState()
	activation, err := kernel.Compile(state, requirement("initial", 1, 1), 1)
	if err != nil {
		t.Fatal(err)
	}
	verdict := check(t, state, activation)
	if !verdict.Valid || verdict.Decision != "activate" || verdict.RuleVersion != 1 {
		t.Fatalf("unexpected activation verdict: %+v", verdict)
	}
	if err := state.Activate(activation); err != nil {
		t.Fatal(err)
	}
	state.Operations["unrecoverable"] = kernel.Operation{
		ID:          "unrecoverable",
		Domain:      "legacy-service",
		Kind:        "legacy-charge",
		RequestHash: "request",
		Costs:       map[string]uint32{"slot": 1},
		Produces:    map[string]uint32{"other": 1},
		Phase:       kernel.Unknown,
	}
	impossibility, err := kernel.Compile(state, requirement("replacement", 1, 1), 2)
	if err != nil {
		t.Fatal(err)
	}
	verdict = check(t, state, impossibility)
	if !verdict.Valid || verdict.Decision != "impossible" || verdict.RuleVersion != 0 {
		t.Fatalf("unexpected impossibility verdict: %+v", verdict)
	}
	forged := impossibility
	witness := *impossibility.Witness
	witness.OpenSucceeded = append([]string(nil), impossibility.Witness.OpenSucceeded...)
	witness.Reason += " (forged)"
	forged.Witness = &witness
	resign(t, &forged)
	if _, err := certcheck.CheckJSON(projectedStateJSON(t, state, forged.Requirement), mustJSON(t, forged)); err == nil || !strings.Contains(err.Error(), "independent exact recomputation") {
		t.Fatalf("forged Impossible witness was not rejected: %v", err)
	}
}

func TestRejectsSemanticallyForgedCertificatesWithValidDigest(t *testing.T) {
	state := kernel.NewState()
	valid, err := kernel.Compile(state, requirement("target", 1, 1), 1)
	if err != nil {
		t.Fatal(err)
	}
	tests := []struct {
		name   string
		mutate func(*kernel.Certificate)
	}{
		{
			name: "remove safe kind",
			mutate: func(value *kernel.Certificate) {
				value.Rule.Allow = nil
			},
		},
		{
			name: "add unsafe kind",
			mutate: func(value *kernel.Certificate) {
				value.Rule.Allow = []string{"finish", "waste"}
			},
		},
		{
			name: "claim impossible",
			mutate: func(value *kernel.Certificate) {
				value.Decision = kernel.Impossible
				value.Rule = nil
				value.Witness = &kernel.Witness{Reason: "invented obstruction"}
			},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			forged := valid
			if valid.Rule != nil {
				rule := *valid.Rule
				rule.Allow = append([]string(nil), valid.Rule.Allow...)
				forged.Rule = &rule
			}
			test.mutate(&forged)
			resign(t, &forged)
			if _, err := certcheck.CheckJSON(projectedStateJSON(t, state, forged.Requirement), mustJSON(t, forged)); err == nil || !strings.Contains(err.Error(), "independent exact recomputation") {
				t.Fatalf("semantically forged Certificate was not rejected: %v", err)
			}
		})
	}
}

func TestRejectsStaleAndMalformedState(t *testing.T) {
	state := kernel.NewState()
	certificate, err := kernel.Compile(state, requirement("target", 1, 1), 1)
	if err != nil {
		t.Fatal(err)
	}
	stale := state.Clone()
	stale.History = kernel.HistoryPoint{Sequence: 1, Hash: strings.Repeat("1", 64)}
	if _, err := certcheck.CheckJSON(projectedStateJSON(t, stale, certificate.Requirement), mustJSON(t, certificate)); err == nil || !strings.Contains(err.Error(), "stale") {
		t.Fatalf("stale Certificate was not rejected: %v", err)
	}

	malformed := state.Clone()
	malformed.Operations["map-key"] = kernel.Operation{
		ID:          "different-id",
		Domain:      "service",
		Kind:        "finish",
		RequestHash: "request",
		Produces:    map[string]uint32{"done": 1},
		RetrySafe:   true,
		Phase:       kernel.Unknown,
	}
	if _, err := certcheck.CheckJSON(projectedStateJSON(t, malformed, certificate.Requirement), mustJSON(t, certificate)); err == nil || !strings.Contains(err.Error(), "differs from identity") {
		t.Fatalf("malformed Operation identity was not rejected: %v", err)
	}
}

func TestRejectsDuplicateJSONKeysAtEveryDepth(t *testing.T) {
	state := kernel.NewState()
	certificate, err := kernel.Compile(state, requirement("target", 1, 1), 1)
	if err != nil {
		t.Fatal(err)
	}
	stateJSON := projectedStateJSON(t, state, certificate.Requirement)
	duplicateState := bytes.Replace(stateJSON, []byte(`{"schema":1,`), []byte(`{"schema":1,"schema":1,`), 1)
	if _, err := certcheck.CheckJSON(duplicateState, mustJSON(t, certificate)); err == nil || !strings.Contains(err.Error(), "duplicate key") {
		t.Fatalf("duplicate top-level State key was not rejected: %v", err)
	}
	certificateJSON := mustJSON(t, certificate)
	duplicateCertificate := bytes.Replace(certificateJSON,
		[]byte(`"id":"target",`), []byte(`"id":"target","id":"target",`), 1)
	if _, err := certcheck.CheckJSON(stateJSON, duplicateCertificate); err == nil || !strings.Contains(err.Error(), "duplicate key") {
		t.Fatalf("duplicate nested Certificate key was not rejected: %v", err)
	}
}

func TestCertificateBindsFrozenOperationMeaning(t *testing.T) {
	state := kernel.NewState()
	state.Operations["open"] = kernel.Operation{
		ID: "open", Domain: "service", Kind: "finish", RequestHash: "request",
		Costs: map[string]uint32{"slot": 1}, Produces: map[string]uint32{"done": 1},
		RetrySafe: true, Phase: kernel.Unknown,
	}
	certificate, err := kernel.Compile(state, requirement("target", 1, 2), 1)
	if err != nil {
		t.Fatal(err)
	}
	check(t, state, certificate)

	mutated := state.Clone()
	operation := mutated.Operations["open"]
	operation.Costs["slot"] = 2
	mutated.Operations["open"] = operation
	if _, err := certcheck.CheckJSON(projectedStateJSON(t, mutated, certificate.Requirement), mustJSON(t, certificate)); err == nil || !strings.Contains(err.Error(), "independent exact recomputation") {
		t.Fatalf("Certificate survived changed frozen Operation meaning: %v", err)
	}
}

func TestCheckerAcceptsQueryableRecoveryAndBindsProjection(t *testing.T) {
	target := kernel.Requirement{
		ID: "queryable-target", Results: map[string]uint32{"done": 1},
		Capacities: map[string]uint32{"slot": 1},
		Kinds: map[string]kernel.KindSpec{
			"finish": {
				Costs: map[string]uint32{"slot": 1}, Produces: map[string]uint32{"done": 1},
				Queryable: true, Target: "http://effect.example", Method: "POST",
				ResponseClassifier: kernel.ResponseReceiptV1,
				QueryTarget:        "http://observer.example", QueryMethod: "POST",
				QueryClassifier: kernel.OperationObservationV1,
			},
		},
	}
	state := kernel.NewState()
	state.Operations["open"] = kernel.Operation{
		ID: "open", Domain: "service", Kind: "finish", RequestHash: "request",
		Costs: map[string]uint32{"slot": 1}, Produces: map[string]uint32{"done": 1},
		Queryable: true, Phase: kernel.Unknown,
	}
	certificate, err := kernel.Compile(state, target, 1)
	if err != nil {
		t.Fatal(err)
	}
	if certificate.Decision != kernel.Activate {
		t.Fatalf("queryable Operation was treated as unrecoverable: %+v", certificate)
	}
	check(t, state, certificate)

	var projection map[string]any
	if err := json.Unmarshal(projectedStateJSON(t, state, target), &projection); err != nil {
		t.Fatal(err)
	}
	open := projection["open_operations"].(map[string]any)
	item := open["open"].(map[string]any)
	delete(item, "queryable")
	forged := mustJSON(t, projection)
	if _, err := certcheck.CheckJSON(forged, mustJSON(t, certificate)); err == nil || !strings.Contains(err.Error(), "independent exact recomputation") {
		t.Fatalf("checker ignored removed queryability: %v", err)
	}
}

func TestCompilerCheckerAgreementAcrossSmallModels(t *testing.T) {
	phases := []kernel.Phase{kernel.Prepared, kernel.Unknown, kernel.Succeeded, kernel.Failed}
	for required := uint32(1); required <= 2; required++ {
		for capacity := uint32(0); capacity <= 3; capacity++ {
			for operationCount := 0; operationCount <= 2; operationCount++ {
				combinations := 1
				for index := 0; index < operationCount; index++ {
					combinations *= len(phases) * 2
				}
				for code := 0; code < combinations; code++ {
					state := kernel.NewState()
					remaining := code
					for index := 0; index < operationCount; index++ {
						choice := remaining % (len(phases) * 2)
						remaining /= len(phases) * 2
						phase := phases[choice/2]
						retrySafe := choice%2 == 1
						id := fmt.Sprintf("op-%d", index)
						operation := kernel.Operation{
							ID: id, Domain: "test", Kind: "finish", RequestHash: "request-" + id,
							Costs: map[string]uint32{"slot": 1}, Produces: map[string]uint32{"done": 1},
							RetrySafe: retrySafe, Phase: phase,
						}
						if phase == kernel.Succeeded || phase == kernel.Failed {
							operation.ResultHash = "result-" + id
						}
						state.Operations[id] = operation
					}
					target := requirement(fmt.Sprintf("r-%d-%d-%d-%d", required, capacity, operationCount, code), required, capacity)
					certificate, err := kernel.Compile(state, target, 1)
					if err != nil {
						t.Fatalf("compiler rejected bounded case: %v", err)
					}
					if _, err := certcheck.CheckJSON(projectedStateJSON(t, state, certificate.Requirement), mustJSON(t, certificate)); err != nil {
						t.Fatalf("checker disagreed for required=%d capacity=%d operations=%d code=%d Certificate=%+v: %v", required, capacity, operationCount, code, certificate, err)
					}
				}
			}
		}
	}
}

func TestCompilerCheckerAgreementAcrossDeterministicRandomModels(t *testing.T) {
	random := rand.New(rand.NewSource(0x5eedcafe))
	phases := []kernel.Phase{
		kernel.Prepared, kernel.Dispatched, kernel.Unknown,
		kernel.Succeeded, kernel.Failed, kernel.Cancelled,
	}
	for trial := 0; trial < 500; trial++ {
		resultCount := 1 + random.Intn(3)
		resourceCount := random.Intn(3)
		kindCount := resultCount + random.Intn(3)
		target := kernel.Requirement{
			ID:         fmt.Sprintf("random-%03d", trial),
			Results:    make(map[string]uint32, resultCount),
			Capacities: make(map[string]uint32, resourceCount),
			Kinds:      make(map[string]kernel.KindSpec, kindCount),
		}
		for index := 0; index < resultCount; index++ {
			target.Results[fmt.Sprintf("result-%d", index)] = uint32(1 + random.Intn(3))
		}
		for index := 0; index < resourceCount; index++ {
			target.Capacities[fmt.Sprintf("resource-%d", index)] = uint32(random.Intn(6))
		}
		for index := 0; index < kindCount; index++ {
			producedResult := fmt.Sprintf("result-%d", index%resultCount)
			spec := kernel.KindSpec{
				Costs:     make(map[string]uint32),
				Produces:  map[string]uint32{producedResult: uint32(1 + random.Intn(2))},
				RetrySafe: random.Intn(4) != 0,
			}
			for resourceIndex := 0; resourceIndex < resourceCount; resourceIndex++ {
				if random.Intn(2) == 0 {
					spec.Costs[fmt.Sprintf("resource-%d", resourceIndex)] = uint32(1 + random.Intn(2))
				}
			}
			if resultCount > 1 && random.Intn(3) == 0 {
				extra := fmt.Sprintf("result-%d", random.Intn(resultCount))
				spec.Produces[extra] = uint32(1 + random.Intn(2))
			}
			target.Kinds[fmt.Sprintf("kind-%d", index)] = spec
		}

		state := kernel.NewState()
		operationCount := random.Intn(4)
		kindNames := make([]string, 0, len(target.Kinds))
		for name := range target.Kinds {
			kindNames = append(kindNames, name)
		}
		sort.Strings(kindNames)
		for index := 0; index < operationCount; index++ {
			kind := kindNames[random.Intn(len(kindNames))]
			spec := target.Kinds[kind]
			phase := phases[random.Intn(len(phases))]
			id := fmt.Sprintf("operation-%d", index)
			operation := kernel.Operation{
				ID: id, Domain: "random-test", Kind: kind, RequestHash: "request-" + id,
				Costs: make(map[string]uint32, len(spec.Costs)), Produces: make(map[string]uint32, len(spec.Produces)),
				RetrySafe: spec.RetrySafe, Queryable: spec.Queryable, Phase: phase,
			}
			for name, amount := range spec.Costs {
				operation.Costs[name] = amount
			}
			for name, amount := range spec.Produces {
				operation.Produces[name] = amount
			}
			if phase == kernel.Succeeded || phase == kernel.Failed {
				operation.ResultHash = "result-" + id
			}
			state.Operations[id] = operation
		}
		certificate, err := kernel.Compile(state, target, 1)
		if err != nil {
			t.Fatalf("trial %d compiler error: %v", trial, err)
		}
		if _, err := certcheck.CheckJSON(projectedStateJSON(t, state, certificate.Requirement), mustJSON(t, certificate)); err != nil {
			t.Fatalf("trial %d checker disagreement: %v\nCertificate=%+v\nState=%+v", trial, err, certificate, state)
		}
	}
}

func TestSolverBudgetDomainMatchesCompilerAtAdversarialBoundary(t *testing.T) {
	target := kernel.Requirement{
		ID:         "solver-domain-boundary",
		Results:    map[string]uint32{"done": kernel.MaxRequiredUnits},
		Capacities: make(map[string]uint32, kernel.MaxRequirementResources),
		Kinds:      make(map[string]kernel.KindSpec, kernel.MaxRequirementResources),
	}
	for index := 0; index < kernel.MaxRequirementResources; index++ {
		resource := fmt.Sprintf("resource-%02d", index)
		kind := fmt.Sprintf("kind-%02d", index)
		target.Capacities[resource] = kernel.MaxRequiredUnits
		target.Kinds[kind] = kernel.KindSpec{
			Costs:    map[string]uint32{resource: 1},
			Produces: map[string]uint32{"done": 1}, RetrySafe: true,
		}
	}
	state := kernel.NewState()
	certificate, err := kernel.Compile(state, target, 1)
	if err != nil {
		t.Fatal(err)
	}
	if certificate.Decision != kernel.Activate || len(certificate.Rule.Allow) != kernel.MaxRequirementResources {
		t.Fatalf("compiler did not admit boundary model: %+v", certificate)
	}
	if _, err := certcheck.CheckJSON(projectedStateJSON(t, state, target), mustJSON(t, certificate)); err != nil {
		t.Fatalf("iterative checker has a narrower resource domain: %v", err)
	}
}

func TestResourceLimitCannotMasqueradeAsImpossibility(t *testing.T) {
	state := kernel.NewState()
	target := requirement("oversized", certcheck.MaxRequiredUnits+1, certcheck.MaxRequiredUnits+1)
	forged := kernel.Certificate{
		Schema: certcheck.CertificateSchema, Decision: kernel.Impossible,
		History: state.History, Requirement: target,
		Witness: &kernel.Witness{Reason: "not a semantic proof"},
	}
	resign(t, &forged)
	_, err := certcheck.CheckJSON(projectedStateJSON(t, state, forged.Requirement), mustJSON(t, forged))
	if !errors.Is(err, certcheck.ErrResourceLimit) {
		t.Fatalf("oversized model did not fail as a resource error: %v", err)
	}
}

func TestProductionPackageImportsOnlyStandardLibrary(t *testing.T) {
	_, filename, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot locate checker source")
	}
	directory := filepath.Dir(filename)
	files, err := filepath.Glob(filepath.Join(directory, "*.go"))
	if err != nil {
		t.Fatal(err)
	}
	for _, filename := range files {
		if strings.HasSuffix(filename, "_test.go") {
			continue
		}
		parsed, err := parser.ParseFile(token.NewFileSet(), filename, nil, parser.ImportsOnly)
		if err != nil {
			t.Fatal(err)
		}
		for _, imported := range parsed.Imports {
			path, err := strconv.Unquote(imported.Path.Value)
			if err != nil {
				t.Fatal(err)
			}
			first := strings.Split(path, "/")[0]
			if strings.Contains(first, ".") || path == "C" {
				t.Errorf("production checker imports non-standard package %q in %s", path, filepath.Base(filename))
			}
		}
	}
	if _, err := os.Stat(filepath.Join(directory, "check.go")); err != nil {
		t.Fatal(err)
	}
}
