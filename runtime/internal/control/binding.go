package control

import (
	"encoding/hex"
	"errors"
	"fmt"
	"math"
	"sort"
	"strings"
	"sync"
	"unicode"
	"unicode/utf8"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/history"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const (
	cutoverSemanticVersion           = 1
	repositoryCutoverSemanticVersion = 2
	maxSandboxBindings               = 1024
	maxRepositoryArtifactBytes       = uint64(2 << 30)
)

const eventRuleBindingsCutover = "rule.bindings.cutover"

var (
	ErrActiveSandboxBindings  = errors.New("active sandbox bindings require an atomic cutover")
	ErrActiveAdapterDispatch  = errors.New("an adapter call is active in a sandbox domain")
	ErrSandboxBindingRequired = errors.New("adapter domain requires its host-bound sandbox endpoint")
	ErrSandboxAlreadyAttached = errors.New("sandbox is already attached to this control boot")
	ErrSandboxNotAttached     = errors.New("sandbox is not attached to this control boot")
	ErrStaleSandboxBinding    = errors.New("sandbox binding is stale")
)

// SandboxBinding is host-owned authority for one concrete sandbox instance.
// It is durable control metadata, deliberately separate from kernel.State.
type SandboxBinding struct {
	SandboxID      string   `json:"sandbox_id"`
	Generation     uint64   `json:"generation"`
	HostInstanceID string   `json:"host_instance_id"`
	Domain         string   `json:"domain"`
	AllowedKinds   []string `json:"allowed_kinds"`
	RepositoryRoot string   `json:"repository_root,omitempty"`
}

// RepositoryChange binds a repository exported by the currently active
// sandbox to the replacement binding published by the same durable Cutover.
// The artifact bytes remain outside History; exact hashes, sizes, and both
// tree roots are inside the History event.
type RepositoryChange struct {
	SandboxID         string `json:"sandbox_id"`
	SourceGeneration  uint64 `json:"source_generation"`
	SourceHostID      string `json:"source_host_instance_id"`
	CheckpointSHA256  string `json:"checkpoint_sha256"`
	BaseRoot          string `json:"base_root"`
	FinalRoot         string `json:"final_root"`
	FinalBundleSHA256 string `json:"final_bundle_sha256"`
	FinalBundleSize   uint64 `json:"final_bundle_size"`
	DeltaSHA256       string `json:"delta_sha256"`
	DeltaSize         uint64 `json:"delta_size"`
}

type ruleBindingsCutoverEvent struct {
	SemanticVersion int                `json:"semantic_version"`
	Certificate     kernel.Certificate `json:"certificate"`
	Bindings        []SandboxBinding   `json:"bindings"`
	Repositories    []RepositoryChange `json:"repositories,omitempty"`
}

// sandboxRegistry is reconstructed from History but is not part of the five
// kernel objects. desired is the complete durable set at the current head;
// the other maps retain enough History-derived identity to reject reuse.
type sandboxRegistry struct {
	desired            map[string]SandboxBinding
	maxGeneration      map[string]uint64
	stableDomain       map[string]string
	seenHostInstanceID map[string]struct{}
}

func newSandboxRegistry() sandboxRegistry {
	return sandboxRegistry{
		desired:            make(map[string]SandboxBinding),
		maxGeneration:      make(map[string]uint64),
		stableDomain:       make(map[string]string),
		seenHostInstanceID: make(map[string]struct{}),
	}
}

func (r sandboxRegistry) clone() sandboxRegistry {
	out := newSandboxRegistry()
	for id, binding := range r.desired {
		out.desired[id] = cloneSandboxBinding(binding)
	}
	for id, generation := range r.maxGeneration {
		out.maxGeneration[id] = generation
	}
	for id, domain := range r.stableDomain {
		out.stableDomain[id] = domain
	}
	for id := range r.seenHostInstanceID {
		out.seenHostInstanceID[id] = struct{}{}
	}
	return out
}

