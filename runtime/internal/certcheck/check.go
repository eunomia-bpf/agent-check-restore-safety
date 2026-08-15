package certcheck

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"reflect"
	"sort"
	"strconv"
	"strings"
)

const emptyHistoryHash = "0000000000000000000000000000000000000000000000000000000000000000"

type analysisBudget struct {
	completionChecks uint64
	expandedStates   uint64
}

func (b *analysisBudget) beginCompletion() error {
	b.completionChecks++
	if b.completionChecks > MaxCompletionChecks {
		return resourceLimit("completion checks", MaxCompletionChecks, b.completionChecks)
	}
	return nil
}

func (b *analysisBudget) expandState(depth uint64) error {
	if depth > MaxSolverDepth {
		return resourceLimit("solver depth", MaxSolverDepth, depth)
	}
	b.expandedStates++
	if b.expandedStates > MaxSolverStates {
		return resourceLimit("expanded solver states", MaxSolverStates, b.expandedStates)
	}
	return nil
}

type facts struct {
	used               map[string]uint64
	results            map[string]uint32
	undeclaredResource string
}

func cloneUint64Map(input map[string]uint64) map[string]uint64 {
	output := make(map[string]uint64, len(input))
	for key, value := range input {
		output[key] = value
	}
	return output
}

func cloneFacts(input facts) facts {
	return facts{
		used: cloneUint64Map(input.used), results: cloneMap(input.results),
		undeclaredResource: input.undeclaredResource,
	}
}

func sortedKeys[V any](values map[string]V) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

// addSuccess independently applies the answer-preserving projection used by
// the runtime: declared resource use remains exact, required results saturate
// at their lower bound, and only the canonical first undeclared resource name
// is retained.
func addSuccess(target *facts, requirement requirement, costs, produces map[string]uint32) error {
	for resource, amount := range costs {
		if _, declared := requirement.Capacities[resource]; !declared {
			if amount != 0 && (target.undeclaredResource == "" || resource < target.undeclaredResource) {
				target.undeclaredResource = resource
			}
			continue
		}
		current := target.used[resource]
		if math.MaxUint64-current < uint64(amount) {
			return resourceLimit(fmt.Sprintf("aggregate resource counter %q", resource), math.MaxUint64, math.MaxUint64)
		}
		target.used[resource] = current + uint64(amount)
	}
	for result, amount := range produces {
		need, required := requirement.Results[result]
		if !required {
			continue
		}
		current := target.results[result]
		if current >= need {
			continue
		}
		if amount >= need-current {
			target.results[result] = need
		} else {
			target.results[result] = current + amount
		}
	}
	return nil
}

func validateHistory(value historyPoint) error {
	if !validDigest(value.Hash) {
		return errors.New("History hash is not a canonical SHA-256 digest")
	}
	if value.Sequence == 0 && value.Hash != emptyHistoryHash {
		return errors.New("empty History has a nonempty hash")
	}
	if value.Sequence != 0 && value.Hash == emptyHistoryHash {
		return errors.New("nonempty History has the empty hash")
	}
	return nil
}

func validateOperation(key string, value operation) error {
	if key == "" || value.ID == "" {
		return errors.New("Operation identity is empty")
	}
	if key != value.ID {
		return fmt.Errorf("Operation map key %q differs from identity %q", key, value.ID)
	}
	if len(value.ID) > MaxNameBytes {
		return resourceLimit("Operation identity bytes", MaxNameBytes, uint64(len(value.ID)))
	}
	if len(value.Costs) > MaxRequirementResources {
		return resourceLimit(fmt.Sprintf("operation %q cost dimensions", key), MaxRequirementResources, uint64(len(value.Costs)))
	}
	if len(value.Produces) == 0 {
		return fmt.Errorf("Operation %q produces no result", key)
	}
	if len(value.Produces) > MaxOperationResults {
		return resourceLimit(fmt.Sprintf("operation %q result dimensions", key), MaxOperationResults, uint64(len(value.Produces)))
	}
	for resource, amount := range value.Costs {
		if resource == "" || amount == 0 {
			return fmt.Errorf("Operation %q has an invalid frozen cost", key)
		}
		if len(resource) > MaxNameBytes {
			return resourceLimit(fmt.Sprintf("operation %q resource name bytes", key), MaxNameBytes, uint64(len(resource)))
		}
		if amount > MaxModelValue {
			return resourceLimit(fmt.Sprintf("operation %q cost %q", key, resource), MaxModelValue, uint64(amount))
		}
	}
	for result, amount := range value.Produces {
		if result == "" || amount == 0 {
			return fmt.Errorf("Operation %q has an invalid frozen result", key)
		}
		if len(result) > MaxNameBytes {
			return resourceLimit(fmt.Sprintf("operation %q result name bytes", key), MaxNameBytes, uint64(len(result)))
		}
		if amount > MaxModelValue {
			return resourceLimit(fmt.Sprintf("operation %q production %q", key, result), MaxModelValue, uint64(amount))
		}
	}
	return nil
}

