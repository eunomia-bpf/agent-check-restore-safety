package apiclient

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const testToken = "test-token-0000000000000000000000000000"

func writeJSON(t *testing.T, writer http.ResponseWriter, status int, value any) {
	t.Helper()
	writer.Header().Set("Content-Type", "application/json; charset=utf-8")
	writer.WriteHeader(status)
	if err := json.NewEncoder(writer).Encode(value); err != nil {
		t.Error(err)
	}
}

func newClient(t *testing.T, handler http.Handler) *Client {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	client, err := New(server.URL, testToken, server.Client())
	if err != nil {
		t.Fatal(err)
	}
	return client
}

func TestClientImplementsEveryControlContract(t *testing.T) {
	requirement := kernel.Requirement{
		ID: "requirement-2", Results: map[string]uint32{"done": 1},
		Capacities: map[string]uint32{"slot": 1}, Kinds: map[string]kernel.KindSpec{},
	}
	certificate := kernel.Certificate{
		Schema: 1, Decision: kernel.Activate,
		History:  kernel.HistoryPoint{Sequence: 2, Hash: strings.Repeat("a", 64)},
		FromRule: 1, Requirement: requirement, Digest: strings.Repeat("b", 64),
	}
	state := kernel.State{
		History:    kernel.HistoryPoint{Sequence: 3, Hash: strings.Repeat("c", 64)},
		Operations: map[string]kernel.Operation{},
	}
	executeRequest := api.ExecuteRequest{
		CallID: "call-7", Kind: "finish", Method: http.MethodPut,
		URL:     "https://effects.invalid/v1/finish",
		Headers: map[string]string{"Content-Type": "application/json"}, Body: []byte(`{"id":7}`),
	}
	outcome := gateway.Outcome{
		OperationID: "op-7", Phase: kernel.Succeeded, StatusCode: http.StatusCreated,
		Body: []byte(`{"ok":true}`), ResultHash: strings.Repeat("d", 64),
	}
	var calls atomic.Int32
	handler := http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		calls.Add(1)
		if got := request.Header.Get("Authorization"); got != "Bearer "+testToken {
			t.Errorf("Authorization = %q", got)
		}
		switch request.URL.Path {
		case "/v1/state":
			if request.Method != http.MethodGet || request.Body == nil {
				t.Errorf("State request = %s body=%v", request.Method, request.Body)
			}
			writeJSON(t, writer, http.StatusOK, state)
		case "/v1/compile":
			if request.Method != http.MethodPost || request.Header.Get("Content-Type") != "application/json" {
				t.Errorf("Compile request = %s Content-Type=%q", request.Method, request.Header.Get("Content-Type"))
			}
			var got kernel.Requirement
			if err := json.NewDecoder(request.Body).Decode(&got); err != nil || !reflect.DeepEqual(got, requirement) {
				t.Errorf("Compile body=%+v error=%v", got, err)
			}
			writeJSON(t, writer, http.StatusOK, certificate)
		case "/v1/certificate-state":
			var got kernel.Certificate
			if err := json.NewDecoder(request.Body).Decode(&got); err != nil || !reflect.DeepEqual(got, certificate) {
				t.Errorf("CertificateState body=%+v error=%v", got, err)
			}
			writeJSON(t, writer, http.StatusOK, map[string]any{"schema": 1, "open_operations": map[string]any{}})
		case "/v1/activate":
			writeJSON(t, writer, http.StatusOK, state)
		case "/v1/execute":
			var got api.ExecuteRequest
			if err := json.NewDecoder(request.Body).Decode(&got); err != nil || !reflect.DeepEqual(got, executeRequest) {
				t.Errorf("Execute body=%+v error=%v", got, err)
			}
			writeJSON(t, writer, http.StatusOK, outcome)
		case "/v1/operations/op/a b/recover":
			if request.URL.EscapedPath() != "/v1/operations/op%2Fa%20b/recover" {
				t.Errorf("Recover escaped path = %q", request.URL.EscapedPath())
			}
			writeJSON(t, writer, http.StatusOK, outcome)
		default:
			t.Errorf("unexpected request %s %s", request.Method, request.URL.String())
			writeJSON(t, writer, http.StatusNotFound, api.ErrorResponse{Error: "not found"})
		}
	})
	client := newClient(t, handler)
	ctx := context.Background()

	gotState, err := client.State(ctx)
	if err != nil || !reflect.DeepEqual(gotState, state) {
		t.Fatalf("State=%+v error=%v", gotState, err)
	}
	gotCertificate, err := client.Compile(ctx, requirement)
	if err != nil || !reflect.DeepEqual(gotCertificate, certificate) {
		t.Fatalf("Compile=%+v error=%v", gotCertificate, err)
	}
	projection, err := client.CertificateState(ctx, certificate)
	if err != nil || string(projection) != `{"open_operations":{},"schema":1}` {
		t.Fatalf("CertificateState=%s error=%v", projection, err)
	}
	gotState, err = client.Activate(ctx, certificate)
	if err != nil || !reflect.DeepEqual(gotState, state) {
		t.Fatalf("Activate=%+v error=%v", gotState, err)
	}
	gotOutcome, err := client.Execute(ctx, executeRequest)
	if err != nil || !reflect.DeepEqual(gotOutcome, outcome) {
		t.Fatalf("Execute=%+v error=%v", gotOutcome, err)
	}
	gotOutcome, err = client.Recover(ctx, "op/a b")
	if err != nil || !reflect.DeepEqual(gotOutcome, outcome) {
		t.Fatalf("Recover=%+v error=%v", gotOutcome, err)
	}
	if calls.Load() != 6 {
		t.Fatalf("HTTP calls = %d, want 6", calls.Load())
	}
}

