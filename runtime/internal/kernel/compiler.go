package kernel

import (
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"sort"
	"strconv"
	"strings"
)

const (
	// These bounds are part of the exact compiler's public resource contract.
	// They keep malformed or simply oversized models from turning exponential
	// search or large integer deficits into an unbounded kernel operation.
	MaxRequirementResults   = 16
	MaxRequirementResources = 16
	MaxRequirementKinds     = 64
	MaxOperationResults     = 32
	MaxNameBytes            = 256
	MaxRequiredUnits        = 256
	MaxModelValue           = 1_000_000
	MaxTrackedOperations    = 16_384
	MaxOpenOperations       = 12
	MaxScenarioCount        = 1 << MaxOpenOperations
	MaxCompletionChecks     = 32_768
	MaxSolverStates         = 100_000
	MaxSolverDepth          = MaxRequiredUnits
)

var ErrResourceLimit = errors.New("kernel exact-analysis resource limit")

// ResourceLimitError is distinct from a semantic impossibility witness. A
// caller may retry with a smaller model or a different solver, but must never
// encode this error as an Impossible Certificate.
type ResourceLimitError struct {
	Resource string
	Limit    uint64
	Actual   uint64
}

func (e *ResourceLimitError) Error() string {
	return fmt.Sprintf("%s: %s is %d, limit is %d", ErrResourceLimit, e.Resource, e.Actual, e.Limit)
}

func (e *ResourceLimitError) Unwrap() error { return ErrResourceLimit }

func resourceLimit(resource string, limit, actual uint64) error {
	return &ResourceLimitError{Resource: resource, Limit: limit, Actual: actual}
}

type analysisBudget struct {
	completionChecks uint64
	solverStates     uint64
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
		return resourceLimit("solver recursion depth", MaxSolverDepth, depth)
	}
	b.solverStates++
	if b.solverStates > MaxSolverStates {
		return resourceLimit("expanded solver states", MaxSolverStates, b.solverStates)
	}
	return nil
}

type facts struct {
	used               map[string]uint64
	results            map[string]uint32
	undeclaredResource string
}

func emptyFacts() facts {
	return facts{used: make(map[string]uint64), results: make(map[string]uint32)}
}

func cloneFacts(in facts) facts {
	used := make(map[string]uint64, len(in.used))
	for resource, amount := range in.used {
		used[resource] = amount
	}
	return facts{
		used: used, results: cloneMap(in.results),
		undeclaredResource: in.undeclaredResource,
	}
}

// addSuccess retains only distinctions that can change the answer for r.
// Resource use stays exact; required results saturate at their lower bound;
// extra results are irrelevant. For undeclared resources, only the canonical
// first name is needed because any positive use already makes completion fail.
func addSuccess(f *facts, r Requirement, costs, produces map[string]uint32) error {
	for resource, amount := range costs {
		if _, declared := r.Capacities[resource]; !declared {
			if amount != 0 && (f.undeclaredResource == "" || resource < f.undeclaredResource) {
				f.undeclaredResource = resource
			}
			continue
		}
		current := f.used[resource]
		f.used[resource] = current + uint64(amount)
	}
	for result, amount := range produces {
		need, required := r.Results[result]
		if !required {
			continue
		}
		current := f.results[result]
		if current >= need {
			continue
		}
		if amount >= need-current {
			f.results[result] = need
		} else {
			f.results[result] = current + amount
		}
	}
	return nil
}

