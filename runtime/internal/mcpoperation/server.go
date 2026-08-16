package mcpoperation

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const (
	MaxMessageBytes       = int(kernel.MaxOperationRequestBodyBytes) + (64 << 10)
	DefaultExecuteTimeout = 60 * time.Second
	serverName            = "safe-change-operation"
	serverVersion         = "0.1.0"
	modernProtocolVersion = "2026-07-28"
	legacyProtocolVersion = "2025-11-25"
)

var ErrTransport = errors.New("MCP transport failed")

type Executor interface {
	Execute(context.Context, string, string, []byte) (gateway.Outcome, error)
}

type ServerOptions struct {
	ExecutionID    string
	ExecuteTimeout time.Duration
	Journal        *Journal
}

type Server struct {
	executor       Executor
	executeTimeout time.Duration
	tools          map[string]Tool
	orderedTools   []Tool
	journal        *Journal
	requestMu      sync.Mutex
}

type rpcRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type callParams struct {
	Name      string                     `json:"name"`
	Arguments map[string]json.RawMessage `json:"arguments"`
	Meta      map[string]json.RawMessage `json:"_meta,omitempty"`
	Input     map[string]json.RawMessage `json:"inputResponses,omitempty"`
	State     json.RawMessage            `json:"requestState,omitempty"`
}

type toolResult struct {
	ResultType        string          `json:"resultType,omitempty"`
	Content           []textContent   `json:"content"`
	StructuredContent operationResult `json:"structuredContent"`
	IsError           bool            `json:"isError,omitempty"`
	Meta              map[string]any  `json:"_meta,omitempty"`
}

type textContent struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

type operationResult struct {
	Schema           int          `json:"schema"`
	OperationID      string       `json:"operation_id,omitempty"`
	Phase            kernel.Phase `json:"phase,omitempty"`
	ResultHash       string       `json:"result_hash,omitempty"`
	Reused           bool         `json:"reused"`
	RecoveredByQuery bool         `json:"recovered_by_query"`
	ExecutionFenced  bool         `json:"execution_fenced"`
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

func NewServer(executor Executor, config Config, options ServerOptions) (*Server, error) {
	if executor == nil {
		return nil, errors.New("MCP Operation server requires an executor")
	}
	if err := validateConfig(config); err != nil {
		return nil, err
	}
	if !validName(options.ExecutionID, MaxExecutionIDSize) {
		return nil, fmt.Errorf("execution identity must contain 1 to %d safe name bytes", MaxExecutionIDSize)
	}
	if options.Journal == nil {
		return nil, errors.New("MCP Operation server requires a durable call journal")
	}
	options.Journal.mu.Lock()
	journalExecutionID := options.Journal.executionID
	journalClosed := options.Journal.closed
	options.Journal.mu.Unlock()
	if journalClosed || journalExecutionID != options.ExecutionID {
		return nil, errors.New("MCP call journal is closed or belongs to another execution")
	}
	timeout := options.ExecuteTimeout
	if timeout == 0 {
		timeout = DefaultExecuteTimeout
	}
	if timeout <= 0 || timeout > 10*time.Minute {
		return nil, errors.New("MCP Operation execution timeout must be positive and at most 10m")
	}
	cloned := cloneConfig(config)
	server := &Server{
		executor: executor, executeTimeout: timeout,
		tools: make(map[string]Tool, len(cloned.Tools)), orderedTools: cloned.Tools,
		journal: options.Journal,
	}
	for _, tool := range cloned.Tools {
		server.tools[tool.Name] = tool
	}
	return server, nil
}

// Serve runs the newline-delimited MCP stdio transport. It is deliberately
// sequential: one execution has one total order of protected tool admission,
// and a later call cannot pass an unsettled earlier call.
func (s *Server) Serve(ctx context.Context, input io.Reader, output io.Writer, diagnostics io.Writer) error {
	if ctx == nil || input == nil || output == nil || diagnostics == nil {
		return errors.New("MCP Operation stdio requires context and all streams")
	}
	scanner := bufio.NewScanner(input)
	scanner.Buffer(make([]byte, 64<<10), MaxMessageBytes)
	writer := bufio.NewWriter(output)
	for scanner.Scan() {
		if err := ctx.Err(); err != nil {
			return err
		}
		line := append([]byte(nil), scanner.Bytes()...)
		s.requestMu.Lock()
		response, respond, err := s.handle(ctx, line, diagnostics)
		s.requestMu.Unlock()
		if err != nil {
			return err
		}
		if !respond {
			continue
		}
		if _, err := writer.Write(response); err != nil {
			return fmt.Errorf("%w: write MCP response: %w", ErrTransport, err)
		}
		if err := writer.WriteByte('\n'); err != nil {
			return fmt.Errorf("%w: terminate MCP response: %w", ErrTransport, err)
		}
		if err := writer.Flush(); err != nil {
			return fmt.Errorf("%w: flush MCP response: %w", ErrTransport, err)
		}
	}
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("%w: read MCP request: %w", ErrTransport, err)
	}
	return nil
}

