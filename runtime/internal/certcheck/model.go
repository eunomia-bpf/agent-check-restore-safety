// Package certcheck is an independent, read-only Certificate checker.
//
// It deliberately imports neither kernel nor control. The duplicated wire
// structs and validation rules make disagreement with the Rule compiler
// observable instead of turning compiler reuse into purported verification.
package certcheck

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
)

const (
	CertificateSchema       = 1
	StateSchema             = 1
	MaxDocumentBytes        = 16 << 20
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

	responseReceiptV1 = "operation-receipt-v1"
)

var ErrResourceLimit = errors.New("independent Certificate checker resource limit")

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

type historyPoint struct {
	Sequence uint64 `json:"sequence"`
	Hash     string `json:"hash"`
}

type requirement struct {
	ID         string              `json:"id"`
	Results    map[string]uint32   `json:"results"`
	Capacities map[string]uint32   `json:"capacities"`
	Kinds      map[string]kindSpec `json:"kinds"`
}

type kindSpec struct {
	Costs              map[string]uint32 `json:"costs"`
	Produces           map[string]uint32 `json:"produces"`
	RetrySafe          bool              `json:"retry_safe"`
	Queryable          bool              `json:"queryable"`
	Target             string            `json:"target,omitempty"`
	Method             string            `json:"method,omitempty"`
	ResponseClassifier string            `json:"response_classifier,omitempty"`
}

type operation struct {
	ID        string            `json:"id"`
	Costs     map[string]uint32 `json:"costs"`
	Produces  map[string]uint32 `json:"produces"`
	RetrySafe bool              `json:"retry_safe"`
}

type rule struct {
	Version         uint64   `json:"version"`
	RequirementHash string   `json:"requirement_hash"`
	Allow           []string `json:"allow"`
}

type decision string

const (
	activate   decision = "activate"
	impossible decision = "impossible"
)

type witness struct {
	OpenSucceeded []string `json:"open_succeeded,omitempty"`
	Reason        string   `json:"reason"`
}

type certificate struct {
	Schema      int          `json:"schema"`
	Decision    decision     `json:"decision"`
	History     historyPoint `json:"history"`
	FromRule    uint64       `json:"from_rule"`
	Requirement requirement  `json:"requirement"`
	Rule        *rule        `json:"rule,omitempty"`
	Witness     *witness     `json:"witness,omitempty"`
	Digest      string       `json:"digest"`
}

type state struct {
	Schema         int                  `json:"schema"`
	History        historyPoint         `json:"history"`
	FromRule       uint64               `json:"from_rule"`
	Settled        settledFacts         `json:"settled"`
	OpenOperations map[string]operation `json:"open_operations"`
}

type settledFacts struct {
	Used               map[string]uint64 `json:"used"`
	Results            map[string]uint32 `json:"results"`
	UndeclaredResource string            `json:"undeclared_resource,omitempty"`
}

type Verdict struct {
	Valid       bool   `json:"valid"`
	Decision    string `json:"decision"`
	Sequence    uint64 `json:"history_sequence"`
	HistoryHash string `json:"history_hash"`
	RuleVersion uint64 `json:"rule_version,omitempty"`
}

func decodeStrict(data []byte, target any) error {
	if len(data) == 0 {
		return errors.New("empty JSON document")
	}
	if len(data) > MaxDocumentBytes {
		return resourceLimit("JSON document bytes", MaxDocumentBytes, uint64(len(data)))
	}
	if err := rejectDuplicateKeys(data); err != nil {
		return err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("JSON document contains multiple values")
		}
		return err
	}
	return nil
}

func rejectDuplicateKeys(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	var consumeValue func() error
	consumeValue = func() error {
		token, err := decoder.Token()
		if err != nil {
			return err
		}
		delimiter, composite := token.(json.Delim)
		if !composite {
			return nil
		}
		switch delimiter {
		case '{':
			seen := make(map[string]bool)
			for decoder.More() {
				keyToken, err := decoder.Token()
				if err != nil {
					return err
				}
				key, ok := keyToken.(string)
				if !ok {
					return errors.New("JSON object key is not a string")
				}
				if seen[key] {
					return fmt.Errorf("JSON object contains duplicate key %q", key)
				}
				seen[key] = true
				if err := consumeValue(); err != nil {
					return err
				}
			}
			end, err := decoder.Token()
			if err != nil {
				return err
			}
			if end != json.Delim('}') {
				return errors.New("JSON object has an invalid terminator")
			}
		case '[':
			for decoder.More() {
				if err := consumeValue(); err != nil {
					return err
				}
			}
			end, err := decoder.Token()
			if err != nil {
				return err
			}
			if end != json.Delim(']') {
				return errors.New("JSON array has an invalid terminator")
			}
		default:
			return errors.New("JSON value has an invalid delimiter")
		}
		return nil
	}
	if err := consumeValue(); err != nil {
		return err
	}
	if _, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("JSON document contains multiple values")
		}
		return err
	}
	return nil
}