func baseAndOpen(state *State, target Requirement) (facts, []Operation, error) {
	if len(state.Operations) > MaxTrackedOperations {
		return facts{}, nil, resourceLimit(
			"tracked operations", MaxTrackedOperations, uint64(len(state.Operations)),
		)
	}
	base := emptyFacts()
	open := make([]Operation, 0)
	ids := sortedKeys(state.Operations)
	for _, id := range ids {
		op := state.Operations[id]
		if len(op.Costs) > MaxRequirementResources {
			return facts{}, nil, resourceLimit(
				fmt.Sprintf("operation %q cost dimensions", id),
				MaxRequirementResources,
				uint64(len(op.Costs)),
			)
		}
		if len(op.Produces) > MaxOperationResults {
			return facts{}, nil, resourceLimit(
				fmt.Sprintf("operation %q result dimensions", id),
				MaxOperationResults,
				uint64(len(op.Produces)),
			)
		}
		for resource, amount := range op.Costs {
			if amount > MaxModelValue {
				return facts{}, nil, resourceLimit(
					fmt.Sprintf("operation %q cost %q", id, resource),
					MaxModelValue,
					uint64(amount),
				)
			}
		}
		for result, amount := range op.Produces {
			if amount > MaxModelValue {
				return facts{}, nil, resourceLimit(
					fmt.Sprintf("operation %q production %q", id, result),
					MaxModelValue,
					uint64(amount),
				)
			}
		}
		switch op.Phase {
		case Succeeded:
			if err := addSuccess(&base, target, op.Costs, op.Produces); err != nil {
				return facts{}, nil, err
			}
		case Prepared:
			// A prepared action has not crossed the external boundary. The
			// current gateway can dispatch it only when stable retry is
			// available; otherwise it remains safely cancellable.
			if op.RetrySafe {
				open = append(open, op)
			}
		case Dispatched, Unknown:
			open = append(open, op)
		case Failed, Cancelled:
		default:
			return facts{}, nil, fmt.Errorf("operation %q has invalid phase %q", id, op.Phase)
		}
	}
	if len(open) > MaxOpenOperations {
		return facts{}, nil, resourceLimit(
			"open operations", MaxOpenOperations, uint64(len(open)),
		)
	}
	return base, open, nil
}

// completionPlan checks whether some multiset of the declared operation kinds
// can satisfy every missing result without exceeding a resource capacity.
// This is deliberately exact for the bounded integer model; it is not a
// heuristic packer.
func completionPlan(r Requirement, start facts, budget *analysisBudget) (bool, string, error) {
	if err := budget.beginCompletion(); err != nil {
		return false, "", err
	}
	if start.undeclaredResource != "" {
		return false, fmt.Sprintf("history uses resource %q absent from the target requirement", start.undeclaredResource), nil
	}
	// Witnesses are part of the signed Certificate in schema 1. Choose the
	// first violated resource canonically so identical inputs cannot produce
	// different diagnostic text and digests through Go map iteration order.
	for _, resource := range sortedKeys(start.used) {
		used := start.used[resource]
		capacity, declared := r.Capacities[resource]
		if !declared {
			return false, fmt.Sprintf("history uses resource %q absent from the target requirement", resource), nil
		}
		if used > uint64(capacity) {
			return false, fmt.Sprintf("resource %q already uses %d above capacity %d", resource, used, capacity), nil
		}
	}
	resultNames := sortedKeys(r.Results)
	resourceNames := sortedKeys(r.Capacities)
	kindNames := sortedKeys(r.Kinds)
	deficit := make([]uint32, len(resultNames))
	remaining := make([]uint32, len(resourceNames))
	for index, name := range resultNames {
		need := r.Results[name]
		have := start.results[name]
		if have < need {
			deficit[index] = need - have
		}
	}
	for index, name := range resourceNames {
		remaining[index] = r.Capacities[name] - uint32(start.used[name])
	}

	encode := func(d, c []uint32) string {
		var b strings.Builder
		for _, value := range d {
			b.WriteString(strconv.FormatUint(uint64(value), 10))
			b.WriteByte(',')
		}
		b.WriteByte('|')
		for _, value := range c {
			b.WriteString(strconv.FormatUint(uint64(value), 10))
			b.WriteByte(',')
		}
		return b.String()
	}

	memo := make(map[string]bool)
	visiting := make(map[string]bool)
	var solve func([]uint32, []uint32, uint64) (bool, error)
	solve = func(d, capacity []uint32, depth uint64) (bool, error) {
		first := -1
		for index, value := range d {
			if value != 0 {
				first = index
				break
			}
		}
		if first == -1 {
			return true, nil
		}
		key := encode(d, capacity)
		if value, ok := memo[key]; ok {
			return value, nil
		}
		if visiting[key] {
			return false, nil
		}
		if err := budget.expandState(depth); err != nil {
			return false, err
		}
		visiting[key] = true
		target := resultNames[first]
		for _, kind := range kindNames {
			spec := r.Kinds[kind]
			// Milestone zero has a stable-retry HTTP adapter but no trusted
			// query adapter. A kind without safe retry is therefore not an
			// executable completion, even if its success branch would fit.
			if !spec.RetrySafe {
				continue
			}
			if spec.Produces[target] == 0 {
				continue
			}
			fits := true
			nextCapacity := append([]uint32(nil), capacity...)
			for index, resource := range resourceNames {
				cost := spec.Costs[resource]
				if cost > nextCapacity[index] {
					fits = false
					break
				}
				nextCapacity[index] -= cost
			}
			if !fits {
				continue
			}
			nextDeficit := append([]uint32(nil), d...)
			for index, result := range resultNames {
				produced := spec.Produces[result]
				if produced >= nextDeficit[index] {
					nextDeficit[index] = 0
				} else {
					nextDeficit[index] -= produced
				}
			}
			resolved, err := solve(nextDeficit, nextCapacity, depth+1)
			if err != nil {
				delete(visiting, key)
				return false, err
			}
			if resolved {
				delete(visiting, key)
				memo[key] = true
				return true, nil
			}
		}
		delete(visiting, key)
		memo[key] = false
		return false, nil
	}

	resolved, err := solve(deficit, remaining, 0)
	if err != nil {
		return false, "", err
	}
	if resolved {
		return true, "", nil
	}
	missing := make([]string, 0)
	for index, count := range deficit {
		if count != 0 {
			missing = append(missing, fmt.Sprintf("%s:%d", resultNames[index], count))
		}
	}
	return false, "no completion fits the remaining resources for " + strings.Join(missing, ","), nil
}

