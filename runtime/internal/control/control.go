// Package control joins the exact kernel to the durable History. Every state
// change is synced before it becomes visible, and reopening reconstructs state
// exclusively from the checked record.
package control

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"sort"
	"sync"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/certcheck"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/headanchor"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/history"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const (
	semanticVersion       = 1
	eventRuleActivated    = "rule.activated"
	eventOperationPrepare = "operation.prepared"
	eventOperationPhase   = "operation.phase"
)

var (
	ErrHistoryRollback = errors.New("History is older than its external head anchor")
	ErrNeedsReopen     = errors.New("control must be closed and reopened")
	ErrClosing         = errors.New("control is closing")
)

type ruleEvent struct {
	SemanticVersion int                `json:"semantic_version"`
	Certificate     kernel.Certificate `json:"certificate"`
}

type prepareEvent struct {
	SemanticVersion int              `json:"semantic_version"`
	Operation       kernel.Operation `json:"operation"`
}

type phaseEvent struct {
	SemanticVersion int                    `json:"semantic_version"`
	ID              string                 `json:"id"`
	Update          kernel.OperationUpdate `json:"update"`
}

// certificateState is the versioned, answer-preserving projection consumed by
// the independent checker. Response bodies, remote metadata, and settled
// Operation identities cannot affect the bounded answer and are deliberately
// excluded from this trust boundary.
type certificateState struct {
	Schema         int                             `json:"schema"`
	History        kernel.HistoryPoint             `json:"history"`
	FromRule       uint64                          `json:"from_rule"`
	Settled        certificateSettled              `json:"settled"`
	OpenOperations map[string]certificateOperation `json:"open_operations"`
}

type certificateSettled struct {
	Used               map[string]uint64 `json:"used"`
	Results            map[string]uint32 `json:"results"`
	UndeclaredResource string            `json:"undeclared_resource,omitempty"`
}

type certificateOperation struct {
	ID        string            `json:"id"`
	Costs     map[string]uint32 `json:"costs"`
	Produces  map[string]uint32 `json:"produces"`
	RetrySafe bool              `json:"retry_safe"`
	Queryable bool              `json:"queryable,omitempty"`
}

type Control struct {
	mu               sync.RWMutex
	history          *history.History
	anchor           *headanchor.Anchor
	state            *kernel.State
	bindings         sandboxRegistry
	attachEligible   map[string]SandboxBinding
	attachedBindings map[string]SandboxBinding
	bootID           string
	failed           error
	closing          bool
	activeDispatches int
	activeAdapters   map[string]int
	dispatchesDone   *sync.Cond
}

func Open(path string) (*Control, error) {
	return OpenWithAnchor(path, path+".head-anchor")
}

// OpenWithAnchor opens a History and a head anchor that must live outside any
// restore domain containing the History path.
func OpenWithAnchor(path, anchorPath string) (*Control, error) {
	record, err := history.Open(path)
	if err != nil {
		return nil, err
	}
	anchor, err := openAnchor(anchorPath, record)
	if err != nil {
		_ = record.Close()
		return nil, err
	}
	state := kernel.NewState()
	bindings := newSandboxRegistry()
	for _, event := range record.Events() {
		if event.Sequence != state.History.Sequence+1 || event.PreviousHash != state.History.Hash {
			_ = anchor.Close()
			_ = record.Close()
			return nil, errors.New("durable event does not extend reconstructed state")
		}
		if err := apply(state, &bindings, event.Operation, event.Data); err != nil {
			_ = anchor.Close()
			_ = record.Close()
			return nil, fmt.Errorf("replay event %d: %w", event.Sequence, err)
		}
		state.History = kernel.HistoryPoint{Sequence: event.Sequence, Hash: event.Hash}
	}
	head := record.Head()
	if err := anchor.Advance(headanchor.Head{Sequence: head.Sequence, Hash: head.Hash}); err != nil {
		_ = anchor.Close()
		_ = record.Close()
		return nil, fmt.Errorf("advance external History head after replay: %w", err)
	}
	bootBytes := make([]byte, 16)
	if _, err := rand.Read(bootBytes); err != nil {
		_ = anchor.Close()
		_ = record.Close()
		return nil, fmt.Errorf("create control boot identity: %w", err)
	}
	control := &Control{
		history: record, anchor: anchor, state: state, bindings: bindings,
		attachEligible: make(map[string]SandboxBinding), attachedBindings: make(map[string]SandboxBinding),
		activeAdapters: make(map[string]int),
		bootID:         hex.EncodeToString(bootBytes),
	}
	control.dispatchesDone = sync.NewCond(&control.mu)
	return control, nil
}