func (s *Server) handle(ctx context.Context, line []byte, diagnostics io.Writer) ([]byte, bool, error) {
	if len(bytes.TrimSpace(line)) == 0 {
		return nil, false, nil
	}
	if len(line) > MaxMessageBytes {
		return marshalRPCError(nil, -32700, "MCP request exceeds the message limit"), true, nil
	}
	if err := rejectDuplicateJSONNames(line); err != nil {
		return marshalRPCError(nil, -32700, "invalid JSON-RPC request"), true, nil
	}
	var request rpcRequest
	if err := json.Unmarshal(line, &request); err != nil || request.JSONRPC != "2.0" || request.Method == "" {
		return marshalRPCError(nil, -32600, "invalid JSON-RPC request"), true, nil
	}
	if len(request.ID) == 0 {
		if request.Method == "notifications/initialized" || strings.HasPrefix(request.Method, "notifications/") {
			return nil, false, nil
		}
		return nil, false, nil
	}
	if !validRPCID(request.ID) {
		return marshalRPCError(nil, -32600, "invalid JSON-RPC request identity"), true, nil
	}

	switch request.Method {
	case "initialize":
		version := legacyProtocolVersion
		var parameters struct {
			ProtocolVersion string `json:"protocolVersion"`
		}
		if json.Unmarshal(request.Params, &parameters) == nil && supportedVersion(parameters.ProtocolVersion) {
			version = parameters.ProtocolVersion
		}
		return marshalRPCResult(request.ID, map[string]any{
			"protocolVersion": version,
			"capabilities":    capabilities(),
			"serverInfo":      serverInfo(),
			"instructions":    serverInstructions(),
			"_meta":           responseMeta(),
		}), true, nil
	case "server/discover":
		return marshalRPCResult(request.ID, map[string]any{
			"resultType":        "complete",
			"supportedVersions": []string{modernProtocolVersion, legacyProtocolVersion, "2025-06-18"},
			"capabilities":      capabilities(),
			"instructions":      serverInstructions(),
			"ttlMs":             0,
			"cacheScope":        "private",
			"_meta":             responseMeta(),
		}), true, nil
	case "ping":
		return marshalRPCResult(request.ID, map[string]any{"_meta": responseMeta()}), true, nil
	case "tools/list":
		tools := make([]map[string]any, 0, len(s.orderedTools))
		for _, tool := range s.orderedTools {
			tools = append(tools, toolDescription(tool))
		}
		return marshalRPCResult(request.ID, map[string]any{
			"tools": tools, "ttlMs": 0, "cacheScope": "private", "_meta": responseMeta(),
		}), true, nil
	case "tools/call":
		response, err := s.callTool(ctx, request, diagnostics)
		return response, true, err
	default:
		return marshalRPCError(request.ID, -32601, "method not found"), true, nil
	}
}