type scenario struct {
	facts     facts
	succeeded []string
}

func scenarios(state *State, target Requirement) ([]scenario, error) {
	base, open, err := baseAndOpen(state, target)
	if err != nil {
		return nil, err
	}
	count := 1 << uint(len(open))
	if count > MaxScenarioCount {
		return nil, resourceLimit("scenarios", MaxScenarioCount, uint64(count))
	}
	result := make([]scenario, 0, count)
	for mask := 0; mask < count; mask++ {
		current := cloneFacts(base)
		ids := make([]string, 0)
		for index, op := range open {
			if mask&(1<<index) == 0 {
				continue
			}
			if err := addSuccess(&current, target, op.Costs, op.Produces); err != nil {
				return nil, err
			}
			ids = append(ids, op.ID)
		}
		result = append(result, scenario{facts: current, succeeded: ids})
	}
	return result, nil
}

func allowedKinds(state *State, r Requirement) ([]string, *Witness, error) {
	// Validate and bound the complete model before deriving any semantic
	// witness. Otherwise an early impossible case could mask an oversized input.
	all, err := scenarios(state, r)
	if err != nil {
		return nil, nil, err
	}
	for _, id := range sortedKeys(state.Operations) {
		op := state.Operations[id]
		if (op.Phase == Dispatched || op.Phase == Unknown) && !op.RetrySafe {
			return nil, &Witness{
				OpenSucceeded: []string{id},
				Reason:        fmt.Sprintf("operation %q is open and has no implemented safe recovery", id),
			}, nil
		}
	}
	retryKinds := 0
	for _, spec := range r.Kinds {
		if spec.RetrySafe {
			retryKinds++
		}
	}
	plannedChecks := uint64(len(all)) * uint64(retryKinds+1)
	if plannedChecks > MaxCompletionChecks {
		return nil, nil, resourceLimit("completion checks", MaxCompletionChecks, plannedChecks)
	}
	budget := &analysisBudget{}
	for _, current := range all {
		ok, reason, err := completionPlan(r, current.facts, budget)
		if err != nil {
			return nil, nil, err
		}
		if !ok {
			return nil, &Witness{OpenSucceeded: current.succeeded, Reason: reason}, nil
		}
	}
	allowed := make([]string, 0, len(r.Kinds))
	for _, kind := range sortedKeys(r.Kinds) {
		spec := r.Kinds[kind]
		if !spec.RetrySafe {
			continue
		}
		safe := true
		for _, current := range all {
			success := cloneFacts(current.facts)
			if err := addSuccess(&success, r, spec.Costs, spec.Produces); err != nil {
				return nil, nil, err
			}
			ok, _, err := completionPlan(r, success, budget)
			if err != nil {
				return nil, nil, err
			}
			if !ok {
				safe = false
				break
			}
		}
		if safe {
			allowed = append(allowed, kind)
		}
	}
	return allowed, nil, nil
}