func TestClientRejectsInvalidResponseProtocol(t *testing.T) {
	tests := []struct {
		name        string
		contentType string
		body        string
	}{
		{name: "non JSON", contentType: "text/plain", body: `{}`},
		{name: "unknown field", contentType: "application/json", body: `{"operations":{},"surprise":true}`},
		{name: "trailing JSON", contentType: "application/json", body: `{"operations":{}} {}`},
		{name: "malformed JSON", contentType: "application/json", body: `{"operations":`},
		{name: "oversize", contentType: "application/json", body: strings.Repeat(" ", maxResponseBytes+1)},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			client := newClient(t, http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
				writer.Header().Set("Content-Type", test.contentType)
				writer.WriteHeader(http.StatusOK)
				_, _ = io.WriteString(writer, test.body)
			}))
			_, err := client.State(context.Background())
			var protocolErr *ProtocolError
			if !errors.As(err, &protocolErr) {
				t.Fatalf("error = %T %v, want ProtocolError", err, err)
			}
			if protocolErr.StatusCode != http.StatusOK || protocolErr.Status != "200 OK" {
				t.Fatalf("ProtocolError = %+v", protocolErr)
			}
		})
	}
}

func TestHTTPErrorPreservesServerStatusAndOperationOutcome(t *testing.T) {
	partial := gateway.Outcome{OperationID: "op-unknown", Phase: kernel.Unknown, ResultHash: strings.Repeat("e", 64)}
	client := newClient(t, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/v1/execute":
			var execute api.ExecuteRequest
			if err := json.NewDecoder(request.Body).Decode(&execute); err != nil {
				t.Error(err)
			}
			if execute.CallID == "conflict" {
				writeJSON(t, writer, http.StatusConflict, api.OperationError{
					Outcome: gateway.Outcome{OperationID: "op-conflict", Phase: kernel.Succeeded},
					Error:   gateway.ErrOperationRequestConflict.Error(), Code: api.OperationErrorRequestConflict,
				})
				return
			}
			writeJSON(t, writer, http.StatusConflict, api.OperationError{
				Outcome: partial, Error: gateway.ErrOutcomeUnknown.Error(), Code: api.OperationErrorOutcomeUnknown,
			})
		case "/v1/operations/missing/recover":
			writeJSON(t, writer, http.StatusNotFound, api.OperationError{
				Error: gateway.ErrOperationNotFound.Error(),
			})
		case "/v1/compile":
			writeJSON(t, writer, http.StatusUnprocessableEntity, api.ErrorResponse{Error: "requirement is impossible"})
		default:
			writeJSON(t, writer, http.StatusNotFound, api.ErrorResponse{Error: "not found"})
		}
	}))

	got, err := client.Execute(context.Background(), api.ExecuteRequest{CallID: "call", Kind: "finish", URL: "https://effect.invalid"})
	if !reflect.DeepEqual(got, partial) || !errors.Is(err, gateway.ErrOutcomeUnknown) {
		t.Fatalf("Execute outcome=%+v error=%v", got, err)
	}
	var httpErr *HTTPError
	if !errors.As(err, &httpErr) || httpErr.StatusCode != http.StatusConflict ||
		httpErr.ServerError != gateway.ErrOutcomeUnknown.Error() || !reflect.DeepEqual(httpErr.Outcome, partial) {
		t.Fatalf("Execute HTTPError = %+v", httpErr)
	}
	conflictOutcome, err := client.Execute(context.Background(), api.ExecuteRequest{
		CallID: "conflict", Kind: "finish", URL: "https://effect.invalid", Body: []byte("different"),
	})
	if !errors.Is(err, gateway.ErrOperationRequestConflict) || conflictOutcome.OperationID != "op-conflict" ||
		conflictOutcome.Phase != kernel.Succeeded {
		t.Fatalf("request conflict outcome=%+v error=%v", conflictOutcome, err)
	}

	_, err = client.Recover(context.Background(), "missing")
	if !errors.Is(err, gateway.ErrOperationNotFound) {
		t.Fatalf("Recover error = %v", err)
	}

	_, err = client.Compile(context.Background(), kernel.Requirement{})
	if !errors.As(err, &httpErr) || httpErr.StatusCode != http.StatusUnprocessableEntity ||
		httpErr.ServerError != "requirement is impossible" || httpErr.Outcome.OperationID != "" {
		t.Fatalf("Compile HTTPError = %+v", httpErr)
	}
}

