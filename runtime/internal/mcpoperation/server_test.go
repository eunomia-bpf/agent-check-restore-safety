package mcpoperation

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

type recordedExecution struct {
	callID string
	kind   string
	body   string
}

type fakeExecutor struct {
	calls []recordedExecution
	fn    func(int, string, string, []byte) (gateway.Outcome, error)
}

func (executor *fakeExecutor) Execute(_ context.Context, callID, kind string, body []byte) (gateway.Outcome, error) {
	executor.calls = append(executor.calls, recordedExecution{callID: callID, kind: kind, body: string(body)})
	if executor.fn != nil {
		return executor.fn(len(executor.calls), callID, kind, body)
	}
	return gateway.Outcome{
		OperationID: "op-" + strings.Repeat("a", 64), Phase: kernel.Succeeded,
		ResultHash: strings.Repeat("b", 64),
	}, nil
}

func testServerConfig(t *testing.T) Config {
	t.Helper()
	config, err := ParseConfig([]byte(`{
      "schema":1,
      "tools":[{
        "name":"charge_payment",
        "description":"Commit one payment.",
        "kind":"protected_commit",
        "arguments":[
          {"name":"effect_id","type":"string","required":true,"max_length":64},
          {"name":"urgent","type":"boolean","required":false}
        ]
      }]
    }`))
	if err != nil {
		t.Fatal(err)
	}
	return config
}

func testJournal(t *testing.T, executionID string) *Journal {
	t.Helper()
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	journal, err := OpenJournal(filepath.Join(directory, "mcp-calls.jsonl"), executionID)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := journal.Close(); err != nil {
			t.Error(err)
		}
	})
	return journal
}

func runServer(t *testing.T, server *Server, requests ...string) ([]string, string) {
	t.Helper()
	var output bytes.Buffer
	var diagnostics bytes.Buffer
	input := strings.NewReader(strings.Join(requests, "\n") + "\n")
	if err := server.Serve(context.Background(), input, &output, &diagnostics); err != nil {
		t.Fatal(err)
	}
	text := strings.TrimSpace(output.String())
	if text == "" {
		return nil, diagnostics.String()
	}
	return strings.Split(text, "\n"), diagnostics.String()
}

func decodeResponse(t *testing.T, line string) map[string]any {
	t.Helper()
	decoder := json.NewDecoder(strings.NewReader(line))
	decoder.UseNumber()
	var response map[string]any
	if err := decoder.Decode(&response); err != nil {
		t.Fatal(err)
	}
	return response
}

func TestServerSupportsLegacyAndModernMCPWithOrderedDurableCalls(t *testing.T) {
	executor := &fakeExecutor{}
	server, err := NewServer(executor, testServerConfig(t), ServerOptions{
		ExecutionID: "execution-A", Journal: testJournal(t, "execution-A"),
	})
	if err != nil {
		t.Fatal(err)
	}
	call := `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"charge_payment","arguments":{"urgent":true,"effect_id":"A-17"}}}`
	lines, diagnostics := runServer(t, server,
		`{"jsonrpc":"2.0","id":0,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}`,
		`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","clientInfo":{"name":"test","version":"1"},"capabilities":{}}}`,
		`{"jsonrpc":"2.0","method":"notifications/initialized"}`,
		`{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}`,
		call,
		call,
		`{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"B-18"}}}`,
	)
	if diagnostics != "" || len(lines) != 6 {
		t.Fatalf("responses=%d diagnostics=%q", len(lines), diagnostics)
	}
	discover := decodeResponse(t, lines[0])["result"].(map[string]any)
	if discover["resultType"] != "complete" || len(discover["supportedVersions"].([]any)) < 2 {
		t.Fatalf("discover result = %+v", discover)
	}
	initialize := decodeResponse(t, lines[1])["result"].(map[string]any)
	if initialize["protocolVersion"] != legacyProtocolVersion {
		t.Fatalf("initialize result = %+v", initialize)
	}
	listed := decodeResponse(t, lines[2])["result"].(map[string]any)
	tools := listed["tools"].([]any)
	if len(tools) != 1 || tools[0].(map[string]any)["name"] != "charge_payment" {
		t.Fatalf("tools/list result = %+v", listed)
	}
	if lines[3] != lines[4] {
		t.Fatal("duplicate JSON-RPC delivery did not return the byte-identical cached response")
	}
	firstResult := decodeResponse(t, lines[3])["result"].(map[string]any)
	if firstResult["isError"] != nil {
		t.Fatalf("successful tool result = %+v", firstResult)
	}
	if len(executor.calls) != 2 {
		t.Fatalf("executor calls = %+v", executor.calls)
	}
	if executor.calls[0] != (recordedExecution{
		callID: "mcp-call-v1:11:execution-A:1", kind: "protected_commit",
		body: `{"effect_id":"A-17","urgent":true}`,
	}) || executor.calls[1].callID != "mcp-call-v1:11:execution-A:2" || executor.calls[1].body != `{"effect_id":"B-18"}` {
		t.Fatalf("ordered executions = %+v", executor.calls)
	}
}

func TestServerRejectsConflictingRPCIdentityWithoutDispatch(t *testing.T) {
	executor := &fakeExecutor{}
	server, err := NewServer(executor, testServerConfig(t), ServerOptions{
		ExecutionID: "execution-B", Journal: testJournal(t, "execution-B"),
	})
	if err != nil {
		t.Fatal(err)
	}
	lines, _ := runServer(t, server,
		`{"jsonrpc":"2.0","id":"call-1","method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"A-17"}}}`,
		`{"jsonrpc":"2.0","id":"call-1","method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"DIFFERENT"}}}`,
	)
	if len(executor.calls) != 1 || len(lines) != 2 {
		t.Fatalf("calls=%+v lines=%d", executor.calls, len(lines))
	}
	errorValue := decodeResponse(t, lines[1])["error"].(map[string]any)
	if errorValue["code"].(json.Number).String() != "-32602" || !strings.Contains(errorValue["message"].(string), "reused") {
		t.Fatalf("conflict response = %+v", errorValue)
	}
}