func openAnchor(path string, record *history.History) (*headanchor.Anchor, error) {
	anchor, err := headanchor.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		if record.Head().Sequence != 0 {
			return nil, errors.New("nonempty History has no external head anchor")
		}
		anchor, err = headanchor.Create(path, headanchor.Head{
			Sequence: 0, Hash: kernel.EmptyHistoryHash,
		})
	}
	if err != nil {
		return nil, err
	}
	current, err := anchor.Current()
	if err != nil {
		_ = anchor.Close()
		return nil, err
	}
	head := record.Head()
	if current.Sequence > head.Sequence {
		_ = anchor.Close()
		return nil, fmt.Errorf("%w: anchor is %d, History is %d", ErrHistoryRollback, current.Sequence, head.Sequence)
	}
	if current.Sequence == head.Sequence && current.Hash != head.Hash {
		_ = anchor.Close()
		return nil, fmt.Errorf("%w: sequence %d has a different hash", ErrHistoryRollback, head.Sequence)
	}
	if current.Sequence < head.Sequence {
		if current.Sequence == 0 {
			if current.Hash != kernel.EmptyHistoryHash {
				_ = anchor.Close()
				return nil, ErrHistoryRollback
			}
		} else {
			events := record.Events()
			if current.Sequence > uint64(len(events)) || events[current.Sequence-1].Hash != current.Hash {
				_ = anchor.Close()
				return nil, fmt.Errorf("%w: anchored point is not in the History chain", ErrHistoryRollback)
			}
		}
	}
	return anchor, nil
}

// BootID identifies this live Control instance. Dispatch ownership uses it to
// distinguish a concurrent caller from recovery after a dead instance.
func (c *Control) BootID() string {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.bootID
}

func (c *Control) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.history == nil {
		return nil
	}
	c.closing = true
	for c.activeDispatches != 0 {
		c.dispatchesDone.Wait()
	}
	err := errors.Join(c.history.Close(), c.anchor.Close())
	c.history = nil
	c.anchor = nil
	return err
}

// BeginDispatch keeps Close from releasing the History lock while a network
// request owned by this Control may still be live.
func (c *Control) BeginDispatch() (func(), error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.history == nil {
		return nil, history.ErrClosed
	}
	if c.closing {
		return nil, ErrClosing
	}
	if c.failed != nil {
		return nil, fmt.Errorf("%w: %v", ErrNeedsReopen, c.failed)
	}
	c.activeDispatches++
	var once sync.Once
	return func() {
		once.Do(func() {
			c.mu.Lock()
			c.activeDispatches--
			c.dispatchesDone.Broadcast()
			c.mu.Unlock()
		})
	}, nil
}

func (c *Control) Snapshot() *kernel.State {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.state.Clone()
}

// Operation returns the frozen meaning of a previously registered Operation.
func (c *Control) Operation(id string) (kernel.Operation, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	operation, ok := c.state.Operations[id]
	if !ok {
		return kernel.Operation{}, false
	}
	return cloneOperation(operation), true
}

func cloneOperation(operation kernel.Operation) kernel.Operation {
	operation.Costs = cloneCountMap(operation.Costs)
	operation.Produces = cloneCountMap(operation.Produces)
	operation.RequestHeaders = cloneStringMap(operation.RequestHeaders)
	operation.RequestBody = append([]byte(nil), operation.RequestBody...)
	operation.ResultBody = append([]byte(nil), operation.ResultBody...)
	return operation
}

func cloneCountMap(input map[string]uint32) map[string]uint32 {
	output := make(map[string]uint32, len(input))
	for key, value := range input {
		output[key] = value
	}
	return output
}

func cloneStringMap(input map[string]string) map[string]string {
	if len(input) == 0 {
		return nil
	}
	output := make(map[string]string, len(input))
	for key, value := range input {
		output[key] = value
	}
	return output
}

func (c *Control) Events() []history.Event {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.history == nil {
		return nil
	}
	return c.history.Events()
}

func (c *Control) Compile(requirement kernel.Requirement) (kernel.Certificate, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.history == nil {
		return kernel.Certificate{}, history.ErrClosed
	}
	if c.closing {
		return kernel.Certificate{}, ErrClosing
	}
	if c.failed != nil {
		return kernel.Certificate{}, fmt.Errorf("%w: %v", ErrNeedsReopen, c.failed)
	}
	next := uint64(1)
	if c.state.Rule != nil {
		next = c.state.Rule.Version + 1
	}
	certificate, err := kernel.Compile(c.state, requirement, next)
	if err != nil {
		return kernel.Certificate{}, err
	}
	if err := checkCertificate(c.state, certificate); err != nil {
		return kernel.Certificate{}, err
	}
	return certificate, nil
}