func (r *sandboxRegistry) advance(complete []SandboxBinding) error {
	for _, binding := range complete {
		prior := r.maxGeneration[binding.SandboxID]
		if prior == math.MaxUint64 {
			return fmt.Errorf("sandbox %q generation is exhausted", binding.SandboxID)
		}
		if binding.Generation != prior+1 {
			return fmt.Errorf("sandbox %q generation is %d, want %d", binding.SandboxID, binding.Generation, prior+1)
		}
		if _, reused := r.seenHostInstanceID[binding.HostInstanceID]; reused {
			return fmt.Errorf("sandbox host instance %q was already used", binding.HostInstanceID)
		}
		if domain, exists := r.stableDomain[binding.SandboxID]; exists && domain != binding.Domain {
			return fmt.Errorf(
				"sandbox %q changed stable domain from %q to %q",
				binding.SandboxID, domain, binding.Domain,
			)
		}
	}
	next := make(map[string]SandboxBinding, len(complete))
	for _, binding := range complete {
		owned := cloneSandboxBinding(binding)
		next[owned.SandboxID] = owned
		r.maxGeneration[owned.SandboxID] = owned.Generation
		r.stableDomain[owned.SandboxID] = owned.Domain
		r.seenHostInstanceID[owned.HostInstanceID] = struct{}{}
	}
	r.desired = next
	return nil
}

func cloneSandboxBinding(binding SandboxBinding) SandboxBinding {
	binding.AllowedKinds = append([]string(nil), binding.AllowedKinds...)
	return binding
}

