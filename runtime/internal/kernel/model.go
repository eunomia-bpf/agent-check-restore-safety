// Package kernel defines the five objects shared by every runtime adapter:
// History, Requirement, Operation, Rule, and Certificate.
package kernel

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
)

const CertificateSchema = 1

const (
	// Stored requests are part of a prepared Operation and therefore one
	// History event. Keep their bounds well below the History frame limit.
	MaxOperationRequestBodyBytes   = 1 << 20
	MaxOperationRequestHeaders     = 64
	MaxOperationRequestHeaderBytes = 64 << 10
)

// ResponseReceiptV1 is the only concrete HTTP response contract implemented
// by milestone zero. A Requirement cannot count an unsupported adapter as a
// possible completion.
const ResponseReceiptV1 = "operation-receipt-v1"

// OperationObservationV1 is the only query result contract implemented by
// the HTTP gateway. A queryable Operation freezes this contract and its query
// endpoint alongside the effect endpoint.
const OperationObservationV1 = "operation-observation-v1"

// SettlementQuery records that a trusted observation, rather than the
// original effect response, definitively settled an Operation.
const SettlementQuery = "query"

const EmptyHistoryHash = "0000000000000000000000000000000000000000000000000000000000000000"

type HistoryPoint struct {
	Sequence uint64 `json:"sequence"`
	Hash     string `json:"hash"`
}

// Requirement names durable results and the resources that successful
// operations may consume. A result count is a lower bound; a capacity is an
// upper bound. Kind specifications are versioned input, not inferred from an
// operation name at runtime.
type Requirement struct {
	ID         string              `json:"id"`
	Results    map[string]uint32   `json:"results"`
	Capacities map[string]uint32   `json:"capacities"`
	Kinds      map[string]KindSpec `json:"kinds"`
}

type KindSpec struct {
	Costs              map[string]uint32 `json:"costs"`
	Produces           map[string]uint32 `json:"produces"`
	RetrySafe          bool              `json:"retry_safe"`
	Queryable          bool              `json:"queryable"`
	Target             string            `json:"target,omitempty"`
	Method             string            `json:"method,omitempty"`
	ResponseClassifier string            `json:"response_classifier,omitempty"`
	QueryTarget        string            `json:"query_target,omitempty"`
	QueryMethod        string            `json:"query_method,omitempty"`
	QueryClassifier    string            `json:"query_classifier,omitempty"`
}

type Phase string

const (
	Prepared   Phase = "prepared"
	Dispatched Phase = "dispatched"
	Unknown    Phase = "unknown"
	Succeeded  Phase = "succeeded"
	Failed     Phase = "failed"
	Cancelled  Phase = "cancelled"
)

// Operation freezes the semantic meaning of an external action. Costs and
// results are copied from the active Requirement so a later change cannot
// reinterpret an operation that is already in flight.
type Operation struct {
	ID                 string            `json:"id"`
	Domain             string            `json:"domain"`
	Kind               string            `json:"kind"`
	RequestHash        string            `json:"request_hash"`
	RuleVersion        uint64            `json:"rule_version"`
	Costs              map[string]uint32 `json:"costs"`
	Produces           map[string]uint32 `json:"produces"`
	RetrySafe          bool              `json:"retry_safe"`
	Queryable          bool              `json:"queryable"`
	Target             string            `json:"target,omitempty"`
	Method             string            `json:"method,omitempty"`
	ResponseClassifier string            `json:"response_classifier,omitempty"`
	QueryTarget        string            `json:"query_target,omitempty"`
	QueryMethod        string            `json:"query_method,omitempty"`
	QueryClassifier    string            `json:"query_classifier,omitempty"`
	RequestStored      bool              `json:"request_stored,omitempty"`
	RequestHeaders     map[string]string `json:"request_headers,omitempty"`
	RequestBody        []byte            `json:"request_body,omitempty"`
	Phase              Phase             `json:"phase"`
	ResultHash         string            `json:"result_hash,omitempty"`
	StatusCode         int               `json:"status_code,omitempty"`
	ResultBody         []byte            `json:"result_body,omitempty"`
	RemoteReference    string            `json:"remote_reference,omitempty"`
	DispatchOwner      string            `json:"dispatch_owner,omitempty"`
	DispatchGeneration uint64            `json:"dispatch_generation,omitempty"`
	Settlement         string            `json:"settlement,omitempty"`
}

type OperationUpdate struct {
	Phase              Phase  `json:"phase"`
	ResultHash         string `json:"result_hash,omitempty"`
	StatusCode         int    `json:"status_code,omitempty"`
	ResultBody         []byte `json:"result_body,omitempty"`
	RemoteReference    string `json:"remote_reference,omitempty"`
	DispatchOwner      string `json:"dispatch_owner,omitempty"`
	DispatchGeneration uint64 `json:"dispatch_generation,omitempty"`
	Settlement         string `json:"settlement,omitempty"`
}