func Compile(state *State, requirement Requirement, nextVersion uint64) (Certificate, error) {
	if state == nil {
		return Certificate{}, errors.New("nil state")
	}
	if err := ValidateRequirement(requirement); err != nil {
		return Certificate{}, err
	}
	fromRule := uint64(0)
	if state.Rule != nil {
		fromRule = state.Rule.Version
	}
	if nextVersion != fromRule+1 {
		return Certificate{}, fmt.Errorf("next rule version must be %d", fromRule+1)
	}
	requirement = cloneRequirement(requirement)
	allow, witness, err := allowedKinds(state, requirement)
	if err != nil {
		return Certificate{}, err
	}
	certificate := Certificate{
		Schema:      CertificateSchema,
		History:     state.History,
		FromRule:    fromRule,
		Requirement: requirement,
	}
	if witness != nil {
		certificate.Decision = Impossible
		certificate.Witness = witness
	} else {
		hash, err := RequirementHash(requirement)
		if err != nil {
			return Certificate{}, err
		}
		certificate.Decision = Activate
		certificate.Rule = &Rule{Version: nextVersion, RequirementHash: hash, Allow: allow}
	}
	digest, err := certificateDigest(certificate)
	if err != nil {
		return Certificate{}, err
	}
	certificate.Digest = digest
	return certificate, nil
}

func VerifyCertificate(state *State, certificate Certificate) error {
	if state == nil {
		return errors.New("nil state")
	}
	if certificate.Schema != CertificateSchema {
		return fmt.Errorf("unsupported certificate schema %d", certificate.Schema)
	}
	digest, err := certificateDigest(certificate)
	if err != nil {
		return err
	}
	if digest != certificate.Digest {
		return errors.New("certificate digest mismatch")
	}
	if certificate.History != state.History {
		return errors.New("certificate is stale for the current history")
	}
	fromRule := uint64(0)
	if state.Rule != nil {
		fromRule = state.Rule.Version
	}
	if certificate.FromRule != fromRule {
		return errors.New("certificate names a different active rule")
	}
	recomputed, err := Compile(state, certificate.Requirement, fromRule+1)
	if err != nil {
		return err
	}
	left, err := json.Marshal(certificate)
	if err != nil {
		return err
	}
	right, err := json.Marshal(recomputed)
	if err != nil {
		return err
	}
	if !reflect.DeepEqual(left, right) {
		return errors.New("certificate differs from exact recomputation")
	}
	return nil
}

func (s *State) Activate(c Certificate) error {
	if err := VerifyCertificate(s, c); err != nil {
		return err
	}
	if c.Decision != Activate || c.Rule == nil {
		return errors.New("certificate proves that the change is impossible")
	}
	requirement := cloneRequirement(c.Requirement)
	rule := *c.Rule
	rule.Allow = append([]string(nil), c.Rule.Allow...)
	sort.Strings(rule.Allow)
	s.Requirement = &requirement
	s.Rule = &rule
	return nil
}

func (s *State) CanPrepare(kind string) error {
	if s.Requirement == nil || s.Rule == nil {
		return errors.New("no active rule")
	}
	hash, err := RequirementHash(*s.Requirement)
	if err != nil {
		return err
	}
	if hash != s.Rule.RequirementHash {
		return errors.New("active rule and requirement disagree")
	}
	allow, witness, err := allowedKinds(s, *s.Requirement)
	if err != nil {
		return err
	}
	if witness != nil {
		return fmt.Errorf("active history has no completion: %s", witness.Reason)
	}
	index := sort.SearchStrings(allow, kind)
	if index == len(allow) || allow[index] != kind {
		return fmt.Errorf("operation kind %q would leave a required result without a completion", kind)
	}
	return nil
}

func (s *State) RefreshRule() error {
	if s.Requirement == nil || s.Rule == nil {
		return nil
	}
	allow, witness, err := allowedKinds(s, *s.Requirement)
	if err != nil {
		return err
	}
	if witness != nil {
		return fmt.Errorf("active history has no completion: %s", witness.Reason)
	}
	s.Rule.Allow = allow
	return nil
}