func sortedBindings(input map[string]SandboxBinding) []SandboxBinding {
	ids := make([]string, 0, len(input))
	for id := range input {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	out := make([]SandboxBinding, 0, len(ids))
	for _, id := range ids {
		out = append(out, cloneSandboxBinding(input[id]))
	}
	return out
}

func validateBindingText(label, value string) error {
	if value == "" {
		return fmt.Errorf("sandbox binding %s is empty", label)
	}
	if len(value) > kernel.MaxNameBytes {
		return fmt.Errorf("sandbox binding %s exceeds %d bytes", label, kernel.MaxNameBytes)
	}
	if !utf8.ValidString(value) {
		return fmt.Errorf("sandbox binding %s is not valid UTF-8", label)
	}
	for _, character := range value {
		if unicode.IsControl(character) {
			return fmt.Errorf("sandbox binding %s contains a control character", label)
		}
	}
	return nil
}

func canonicalSandboxBinding(binding SandboxBinding) (SandboxBinding, error) {
	for _, field := range []struct {
		label string
		value string
	}{
		{label: "sandbox id", value: binding.SandboxID},
		{label: "host instance id", value: binding.HostInstanceID},
		{label: "domain", value: binding.Domain},
	} {
		if err := validateBindingText(field.label, field.value); err != nil {
			return SandboxBinding{}, err
		}
	}
	if binding.Generation == 0 {
		return SandboxBinding{}, errors.New("sandbox binding generation is zero")
	}
	if binding.RepositoryRoot != "" {
		if err := validateSHA256("sandbox binding repository root", binding.RepositoryRoot); err != nil {
			return SandboxBinding{}, err
		}
	}
	if len(binding.AllowedKinds) == 0 {
		return SandboxBinding{}, errors.New("sandbox binding has no allowed kind")
	}
	if len(binding.AllowedKinds) > kernel.MaxRequirementKinds {
		return SandboxBinding{}, fmt.Errorf("sandbox binding has more than %d allowed kinds", kernel.MaxRequirementKinds)
	}
	kinds := append([]string(nil), binding.AllowedKinds...)
	sort.Strings(kinds)
	for index, kind := range kinds {
		if err := validateBindingText("allowed kind", kind); err != nil {
			return SandboxBinding{}, err
		}
		if index != 0 && kinds[index-1] == kind {
			return SandboxBinding{}, fmt.Errorf("sandbox binding repeats allowed kind %q", kind)
		}
	}
	binding.AllowedKinds = kinds
	return binding, nil
}

func canonicalSandboxBindings(bindings []SandboxBinding) ([]SandboxBinding, error) {
	if len(bindings) > maxSandboxBindings {
		return nil, fmt.Errorf("sandbox binding count exceeds %d", maxSandboxBindings)
	}
	canonical := make([]SandboxBinding, len(bindings))
	for index, binding := range bindings {
		owned, err := canonicalSandboxBinding(binding)
		if err != nil {
			return nil, fmt.Errorf("binding %d: %w", index, err)
		}
		canonical[index] = owned
	}
	sort.Slice(canonical, func(left, right int) bool {
		return canonical[left].SandboxID < canonical[right].SandboxID
	})
	seenHosts := make(map[string]string, len(canonical))
	for index, binding := range canonical {
		if index != 0 && canonical[index-1].SandboxID == binding.SandboxID {
			return nil, fmt.Errorf("duplicate sandbox id %q", binding.SandboxID)
		}
		if prior, duplicate := seenHosts[binding.HostInstanceID]; duplicate {
			return nil, fmt.Errorf("host instance %q is shared by sandboxes %q and %q", binding.HostInstanceID, prior, binding.SandboxID)
		}
		seenHosts[binding.HostInstanceID] = binding.SandboxID
	}
	return canonical, nil
}

func sandboxBindingEqual(left, right SandboxBinding) bool {
	if left.SandboxID != right.SandboxID || left.Generation != right.Generation ||
		left.HostInstanceID != right.HostInstanceID || left.Domain != right.Domain ||
		left.RepositoryRoot != right.RepositoryRoot ||
		len(left.AllowedKinds) != len(right.AllowedKinds) {
		return false
	}
	for index := range left.AllowedKinds {
		if left.AllowedKinds[index] != right.AllowedKinds[index] {
			return false
		}
	}
	return true
}

func validateSHA256(label, value string) error {
	if len(value) != 64 || strings.ToLower(value) != value {
		return fmt.Errorf("%s must be 64 lowercase hexadecimal characters", label)
	}
	if _, err := hex.DecodeString(value); err != nil {
		return fmt.Errorf("%s is not hexadecimal", label)
	}
	return nil
}

func canonicalRepositoryChanges(changes []RepositoryChange) ([]RepositoryChange, error) {
	if len(changes) > maxSandboxBindings {
		return nil, fmt.Errorf("repository change count exceeds %d", maxSandboxBindings)
	}
	canonical := append([]RepositoryChange(nil), changes...)
	for index, change := range canonical {
		if err := validateBindingText("repository sandbox id", change.SandboxID); err != nil {
			return nil, fmt.Errorf("repository change %d: %w", index, err)
		}
		if change.SourceGeneration == 0 {
			return nil, fmt.Errorf("repository change %d has zero source generation", index)
		}
		if err := validateBindingText("repository source host instance id", change.SourceHostID); err != nil {
			return nil, fmt.Errorf("repository change %d: %w", index, err)
		}
		for _, digest := range []struct {
			label string
			value string
		}{
			{"checkpoint SHA-256", change.CheckpointSHA256},
			{"base repository root", change.BaseRoot},
			{"final repository root", change.FinalRoot},
			{"final repository bundle SHA-256", change.FinalBundleSHA256},
			{"repository delta SHA-256", change.DeltaSHA256},
		} {
			if err := validateSHA256(digest.label, digest.value); err != nil {
				return nil, fmt.Errorf("repository change %d: %w", index, err)
			}
		}
		if change.FinalBundleSize == 0 || change.FinalBundleSize > maxRepositoryArtifactBytes || change.FinalBundleSize%512 != 0 {
			return nil, fmt.Errorf("repository change %d has invalid final bundle size %d", index, change.FinalBundleSize)
		}
		if change.DeltaSize == 0 || change.DeltaSize > maxRepositoryArtifactBytes {
			return nil, fmt.Errorf("repository change %d has invalid delta size %d", index, change.DeltaSize)
		}
	}
	sort.Slice(canonical, func(left, right int) bool {
		return canonical[left].SandboxID < canonical[right].SandboxID
	})
	for index := 1; index < len(canonical); index++ {
		if canonical[index-1].SandboxID == canonical[index].SandboxID {
			return nil, fmt.Errorf("duplicate repository sandbox id %q", canonical[index].SandboxID)
		}
	}
	return canonical, nil
}

func repositoryChangesEqual(left, right []RepositoryChange) bool {
	if (left == nil) != (right == nil) || len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}

func validateRepositoryTransitions(current sandboxRegistry, target []SandboxBinding, changes []RepositoryChange) error {
	targetByID := make(map[string]SandboxBinding, len(target))
	for _, binding := range target {
		targetByID[binding.SandboxID] = binding
	}
	changeByID := make(map[string]RepositoryChange, len(changes))
	for _, change := range changes {
		prior, exists := current.desired[change.SandboxID]
		if !exists {
			return fmt.Errorf("repository change for sandbox %q has no active source binding", change.SandboxID)
		}
		next, exists := targetByID[change.SandboxID]
		if !exists {
			return fmt.Errorf("repository change for sandbox %q has no replacement binding", change.SandboxID)
		}
		if prior.RepositoryRoot == "" {
			return fmt.Errorf("repository change for sandbox %q has no recorded base root", change.SandboxID)
		}
		if change.SourceGeneration != prior.Generation || change.SourceHostID != prior.HostInstanceID || change.BaseRoot != prior.RepositoryRoot {
			return fmt.Errorf("repository change for sandbox %q differs from its active source", change.SandboxID)
		}
		if change.FinalRoot != next.RepositoryRoot {
			return fmt.Errorf("repository change for sandbox %q differs from its replacement root", change.SandboxID)
		}
		changeByID[change.SandboxID] = change
	}
	for id, prior := range current.desired {
		next, retained := targetByID[id]
		if !retained || prior.RepositoryRoot == next.RepositoryRoot {
			continue
		}
		if prior.RepositoryRoot == "" || next.RepositoryRoot == "" {
			return fmt.Errorf("sandbox %q cannot add or remove a repository root during replacement", id)
		}
		if _, exists := changeByID[id]; !exists {
			return fmt.Errorf("sandbox %q changed repository root without a repository change", id)
		}
	}
	return nil
}

func sandboxBindingsEqual(left, right []SandboxBinding) bool {
	if (left == nil) != (right == nil) || len(left) != len(right) {
		return false
	}
	for index := range left {
		if !sandboxBindingEqual(left[index], right[index]) {
			return false
		}
	}
	return true
}

func validateBindingKinds(state *kernel.State, bindings []SandboxBinding) error {
	if state.Requirement == nil {
		return errors.New("sandbox bindings require an active Requirement")
	}
	for _, binding := range bindings {
		for _, kind := range binding.AllowedKinds {
			if _, exists := state.Requirement.Kinds[kind]; !exists {
				return fmt.Errorf("sandbox %q allows unknown operation kind %q", binding.SandboxID, kind)
			}
		}
	}
	return nil
}

// validateRecoverableBindingOperations prevents a cutover from fencing the
// only caller that still holds request bytes needed to finish an open
// Operation. Bound sandboxes always record those bytes before network I/O;
// this check matters when adopting bindings over an older History.
func validateRecoverableBindingOperations(state *kernel.State, bindings []SandboxBinding) error {
	domains := make(map[string]struct{}, len(bindings))
	for _, binding := range bindings {
		domains[binding.Domain] = struct{}{}
	}
	ids := make([]string, 0, len(state.Operations))
	for id := range state.Operations {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		operation := state.Operations[id]
		if _, bound := domains[operation.Domain]; !bound || operation.RequestStored {
			continue
		}
		switch operation.Phase {
		case kernel.Prepared, kernel.Dispatched, kernel.Unknown:
			return fmt.Errorf(
				"sandbox domain %q has open operation %q without a stored request",
				operation.Domain, operation.ID,
			)
		}
	}
	return nil
}

func (c *Control) rejectActiveAdaptersLocked(bindings []SandboxBinding) error {
	for _, binding := range bindings {
		if c.activeAdapters[binding.Domain] != 0 {
			return fmt.Errorf("%w %q", ErrActiveAdapterDispatch, binding.Domain)
		}
	}
	return nil
}

// Cutover durably publishes one Rule and the complete desired sandbox set in
// one History event. Every listed sandbox is a fresh host instance whose
// generation strictly follows its last recorded generation. The event does
// not attach a sandbox: the host must do that explicitly after the cutover.
func (c *Control) Cutover(certificate kernel.Certificate, completeBindings []SandboxBinding) error {
	return c.CutoverWithRepositoryChanges(certificate, completeBindings, nil)
}

// CutoverWithRepositoryChanges durably commits the Rule, replacement sandbox
// set, and host-derived repository results in one History event. A repository
// root may change only when the event also binds the active source instance,
// the VM checkpoint, the complete final bundle, and the canonical delta.
func (c *Control) CutoverWithRepositoryChanges(certificate kernel.Certificate, completeBindings []SandboxBinding, repositoryChanges []RepositoryChange) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.bindingReadyLocked(); err != nil {
		return err
	}
	if err := checkCertificate(c.state, certificate); err != nil {
		return err
	}
	nextState := c.state.Clone()
	if err := nextState.Activate(certificate); err != nil {
		return err
	}
	canonical, err := canonicalSandboxBindings(completeBindings)
	if err != nil {
		return err
	}
	canonicalRepositories, err := canonicalRepositoryChanges(repositoryChanges)
	if err != nil {
		return err
	}
	if err := validateRepositoryTransitions(c.bindings, canonical, canonicalRepositories); err != nil {
		return err
	}
	if err := c.rejectActiveAdaptersLocked(canonical); err != nil {
		return err
	}
	if err := validateBindingKinds(nextState, canonical); err != nil {
		return err
	}
	if err := validateRecoverableBindingOperations(nextState, canonical); err != nil {
		return err
	}
	nextBindings := c.bindings.clone()
	if err := nextBindings.advance(canonical); err != nil {
		return err
	}
	eventVersion := cutoverSemanticVersion
	if len(canonicalRepositories) != 0 {
		eventVersion = repositoryCutoverSemanticVersion
	}
	event, err := c.history.Append(eventRuleBindingsCutover, ruleBindingsCutoverEvent{
		SemanticVersion: eventVersion,
		Certificate:     certificate,
		Bindings:        canonical,
		Repositories:    canonicalRepositories,
	})
	if err != nil {
		return c.appendError(err)
	}
	if err := c.advanceAnchor(event); err != nil {
		return err
	}
	nextState.History = kernel.HistoryPoint{Sequence: event.Sequence, Hash: event.Hash}
	c.state = nextState
	c.bindings = nextBindings
	c.attachEligible = make(map[string]SandboxBinding, len(canonical))
	for _, binding := range canonical {
		c.attachEligible[binding.SandboxID] = cloneSandboxBinding(binding)
	}
	c.attachedBindings = make(map[string]SandboxBinding)
	return nil
}