func (o Operation) Open() bool {
	return o.Phase == Prepared || o.Phase == Dispatched || o.Phase == Unknown
}

type Rule struct {
	Version         uint64   `json:"version"`
	RequirementHash string   `json:"requirement_hash"`
	Allow           []string `json:"allow"`
}

type Decision string

const (
	Activate   Decision = "activate"
	Impossible Decision = "impossible"
)

type Witness struct {
	OpenSucceeded []string `json:"open_succeeded,omitempty"`
	Reason        string   `json:"reason"`
}

// Certificate is bound to the complete History head. It becomes stale after
// any operation progress, even if an authorization-only view is unchanged.
type Certificate struct {
	Schema      int          `json:"schema"`
	Decision    Decision     `json:"decision"`
	History     HistoryPoint `json:"history"`
	FromRule    uint64       `json:"from_rule"`
	Requirement Requirement  `json:"requirement"`
	Rule        *Rule        `json:"rule,omitempty"`
	Witness     *Witness     `json:"witness,omitempty"`
	Digest      string       `json:"digest"`
}

type State struct {
	History     HistoryPoint         `json:"history"`
	Requirement *Requirement         `json:"requirement,omitempty"`
	Rule        *Rule                `json:"rule,omitempty"`
	Operations  map[string]Operation `json:"operations"`
}

func NewState() *State {
	return &State{
		History:    HistoryPoint{Hash: EmptyHistoryHash},
		Operations: make(map[string]Operation),
	}
}

func (s *State) Clone() *State {
	if s == nil {
		return nil
	}
	out := &State{
		History:    s.History,
		Operations: make(map[string]Operation, len(s.Operations)),
	}
	if s.Requirement != nil {
		requirement := cloneRequirement(*s.Requirement)
		out.Requirement = &requirement
	}
	if s.Rule != nil {
		rule := *s.Rule
		rule.Allow = append([]string{}, s.Rule.Allow...)
		out.Rule = &rule
	}
	for id, operation := range s.Operations {
		out.Operations[id] = cloneOperation(operation)
	}
	return out
}

func cloneOperation(operation Operation) Operation {
	operation.Costs = cloneMap(operation.Costs)
	operation.Produces = cloneMap(operation.Produces)
	operation.RequestHeaders = cloneStringMap(operation.RequestHeaders)
	operation.RequestBody = append([]byte(nil), operation.RequestBody...)
	operation.ResultBody = append([]byte(nil), operation.ResultBody...)
	return operation
}

func cloneMap(in map[string]uint32) map[string]uint32 {
	out := make(map[string]uint32, len(in))
	for key, value := range in {
		out[key] = value
	}
	return out
}

func cloneStringMap(in map[string]string) map[string]string {
	if len(in) == 0 {
		return nil
	}
	out := make(map[string]string, len(in))
	for key, value := range in {
		out[key] = value
	}
	return out
}

func cloneRequirement(in Requirement) Requirement {
	out := Requirement{
		ID:         in.ID,
		Results:    cloneMap(in.Results),
		Capacities: cloneMap(in.Capacities),
		Kinds:      make(map[string]KindSpec, len(in.Kinds)),
	}
	for name, spec := range in.Kinds {
		out.Kinds[name] = KindSpec{
			Costs:              cloneMap(spec.Costs),
			Produces:           cloneMap(spec.Produces),
			RetrySafe:          spec.RetrySafe,
			Queryable:          spec.Queryable,
			Target:             spec.Target,
			Method:             spec.Method,
			ResponseClassifier: spec.ResponseClassifier,
			QueryTarget:        spec.QueryTarget,
			QueryMethod:        spec.QueryMethod,
			QueryClassifier:    spec.QueryClassifier,
		}
	}
	return out
}