func (c *Control) Activate(certificate kernel.Certificate) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.history == nil {
		return history.ErrClosed
	}
	if c.closing {
		return ErrClosing
	}
	if c.failed != nil {
		return fmt.Errorf("%w: %v", ErrNeedsReopen, c.failed)
	}
	if len(c.bindings.desired) != 0 {
		return ErrActiveSandboxBindings
	}
	if err := checkCertificate(c.state, certificate); err != nil {
		return err
	}
	next := c.state.Clone()
	if err := next.Activate(certificate); err != nil {
		return err
	}
	event, err := c.history.Append(eventRuleActivated, ruleEvent{
		SemanticVersion: semanticVersion, Certificate: certificate,
	})
	if err != nil {
		return c.appendError(err)
	}
	if err := c.advanceAnchor(event); err != nil {
		return err
	}
	next.History = kernel.HistoryPoint{Sequence: event.Sequence, Hash: event.Hash}
	c.state = next
	return nil
}

func checkCertificate(state *kernel.State, certificate kernel.Certificate) error {
	stateJSON, err := certificateStateJSON(state, certificate.Requirement)
	if err != nil {
		return fmt.Errorf("derive State for independent Certificate checker: %w", err)
	}
	certificateJSON, err := json.Marshal(certificate)
	if err != nil {
		return fmt.Errorf("encode Certificate for independent checker: %w", err)
	}
	if _, err := certcheck.CheckJSON(stateJSON, certificateJSON); err != nil {
		return fmt.Errorf("independent Certificate checker: %w", err)
	}
	return nil
}

func addSettledProjection(target kernel.Requirement, settled *certificateSettled,
	costs, produces map[string]uint32) {
	for resource, amount := range costs {
		if _, declared := target.Capacities[resource]; !declared {
			if amount != 0 && (settled.UndeclaredResource == "" || resource < settled.UndeclaredResource) {
				settled.UndeclaredResource = resource
			}
			continue
		}
		settled.Used[resource] += uint64(amount)
	}
	for result, amount := range produces {
		need, required := target.Results[result]
		if !required {
			continue
		}
		current := settled.Results[result]
		if current >= need {
			continue
		}
		if amount >= need-current {
			settled.Results[result] = need
		} else {
			settled.Results[result] = current + amount
		}
	}
}

func certificateStateJSON(state *kernel.State, target kernel.Requirement) ([]byte, error) {
	if state == nil {
		return nil, errors.New("nil State")
	}
	if len(state.Operations) > kernel.MaxTrackedOperations {
		return nil, fmt.Errorf("tracked Operations exceed %d", kernel.MaxTrackedOperations)
	}
	fromRule := uint64(0)
	if state.Rule != nil {
		fromRule = state.Rule.Version
	}
	projection := certificateState{
		Schema: certcheck.StateSchema, History: state.History, FromRule: fromRule,
		Settled: certificateSettled{
			Used: make(map[string]uint64), Results: make(map[string]uint32),
		},
		OpenOperations: make(map[string]certificateOperation),
	}
	ids := make([]string, 0, len(state.Operations))
	for id := range state.Operations {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		operation := state.Operations[id]
		if id != operation.ID || id == "" || len(id) > kernel.MaxNameBytes {
			return nil, fmt.Errorf("Operation map identity %q is invalid", id)
		}
		if len(operation.Costs) > kernel.MaxRequirementResources || len(operation.Produces) > kernel.MaxOperationResults {
			return nil, fmt.Errorf("Operation %q exceeds semantic dimension limits", id)
		}
		for resource, amount := range operation.Costs {
			if resource == "" || len(resource) > kernel.MaxNameBytes || amount == 0 || amount > kernel.MaxModelValue {
				return nil, fmt.Errorf("Operation %q has an invalid frozen cost", id)
			}
		}
		if len(operation.Produces) == 0 {
			return nil, fmt.Errorf("Operation %q produces no result", id)
		}
		for result, amount := range operation.Produces {
			if result == "" || len(result) > kernel.MaxNameBytes || amount == 0 || amount > kernel.MaxModelValue {
				return nil, fmt.Errorf("Operation %q has an invalid frozen result", id)
			}
		}
		switch operation.Phase {
		case kernel.Succeeded:
			addSettledProjection(target, &projection.Settled, operation.Costs, operation.Produces)
		case kernel.Prepared:
			if !operation.RetrySafe && !operation.Queryable {
				continue
			}
			fallthrough
		case kernel.Dispatched, kernel.Unknown:
			projection.OpenOperations[id] = certificateOperation{
				ID: id, Costs: cloneCountMap(operation.Costs),
				Produces: cloneCountMap(operation.Produces), RetrySafe: operation.RetrySafe,
				Queryable: operation.Queryable,
			}
		case kernel.Failed, kernel.Cancelled:
		default:
			return nil, fmt.Errorf("Operation %q has invalid phase %q", id, operation.Phase)
		}
	}
	if len(projection.OpenOperations) > kernel.MaxOpenOperations {
		return nil, fmt.Errorf("open Operations exceed %d", kernel.MaxOpenOperations)
	}
	return json.Marshal(projection)
}