func applyRuleBindingsCutover(state *kernel.State, bindings *sandboxRegistry, data []byte) error {
	if bindings == nil {
		return errors.New("nil sandbox binding registry")
	}
	var event ruleBindingsCutoverEvent
	if err := decodeStrict(data, &event); err != nil {
		return err
	}
	if event.SemanticVersion != cutoverSemanticVersion && event.SemanticVersion != repositoryCutoverSemanticVersion {
		return fmt.Errorf("unsupported rule-and-binding cutover semantic version %d", event.SemanticVersion)
	}
	canonical, err := canonicalSandboxBindings(event.Bindings)
	if err != nil {
		return err
	}
	if !sandboxBindingsEqual(event.Bindings, canonical) {
		return errors.New("sandbox bindings are not in canonical order")
	}
	canonicalRepositories, err := canonicalRepositoryChanges(event.Repositories)
	if err != nil {
		return err
	}
	if !repositoryChangesEqual(event.Repositories, canonicalRepositories) {
		return errors.New("repository changes are not in canonical order")
	}
	if event.SemanticVersion == cutoverSemanticVersion && len(canonicalRepositories) != 0 {
		return errors.New("legacy rule-and-binding cutover contains repository changes")
	}
	if event.SemanticVersion == repositoryCutoverSemanticVersion && len(canonicalRepositories) == 0 {
		return errors.New("repository cutover contains no repository change")
	}
	if err := checkCertificate(state, event.Certificate); err != nil {
		return err
	}
	nextState := state.Clone()
	if err := nextState.Activate(event.Certificate); err != nil {
		return err
	}
	if err := validateBindingKinds(nextState, canonical); err != nil {
		return err
	}
	if err := validateRecoverableBindingOperations(nextState, canonical); err != nil {
		return err
	}
	if err := validateRepositoryTransitions(*bindings, canonical, canonicalRepositories); err != nil {
		return err
	}
	nextBindings := bindings.clone()
	if err := nextBindings.advance(canonical); err != nil {
		return err
	}
	*state = *nextState
	*bindings = nextBindings
	return nil
}