func validateState(value state) error {
	if value.Schema != StateSchema {
		return fmt.Errorf("unsupported State schema %d", value.Schema)
	}
	if err := validateHistory(value.History); err != nil {
		return err
	}
	if value.FromRule == math.MaxUint64 {
		return errors.New("active Rule version cannot advance")
	}
	if value.Settled.Used == nil || value.Settled.Results == nil {
		return errors.New("State has incomplete settled facts")
	}
	if len(value.Settled.Used) > MaxRequirementResources {
		return resourceLimit("settled resource dimensions", MaxRequirementResources, uint64(len(value.Settled.Used)))
	}
	if len(value.Settled.Results) > MaxRequirementResults {
		return resourceLimit("settled result dimensions", MaxRequirementResults, uint64(len(value.Settled.Results)))
	}
	for resource := range value.Settled.Used {
		if resource == "" {
			return errors.New("State has an empty settled resource")
		}
		if len(resource) > MaxNameBytes {
			return resourceLimit("settled resource name bytes", MaxNameBytes, uint64(len(resource)))
		}
	}
	for result := range value.Settled.Results {
		if result == "" {
			return errors.New("State has an empty settled result")
		}
		if len(result) > MaxNameBytes {
			return resourceLimit("settled result name bytes", MaxNameBytes, uint64(len(result)))
		}
	}
	if len(value.Settled.UndeclaredResource) > MaxNameBytes {
		return resourceLimit("undeclared resource name bytes", MaxNameBytes, uint64(len(value.Settled.UndeclaredResource)))
	}
	if value.OpenOperations == nil {
		return errors.New("State has no open Operation map")
	}
	if len(value.OpenOperations) > MaxOpenOperations {
		return resourceLimit("open operations", MaxOpenOperations, uint64(len(value.OpenOperations)))
	}
	for _, key := range sortedKeys(value.OpenOperations) {
		if err := validateOperation(key, value.OpenOperations[key]); err != nil {
			return err
		}
	}
	return nil
}

func validateProjection(value state, target requirement) error {
	for resource := range value.Settled.Used {
		if _, declared := target.Capacities[resource]; !declared {
			return fmt.Errorf("settled resource %q is not declared by the target Requirement", resource)
		}
	}
	for result, amount := range value.Settled.Results {
		need, required := target.Results[result]
		if !required {
			return fmt.Errorf("settled result %q is not required by the target Requirement", result)
		}
		if amount > need {
			return fmt.Errorf("settled result %q is not saturated at its target lower bound", result)
		}
	}
	if value.Settled.UndeclaredResource != "" {
		if _, declared := target.Capacities[value.Settled.UndeclaredResource]; declared {
			return errors.New("State marks a declared resource as undeclared")
		}
	}
	return nil
}

func baseAndOpen(value state) (facts, []operation) {
	base := facts{
		used: cloneUint64Map(value.Settled.Used), results: cloneMap(value.Settled.Results),
		undeclaredResource: value.Settled.UndeclaredResource,
	}
	open := make([]operation, 0, len(value.OpenOperations))
	for _, id := range sortedKeys(value.OpenOperations) {
		open = append(open, value.OpenOperations[id])
	}
	return base, open
}