// CertificateState returns the exact compact State projection used by online
// checking. Its History point must still be compared with a trusted external
// head when the result is checked outside this Control instance.
func (c *Control) CertificateState(certificate kernel.Certificate) (json.RawMessage, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if c.history == nil {
		return nil, history.ErrClosed
	}
	if c.closing {
		return nil, ErrClosing
	}
	if c.failed != nil {
		return nil, fmt.Errorf("%w: %v", ErrNeedsReopen, c.failed)
	}
	encoded, err := certificateStateJSON(c.state, certificate.Requirement)
	if err != nil {
		return nil, err
	}
	return json.RawMessage(encoded), nil
}

func (c *Control) Prepare(id, domain, kind, requestHash string) (kernel.Operation, error) {
	return c.prepare(id, domain, "", kind, requestHash, false, nil, nil)
}

func (c *Control) PrepareWithRequest(
	id, domain, kind, requestHash string,
	headers map[string]string,
	body []byte,
) (kernel.Operation, error) {
	return c.prepare(id, domain, "", kind, requestHash, true, headers, body)
}

func (c *Control) prepare(
	id, domain, sandboxID, kind, requestHash string,
	requestStored bool,
	headers map[string]string,
	body []byte,
) (kernel.Operation, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.prepareLocked(id, domain, sandboxID, kind, requestHash, requestStored, headers, body)
}

func (c *Control) prepareLocked(
	id, domain, sandboxID, kind, requestHash string,
	requestStored bool,
	headers map[string]string,
	body []byte,
) (kernel.Operation, error) {
	if c.history == nil {
		return kernel.Operation{}, history.ErrClosed
	}
	if c.closing {
		return kernel.Operation{}, ErrClosing
	}
	if c.failed != nil {
		return kernel.Operation{}, fmt.Errorf("%w: %v", ErrNeedsReopen, c.failed)
	}
	_, existed := c.state.Operations[id]
	next := c.state.Clone()
	var operation kernel.Operation
	var err error
	if requestStored {
		if sandboxID == "" {
			operation, err = next.PrepareWithRequest(id, domain, kind, requestHash, headers, body)
		} else {
			operation, err = next.PrepareWithRequestForSandbox(
				id, domain, sandboxID, kind, requestHash, headers, body,
			)
		}
	} else {
		if sandboxID != "" {
			return kernel.Operation{}, errors.New("sandbox operation must store its request")
		}
		operation, err = next.Prepare(id, domain, kind, requestHash)
	}
	if err != nil {
		return kernel.Operation{}, err
	}
	if existed {
		return cloneOperation(operation), nil
	}
	event, err := c.history.Append(eventOperationPrepare, prepareEvent{
		SemanticVersion: semanticVersion, Operation: operation,
	})
	if err != nil {
		return kernel.Operation{}, c.appendError(err)
	}
	if err := c.advanceAnchor(event); err != nil {
		return kernel.Operation{}, err
	}
	next.History = kernel.HistoryPoint{Sequence: event.Sequence, Hash: event.Hash}
	c.state = next
	return cloneOperation(operation), nil
}

func (c *Control) Move(id string, update kernel.OperationUpdate) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.moveLocked(id, update)
}