func (c *Control) bindingReadyLocked() error {
	if c.history == nil {
		return history.ErrClosed
	}
	if c.closing {
		return ErrClosing
	}
	if c.failed != nil {
		return fmt.Errorf("%w: %v", ErrNeedsReopen, c.failed)
	}
	return nil
}

func (c *Control) validateSandboxLocked(binding SandboxBinding) (SandboxBinding, error) {
	if err := c.bindingReadyLocked(); err != nil {
		return SandboxBinding{}, err
	}
	canonical, err := canonicalSandboxBinding(binding)
	if err != nil {
		return SandboxBinding{}, err
	}
	desired, exists := c.bindings.desired[canonical.SandboxID]
	if !exists || !sandboxBindingEqual(desired, canonical) {
		return SandboxBinding{}, ErrStaleSandboxBinding
	}
	attached, exists := c.attachedBindings[canonical.SandboxID]
	if !exists || !sandboxBindingEqual(attached, canonical) {
		return SandboxBinding{}, ErrSandboxNotAttached
	}
	return cloneSandboxBinding(desired), nil
}

func bindingAllowsKind(binding SandboxBinding, kind string) bool {
	index := sort.SearchStrings(binding.AllowedKinds, kind)
	return index != len(binding.AllowedKinds) && binding.AllowedKinds[index] == kind
}