// completionExists uses an explicit depth-first stack over deficit/capacity
// vectors. It is independent code, but follows the compiler's canonical
// first-missing-result and sorted-kind order so both exact implementations
// have the same public resource acceptance domain.
func completionExists(target requirement, start facts, budget *analysisBudget) (bool, string, error) {
	if err := budget.beginCompletion(); err != nil {
		return false, "", err
	}
	if start.undeclaredResource != "" {
		return false, fmt.Sprintf("history uses resource %q absent from the target requirement", start.undeclaredResource), nil
	}
	for _, resource := range sortedKeys(start.used) {
		used := start.used[resource]
		capacity, declared := target.Capacities[resource]
		if !declared {
			return false, fmt.Sprintf("history uses resource %q absent from the target requirement", resource), nil
		}
		if used > uint64(capacity) {
			return false, fmt.Sprintf("resource %q already uses %d above capacity %d", resource, used, capacity), nil
		}
	}

	resultNames := sortedKeys(target.Results)
	resourceNames := sortedKeys(target.Capacities)
	kindNames := sortedKeys(target.Kinds)
	initialDeficit := make([]uint32, len(resultNames))
	initialRemaining := make([]uint32, len(resourceNames))
	missing := make([]string, 0)
	for index, name := range resultNames {
		need := target.Results[name]
		have := start.results[name]
		if have < need {
			initialDeficit[index] = need - have
			missing = append(missing, fmt.Sprintf("%s:%d", name, need-have))
		}
	}
	for index, name := range resourceNames {
		initialRemaining[index] = target.Capacities[name] - uint32(start.used[name])
	}
	if len(missing) == 0 {
		return true, "", nil
	}

	encode := func(deficit, remaining []uint32) string {
		var builder strings.Builder
		for _, value := range deficit {
			builder.WriteString(strconv.FormatUint(uint64(value), 10))
			builder.WriteByte(',')
		}
		builder.WriteByte('|')
		for _, value := range remaining {
			builder.WriteString(strconv.FormatUint(uint64(value), 10))
			builder.WriteByte(',')
		}
		return builder.String()
	}
	type frame struct {
		deficit     []uint32
		remaining   []uint32
		key         string
		first       int
		nextKind    int
		initialized bool
	}
	stack := []frame{{deficit: initialDeficit, remaining: initialRemaining}}
	failed := make(map[string]bool)
	for len(stack) != 0 {
		current := &stack[len(stack)-1]
		if !current.initialized {
			current.first = -1
			for index, amount := range current.deficit {
				if amount != 0 {
					current.first = index
					break
				}
			}
			if current.first == -1 {
				return true, "", nil
			}
			current.key = encode(current.deficit, current.remaining)
			if failed[current.key] {
				stack = stack[:len(stack)-1]
				continue
			}
			if err := budget.expandState(uint64(len(stack) - 1)); err != nil {
				return false, "", err
			}
			current.initialized = true
		}
		if current.nextKind == len(kindNames) {
			failed[current.key] = true
			stack = stack[:len(stack)-1]
			continue
		}
		kind := kindNames[current.nextKind]
		current.nextKind++
		spec := target.Kinds[kind]
		if (!spec.RetrySafe && !spec.Queryable) || spec.Produces[resultNames[current.first]] == 0 {
			continue
		}
		nextRemaining := append([]uint32(nil), current.remaining...)
		fits := true
		for index, resource := range resourceNames {
			cost := spec.Costs[resource]
			if cost > nextRemaining[index] {
				fits = false
				break
			}
			nextRemaining[index] -= cost
		}
		if !fits {
			continue
		}
		nextDeficit := append([]uint32(nil), current.deficit...)
		for index, result := range resultNames {
			produced := spec.Produces[result]
			if produced >= nextDeficit[index] {
				nextDeficit[index] = 0
			} else {
				nextDeficit[index] -= produced
			}
		}
		stack = append(stack, frame{deficit: nextDeficit, remaining: nextRemaining})
	}
	return false, "no completion fits the remaining resources for " + strings.Join(missing, ","), nil
}

type scenario struct {
	facts     facts
	succeeded []string
}

func enumerateScenarios(value state, target requirement) ([]scenario, error) {
	base, open := baseAndOpen(value)
	count := 1 << uint(len(open))
	if count > MaxScenarioCount {
		return nil, resourceLimit("scenarios", MaxScenarioCount, uint64(count))
	}
	all := make([]scenario, 0, count)
	for mask := 0; mask < count; mask++ {
		current := cloneFacts(base)
		ids := make([]string, 0)
		for index, item := range open {
			if mask&(1<<index) == 0 {
				continue
			}
			if err := addSuccess(&current, target, item.Costs, item.Produces); err != nil {
				return nil, err
			}
			ids = append(ids, item.ID)
		}
		all = append(all, scenario{facts: current, succeeded: ids})
	}
	return all, nil
}