func ValidateRequirement(r Requirement) error {
	if r.ID == "" {
		return errors.New("requirement id is empty")
	}
	if len(r.ID) > MaxNameBytes {
		return resourceLimit("requirement id bytes", MaxNameBytes, uint64(len(r.ID)))
	}
	if len(r.Results) == 0 {
		return errors.New("requirement has no result")
	}
	if len(r.Results) > MaxRequirementResults {
		return resourceLimit("required result dimensions", MaxRequirementResults, uint64(len(r.Results)))
	}
	if len(r.Capacities) > MaxRequirementResources {
		return resourceLimit("resource dimensions", MaxRequirementResources, uint64(len(r.Capacities)))
	}
	if len(r.Kinds) > MaxRequirementKinds {
		return resourceLimit("operation kinds", MaxRequirementKinds, uint64(len(r.Kinds)))
	}
	var requiredUnits uint64
	for result, count := range r.Results {
		if result == "" || count == 0 {
			return fmt.Errorf("invalid required result %q", result)
		}
		if len(result) > MaxNameBytes {
			return resourceLimit("required result name bytes", MaxNameBytes, uint64(len(result)))
		}
		requiredUnits += uint64(count)
		if requiredUnits > MaxRequiredUnits {
			return resourceLimit("total required result units", MaxRequiredUnits, requiredUnits)
		}
	}
	for resource, capacity := range r.Capacities {
		if resource == "" {
			return errors.New("empty resource name")
		}
		if len(resource) > MaxNameBytes {
			return resourceLimit("resource name bytes", MaxNameBytes, uint64(len(resource)))
		}
		if capacity > MaxModelValue {
			return resourceLimit(fmt.Sprintf("resource %q capacity", resource), MaxModelValue, uint64(capacity))
		}
	}
	if len(r.Kinds) == 0 {
		return errors.New("requirement has no operation kind")
	}
	producible := make(map[string]bool)
	for kind, spec := range r.Kinds {
		if kind == "" {
			return errors.New("empty operation kind")
		}
		if len(kind) > MaxNameBytes {
			return resourceLimit("operation kind name bytes", MaxNameBytes, uint64(len(kind)))
		}
		if len(spec.Costs) > MaxRequirementResources {
			return resourceLimit(fmt.Sprintf("operation kind %q cost dimensions", kind), MaxRequirementResources, uint64(len(spec.Costs)))
		}
		if len(spec.Produces) > MaxOperationResults {
			return resourceLimit(fmt.Sprintf("operation kind %q result dimensions", kind), MaxOperationResults, uint64(len(spec.Produces)))
		}
		if len(spec.Produces) == 0 {
			return fmt.Errorf("operation kind %q produces no result", kind)
		}
		if spec.Target == "" {
			if spec.Method != "" || spec.ResponseClassifier != "" {
				return fmt.Errorf("operation kind %q has an HTTP contract without a target", kind)
			}
		} else if spec.Method == "" || spec.ResponseClassifier == "" {
			return fmt.Errorf("operation kind %q target requires a method and response classifier", kind)
		} else if spec.ResponseClassifier != ResponseReceiptV1 {
			return fmt.Errorf("operation kind %q uses unsupported response classifier %q", kind, spec.ResponseClassifier)
		}
		if spec.Queryable {
			if spec.QueryTarget == "" || spec.QueryMethod == "" || spec.QueryClassifier == "" {
				return fmt.Errorf("queryable operation kind %q requires a query target, method, and classifier", kind)
			}
			if spec.QueryClassifier != OperationObservationV1 {
				return fmt.Errorf("operation kind %q uses unsupported query classifier %q", kind, spec.QueryClassifier)
			}
		} else if spec.QueryTarget != "" || spec.QueryMethod != "" || spec.QueryClassifier != "" {
			return fmt.Errorf("non-queryable operation kind %q has a query contract", kind)
		}
		for resource, amount := range spec.Costs {
			if resource == "" || amount == 0 {
				return fmt.Errorf("invalid cost in operation kind %q", kind)
			}
			if _, ok := r.Capacities[resource]; !ok {
				return fmt.Errorf("operation kind %q uses undeclared resource %q", kind, resource)
			}
			if amount > MaxModelValue {
				return resourceLimit(fmt.Sprintf("operation kind %q cost %q", kind, resource), MaxModelValue, uint64(amount))
			}
		}
		for result, amount := range spec.Produces {
			if result == "" || amount == 0 {
				return fmt.Errorf("invalid result in operation kind %q", kind)
			}
			if _, ok := r.Results[result]; ok {
				producible[result] = true
			}
			if len(result) > MaxNameBytes {
				return resourceLimit("produced result name bytes", MaxNameBytes, uint64(len(result)))
			}
			if amount > MaxModelValue {
				return resourceLimit(fmt.Sprintf("operation kind %q production %q", kind, result), MaxModelValue, uint64(amount))
			}
		}
	}
	for result := range r.Results {
		if !producible[result] {
			return fmt.Errorf("required result %q has no producing operation kind", result)
		}
	}
	return nil
}

func RequirementHash(r Requirement) (string, error) {
	if err := ValidateRequirement(r); err != nil {
		return "", err
	}
	encoded, err := json.Marshal(cloneRequirement(r))
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(encoded)
	return hex.EncodeToString(sum[:]), nil
}

func certificateDigest(c Certificate) (string, error) {
	c.Digest = ""
	encoded, err := json.Marshal(c)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(encoded)
	return hex.EncodeToString(sum[:]), nil
}

func sortedKeys[V any](values map[string]V) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
