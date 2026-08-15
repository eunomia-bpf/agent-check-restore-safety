package control

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/headanchor"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/history"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

func requirement(id string) kernel.Requirement {
	return kernel.Requirement{
		ID:         id,
		Results:    map[string]uint32{"invoice-paid": 1},
		Capacities: map[string]uint32{"spend": 1},
		Kinds: map[string]kernel.KindSpec{
			"charge": {
				Costs:     map[string]uint32{"spend": 1},
				Produces:  map[string]uint32{"invoice-paid": 1},
				RetrySafe: true,
			},
			"tip": {
				Costs:    map[string]uint32{"spend": 1},
				Produces: map[string]uint32{"tip-sent": 1},
			},
		},
	}
}

func TestExternalHeadRejectsRestoredHistory(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "guest", "runtime.history")
	if err := os.Mkdir(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	anchorPath := filepath.Join(directory, "host", "runtime.head")
	if err := os.Mkdir(filepath.Dir(anchorPath), 0o700); err != nil {
		t.Fatal(err)
	}
	c, err := OpenWithAnchor(path, anchorPath)
	if err != nil {
		t.Fatal(err)
	}
	activate(t, c, "invoice-v1")
	oldHistory, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.Prepare("charge-1", "vm", "charge", "request"); err != nil {
		t.Fatal(err)
	}
	if err := c.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, oldHistory, 0o600); err != nil {
		t.Fatal(err)
	}
	reopened, err := OpenWithAnchor(path, anchorPath)
	if reopened != nil {
		_ = reopened.Close()
	}
	if !errors.Is(err, ErrHistoryRollback) {
		t.Fatalf("restored History error = %v", err)
	}
}

func TestReplayRefusesUnknownSemanticVersionBeforeAdvancingAnchor(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.history")
	c, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Close(); err != nil {
		t.Fatal(err)
	}
	record, err := history.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := record.Append(eventRuleActivated, map[string]any{
		"semantic_version": 2,
		"certificate":      kernel.Certificate{},
	}); err != nil {
		t.Fatal(err)
	}
	if err := record.Close(); err != nil {
		t.Fatal(err)
	}
	if reopened, err := Open(path); err == nil || !strings.Contains(err.Error(), "unsupported rule semantic version") {
		if reopened != nil {
			_ = reopened.Close()
		}
		t.Fatalf("unknown semantic version error = %v", err)
	}
	anchor, err := headanchor.Open(path + ".head-anchor")
	if err != nil {
		t.Fatal(err)
	}
	defer anchor.Close()
	point, err := anchor.Current()
	if err != nil {
		t.Fatal(err)
	}
	if point.Sequence != 0 {
		t.Fatalf("invalid event advanced external anchor to %+v", point)
	}
}

func activate(t *testing.T, control *Control, id string) {
	t.Helper()
	certificate, err := control.Compile(requirement(id))
	if err != nil {
		t.Fatal(err)
	}
	if certificate.Decision != kernel.Activate {
		t.Fatalf("unexpected certificate: %+v", certificate)
	}
	if err := control.Activate(certificate); err != nil {
		t.Fatal(err)
	}
}

func TestDurableReplayPreservesOperationMeaning(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.history")
	first, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	activate(t, first, "invoice-v1")
	if _, err := first.Prepare("tip-1", "agent", "tip", "tip-request"); err == nil {
		t.Fatal("operation that strands invoice-paid was accepted")
	}
	prepared, err := first.Prepare("charge-1", "microservice", "charge", "charge-request")
	if err != nil {
		t.Fatal(err)
	}
	if prepared.RuleVersion != 1 || prepared.Costs["spend"] != 1 {
		t.Fatalf("operation meaning was not frozen: %+v", prepared)
	}
	if err := first.Move("charge-1", kernel.OperationUpdate{Phase: kernel.Dispatched, RemoteReference: "payment-9", DispatchOwner: "boot-a", DispatchGeneration: 1}); err != nil {
		t.Fatal(err)
	}
	if err := first.Move("charge-1", kernel.OperationUpdate{Phase: kernel.Unknown, RemoteReference: "payment-9"}); err != nil {
		t.Fatal(err)
	}
	wantHead := first.Snapshot().History
	if err := first.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	state := reopened.Snapshot()
	if state.History != wantHead {
		t.Fatalf("replayed head = %+v, want %+v", state.History, wantHead)
	}
	op := state.Operations["charge-1"]
	if op.Phase != kernel.Unknown || op.RemoteReference != "payment-9" {
		t.Fatalf("replayed operation = %+v", op)
	}
	if len(reopened.Events()) != 4 {
		t.Fatalf("durable event count = %d", len(reopened.Events()))
	}
}

func TestRuleChangeAndOperationProgressAreSerialized(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.history")
	control, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	activate(t, control, "invoice-v1")
	certificate, err := control.Compile(requirement("invoice-v2"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := control.Prepare("charge-1", "vm", "charge", "request"); err != nil {
		t.Fatal(err)
	}
	if err := control.Activate(certificate); err == nil || !strings.Contains(err.Error(), "stale") {
		t.Fatalf("rule change based on stale operation progress was accepted: %v", err)
	}
	state := control.Snapshot()
	if state.Rule.Version != 1 || state.Requirement.ID != "invoice-v1" {
		t.Fatalf("failed change mutated active state: %+v", state)
	}
}

func TestStableRetryDoesNotAppendAnotherPrepare(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.history")
	control, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	activate(t, control, "invoice-v1")
	if _, err := control.Prepare("charge-1", "agent", "charge", "request"); err != nil {
		t.Fatal(err)
	}
	count := len(control.Events())
	if _, err := control.Prepare("charge-1", "agent", "charge", "request"); err != nil {
		t.Fatal(err)
	}
	if len(control.Events()) != count {
		t.Fatal("stable retry appended another prepare event")
	}
	if _, err := control.Prepare("charge-1", "agent", "charge", "different"); err == nil {
		t.Fatal("stable identity was rebound")
	}
}
