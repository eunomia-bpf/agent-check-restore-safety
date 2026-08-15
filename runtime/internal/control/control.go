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
	"sync"

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

type Control struct {
	mu               sync.RWMutex
	history          *history.History
	anchor           *headanchor.Anchor
	state            *kernel.State
	bootID           string
	failed           error
	closing          bool
	activeDispatches int
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
	for _, event := range record.Events() {
		if event.Sequence != state.History.Sequence+1 || event.PreviousHash != state.History.Hash {
			_ = anchor.Close()
			_ = record.Close()
			return nil, errors.New("durable event does not extend reconstructed state")
		}
		if err := apply(state, event.Operation, event.Data); err != nil {
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
		history: record, anchor: anchor, state: state, bootID: hex.EncodeToString(bootBytes),
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
	return kernel.Compile(c.state, requirement, next)
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

func (c *Control) Prepare(id, domain, kind, requestHash string) (kernel.Operation, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.history == nil {
		return kernel.Operation{}, history.ErrClosed
	}
	if c.closing {
		return kernel.Operation{}, ErrClosing
	}
	if c.failed != nil {
		return kernel.Operation{}, fmt.Errorf("%w: %v", ErrNeedsReopen, c.failed)
	}
	if prior, ok := c.state.Operations[id]; ok {
		if prior.Domain != domain || prior.Kind != kind || prior.RequestHash != requestHash {
			return kernel.Operation{}, errors.New("stable operation identity is already bound to different work")
		}
		return prior, nil
	}
	next := c.state.Clone()
	operation, err := next.Prepare(id, domain, kind, requestHash)
	if err != nil {
		return kernel.Operation{}, err
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
	return operation, nil
}

func (c *Control) Move(id string, update kernel.OperationUpdate) error {
	c.mu.Lock()
	defer c.mu.Unlock()
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

func apply(state *kernel.State, operation string, data json.RawMessage) error {
	switch operation {
	case eventRuleActivated:
		var event ruleEvent
		if err := decodeStrict(data, &event); err != nil {
			return err
		}
		if event.SemanticVersion != semanticVersion {
			return fmt.Errorf("unsupported rule semantic version %d", event.SemanticVersion)
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
		actual, err := state.Prepare(expected.ID, expected.Domain, expected.Kind, expected.RequestHash)
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
