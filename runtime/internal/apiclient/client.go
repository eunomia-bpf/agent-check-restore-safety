// Package apiclient provides a strict client for the durable control API.
package apiclient

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strings"
	"unicode"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const maxResponseBytes = 4 << 20

// Client calls one control API with one fixed Bearer credential. It performs
// each method exactly once and never follows redirects.
type Client struct {
	baseURL string
	token   string
	client  *http.Client
}

// HTTPError reports a syntactically valid non-200 response. Outcome is set
// for Operation errors and may describe durable progress made by the server.
type HTTPError struct {
	Method      string
	URL         string
	StatusCode  int
	Status      string
	ServerError string
	Outcome     gateway.Outcome
	cause       error
}

func (e *HTTPError) Error() string {
	message := e.ServerError
	if message == "" && e.cause != nil {
		message = e.cause.Error()
	}
	if message == "" {
		return fmt.Sprintf("%s %s returned %s", e.Method, e.URL, e.Status)
	}
	return fmt.Sprintf("%s %s returned %s: %s", e.Method, e.URL, e.Status, message)
}

func (e *HTTPError) Unwrap() error {
	return e.cause
}

// ProtocolError reports a response that does not implement the strict JSON
// wire contract. StatusCode and Status remain available when HTTP succeeded.
type ProtocolError struct {
	Method     string
	URL        string
	StatusCode int
	Status     string
	Err        error
}

func (e *ProtocolError) Error() string {
	return fmt.Sprintf("%s %s returned an invalid %s response: %v", e.Method, e.URL, e.Status, e.Err)
}

func (e *ProtocolError) Unwrap() error {
	return e.Err
}

type wireResponse struct {
	method     string
	url        string
	statusCode int
	status     string
	body       []byte
}

// New binds a client to baseURL and token. httpClient is copied so redirect
// policy can be tightened without mutating the caller's client. A nil client
// uses a copy of http.DefaultClient.
func New(baseURL, token string, httpClient *http.Client) (*Client, error) {
	parsed, err := url.Parse(baseURL)
	if err != nil {
		return nil, fmt.Errorf("parse control API URL: %w", err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return nil, errors.New("control API URL must use http or https")
	}
	if parsed.Host == "" {
		return nil, errors.New("control API URL has no host")
	}
	if parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, errors.New("control API URL must not contain credentials, a query, or a fragment")
	}
	if len(token) < 32 || strings.IndexFunc(token, func(value rune) bool {
		return unicode.IsSpace(value) || unicode.IsControl(value)
	}) >= 0 {
		return nil, errors.New("Bearer token must contain at least 32 bytes and no whitespace or control separators")
	}

	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	boundClient := *httpClient
	boundClient.CheckRedirect = func(_ *http.Request, _ []*http.Request) error {
		return http.ErrUseLastResponse
	}
	return &Client{
		baseURL: strings.TrimRight(parsed.String(), "/"),
		token:   token,
		client:  &boundClient,
	}, nil
}

// State returns the current durable State.
func (c *Client) State(ctx context.Context) (kernel.State, error) {
	var state kernel.State
	err := c.callControl(ctx, http.MethodGet, "/v1/state", nil, &state)
	return state, err
}

// SandboxBindings returns the complete currently active host binding set.
func (c *Client) SandboxBindings(ctx context.Context) ([]control.SandboxBinding, error) {
	var bindings []control.SandboxBinding
	err := c.callControl(ctx, http.MethodGet, "/v1/sandbox-bindings", nil, &bindings)
	return bindings, err
}

// Compile computes a Certificate without activating it.
func (c *Client) Compile(ctx context.Context, requirement kernel.Requirement) (kernel.Certificate, error) {
	var certificate kernel.Certificate
	err := c.callControl(ctx, http.MethodPost, "/v1/compile", requirement, &certificate)
	return certificate, err
}

// CertificateState returns the exact JSON projection consumed by the
// independent Certificate checker. The projection is intentionally opaque to
// this transport client, but it must still be one complete JSON value.
func (c *Client) CertificateState(ctx context.Context, certificate kernel.Certificate) (json.RawMessage, error) {
	var projection json.RawMessage
	err := c.callControl(ctx, http.MethodPost, "/v1/certificate-state", certificate, &projection)
	return projection, err
}

// Activate installs a compiled Certificate and returns the resulting State.
func (c *Client) Activate(ctx context.Context, certificate kernel.Certificate) (kernel.State, error) {
	var state kernel.State
	err := c.callControl(ctx, http.MethodPost, "/v1/activate", certificate, &state)
	return state, err
}

// Execute asks the authenticated adapter gateway to perform or reuse one
// stable external Operation.
func (c *Client) Execute(ctx context.Context, request api.ExecuteRequest) (gateway.Outcome, error) {
	response, err := c.roundTrip(ctx, http.MethodPost, "/v1/execute", request)
	if err != nil {
		return gateway.Outcome{}, err
	}
	if response.statusCode != http.StatusOK {
		httpErr := operationHTTPError(response)
		return httpErr.Outcome, httpErr
	}
	var outcome gateway.Outcome
	if err := decodeStrict(response.body, &outcome); err != nil {
		return gateway.Outcome{}, protocolError(response, err)
	}
	return outcome, nil
}

