package api

import "github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"

const (
	OperationErrorOutcomeUnknown  = "outcome_unknown"
	OperationErrorRequestConflict = "request_conflict"
)

// ErrorResponse is the error envelope returned by control-plane endpoints.
type ErrorResponse struct {
	Error string `json:"error"`
}

// ExecuteRequest is the adapter-facing request accepted by POST /v1/execute.
// The authenticated adapter credential, rather than this payload, supplies
// the Operation domain. URL, Headers, and Body are durable public Operation
// data: callers must never place provider credentials in any of them.
type ExecuteRequest struct {
	CallID  string            `json:"call_id"`
	Kind    string            `json:"kind"`
	Method  string            `json:"method,omitempty"`
	URL     string            `json:"url"`
	Headers map[string]string `json:"headers,omitempty"`
	Body    []byte            `json:"body,omitempty"`
}

// OperationError is the error envelope returned after an Execute or Recover
// request has reached the Operation gateway. Outcome may contain durable
// progress even when the HTTP request is rejected.
type OperationError struct {
	Outcome gateway.Outcome `json:"outcome"`
	Error   string          `json:"error"`
	Code    string          `json:"code,omitempty"`
}

// Keep package-local callers source-compatible while the protocol types are
// made available to clients in other internal packages.
type errorBody = ErrorResponse
type executeRequest = ExecuteRequest
