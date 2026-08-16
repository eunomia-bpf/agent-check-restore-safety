package api

import (
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const (
	OperationErrorOutcomeUnknown  = "outcome_unknown"
	OperationErrorRequestConflict = "request_conflict"
	OperationErrorSandboxStale    = "sandbox_stale"
)

// CutoverRequest is accepted only on the admin endpoint. Bindings are a
// complete host-owned replacement set, not fields accepted from a sandbox.
type CutoverRequest struct {
	Certificate kernel.Certificate       `json:"certificate"`
	Bindings    []control.SandboxBinding `json:"bindings"`
}

type CutoverResponse struct {
	State    *kernel.State            `json:"state"`
	Bindings []control.SandboxBinding `json:"bindings"`
}

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

// sandboxExecuteRequest deliberately excludes transport targets and identity
// fields. The host resolves those from the active Requirement or an existing
// Operation after authenticating the concrete sandbox endpoint.
type sandboxExecuteRequest struct {
	CallID  string            `json:"call_id"`
	Kind    string            `json:"kind"`
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