func validDigest(value string) bool {
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size && hex.EncodeToString(decoded) == value
}

func cloneMap(input map[string]uint32) map[string]uint32 {
	output := make(map[string]uint32, len(input))
	for key, value := range input {
		output[key] = value
	}
	return output
}

func cloneRequirement(input requirement) requirement {
	output := requirement{
		ID: input.ID, Results: cloneMap(input.Results), Capacities: cloneMap(input.Capacities),
		Kinds: make(map[string]kindSpec, len(input.Kinds)),
	}
	for name, spec := range input.Kinds {
		output.Kinds[name] = kindSpec{
			Costs: cloneMap(spec.Costs), Produces: cloneMap(spec.Produces),
			RetrySafe: spec.RetrySafe, Queryable: spec.Queryable,
			Target: spec.Target, Method: spec.Method, ResponseClassifier: spec.ResponseClassifier,
		}
	}
	return output
}

func validateRequirement(value requirement) error {
	if value.ID == "" {
		return errors.New("Requirement id is empty")
	}
	if len(value.ID) > MaxNameBytes {
		return resourceLimit("Requirement id bytes", MaxNameBytes, uint64(len(value.ID)))
	}
	if len(value.Results) == 0 {
		return errors.New("Requirement has no result")
	}
	if len(value.Results) > MaxRequirementResults {
		return resourceLimit("required result dimensions", MaxRequirementResults, uint64(len(value.Results)))
	}
	if len(value.Capacities) > MaxRequirementResources {
		return resourceLimit("resource dimensions", MaxRequirementResources, uint64(len(value.Capacities)))
	}
	if len(value.Kinds) == 0 {
		return errors.New("Requirement has no Operation kind")
	}
	if len(value.Kinds) > MaxRequirementKinds {
		return resourceLimit("Operation kinds", MaxRequirementKinds, uint64(len(value.Kinds)))
	}
	var requiredUnits uint64
	for result, count := range value.Results {
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
	for resource, capacity := range value.Capacities {
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
	producible := make(map[string]bool)
	for name, spec := range value.Kinds {
		if name == "" {
			return errors.New("empty Operation kind")
		}
		if len(name) > MaxNameBytes {
			return resourceLimit("Operation kind name bytes", MaxNameBytes, uint64(len(name)))
		}
		if len(spec.Costs) > MaxRequirementResources {
			return resourceLimit(fmt.Sprintf("Operation kind %q cost dimensions", name), MaxRequirementResources, uint64(len(spec.Costs)))
		}
		if len(spec.Produces) == 0 {
			return fmt.Errorf("Operation kind %q produces no result", name)
		}
		if len(spec.Produces) > MaxOperationResults {
			return resourceLimit(fmt.Sprintf("Operation kind %q result dimensions", name), MaxOperationResults, uint64(len(spec.Produces)))
		}
		if spec.Target == "" {
			if spec.Method != "" || spec.ResponseClassifier != "" {
				return fmt.Errorf("Operation kind %q has an HTTP contract without a target", name)
			}
		} else if spec.Method == "" || spec.ResponseClassifier == "" {
			return fmt.Errorf("Operation kind %q target requires a method and response classifier", name)
		} else if spec.ResponseClassifier != responseReceiptV1 {
			return fmt.Errorf("Operation kind %q uses unsupported response classifier %q", name, spec.ResponseClassifier)
		}
		for resource, amount := range spec.Costs {
			if resource == "" || amount == 0 {
				return fmt.Errorf("invalid cost in Operation kind %q", name)
			}
			if _, declared := value.Capacities[resource]; !declared {
				return fmt.Errorf("Operation kind %q uses undeclared resource %q", name, resource)
			}
			if amount > MaxModelValue {
				return resourceLimit(fmt.Sprintf("Operation kind %q cost %q", name, resource), MaxModelValue, uint64(amount))
			}
		}
		for result, amount := range spec.Produces {
			if result == "" || amount == 0 {
				return fmt.Errorf("invalid result in Operation kind %q", name)
			}
			if len(result) > MaxNameBytes {
				return resourceLimit("produced result name bytes", MaxNameBytes, uint64(len(result)))
			}
			if amount > MaxModelValue {
				return resourceLimit(fmt.Sprintf("Operation kind %q production %q", name, result), MaxModelValue, uint64(amount))
			}
			if _, required := value.Results[result]; required {
				producible[result] = true
			}
		}
	}
	for result := range value.Results {
		if !producible[result] {
			return fmt.Errorf("required result %q has no producing Operation kind", result)
		}
	}
	return nil
}

func requirementHash(value requirement) (string, error) {
	if err := validateRequirement(value); err != nil {
		return "", err
	}
	encoded, err := json.Marshal(cloneRequirement(value))
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(encoded)
	return hex.EncodeToString(digest[:]), nil
}

func certificateDigest(value certificate) (string, error) {
	value.Digest = ""
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(encoded)
	return hex.EncodeToString(digest[:]), nil
}