func (s *State) Prepare(id, domain, kind, requestHash string) (Operation, error) {
	if id == "" || domain == "" || kind == "" || requestHash == "" {
		return Operation{}, errors.New("operation identity, domain, kind, and request hash are required")
	}
	for _, field := range []struct{ label, value string }{
		{"operation identity", id}, {"operation domain", domain},
		{"operation kind", kind}, {"request hash", requestHash},
	} {
		if len(field.value) > MaxNameBytes {
			return Operation{}, resourceLimit(field.label+" bytes", MaxNameBytes, uint64(len(field.value)))
		}
	}
	if prior, ok := s.Operations[id]; ok {
		if prior.Domain != domain || prior.Kind != kind || prior.RequestHash != requestHash {
			return Operation{}, errors.New("stable operation identity is already bound to different work")
		}
		return prior, nil
	}
	if err := s.CanPrepare(kind); err != nil {
		return Operation{}, err
	}
	spec, ok := s.Requirement.Kinds[kind]
	if !ok {
		return Operation{}, fmt.Errorf("unknown operation kind %q", kind)
	}
	op := Operation{
		ID:                 id,
		Domain:             domain,
		Kind:               kind,
		RequestHash:        requestHash,
		RuleVersion:        s.Rule.Version,
		Costs:              cloneMap(spec.Costs),
		Produces:           cloneMap(spec.Produces),
		RetrySafe:          spec.RetrySafe,
		Queryable:          spec.Queryable,
		Target:             spec.Target,
		Method:             spec.Method,
		ResponseClassifier: spec.ResponseClassifier,
		Phase:              Prepared,
	}
	s.Operations[id] = op
	if err := s.RefreshRule(); err != nil {
		delete(s.Operations, id)
		return Operation{}, err
	}
	return op, nil
}

func (s *State) MoveOperation(id string, update OperationUpdate) error {
	op, ok := s.Operations[id]
	if !ok {
		return fmt.Errorf("unknown operation %q", id)
	}
	valid := false
	switch update.Phase {
	case Dispatched:
		valid = op.Phase == Prepared || op.Phase == Unknown
		if !op.RetrySafe {
			return fmt.Errorf("operation %q has no implemented safe recovery", id)
		}
		if update.DispatchOwner == "" || update.DispatchGeneration != op.DispatchGeneration+1 {
			return fmt.Errorf("operation %q dispatch requires a new owner generation", id)
		}
	case Unknown:
		valid = op.Phase == Dispatched
	case Succeeded, Failed:
		valid = op.Phase == Dispatched || op.Phase == Unknown
	case Cancelled:
		valid = op.Phase == Prepared
	}
	if !valid {
		return fmt.Errorf("invalid operation transition %s -> %s", op.Phase, update.Phase)
	}
	if (update.Phase == Succeeded || update.Phase == Failed) && update.ResultHash == "" {
		return errors.New("settled operation requires a result hash")
	}
	if update.Phase != Succeeded && update.Phase != Failed &&
		(update.ResultHash != "" || update.StatusCode != 0 || len(update.ResultBody) != 0) {
		return errors.New("unsettled operation cannot carry a result")
	}
	if update.Phase != Dispatched && (update.DispatchOwner != "" || update.DispatchGeneration != 0) {
		return errors.New("only a dispatch can change dispatch ownership")
	}
	previous := op
	priorAllow := []string(nil)
	if s.Rule != nil {
		priorAllow = append(priorAllow, s.Rule.Allow...)
	}
	op.Phase = update.Phase
	op.ResultHash = update.ResultHash
	op.StatusCode = update.StatusCode
	op.ResultBody = append([]byte(nil), update.ResultBody...)
	op.RemoteReference = update.RemoteReference
	if update.Phase == Dispatched {
		op.DispatchOwner = update.DispatchOwner
		op.DispatchGeneration = update.DispatchGeneration
	}
	s.Operations[id] = op
	if err := s.RefreshRule(); err != nil {
		s.Operations[id] = previous
		if s.Rule != nil {
			s.Rule.Allow = priorAllow
		}
		return err
	}
	return nil
}