func validateSandboxOperation(binding SandboxBinding, operation kernel.Operation) error {
	if operation.Domain != binding.Domain {
		return fmt.Errorf("operation %q belongs to domain %q, not sandbox domain %q", operation.ID, operation.Domain, binding.Domain)
	}
	if operation.SandboxID != binding.SandboxID {
		return fmt.Errorf(
			"operation %q belongs to sandbox %q, not sandbox %q",
			operation.ID, operation.SandboxID, binding.SandboxID,
		)
	}
	return nil
}

// SandboxBindings returns the complete durable desired set at the current
// History head. Returned bindings and their AllowedKinds are independent.
func (c *Control) SandboxBindings() []SandboxBinding {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return sortedBindings(c.bindings.desired)
}

// SnapshotWithSandboxBindings returns one internally consistent control view.
func (c *Control) SnapshotWithSandboxBindings() (*kernel.State, []SandboxBinding) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.state.Clone(), sortedBindings(c.bindings.desired)
}

// AttachSandboxHost is a host-supervisor operation. Only a binding published
// by a successful Cutover in this Control boot is eligible; replay alone never
// re-enables a restored or restarted sandbox.
func (c *Control) AttachSandboxHost(binding SandboxBinding) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.bindingReadyLocked(); err != nil {
		return err
	}
	canonical, err := canonicalSandboxBinding(binding)
	if err != nil {
		return err
	}
	desired, desiredExists := c.bindings.desired[canonical.SandboxID]
	eligible, eligibleExists := c.attachEligible[canonical.SandboxID]
	if !desiredExists || !eligibleExists || !sandboxBindingEqual(desired, canonical) ||
		!sandboxBindingEqual(eligible, canonical) {
		if attached, exists := c.attachedBindings[canonical.SandboxID]; exists &&
			sandboxBindingEqual(attached, canonical) {
			return ErrSandboxAlreadyAttached
		}
		return ErrStaleSandboxBinding
	}
	delete(c.attachEligible, canonical.SandboxID)
	c.attachedBindings[canonical.SandboxID] = cloneSandboxBinding(canonical)
	return nil
}