func (c *Control) moveLocked(id string, update kernel.OperationUpdate) error {
	if c.history == nil {
		return history.ErrClosed
	}
	if c.failed != nil {
		return fmt.Errorf("%w: %v", ErrNeedsReopen, c.failed)
	}
	if prior, ok := c.state.Operations[id]; ok && prior.Phase == update.Phase &&
		prior.ResultHash == update.ResultHash && prior.StatusCode == update.StatusCode &&
		string(prior.ResultBody) == string(update.ResultBody) &&
		prior.RemoteReference == update.RemoteReference &&
		prior.Settlement == update.Settlement &&
		(update.Phase != kernel.Dispatched ||
			(prior.DispatchOwner == update.DispatchOwner && prior.DispatchGeneration == update.DispatchGeneration)) {
		return nil
	}
	next := c.state.Clone()
	if err := next.MoveOperation(id, update); err != nil {
		return err
	}
	body := phaseEvent{SemanticVersion: semanticVersion, ID: id, Update: update}
	event, err := c.history.Append(eventOperationPhase, body)
	if err != nil {
		return c.appendError(err)
	}
	if err := c.advanceAnchor(event); err != nil {
		return err
	}
	next.History = kernel.HistoryPoint{Sequence: event.Sequence, Hash: event.Hash}
	c.state = next
	return nil
}

func (c *Control) advanceAnchor(event history.Event) error {
	if err := c.anchor.Advance(headanchor.Head{Sequence: event.Sequence, Hash: event.Hash}); err != nil {
		c.failed = err
		return fmt.Errorf("%w: advance external History head: %v", ErrNeedsReopen, err)
	}
	return nil
}

func (c *Control) appendError(err error) error {
	if errors.Is(err, history.ErrNeedsReopen) {
		c.failed = err
		return fmt.Errorf("%w: %v", ErrNeedsReopen, err)
	}
	return err
}

func apply(state *kernel.State, bindings *sandboxRegistry, operation string, data json.RawMessage) error {
	switch operation {
	case eventRuleActivated:
		if bindings == nil {
			return errors.New("nil sandbox binding registry")
		}
		if len(bindings.desired) != 0 {
			return ErrActiveSandboxBindings
		}
		var event ruleEvent
		if err := decodeStrict(data, &event); err != nil {
			return err
		}
		if event.SemanticVersion != semanticVersion {
			return fmt.Errorf("unsupported rule semantic version %d", event.SemanticVersion)
		}
		if err := checkCertificate(state, event.Certificate); err != nil {
			return err
		}
		return state.Activate(event.Certificate)
	case eventOperationPrepare:
		var event prepareEvent
		if err := decodeStrict(data, &event); err != nil {
			return err
		}
		if event.SemanticVersion != semanticVersion {
			return fmt.Errorf("unsupported prepare semantic version %d", event.SemanticVersion)
		}
		expected := event.Operation
		sandboxID := expected.SandboxID
		if sandboxID == "" && bindings != nil {
			for _, binding := range bindings.desired {
				if binding.Domain != expected.Domain {
					continue
				}
				if sandboxID != "" {
					return fmt.Errorf("legacy operation %q has multiple sandbox owners", expected.ID)
				}
				sandboxID = binding.SandboxID
			}
		}
		var actual kernel.Operation
		var err error
		if expected.RequestStored {
			if sandboxID == "" {
				actual, err = state.PrepareWithRequest(
					expected.ID, expected.Domain, expected.Kind, expected.RequestHash,
					expected.RequestHeaders, expected.RequestBody,
				)
			} else {
				actual, err = state.PrepareWithRequestForSandbox(
					expected.ID, expected.Domain, sandboxID, expected.Kind,
					expected.RequestHash, expected.RequestHeaders, expected.RequestBody,
				)
				expected.SandboxID = sandboxID
			}
		} else {
			if sandboxID != "" {
				return fmt.Errorf("legacy sandbox operation %q has no stored request", expected.ID)
			}
			actual, err = state.Prepare(expected.ID, expected.Domain, expected.Kind, expected.RequestHash)
		}
		if err != nil {
			return err
		}
		actualJSON, _ := json.Marshal(actual)
		expectedJSON, _ := json.Marshal(expected)
		if string(actualJSON) != string(expectedJSON) {
			return errors.New("prepared operation differs from deterministic replay")
		}
		return nil
	case eventOperationPhase:
		var event phaseEvent
		if err := decodeStrict(data, &event); err != nil {
			return err
		}
		if event.SemanticVersion != semanticVersion {
			return fmt.Errorf("unsupported phase semantic version %d", event.SemanticVersion)
		}
		return state.MoveOperation(event.ID, event.Update)
	case eventRuleBindingsCutover:
		return applyRuleBindingsCutover(state, bindings, data)
	default:
		return fmt.Errorf("unknown durable event %q", operation)
	}
}

func decodeStrict(data []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("multiple JSON values")
		}
		return err
	}
	return nil
}