func TestErrorResponsesAreStrictlyDecoded(t *testing.T) {
	client := newClient(t, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		writer.WriteHeader(http.StatusUnprocessableEntity)
		if request.URL.Path == "/v1/execute" {
			_, _ = io.WriteString(writer, `{"outcome":{},"error":"denied","extra":true}`)
			return
		}
		_, _ = io.WriteString(writer, `{"error":"denied"} {}`)
	}))

	_, err := client.Execute(context.Background(), api.ExecuteRequest{})
	var httpErr *HTTPError
	var protocolErr *ProtocolError
	if !errors.As(err, &httpErr) || httpErr.StatusCode != http.StatusUnprocessableEntity ||
		!errors.As(err, &protocolErr) {
		t.Fatalf("Execute error = %T %v", err, err)
	}
	_, err = client.Compile(context.Background(), kernel.Requirement{})
	if !errors.As(err, &httpErr) || httpErr.StatusCode != http.StatusUnprocessableEntity ||
		!errors.As(err, &protocolErr) {
		t.Fatalf("Compile error = %T %v", err, err)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (function roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}

func TestClientUsesContextAndDoesNotRetry(t *testing.T) {
	var calls atomic.Int32
	transportErr := errors.New("transport failed")
	client, err := New("https://control.invalid", testToken, &http.Client{
		Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
			calls.Add(1)
			if request.Context().Err() != nil {
				return nil, request.Context().Err()
			}
			return nil, transportErr
		}),
	})
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.State(context.Background())
	if !errors.Is(err, transportErr) || calls.Load() != 1 {
		t.Fatalf("transport error=%v calls=%d", err, calls.Load())
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err = client.State(ctx)
	if !errors.Is(err, context.Canceled) || calls.Load() != 2 {
		t.Fatalf("cancel error=%v calls=%d", err, calls.Load())
	}
}

func TestClientDoesNotFollowRedirects(t *testing.T) {
	var destinationCalls atomic.Int32
	destination := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		destinationCalls.Add(1)
		writeJSON(t, writer, http.StatusOK, kernel.State{Operations: map[string]kernel.Operation{}})
	}))
	defer destination.Close()
	client := newClient(t, http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writer.Header().Set("Location", destination.URL+"/v1/state")
		writeJSON(t, writer, http.StatusTemporaryRedirect, api.ErrorResponse{Error: "redirect denied"})
	}))
	_, err := client.State(context.Background())
	var httpErr *HTTPError
	if !errors.As(err, &httpErr) || httpErr.StatusCode != http.StatusTemporaryRedirect {
		t.Fatalf("redirect error = %T %v", err, err)
	}
	if destinationCalls.Load() != 0 {
		t.Fatalf("redirect destination calls = %d", destinationCalls.Load())
	}
}

func TestNewRejectsUnsafeConfiguration(t *testing.T) {
	tests := []struct {
		baseURL string
		token   string
	}{
		{baseURL: "", token: testToken},
		{baseURL: "unix:///run/control.sock", token: testToken},
		{baseURL: "https://name:secret@control.invalid", token: testToken},
		{baseURL: "https://control.invalid?token=secret", token: testToken},
		{baseURL: "https://control.invalid#fragment", token: testToken},
		{baseURL: "https://control.invalid", token: ""},
		{baseURL: "https://control.invalid", token: "too-short"},
		{baseURL: "https://control.invalid", token: "has space"},
		{baseURL: "https://control.invalid", token: "has\x07control"},
	}
	for _, test := range tests {
		if _, err := New(test.baseURL, test.token, nil); err == nil {
			t.Errorf("New(%q, %q) succeeded", test.baseURL, test.token)
		}
	}
}
