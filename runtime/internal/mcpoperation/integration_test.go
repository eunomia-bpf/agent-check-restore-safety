package mcpoperation

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	controlapi "github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/payment"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/sandboxhost"
)

func TestRealHistoryMCPBoundaryRecoversLostResponseThenContinues(t *testing.T) {
	root, err := os.MkdirTemp("/tmp", "mcp-op-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(root) })
	paymentService, err := payment.OpenWithOptions(filepath.Join(root, "payment.history"), payment.Options{
		DropFirstResponse: true, ReferencePrefix: "mcp-payment",
	})
	if err != nil {
		t.Fatal(err)
	}
	defer paymentService.Close()
	paymentServer := httptest.NewServer(paymentService.Handler())
	defer paymentServer.Close()

	controller, err := control.Open(filepath.Join(root, "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer controller.Close()
	serverAPI, err := controlapi.New(controller, nil, controlapi.Credentials{
		AdminToken: "mcp-admin-token-000000000000000000000000",
	})
	if err != nil {
		t.Fatal(err)
	}
	requirement := kernel.Requirement{
		ID:         "mcp-real-query-recovery",
		Results:    map[string]uint32{"committed": 2},
		Capacities: map[string]uint32{"external-write": 2},
		Kinds: map[string]kernel.KindSpec{
			"protected_commit": {
				Costs: map[string]uint32{"external-write": 1}, Produces: map[string]uint32{"committed": 1},
				RetrySafe: false, Queryable: true,
				Target: paymentServer.URL + "/v1/charge", Method: http.MethodPost,
				ResponseClassifier: gateway.ResponseReceiptV1,
				QueryTarget:        paymentServer.URL + "/v1/query", QueryMethod: http.MethodPost,
				QueryClassifier: gateway.OperationObservationV1,
			},
		},
	}
	certificate, err := controller.Compile(requirement)
	if err != nil {
		t.Fatal(err)
	}
	binding := control.SandboxBinding{
		SandboxID: "mcp-agent", Generation: 1, HostInstanceID: "host-mcp-agent-1",
		Domain: "mcp-agent-domain", AllowedKinds: []string{"protected_commit"},
	}
	if err := controller.Cutover(certificate, []control.SandboxBinding{binding}); err != nil {
		t.Fatal(err)
	}

	socketDirectory := filepath.Join(root, "sandboxes")
	if err := os.Mkdir(socketDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(socketDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	socketPath := filepath.Join(socketDirectory, "mcp-agent.sock")
	endpoint, err := sandboxhost.ListenUnix(controller, serverAPI, binding, socketPath)
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		closeContext, cancel := context.WithTimeout(context.Background(), time.Second)
		defer cancel()
		if err := endpoint.Close(closeContext); err != nil {
			t.Error(err)
		}
	}()

	executor, err := NewSandboxExecutor(socketPath, SandboxExecutorOptions{})
	if err != nil {
		t.Fatal(err)
	}
	config, err := ParseConfig([]byte(`{
      "schema":1,
      "tools":[{
        "name":"commit_effect",
        "description":"Commit one real protected effect.",
        "kind":"protected_commit",
        "arguments":[{"name":"effect_id","type":"string","required":true,"max_length":128}]
      }]
    }`))
	if err != nil {
		t.Fatal(err)
	}
	journalPath := filepath.Join(root, "mcp-calls.jsonl")
	journal, err := OpenJournal(journalPath, "real-mcp-execution")
	if err != nil {
		t.Fatal(err)
	}
	firstServer, err := NewServer(executor, config, ServerOptions{
		ExecutionID: "real-mcp-execution", Journal: journal,
	})
	if err != nil {
		t.Fatal(err)
	}
	firstCall := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"commit_effect","arguments":{"effect_id":"A-17"}}}`
	firstLines, firstDiagnostics := runServer(t, firstServer, firstCall)
	if err := journal.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := OpenJournal(journalPath, "real-mcp-execution")
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	restartedServer, err := NewServer(executor, config, ServerOptions{
		ExecutionID: "real-mcp-execution", Journal: reopened,
	})
	if err != nil {
		t.Fatal(err)
	}
	restartedLines, restartedDiagnostics := runServer(t, restartedServer,
		firstCall,
		`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"commit_effect","arguments":{"effect_id":"B-18"}}}`,
	)
	if firstDiagnostics != "" || restartedDiagnostics != "" || len(firstLines) != 1 || len(restartedLines) != 2 || firstLines[0] != restartedLines[0] {
		t.Fatalf("first=%d restarted=%d diagnostics=%q/%q", len(firstLines), len(restartedLines), firstDiagnostics, restartedDiagnostics)
	}
	first := decodeResponse(t, firstLines[0])["result"].(map[string]any)
	second := decodeResponse(t, restartedLines[1])["result"].(map[string]any)
	firstOutcome := first["structuredContent"].(map[string]any)
	secondOutcome := second["structuredContent"].(map[string]any)
	if first["isError"] != nil || second["isError"] != nil ||
		firstOutcome["phase"] != string(kernel.Succeeded) || firstOutcome["recovered_by_query"] != true || firstOutcome["execution_fenced"] != false ||
		secondOutcome["phase"] != string(kernel.Succeeded) || secondOutcome["recovered_by_query"] != false || secondOutcome["execution_fenced"] != false {
		t.Fatalf("first=%+v second=%+v", first, second)
	}
	firstID := firstOutcome["operation_id"].(string)
	secondID := secondOutcome["operation_id"].(string)
	if firstID == secondID || !strings.HasPrefix(firstID, "op-") || !strings.HasPrefix(secondID, "op-") {
		t.Fatalf("operation identities = %q / %q", firstID, secondID)
	}
	stats := paymentService.Stats()
	if stats.Deliveries != 2 || stats.Commits != 2 || stats.Paths["/v1/charge"] != 2 {
		t.Fatalf("payment stats = %+v", stats)
	}
	state := controller.Snapshot()
	if state.History.Sequence != 8 || len(state.Operations) != 2 ||
		state.Operations[firstID].Settlement != kernel.SettlementQuery ||
		state.Operations[secondID].Settlement != "" {
		t.Fatalf("History=%+v Operations=%+v", state.History, state.Operations)
	}
	if state.Operations[firstID].RequestBody == nil || state.Operations[secondID].RequestBody == nil {
		t.Fatal("History did not retain the exact MCP business requests")
	}
}