func computeAllowed(value state, target requirement) ([]string, *witness, error) {
	all, err := enumerateScenarios(value, target)
	if err != nil {
		return nil, nil, err
	}
	for _, id := range sortedKeys(value.OpenOperations) {
		item := value.OpenOperations[id]
		if !item.RetrySafe && !item.Queryable {
			return nil, &witness{
				OpenSucceeded: []string{id},
				Reason:        fmt.Sprintf("operation %q is open and has no implemented safe recovery", id),
			}, nil
		}
	}
	recoverableKinds := 0
	for _, spec := range target.Kinds {
		if spec.RetrySafe || spec.Queryable {
			recoverableKinds++
		}
	}
	plannedChecks := uint64(len(all)) * uint64(recoverableKinds+1)
	if plannedChecks > MaxCompletionChecks {
		return nil, nil, resourceLimit("completion checks", MaxCompletionChecks, plannedChecks)
	}
	budget := &analysisBudget{}
	for _, current := range all {
		ok, reason, err := completionExists(target, current.facts, budget)
		if err != nil {
			return nil, nil, err
		}
		if !ok {
			return nil, &witness{OpenSucceeded: current.succeeded, Reason: reason}, nil
		}
	}
	allowed := make([]string, 0, len(target.Kinds))
	for _, name := range sortedKeys(target.Kinds) {
		spec := target.Kinds[name]
		if !spec.RetrySafe && !spec.Queryable {
			continue
		}
		safe := true
		for _, current := range all {
			afterSuccess := cloneFacts(current.facts)
			if err := addSuccess(&afterSuccess, target, spec.Costs, spec.Produces); err != nil {
				return nil, nil, err
			}
			ok, _, err := completionExists(target, afterSuccess, budget)
			if err != nil {
				return nil, nil, err
			}
			if !ok {
				safe = false
				break
			}
		}
		if safe {
			allowed = append(allowed, name)
		}
	}
	return allowed, nil, nil
}

func recompute(value state, target requirement) (certificate, error) {
	if err := validateRequirement(target); err != nil {
		return certificate{}, err
	}
	if err := validateProjection(value, target); err != nil {
		return certificate{}, err
	}
	target = cloneRequirement(target)
	allow, obstruction, err := computeAllowed(value, target)
	if err != nil {
		return certificate{}, err
	}
	result := certificate{
		Schema: CertificateSchema, History: value.History,
		FromRule: value.FromRule, Requirement: target,
	}
	if obstruction != nil {
		result.Decision = impossible
		result.Witness = obstruction
	} else {
		hash, err := requirementHash(target)
		if err != nil {
			return certificate{}, err
		}
		result.Decision = activate
		result.Rule = &rule{Version: value.FromRule + 1, RequirementHash: hash, Allow: allow}
	}
	digest, err := certificateDigest(result)
	if err != nil {
		return certificate{}, err
	}
	result.Digest = digest
	return result, nil
}

// CheckJSON verifies a Certificate against a versioned, answer-preserving
// State projection. It does not mutate State and shares no compiler/runtime
// implementation code. The verdict is conditional on the projection being
// derived from the History point it names; the standalone checker does not
// replay History or read an external head anchor.
func CheckJSON(stateJSON, certificateJSON []byte) (Verdict, error) {
	var suppliedState state
	if err := decodeStrict(stateJSON, &suppliedState); err != nil {
		return Verdict{}, fmt.Errorf("decode State: %w", err)
	}
	var supplied certificate
	if err := decodeStrict(certificateJSON, &supplied); err != nil {
		return Verdict{}, fmt.Errorf("decode Certificate: %w", err)
	}
	if err := validateState(suppliedState); err != nil {
		return Verdict{}, fmt.Errorf("invalid State: %w", err)
	}
	if supplied.Schema != CertificateSchema {
		return Verdict{}, fmt.Errorf("unsupported Certificate schema %d", supplied.Schema)
	}
	if !validDigest(supplied.Digest) {
		return Verdict{}, errors.New("Certificate digest is not a canonical SHA-256 digest")
	}
	digest, err := certificateDigest(supplied)
	if err != nil {
		return Verdict{}, err
	}
	if digest != supplied.Digest {
		return Verdict{}, errors.New("Certificate digest mismatch")
	}
	if supplied.History != suppliedState.History {
		return Verdict{}, errors.New("Certificate is stale for the current History")
	}
	if supplied.FromRule != suppliedState.FromRule {
		return Verdict{}, errors.New("Certificate names a different active Rule")
	}
	expected, err := recompute(suppliedState, supplied.Requirement)
	if err != nil {
		return Verdict{}, err
	}
	left, err := json.Marshal(supplied)
	if err != nil {
		return Verdict{}, err
	}
	right, err := json.Marshal(expected)
	if err != nil {
		return Verdict{}, err
	}
	if !reflect.DeepEqual(left, right) {
		return Verdict{}, errors.New("Certificate differs from independent exact recomputation")
	}
	verdict := Verdict{
		Valid: true, Decision: string(supplied.Decision),
		Sequence: supplied.History.Sequence, HistoryHash: supplied.History.Hash,
	}
	if supplied.Rule != nil {
		verdict.RuleVersion = supplied.Rule.Version
	}
	return verdict, nil
}