// Recover queries durable evidence for one Operation whose outcome is
// unknown. The admin Bearer credential is required by the server.
func (c *Client) Recover(ctx context.Context, operationID string) (gateway.Outcome, error) {
	if operationID == "" {
		return gateway.Outcome{}, errors.New("operation identity is empty")
	}
	path := "/v1/operations/" + url.PathEscape(operationID) + "/recover"
	response, err := c.roundTrip(ctx, http.MethodPost, path, nil)
	if err != nil {
		return gateway.Outcome{}, err
	}
	if response.statusCode != http.StatusOK {
		httpErr := operationHTTPError(response)
		if response.statusCode == http.StatusNotFound && httpErr.cause == nil {
			httpErr.cause = gateway.ErrOperationNotFound
		}
		return httpErr.Outcome, httpErr
	}
	var outcome gateway.Outcome
	if err := decodeStrict(response.body, &outcome); err != nil {
		return gateway.Outcome{}, protocolError(response, err)
	}
	return outcome, nil
}

func (c *Client) callControl(ctx context.Context, method, path string, requestBody, target any) error {
	response, err := c.roundTrip(ctx, method, path, requestBody)
	if err != nil {
		return err
	}
	if response.statusCode != http.StatusOK {
		return controlHTTPError(response)
	}
	if err := decodeStrict(response.body, target); err != nil {
		return protocolError(response, err)
	}
	return nil
}

func (c *Client) roundTrip(ctx context.Context, method, path string, requestBody any) (wireResponse, error) {
	endpoint := c.baseURL + path
	var body io.Reader
	if requestBody != nil {
		encoded, err := json.Marshal(requestBody)
		if err != nil {
			return wireResponse{}, fmt.Errorf("encode %s %s request: %w", method, endpoint, err)
		}
		body = bytes.NewReader(encoded)
	}
	request, err := http.NewRequestWithContext(ctx, method, endpoint, body)
	if err != nil {
		return wireResponse{}, fmt.Errorf("create %s %s request: %w", method, endpoint, err)
	}
	request.Header.Set("Authorization", "Bearer "+c.token)
	if requestBody != nil {
		request.Header.Set("Content-Type", "application/json")
	}

	httpResponse, err := c.client.Do(request)
	if err != nil {
		return wireResponse{}, fmt.Errorf("send %s %s request: %w", method, endpoint, err)
	}
	defer httpResponse.Body.Close()
	response := wireResponse{
		method: method, url: endpoint,
		statusCode: httpResponse.StatusCode, status: httpResponse.Status,
	}
	mediaType, _, err := mime.ParseMediaType(httpResponse.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" {
		if err == nil {
			err = fmt.Errorf("Content-Type is %q, want application/json", mediaType)
		} else {
			err = fmt.Errorf("invalid JSON Content-Type: %w", err)
		}
		return response, protocolError(response, err)
	}
	encoded, err := io.ReadAll(io.LimitReader(httpResponse.Body, maxResponseBytes+1))
	if err != nil {
		return response, protocolError(response, fmt.Errorf("read response body: %w", err))
	}
	if len(encoded) > maxResponseBytes {
		return response, protocolError(response, fmt.Errorf("response body exceeds %d bytes", maxResponseBytes))
	}
	response.body = encoded
	return response, nil
}

func controlHTTPError(response wireResponse) *HTTPError {
	var envelope api.ErrorResponse
	if err := decodeStrict(response.body, &envelope); err != nil {
		return &HTTPError{
			Method: response.method, URL: response.url,
			StatusCode: response.statusCode, Status: response.status,
			cause: protocolError(response, err),
		}
	}
	if envelope.Error == "" {
		return &HTTPError{
			Method: response.method, URL: response.url,
			StatusCode: response.statusCode, Status: response.status,
			cause: protocolError(response, errors.New("error response has an empty error field")),
		}
	}
	return &HTTPError{
		Method: response.method, URL: response.url,
		StatusCode: response.statusCode, Status: response.status,
		ServerError: envelope.Error,
	}
}

func operationHTTPError(response wireResponse) *HTTPError {
	// Authentication, method, and payload validation fail before an Operation
	// reaches the gateway and therefore use the ordinary control error shape.
	if response.statusCode == http.StatusBadRequest ||
		response.statusCode == http.StatusUnauthorized ||
		response.statusCode == http.StatusForbidden ||
		response.statusCode == http.StatusMethodNotAllowed {
		return controlHTTPError(response)
	}
	var envelope api.OperationError
	if err := decodeStrict(response.body, &envelope); err != nil {
		return &HTTPError{
			Method: response.method, URL: response.url,
			StatusCode: response.statusCode, Status: response.status,
			cause: protocolError(response, err),
		}
	}
	if envelope.Error == "" {
		return &HTTPError{
			Method: response.method, URL: response.url,
			StatusCode: response.statusCode, Status: response.status,
			Outcome: envelope.Outcome,
			cause:   protocolError(response, errors.New("Operation error response has an empty error field")),
		}
	}
	var cause error
	switch envelope.Code {
	case api.OperationErrorOutcomeUnknown:
		cause = gateway.ErrOutcomeUnknown
	case api.OperationErrorRequestConflict:
		cause = gateway.ErrOperationRequestConflict
	case "":
		// Accept the original v1 error envelope while peers are upgraded.
		if response.statusCode == http.StatusConflict {
			cause = gateway.ErrOutcomeUnknown
		}
	}
	return &HTTPError{
		Method: response.method, URL: response.url,
		StatusCode: response.statusCode, Status: response.status,
		ServerError: envelope.Error, Outcome: envelope.Outcome, cause: cause,
	}
}

func protocolError(response wireResponse, err error) *ProtocolError {
	return &ProtocolError{
		Method: response.method, URL: response.url,
		StatusCode: response.statusCode, Status: response.status, Err: err,
	}
}

func decodeStrict(encoded []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(encoded))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("response contains multiple JSON values")
		}
		return err
	}
	return nil
}