// AttachSandboxHosts atomically attaches the complete desired sandbox set.
// It is used by a host supervisor after every endpoint has been created but
// before any endpoint starts serving. Either every binding from the latest
// Cutover becomes live in this Control boot or none does.
func (c *Control) AttachSandboxHosts(completeBindings []SandboxBinding) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.bindingReadyLocked(); err != nil {
		return err
	}
	canonical, err := canonicalSandboxBindings(completeBindings)
	if err != nil {
		return err
	}
	if len(canonical) != len(c.bindings.desired) {
		return errors.New("sandbox attachment must contain the complete desired set")
	}
	if len(c.attachedBindings) != 0 {
		return ErrSandboxAlreadyAttached
	}
	for _, binding := range canonical {
		desired, desiredExists := c.bindings.desired[binding.SandboxID]
		eligible, eligibleExists := c.attachEligible[binding.SandboxID]
		if !desiredExists || !eligibleExists || !sandboxBindingEqual(desired, binding) ||
			!sandboxBindingEqual(eligible, binding) {
			return ErrStaleSandboxBinding
		}
	}
	for _, binding := range canonical {
		delete(c.attachEligible, binding.SandboxID)
		c.attachedBindings[binding.SandboxID] = cloneSandboxBinding(binding)
	}
	return nil
}

// DetachSandboxHost closes a matching host attachment without changing the
// durable desired set. A stale host cannot detach a newer instance.
func (c *Control) DetachSandboxHost(binding SandboxBinding) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.bindingReadyLocked(); err != nil {
		return err
	}
	canonical, err := canonicalSandboxBinding(binding)
	if err != nil {
		return err
	}
	attached, exists := c.attachedBindings[canonical.SandboxID]
	if !exists || !sandboxBindingEqual(attached, canonical) {
		return ErrSandboxNotAttached
	}
	delete(c.attachedBindings, canonical.SandboxID)
	return nil
}

// ValidateSandbox checks durable identity and this-boot host attachment under
// the same lock used by Rule changes and Operation progress.
func (c *Control) ValidateSandbox(binding SandboxBinding) error {
	c.mu.RLock()
	defer c.mu.RUnlock()
	_, err := c.validateSandboxLocked(binding)
	return err
}