func (s *Server) callTool(ctx context.Context, request rpcRequest, diagnostics io.Writer) ([]byte, error) {
	var parameters callParams
	decoder := json.NewDecoder(bytes.NewReader(request.Params))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&parameters); err != nil || parameters.Name == "" || parameters.Arguments == nil || len(parameters.Input) != 0 || len(parameters.State) != 0 {
		return marshalRPCError(request.ID, -32602, "invalid tool parameters"), nil
	}
	if err := validateProtocolMeta(parameters.Meta); err != nil {
		return marshalRPCError(request.ID, -32022, "unsupported MCP protocol version"), nil
	}
	tool, ok := s.tools[parameters.Name]
	if !ok {
		return marshalRPCError(request.ID, -32602, "unknown protected tool"), nil
	}
	body, err := validateArguments(tool, parameters.Arguments)
	if err != nil {
		return marshalRPCError(request.ID, -32602, "tool arguments do not match the protected schema"), nil
	}
	// MCP _meta is transport and client context. Codex legitimately changes it
	// after restart, so it is validated above but cannot define the external
	// action. Bind replay to the ordered JSON-RPC identity plus the exact
	// operator tool mapping and canonical business arguments instead.
	protectedRequest, err := json.Marshal(struct {
		Schema    int             `json:"schema"`
		Name      string          `json:"name"`
		Kind      string          `json:"kind"`
		Arguments json.RawMessage `json:"arguments"`
	}{Schema: 1, Name: parameters.Name, Kind: tool.Kind, Arguments: body})
	if err != nil {
		return nil, err
	}
	digestBytes := sha256.Sum256(append([]byte("mcp-protected-call-v2\x00"), protectedRequest...))
	digest := hex.EncodeToString(digestBytes[:])
	identity := string(request.ID)

	call, exists, lookupErr := s.journal.Lookup(identity, digest)
	if lookupErr != nil {
		if exists {
			return marshalRPCError(request.ID, -32602, "JSON-RPC identity was reused for a different protected call"), nil
		}
		return nil, lookupErr
	}
	if exists && call.Completed {
		return append([]byte(nil), call.Response...), nil
	}
	if !exists {
		fenced, pending, err := s.journal.Fenced()
		if err != nil {
			return nil, err
		}
		if fenced || pending {
			return marshalRPCResult(request.ID, fencedToolResult("an earlier protected operation has not reached a definitive outcome")), nil
		}
	}

	if !exists {
		call, err = s.journal.Prepare(identity, digest)
		if err != nil {
			return nil, err
		}
	}

	executeContext, cancel := context.WithTimeout(ctx, s.executeTimeout)
	outcome, executeErr := s.executor.Execute(executeContext, call.CallID, tool.Kind, body)
	cancel()
	result, uncertain := resultForOutcome(outcome, executeErr)
	if executeErr != nil {
		_, _ = fmt.Fprintf(diagnostics, "protected MCP call %s failed: %v\n", call.CallID, executeErr)
	}
	response := marshalRPCResult(request.ID, result)
	if err := s.journal.Complete(call, response, uncertain); err != nil {
		return nil, err
	}
	return response, nil
}

func resultForOutcome(outcome gateway.Outcome, executeErr error) (toolResult, bool) {
	uncertain := executeErr != nil || outcome.Phase == kernel.Unknown || outcome.Phase == kernel.Dispatched
	structured := operationResult{
		Schema: 1, OperationID: outcome.OperationID, Phase: outcome.Phase,
		ResultHash: outcome.ResultHash, Reused: outcome.Reused,
		RecoveredByQuery: outcome.RecoveredByQuery, ExecutionFenced: uncertain,
	}
	result := toolResult{
		ResultType: "complete", StructuredContent: structured, Meta: responseMeta(),
	}
	switch {
	case executeErr != nil:
		result.IsError = true
		result.Content = []textContent{{Type: "text", Text: "Protected operation did not settle safely."}}
	case outcome.Phase == kernel.Succeeded && outcome.OperationID != "" && outcome.ResultHash != "":
		result.Content = []textContent{{Type: "text", Text: "Protected operation committed."}}
	case outcome.Phase == kernel.Failed && outcome.OperationID != "" && outcome.ResultHash != "":
		result.IsError = true
		result.Content = []textContent{{Type: "text", Text: "Protected operation completed with a definitive provider failure."}}
	default:
		uncertain = true
		result.IsError = true
		result.StructuredContent.ExecutionFenced = true
		result.Content = []textContent{{Type: "text", Text: "Protected operation returned an invalid or unsettled outcome."}}
	}
	return result, uncertain
}

func fencedToolResult(reason string) toolResult {
	return toolResult{
		ResultType: "complete", IsError: true, Meta: responseMeta(),
		Content:           []textContent{{Type: "text", Text: "Protected execution is fenced: " + reason + "."}},
		StructuredContent: operationResult{Schema: 1, ExecutionFenced: true},
	}
}

func validateArguments(tool Tool, values map[string]json.RawMessage) ([]byte, error) {
	schemas := make(map[string]Argument, len(tool.Arguments))
	for _, argument := range tool.Arguments {
		schemas[argument.Name] = argument
		if argument.Required {
			if _, ok := values[argument.Name]; !ok {
				return nil, fmt.Errorf("required argument %q is absent", argument.Name)
			}
		}
	}
	canonical := make(map[string]any, len(values))
	for name, raw := range values {
		argument, ok := schemas[name]
		if !ok {
			return nil, fmt.Errorf("argument %q is not declared", name)
		}
		decoder := json.NewDecoder(bytes.NewReader(raw))
		decoder.UseNumber()
		var value any
		if err := decoder.Decode(&value); err != nil {
			return nil, err
		}
		switch argument.Type {
		case "string":
			text, ok := value.(string)
			if !ok || len(text) > argument.MaxLength || !safeText(text, false) {
				return nil, errors.New("invalid string argument")
			}
			if len(argument.Enum) != 0 && !contains(argument.Enum, text) {
				return nil, errors.New("string argument is outside its enum")
			}
		case "integer":
			number, ok := value.(json.Number)
			if !ok || strings.ContainsAny(number.String(), ".eE") {
				return nil, errors.New("invalid integer argument")
			}
			if _, err := strconv.ParseInt(number.String(), 10, 64); err != nil {
				return nil, errors.New("integer argument is out of range")
			}
		case "number":
			number, ok := value.(json.Number)
			if !ok {
				return nil, errors.New("invalid number argument")
			}
			if _, err := strconv.ParseFloat(number.String(), 64); err != nil {
				return nil, errors.New("number argument is out of range")
			}
		case "boolean":
			if _, ok := value.(bool); !ok {
				return nil, errors.New("invalid boolean argument")
			}
		}
		canonical[name] = value
	}
	encoded, err := json.Marshal(canonical)
	if err != nil || len(encoded) > int(kernel.MaxOperationRequestBodyBytes) {
		return nil, errors.New("canonical tool arguments exceed the Operation request limit")
	}
	return encoded, nil
}