func TestServerFencesExecutionAfterUnsettledOperation(t *testing.T) {
	executor := &fakeExecutor{fn: func(_ int, _ string, _ string, _ []byte) (gateway.Outcome, error) {
		return gateway.Outcome{
			OperationID: "op-" + strings.Repeat("c", 64), Phase: kernel.Unknown,
		}, gateway.ErrOutcomeUnknown
	}}
	server, err := NewServer(executor, testServerConfig(t), ServerOptions{
		ExecutionID: "execution-C", Journal: testJournal(t, "execution-C"),
	})
	if err != nil {
		t.Fatal(err)
	}
	lines, diagnostics := runServer(t, server,
		`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"A-17"}}}`,
		`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"B-18"}}}`,
	)
	if len(executor.calls) != 1 || len(lines) != 2 || !strings.Contains(diagnostics, "outcome is unknown") {
		t.Fatalf("calls=%+v diagnostics=%q", executor.calls, diagnostics)
	}
	for index, line := range lines {
		result := decodeResponse(t, line)["result"].(map[string]any)
		if result["isError"] != true || result["structuredContent"].(map[string]any)["execution_fenced"] != true {
			t.Fatalf("result %d = %+v", index, result)
		}
	}
}

func TestServerRestoredBeforeCallReusesSupervisorIdentityAndSequence(t *testing.T) {
	firstCall := `{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"A-17"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2025-11-25","progressToken":"first-process"}}}`
	restoredCall := `{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"A-17"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","progressToken":"restored-process"}}}`
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, "mcp-calls.jsonl")
	firstJournal, err := OpenJournal(path, "restore-scope")
	if err != nil {
		t.Fatal(err)
	}
	firstExecutor := &fakeExecutor{}
	first, err := NewServer(firstExecutor, testServerConfig(t), ServerOptions{
		ExecutionID: "restore-scope", Journal: firstJournal,
	})
	if err != nil {
		t.Fatal(err)
	}
	firstLines, _ := runServer(t, first, firstCall)
	if err := firstJournal.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := OpenJournal(path, "restore-scope")
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	secondExecutor := &fakeExecutor{}
	second, err := NewServer(secondExecutor, testServerConfig(t), ServerOptions{
		ExecutionID: "restore-scope", Journal: reopened,
	})
	if err != nil {
		t.Fatal(err)
	}
	secondLines, _ := runServer(t, second, restoredCall)
	if len(firstExecutor.calls) != 1 || firstExecutor.calls[0].callID != "mcp-call-v1:13:restore-scope:1" ||
		len(secondExecutor.calls) != 0 || len(firstLines) != 1 || len(secondLines) != 1 || firstLines[0] != secondLines[0] {
		t.Fatalf("first calls=%+v second calls=%+v responses=%v/%v", firstExecutor.calls, secondExecutor.calls, firstLines, secondLines)
	}
}

func TestServerRestoredMetadataCannotHideChangedBusinessArguments(t *testing.T) {
	executor := &fakeExecutor{}
	server, err := NewServer(executor, testServerConfig(t), ServerOptions{
		ExecutionID: "metadata-conflict", Journal: testJournal(t, "metadata-conflict"),
	})
	if err != nil {
		t.Fatal(err)
	}
	lines, _ := runServer(t, server,
		`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"A-17"},"_meta":{"progressToken":"one"}}}`,
		`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"B-18"},"_meta":{"progressToken":"two"}}}`,
	)
	if len(lines) != 2 || len(executor.calls) != 1 {
		t.Fatalf("responses=%v calls=%+v", lines, executor.calls)
	}
	errorValue := decodeResponse(t, lines[1])["error"].(map[string]any)
	if !strings.Contains(errorValue["message"].(string), "reused") {
		t.Fatalf("conflict response = %+v", errorValue)
	}
}

func TestServerRejectsInvalidArgumentsBeforeAllocatingOperationSequence(t *testing.T) {
	executor := &fakeExecutor{}
	server, err := NewServer(executor, testServerConfig(t), ServerOptions{
		ExecutionID: "execution-D", Journal: testJournal(t, "execution-D"),
	})
	if err != nil {
		t.Fatal(err)
	}
	lines, _ := runServer(t, server,
		`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"A-17","provider_url":"https://bypass"}}}`,
		`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"A-17"}}}`,
	)
	if len(lines) != 2 || decodeResponse(t, lines[0])["error"] == nil || len(executor.calls) != 1 || !strings.HasSuffix(executor.calls[0].callID, ":1") {
		t.Fatalf("lines=%v calls=%+v", lines, executor.calls)
	}
}

func TestNewServerRejectsUnsafeSupervisorIdentityAndTimeout(t *testing.T) {
	for _, options := range []ServerOptions{
		{},
		{ExecutionID: "bad/id"},
		{ExecutionID: "ok", ExecuteTimeout: -1, Journal: testJournal(t, "ok")},
		{ExecutionID: "ok"},
	} {
		if _, err := NewServer(&fakeExecutor{}, testServerConfig(t), options); err == nil {
			t.Fatalf("options accepted: %+v", options)
		}
	}
	if _, err := NewServer(nil, testServerConfig(t), ServerOptions{ExecutionID: "ok"}); err == nil {
		t.Fatal("nil executor accepted")
	}
}