// BeginSandboxDispatch validates the host-owned binding before admitting a
// live request and keeps Close from releasing the History lock underneath it.
func (c *Control) BeginSandboxDispatch(binding SandboxBinding) (func(), error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, err := c.validateSandboxLocked(binding); err != nil {
		return nil, err
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

// BeginAdapterDispatch admits a bearer-token adapter only while its domain is
// not assigned to a host-bound sandbox. Cutover checks the same live counter
// under Control.mu, so either the whole adapter call precedes the cutover or
// the bound endpoint owns the domain.
func (c *Control) BeginAdapterDispatch(domain string) (func(), error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.bindingReadyLocked(); err != nil {
		return nil, err
	}
	for _, binding := range c.bindings.desired {
		if binding.Domain == domain {
			return nil, fmt.Errorf("%w %q", ErrSandboxBindingRequired, domain)
		}
	}
	c.activeDispatches++
	c.activeAdapters[domain]++
	var once sync.Once
	return func() {
		once.Do(func() {
			c.mu.Lock()
			c.activeDispatches--
			c.activeAdapters[domain]--
			if c.activeAdapters[domain] == 0 {
				delete(c.activeAdapters, domain)
			}
			c.dispatchesDone.Broadcast()
			c.mu.Unlock()
		})
	}, nil
}

// BeginSandboxResponse orders delivery of an Operation result against Cutover.
// The caller must hold the returned read lease until the response has been
// handed to a bounded host transport. Supervisors must put a finite write
// deadline on that transport so an unresponsive guest cannot block Cutover.
func (c *Control) BeginSandboxResponse(binding SandboxBinding) (func(), error) {
	c.mu.RLock()
	if _, err := c.validateSandboxLocked(binding); err != nil {
		c.mu.RUnlock()
		return nil, err
	}
	var once sync.Once
	return func() {
		once.Do(c.mu.RUnlock)
	}, nil
}

// OperationForSandbox validates the binding before looking up an Operation,
// then prevents one sandbox domain from observing another domain's identity.
func (c *Control) OperationForSandbox(binding SandboxBinding, id string) (kernel.Operation, bool, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	current, err := c.validateSandboxLocked(binding)
	if err != nil {
		return kernel.Operation{}, false, err
	}
	operation, exists := c.state.Operations[id]
	if !exists {
		return kernel.Operation{}, false, nil
	}
	if err := validateSandboxOperation(current, operation); err != nil {
		return kernel.Operation{}, false, err
	}
	return cloneOperation(operation), true, nil
}

// OperationForAdapter rejects a bearer-token path for a domain owned by a
// sandbox before it looks up an Operation identity.
func (c *Control) OperationForAdapter(domain, id string) (kernel.Operation, bool, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if err := c.bindingReadyLocked(); err != nil {
		return kernel.Operation{}, false, err
	}
	for _, binding := range c.bindings.desired {
		if binding.Domain == domain {
			return kernel.Operation{}, false, fmt.Errorf("%w %q", ErrSandboxBindingRequired, domain)
		}
	}
	operation, exists := c.state.Operations[id]
	if !exists {
		return kernel.Operation{}, false, nil
	}
	if operation.Domain != domain {
		return kernel.Operation{}, false, fmt.Errorf(
			"operation %q belongs to domain %q, not adapter domain %q",
			operation.ID, operation.Domain, domain,
		)
	}
	if operation.SandboxID != "" {
		return kernel.Operation{}, false, fmt.Errorf(
			"operation %q belongs to sandbox %q, not an adapter",
			operation.ID, operation.SandboxID,
		)
	}
	return cloneOperation(operation), true, nil
}

// OperationRouteForSandbox resolves a new call's HTTP method and target from
// host-owned Rule state. Existing Operations use their own frozen route.
func (c *Control) OperationRouteForSandbox(binding SandboxBinding, kind string) (string, string, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	current, err := c.validateSandboxLocked(binding)
	if err != nil {
		return "", "", err
	}
	if !bindingAllowsKind(current, kind) {
		return "", "", fmt.Errorf("operation kind %q is not allowed for sandbox %q", kind, current.SandboxID)
	}
	spec, exists := c.state.Requirement.Kinds[kind]
	if !exists {
		return "", "", fmt.Errorf("unknown operation kind %q", kind)
	}
	return spec.Method, spec.Target, nil
}

// PrepareWithRequestForSandbox derives the Operation domain from host-owned
// binding state and validates the binding before any Operation lookup.
func (c *Control) PrepareWithRequestForSandbox(
	binding SandboxBinding,
	id, kind, requestHash string,
	headers map[string]string,
	body []byte,
) (kernel.Operation, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	current, err := c.validateSandboxLocked(binding)
	if err != nil {
		return kernel.Operation{}, err
	}
	_, existed := c.state.Operations[id]
	if !existed && !bindingAllowsKind(current, kind) {
		return kernel.Operation{}, fmt.Errorf("operation kind %q is not allowed for sandbox %q", kind, current.SandboxID)
	}
	return c.prepareLocked(
		id, current.Domain, current.SandboxID, kind, requestHash, true, headers, body,
	)
}

// MoveForSandbox records only pre-network control transitions. Binding
// validation and the durable move share Control.mu, so a cutover wins before
// the transition or the transition wins before the new Certificate can
// activate. Definitive or uncertain post-network settlement remains host-owned
// and uses Move.
func (c *Control) MoveForSandbox(binding SandboxBinding, id string, update kernel.OperationUpdate) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	current, err := c.validateSandboxLocked(binding)
	if err != nil {
		return err
	}
	if update.Phase != kernel.Dispatched && update.Phase != kernel.Unknown &&
		update.Phase != kernel.Cancelled {
		return errors.New("sandbox-bound move is only valid before external network I/O")
	}
	operation, exists := c.state.Operations[id]
	if !exists {
		return fmt.Errorf("unknown operation %q", id)
	}
	if err := validateSandboxOperation(current, operation); err != nil {
		return err
	}
	if update.Phase == kernel.Unknown && operation.DispatchOwner == c.bootID {
		return errors.New("current control boot cannot recover its own live dispatch before network completion")
	}
	return c.moveLocked(id, update)
}