func toolDescription(tool Tool) map[string]any {
	properties := make(map[string]any, len(tool.Arguments))
	required := make([]string, 0, len(tool.Arguments))
	for _, argument := range tool.Arguments {
		schema := map[string]any{"type": argument.Type}
		if argument.Description != "" {
			schema["description"] = argument.Description
		}
		if argument.Type == "string" {
			schema["maxLength"] = argument.MaxLength
			if len(argument.Enum) != 0 {
				schema["enum"] = append([]string(nil), argument.Enum...)
			}
		}
		properties[argument.Name] = schema
		if argument.Required {
			required = append(required, argument.Name)
		}
	}
	inputSchema := map[string]any{
		"type": "object", "properties": properties, "additionalProperties": false,
	}
	if len(required) != 0 {
		inputSchema["required"] = required
	}
	return map[string]any{
		"name": tool.Name, "description": tool.Description, "inputSchema": inputSchema,
		"outputSchema": map[string]any{
			"type": "object",
			"properties": map[string]any{
				"schema":             map[string]any{"type": "integer"},
				"operation_id":       map[string]any{"type": "string"},
				"phase":              map[string]any{"type": "string"},
				"result_hash":        map[string]any{"type": "string"},
				"reused":             map[string]any{"type": "boolean"},
				"recovered_by_query": map[string]any{"type": "boolean"},
				"execution_fenced":   map[string]any{"type": "boolean"},
			},
			"required": []string{"schema", "reused", "recovered_by_query", "execution_fenced"},
		},
	}
}

func validRPCID(raw json.RawMessage) bool {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return false
	}
	switch id := value.(type) {
	case string:
		return id != "" && len(id) <= 1024 && safeText(id, false)
	case json.Number:
		if strings.ContainsAny(id.String(), ".eE") {
			return false
		}
		_, err := strconv.ParseInt(id.String(), 10, 64)
		return err == nil
	default:
		return false
	}
}

func supportedVersion(version string) bool {
	return version == modernProtocolVersion || version == legacyProtocolVersion || version == "2025-06-18"
}

func validateProtocolMeta(meta map[string]json.RawMessage) error {
	raw, exists := meta["io.modelcontextprotocol/protocolVersion"]
	if !exists {
		return nil
	}
	var version string
	if json.Unmarshal(raw, &version) != nil || !supportedVersion(version) {
		return errors.New("unsupported MCP protocol version")
	}
	return nil
}

func capabilities() map[string]any {
	return map[string]any{"tools": map[string]any{"listChanged": false}}
}

func serverInfo() map[string]any {
	return map[string]any{"name": serverName, "version": serverVersion}
}

func responseMeta() map[string]any {
	return map[string]any{"io.modelcontextprotocol/serverInfo": serverInfo()}
}

func serverInstructions() string {
	return "All tools are durable protected Operations. Never retry an execution_fenced result as a new call."
}

func marshalRPCResult(id json.RawMessage, result any) []byte {
	encoded, _ := json.Marshal(struct {
		JSONRPC string          `json:"jsonrpc"`
		ID      json.RawMessage `json:"id"`
		Result  any             `json:"result"`
	}{JSONRPC: "2.0", ID: id, Result: result})
	return encoded
}

func marshalRPCError(id json.RawMessage, code int, message string) []byte {
	if len(id) == 0 {
		id = json.RawMessage("null")
	}
	encoded, _ := json.Marshal(struct {
		JSONRPC string          `json:"jsonrpc"`
		ID      json.RawMessage `json:"id"`
		Error   rpcError        `json:"error"`
	}{JSONRPC: "2.0", ID: id, Error: rpcError{Code: code, Message: message}})
	return encoded
}

func contains(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}
