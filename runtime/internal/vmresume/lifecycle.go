package vmresume

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sync"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const maxLifecycleFactsBytes = 1 << 20

// LifecycleRequest binds one backend execution primitive to the exact edit
// decision, activated History, sandbox binding, and backend-specific live
// facts. RuntimeFacts must be canonical JSON and are interpreted only by the
// backend validator supplied to NewLifecycleGuard.
type LifecycleRequest struct {
	CheckedState     *kernel.State          `json:"checked_state"`
	Certificate      kernel.Certificate     `json:"certificate"`
	ActivatedHistory kernel.HistoryPoint    `json:"activated_history"`
	Binding          control.SandboxBinding `json:"binding"`
	RuntimeFacts     json.RawMessage        `json:"runtime_facts"`
}

// LifecycleSources supplies fresh host facts. Start must be the sole owner of
// the backend execution primitive, such as Firecracker InstanceStart.
type LifecycleSources struct {
	CurrentState    func() (*kernel.State, error)
	ValidateBinding func(control.SandboxBinding) error
	ValidateRuntime func(context.Context, json.RawMessage) error
	Start           func(context.Context) error
}

// LifecycleAuthorization is opaque outside this package and can be consumed
// once by the LifecycleGuard that issued it.
type LifecycleAuthorization struct {
	nonce  [32]byte
	digest [32]byte
}

type pendingLifecycleAuthorization struct {
	authorization LifecycleAuthorization
	request       LifecycleRequest
}

// LifecycleGuard serializes decision validation and one backend start. It is
// backend-neutral: backend identity and immutable-artifact checks are supplied
// through RuntimeFacts and ValidateRuntime.
type LifecycleGuard struct {
	mu      sync.Mutex
	sources LifecycleSources
	pending *pendingLifecycleAuthorization
	used    bool
}

func NewLifecycleGuard(sources LifecycleSources) (*LifecycleGuard, error) {
	if sources.CurrentState == nil || sources.ValidateBinding == nil ||
		sources.ValidateRuntime == nil || sources.Start == nil {
		return nil, errors.New("lifecycle guard requires all host fact sources")
	}
	return &LifecycleGuard{sources: sources}, nil
}

// Authorize independently verifies the checked Certificate. Impossible
// decisions fail before any live-state or backend-start callback. Activate
// decisions validate every live fact and issue one opaque authorization.
func (g *LifecycleGuard) Authorize(ctx context.Context, request LifecycleRequest) (LifecycleAuthorization, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.pending = nil
	g.used = false
	decision := decisionRequest{
		CheckedState: request.CheckedState, Certificate: request.Certificate,
		ActivatedHistory: request.ActivatedHistory,
	}
	if err := validateCheckedDecision(decision); err != nil {
		return LifecycleAuthorization{}, err
	}
	if request.Certificate.Decision != kernel.Activate {
		return LifecycleAuthorization{}, fmt.Errorf("%w: Certificate decision is %q", ErrDenied, request.Certificate.Decision)
	}
	if err := validateLifecycleFacts(request.RuntimeFacts); err != nil {
		return LifecycleAuthorization{}, err
	}
	if err := g.validateCurrent(ctx, request); err != nil {
		return LifecycleAuthorization{}, err
	}
	encoded, err := json.Marshal(request)
	if err != nil {
		return LifecycleAuthorization{}, err
	}
	var authorization LifecycleAuthorization
	if _, err := rand.Read(authorization.nonce[:]); err != nil {
		return LifecycleAuthorization{}, err
	}
	digest := sha256.New()
	_, _ = digest.Write(encoded)
	_, _ = digest.Write(authorization.nonce[:])
	copy(authorization.digest[:], digest.Sum(nil))
	g.pending = &pendingLifecycleAuthorization{
		authorization: authorization, request: cloneLifecycleRequest(request),
	}
	return authorization, nil
}

// Start consumes one authorization after immediately revalidating all dynamic
// facts. A failed backend start cannot be retried with the same authority.
func (g *LifecycleGuard) Start(ctx context.Context, authorization LifecycleAuthorization) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.used {
		return ErrConsumed
	}
	if g.pending == nil || authorization != g.pending.authorization {
		return ErrUnauthorized
	}
	request := g.pending.request
	g.pending = nil
	g.used = true
	if err := g.validateCurrent(ctx, request); err != nil {
		return fmt.Errorf("revalidate lifecycle facts: %w", err)
	}
	if err := g.sources.Start(ctx); err != nil {
		return fmt.Errorf("backend start failed after authorization was consumed: %w", err)
	}
	return nil
}

func (g *LifecycleGuard) validateCurrent(ctx context.Context, request LifecycleRequest) error {
	state, err := g.sources.CurrentState()
	if err != nil {
		return fmt.Errorf("read current State: %w", err)
	}
	decision := decisionRequest{
		CheckedState: request.CheckedState, Certificate: request.Certificate,
		ActivatedHistory: request.ActivatedHistory,
	}
	if err := validateActivatedState(state, decision); err != nil {
		return err
	}
	if err := g.sources.ValidateBinding(request.Binding); err != nil {
		return fmt.Errorf("validate sandbox binding: %w", err)
	}
	if err := g.sources.ValidateRuntime(ctx, append(json.RawMessage(nil), request.RuntimeFacts...)); err != nil {
		return fmt.Errorf("validate backend runtime facts: %w", err)
	}
	return nil
}

func validateLifecycleFacts(facts json.RawMessage) error {
	if len(facts) == 0 || len(facts) > maxLifecycleFactsBytes {
		return errors.New("lifecycle runtime facts are empty or oversized")
	}
	decoder := json.NewDecoder(bytes.NewReader(facts))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return fmt.Errorf("decode lifecycle runtime facts: %w", err)
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return errors.New("lifecycle runtime facts contain trailing JSON")
	}
	canonical, err := json.Marshal(value)
	if err != nil {
		return err
	}
	if !bytes.Equal(canonical, facts) {
		return errors.New("lifecycle runtime facts are not canonical JSON")
	}
	return nil
}

func cloneLifecycleRequest(request LifecycleRequest) LifecycleRequest {
	encoded, err := json.Marshal(request)
	if err != nil {
		panic(err)
	}
	var clone LifecycleRequest
	if err := json.Unmarshal(encoded, &clone); err != nil {
		panic(err)
	}
	return clone
}
