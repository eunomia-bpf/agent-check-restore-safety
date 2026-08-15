package control

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/certcheck"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/headanchor"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/history"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

func resignCertificate(t *testing.T, certificate *kernel.Certificate) {
	t.Helper()
	certificate.Digest = ""
	encoded, err := json.Marshal(certificate)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(encoded)
	certificate.Digest = hex.EncodeToString(digest[:])
}

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

func TestActivationAndReplayRequireIndependentCertificateCheck(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "runtime.history")
	control, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	certificate, err := control.Compile(requirement("invoice-v1"))
	if err != nil {
		t.Fatal(err)
	}
	certificate.Rule.Allow = nil
	resignCertificate(t, &certificate)
	if err := control.Activate(certificate); err == nil || !strings.Contains(err.Error(), "independent Certificate checker") {
		t.Fatalf("online activation bypassed independent checker: %v", err)
	}
	if len(control.Events()) != 0 {
		t.Fatal("rejected Certificate was appended to History")
	}
	if err := control.Close(); err != nil {
		t.Fatal(err)
	}

	record, err := history.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := record.Append(eventRuleActivated, ruleEvent{
		SemanticVersion: semanticVersion,
		Certificate:     certificate,
	}); err != nil {
		t.Fatal(err)
	}
	if err := record.Close(); err != nil {
		t.Fatal(err)
	}
	if reopened, err := Open(path); err == nil || !strings.Contains(err.Error(), "independent Certificate checker") {
		if reopened != nil {
			_ = reopened.Close()
		}
		t.Fatalf("History replay bypassed independent checker: %v", err)
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
		t.Fatalf("rejected Certificate advanced external anchor to %+v", point)
	}
}

func TestCertificateProjectionExcludesLargeResponsePayloads(t *testing.T) {
	control, err := Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer control.Close()
	payload := bytes.Repeat([]byte("r"), 1024)
	remote := strings.Repeat("x", 1024)
	for index := 0; index < 10_000; index++ {
		id := fmt.Sprintf("settled-%05d", index)
		control.state.Operations[id] = kernel.Operation{
			ID: id, Domain: "old-service", Kind: "old-kind", RequestHash: "old-request",
			Produces: map[string]uint32{fmt.Sprintf("old-result-%05d", index): 1},
			Phase:    kernel.Succeeded, ResultHash: "result", ResultBody: payload,
			RemoteReference: remote,
		}
	}
	for index := 0; index < kernel.MaxOpenOperations; index++ {
		id := fmt.Sprintf("open-%02d", index)
		control.state.Operations[id] = kernel.Operation{
			ID: id, Domain: "old-service", Kind: "old-kind", RequestHash: "old-request",
			Produces:  map[string]uint32{fmt.Sprintf("open-result-%02d", index): 1},
			RetrySafe: true, Phase: kernel.Unknown,
		}
	}
	target := kernel.Requirement{
		ID: "large-History-change", Results: map[string]uint32{"done": 1},
		Kinds: map[string]kernel.KindSpec{
			"finish": {Produces: map[string]uint32{"done": 1}, RetrySafe: true},
		},
	}
	certificate, err := control.Compile(target)
	if err != nil {
		t.Fatal(err)
	}
	fullState, err := json.Marshal(control.state)
	if err != nil {
		t.Fatal(err)
	}
	if len(fullState) <= certcheck.MaxDocumentBytes {
		t.Fatalf("test State is only %d bytes; expected it to exceed the old checker limit", len(fullState))
	}
	projection, err := control.CertificateState(certificate)
	if err != nil {
		t.Fatal(err)
	}
	if len(projection) >= 1<<20 {
		t.Fatalf("answer-preserving projection is unexpectedly large: %d bytes", len(projection))
	}
	certificateJSON, err := json.Marshal(certificate)
	if err != nil {
		t.Fatal(err)
	}
	verdict, err := certcheck.CheckJSON(projection, certificateJSON)
	if err != nil || !verdict.Valid {
		t.Fatalf("large-History Certificate verdict=%+v error=%v", verdict, err)
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
	if op.RequestStored {
		t.Fatal("legacy direct Prepare acquired a request snapshot during replay")
	}
	if len(reopened.Events()) != 4 {
		t.Fatalf("durable event count = %d", len(reopened.Events()))
	}
}

func TestStoredRequestReplaysWithoutEnteringCertificateProjection(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.history")
	first, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	activate(t, first, "invoice-v1")
	headers := map[string]string{"Content-Type": "application/json", "X-Private": "history-only"}
	body := []byte(`{"account":"private-account","amount":42}`)
	prepared, err := first.PrepareWithRequest(
		"charge-stored", "microservice", "charge", "stored-request-hash", headers, body,
	)
	if err != nil {
		t.Fatal(err)
	}
	headers["X-Private"] = "mutated"
	body[0] = 'x'
	prepared.RequestHeaders["X-Private"] = "mutated-result"
	prepared.RequestBody[0] = 'y'
	stored, ok := first.Operation("charge-stored")
	if !ok || !stored.RequestStored || stored.RequestHeaders["X-Private"] != "history-only" ||
		string(stored.RequestBody) != `{"account":"private-account","amount":42}` {
		t.Fatalf("stored Operation = %+v", stored)
	}

	state := first.Snapshot()
	projection, err := certificateStateJSON(state, requirement("invoice-v2"))
	if err != nil {
		t.Fatal(err)
	}
	mutated := state.Clone()
	mutatedOperation := mutated.Operations["charge-stored"]
	mutatedOperation.RequestHeaders["X-Private"] = strings.Repeat("z", 1024)
	mutatedOperation.RequestBody = bytes.Repeat([]byte("secret"), 1024)
	mutated.Operations["charge-stored"] = mutatedOperation
	mutatedProjection, err := certificateStateJSON(mutated, requirement("invoice-v2"))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(projection, mutatedProjection) {
		t.Fatalf("stored bytes changed Certificate projection:\n%s\n%s", projection, mutatedProjection)
	}
	if bytes.Contains(projection, []byte("history-only")) || bytes.Contains(projection, []byte("private-account")) {
		t.Fatalf("Certificate projection exposed stored request bytes: %s", projection)
	}
	if err := first.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	replayed, ok := reopened.Operation("charge-stored")
	if !ok || !replayed.RequestStored || replayed.RequestHeaders["X-Private"] != "history-only" ||
		string(replayed.RequestBody) != `{"account":"private-account","amount":42}` {
		t.Fatalf("replayed stored Operation = %+v", replayed)
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
