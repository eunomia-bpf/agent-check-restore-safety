package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

type executorFunc func(context.Context, api.ExecuteRequest) (gateway.Outcome, error)

func (function executorFunc) Execute(ctx context.Context, request api.ExecuteRequest) (gateway.Outcome, error) {
	return function(ctx, request)
}

func testConfig(t *testing.T) Config {
	t.Helper()
	config, err := ParseConfig([]byte(validAdapterConfig))
	if err != nil {
		t.Fatal(err)
	}
	return config
}

func newTestAdapter(t *testing.T, executor Executor, timeout time.Duration) *Adapter {
	t.Helper()
	adapter, err := NewAdapter(executor, testConfig(t), timeout)
	if err != nil {
		t.Fatal(err)
	}
	return adapter
}

func effectHTTPBody(orderID string, closure *string) string {
	if closure == nil {
		return `{"order_id":"` + orderID + `","amount_cents":4200}`
	}
	return `{"order_id":"` + orderID + `","amount_cents":4200,"closure_version":"` + *closure + `"}`
}

func effectRequestFor(path, body, callID string) *http.Request {
	request := httptest.NewRequest(http.MethodPost, path, strings.NewReader(body))
	operationID := deriveOperationID(callID)
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set(headerOperationID, operationID)
	request.Header.Set(headerIdempotencyKey, operationID)
	request.Header.Set("Content-Length", strconv.Itoa(len(body)))
	return request
}

func TestOrdinarySuccessPreservesProviderStatusAndBody(t *testing.T) {
	orderID := "order-ordinary"
	body := effectHTTPBody(orderID, nil)
	operationID := deriveOperationID(orderID)
	resultHash := strings.Repeat("a", 64)
	providerBody := []byte(` {"schema":1,"operation_id":"` + operationID + `","outcome":"succeeded","result_hash":"` + resultHash + `","remote_reference":"payment/7"} `)
	var calls atomic.Int32
	adapter := newTestAdapter(t, executorFunc(func(_ context.Context, got api.ExecuteRequest) (gateway.Outcome, error) {
		calls.Add(1)
		want := api.ExecuteRequest{
			CallID: orderID, Kind: "charge-v2", Method: http.MethodPost,
			URL:     "http://payment:8081/v2/charge",
			Headers: map[string]string{"Content-Type": "application/json"}, Body: []byte(body),
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("Execute request = %+v, want %+v", got, want)
		}
		return gateway.Outcome{
			OperationID: operationID, Phase: kernel.Succeeded, StatusCode: http.StatusOK,
			Body: providerBody, ResultHash: resultHash,
		}, nil
	}), time.Second)

	response := httptest.NewRecorder()
	adapter.Handler().ServeHTTP(response, effectRequestFor("/v2/charge", body, orderID))
	if response.Code != http.StatusOK || !reflect.DeepEqual(response.Body.Bytes(), providerBody) {
		t.Fatalf("response status=%d body=%q", response.Code, response.Body.Bytes())
	}
	if response.Header().Get("Content-Type") != "application/json" ||
		response.Header().Get("Cache-Control") != "no-store" ||
		response.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Fatalf("response headers = %+v", response.Header())
	}
	if calls.Load() != 1 {
		t.Fatalf("Execute calls = %d", calls.Load())
	}
}

func TestRecoveredObservationBecomesEquivalentEffectReceipt(t *testing.T) {
	orderID := "order-recovered"
	closure := "unsafe-v2"
	body := effectHTTPBody(orderID, &closure)
	callID := "complete:" + orderID
	operationID := deriveOperationID(callID)
	requestHash := strings.Repeat("b", 64)
	factHash := strings.Repeat("c", 64)
	observation := []byte(`{"schema":1,"operation_id":"` + operationID + `","request_hash":"` + requestHash + `","outcome":"succeeded","fact_hash":"` + factHash + `","remote_reference":"completion/9"}`)
	adapter := newTestAdapter(t, executorFunc(func(_ context.Context, got api.ExecuteRequest) (gateway.Outcome, error) {
		if got.CallID != callID || got.Kind != "finish-v2" || got.URL != "http://completion:8081/v1/complete" {
			t.Errorf("Execute request = %+v", got)
		}
		return gateway.Outcome{
			OperationID: operationID, Phase: kernel.Succeeded, StatusCode: http.StatusOK,
			Body: observation, ResultHash: factHash, RecoveredByQuery: true,
		}, nil
	}), time.Second)

	response := httptest.NewRecorder()
	adapter.Handler().ServeHTTP(response, effectRequestFor("/v1/complete", body, callID))
	want := `{"schema":1,"operation_id":"` + operationID + `","outcome":"succeeded","result_hash":"` + factHash + `","remote_reference":"completion/9"}`
	if response.Code != http.StatusOK || response.Body.String() != want {
		t.Fatalf("response status=%d body=%q want=%q", response.Code, response.Body.String(), want)
	}
}

func TestRequestValidationPrecedesControlExecution(t *testing.T) {
	var calls atomic.Int32
	adapter := newTestAdapter(t, executorFunc(func(context.Context, api.ExecuteRequest) (gateway.Outcome, error) {
		calls.Add(1)
		return gateway.Outcome{}, nil
	}), time.Second)
	legacyBody := effectHTTPBody("order-1", nil)
	unsafe := "unsafe-v2"
	unsafeBody := effectHTTPBody("order-1", &unsafe)

	tests := []struct {
		name   string
		status int
		make   func() *http.Request
	}{
		{name: "unknown path", status: http.StatusNotFound, make: func() *http.Request {
			return effectRequestFor("/v1/query", legacyBody, "order-1")
		}},
		{name: "wrong method", status: http.StatusMethodNotAllowed, make: func() *http.Request {
			request := effectRequestFor("/v1/charge", legacyBody, "order-1")
			request.Method = http.MethodPut
			return request
		}},
		{name: "query", status: http.StatusBadRequest, make: func() *http.Request {
			return effectRequestFor("/v1/charge?target=http://other", legacyBody, "order-1")
		}},
		{name: "absolute form", status: http.StatusBadRequest, make: func() *http.Request {
			request := effectRequestFor("/v1/charge", legacyBody, "order-1")
			request.URL.Scheme = "http"
			request.URL.Host = "attacker.invalid"
			return request
		}},
		{name: "unexpected header", status: http.StatusBadRequest, make: func() *http.Request {
			request := effectRequestFor("/v1/charge", legacyBody, "order-1")
			request.Header.Set("Authorization", "Bearer leaked")
			return request
		}},
		{name: "duplicate identity", status: http.StatusBadRequest, make: func() *http.Request {
			request := effectRequestFor("/v1/charge", legacyBody, "order-1")
			request.Header[headerOperationID] = []string{deriveOperationID("order-1"), deriveOperationID("order-1")}
			return request
		}},
		{name: "content type parameters", status: http.StatusUnsupportedMediaType, make: func() *http.Request {
			request := effectRequestFor("/v1/charge", legacyBody, "order-1")
			request.Header.Set("Content-Type", "application/json; charset=utf-8")
			return request
		}},
		{name: "unsupported response encoding", status: http.StatusBadRequest, make: func() *http.Request {
			request := effectRequestFor("/v1/charge", legacyBody, "order-1")
			request.Header.Set("Accept-Encoding", "br")
			return request
		}},
		{name: "wrong operation identity", status: http.StatusBadRequest, make: func() *http.Request {
			return effectRequestFor("/v1/charge", legacyBody, "different-order")
		}},
		{name: "unknown length", status: http.StatusLengthRequired, make: func() *http.Request {
			request := effectRequestFor("/v1/charge", legacyBody, "order-1")
			request.Header.Del("Content-Length")
			request.ContentLength = -1
			return request
		}},
		{name: "mismatched content length", status: http.StatusBadRequest, make: func() *http.Request {
			request := effectRequestFor("/v1/charge", legacyBody, "order-1")
			request.Header.Set("Content-Length", "1")
			return request
		}},
		{name: "transfer encoding", status: http.StatusBadRequest, make: func() *http.Request {
			request := effectRequestFor("/v1/charge", legacyBody, "order-1")
			request.TransferEncoding = []string{"chunked"}
			return request
		}},
		{name: "unknown body field", status: http.StatusBadRequest, make: func() *http.Request {
			return effectRequestFor("/v1/charge", `{"order_id":"order-1","amount_cents":4200,"url":"http://other"}`, "order-1")
		}},
		{name: "duplicate body field", status: http.StatusBadRequest, make: func() *http.Request {
			return effectRequestFor("/v1/charge", `{"order_id":"order-1","order_id":"order-1","amount_cents":4200}`, "order-1")
		}},
		{name: "missing body field", status: http.StatusBadRequest, make: func() *http.Request {
			return effectRequestFor("/v1/charge", `{"order_id":"order-1"}`, "order-1")
		}},
		{name: "null body field", status: http.StatusBadRequest, make: func() *http.Request {
			return effectRequestFor("/v1/charge", `{"order_id":null,"amount_cents":4200}`, "order-1")
		}},
		{name: "noncanonical amount", status: http.StatusBadRequest, make: func() *http.Request {
			return effectRequestFor("/v1/charge", `{"order_id":"order-1","amount_cents":42e2}`, "order-1")
		}},
		{name: "cross-kind identity order", status: http.StatusBadRequest, make: func() *http.Request {
			return effectRequestFor("/v1/charge", `{"order_id":"complete:order-1","amount_cents":4200}`, "complete:order-1")
		}},
		{name: "wrong closure binding", status: http.StatusBadRequest, make: func() *http.Request {
			return effectRequestFor("/v2/charge", unsafeBody, "order-1")
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			response := httptest.NewRecorder()
			adapter.Handler().ServeHTTP(response, test.make())
			if response.Code != test.status {
				t.Fatalf("status=%d body=%q want=%d", response.Code, response.Body.String(), test.status)
			}
		})
	}

	oversize := effectRequestFor("/v1/charge", strings.Repeat("x", maxEffectRequestBytes+1), "order-1")
	response := httptest.NewRecorder()
	adapter.Handler().ServeHTTP(response, oversize)
	if response.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("oversize status=%d body=%q", response.Code, response.Body.String())
	}
	if calls.Load() != 0 {
		t.Fatalf("invalid requests reached Execute %d times", calls.Load())
	}
}

func TestMissingExactClosureDoesNotFallBackToAnotherBinding(t *testing.T) {
	config := testConfig(t)
	config.Routes = []Route{config.Routes[3]}
	var calls atomic.Int32
	adapter, err := NewAdapter(executorFunc(func(context.Context, api.ExecuteRequest) (gateway.Outcome, error) {
		calls.Add(1)
		return gateway.Outcome{}, nil
	}), config, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	body := effectHTTPBody("order-1", nil)
	response := httptest.NewRecorder()
	adapter.Handler().ServeHTTP(response, effectRequestFor("/v1/complete", body, "complete:order-1"))
	if response.Code != http.StatusBadRequest || calls.Load() != 0 {
		t.Fatalf("status=%d calls=%d body=%q", response.Code, calls.Load(), response.Body.String())
	}
}

func TestInvalidControlRecordsAreNotReturnedToTemporal(t *testing.T) {
	orderID := "order-control-invalid"
	body := effectHTTPBody(orderID, nil)
	operationID := deriveOperationID(orderID)
	hash := strings.Repeat("d", 64)
	validReceipt := `{"schema":1,"operation_id":"` + operationID + `","outcome":"succeeded","result_hash":"` + hash + `","remote_reference":"payment/1"}`
	validObservation := `{"schema":1,"operation_id":"` + operationID + `","request_hash":"` + strings.Repeat("e", 64) + `","outcome":"succeeded","fact_hash":"` + hash + `","remote_reference":"payment/1"}`
	tests := []struct {
		name    string
		outcome gateway.Outcome
	}{
		{name: "ordinary unknown field", outcome: gateway.Outcome{
			OperationID: operationID, Phase: kernel.Succeeded, StatusCode: http.StatusOK,
			Body: []byte(strings.Replace(validReceipt, `}`, `,"extra":true}`, 1)), ResultHash: hash,
		}},
		{name: "ordinary mismatched result", outcome: gateway.Outcome{
			OperationID: operationID, Phase: kernel.Succeeded, StatusCode: http.StatusOK,
			Body: []byte(validReceipt), ResultHash: strings.Repeat("f", 64),
		}},
		{name: "ordinary wrong status", outcome: gateway.Outcome{
			OperationID: operationID, Phase: kernel.Succeeded, StatusCode: http.StatusCreated,
			Body: []byte(validReceipt), ResultHash: hash,
		}},
		{name: "observation duplicate", outcome: gateway.Outcome{
			OperationID: operationID, Phase: kernel.Succeeded, StatusCode: http.StatusOK,
			Body:       []byte(strings.Replace(validObservation, `"schema":1`, `"schema":1,"schema":1`, 1)),
			ResultHash: hash, RecoveredByQuery: true,
		}},
		{name: "observation mismatched fact", outcome: gateway.Outcome{
			OperationID: operationID, Phase: kernel.Succeeded, StatusCode: http.StatusOK,
			Body: []byte(validObservation), ResultHash: strings.Repeat("f", 64), RecoveredByQuery: true,
		}},
		{name: "observation invalid request hash", outcome: gateway.Outcome{
			OperationID: operationID, Phase: kernel.Succeeded, StatusCode: http.StatusOK,
			Body:       []byte(strings.Replace(validObservation, strings.Repeat("e", 64), "not-a-hash", 1)),
			ResultHash: hash, RecoveredByQuery: true,
		}},
		{name: "wrong control identity", outcome: gateway.Outcome{
			OperationID: deriveOperationID("different"), Phase: kernel.Succeeded, StatusCode: http.StatusOK,
			Body: []byte(validReceipt), ResultHash: hash,
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			adapter := newTestAdapter(t, executorFunc(func(context.Context, api.ExecuteRequest) (gateway.Outcome, error) {
				return test.outcome, nil
			}), time.Second)
			response := httptest.NewRecorder()
			adapter.Handler().ServeHTTP(response, effectRequestFor("/v1/charge", body, orderID))
			if response.Code != http.StatusBadGateway {
				t.Fatalf("status=%d body=%q", response.Code, response.Body.String())
			}
		})
	}
}

func TestExecutionErrorsRemainUnsettled(t *testing.T) {
	body := effectHTTPBody("order-error", nil)
	tests := []struct {
		name   string
		status int
		fn     executorFunc
	}{
		{name: "unknown", status: http.StatusConflict, fn: func(context.Context, api.ExecuteRequest) (gateway.Outcome, error) {
			return gateway.Outcome{Phase: kernel.Unknown}, gateway.ErrOutcomeUnknown
		}},
		{name: "control failure", status: http.StatusBadGateway, fn: func(context.Context, api.ExecuteRequest) (gateway.Outcome, error) {
			return gateway.Outcome{}, errors.New("control unavailable")
		}},
		{name: "deadline", status: http.StatusGatewayTimeout, fn: func(ctx context.Context, _ api.ExecuteRequest) (gateway.Outcome, error) {
			<-ctx.Done()
			return gateway.Outcome{}, ctx.Err()
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			timeout := time.Second
			if test.name == "deadline" {
				timeout = time.Millisecond
			}
			adapter := newTestAdapter(t, test.fn, timeout)
			response := httptest.NewRecorder()
			adapter.Handler().ServeHTTP(response, effectRequestFor("/v1/charge", body, "order-error"))
			if response.Code != test.status {
				t.Fatalf("status=%d body=%q want=%d", response.Code, response.Body.String(), test.status)
			}
		})
	}
}

func TestHealthIsTheOnlyNonEffectEndpoint(t *testing.T) {
	adapter := newTestAdapter(t, executorFunc(func(context.Context, api.ExecuteRequest) (gateway.Outcome, error) {
		t.Fatal("health reached executor")
		return gateway.Outcome{}, nil
	}), time.Second)
	response := httptest.NewRecorder()
	adapter.Handler().ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if response.Code != http.StatusOK || response.Body.String() != `{"status":"ok"}` {
		t.Fatalf("health status=%d body=%q", response.Code, response.Body.String())
	}
	var decoded map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &decoded); err != nil {
		t.Fatal(err)
	}
	response = httptest.NewRecorder()
	adapter.Handler().ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/v1/stats", nil))
	if response.Code != http.StatusNotFound {
		t.Fatalf("undeclared status=%d", response.Code)
	}
}

func TestReadBodyFailureIsRejected(t *testing.T) {
	adapter := newTestAdapter(t, executorFunc(func(context.Context, api.ExecuteRequest) (gateway.Outcome, error) {
		t.Fatal("broken body reached executor")
		return gateway.Outcome{}, nil
	}), time.Second)
	request := effectRequestFor("/v1/charge", effectHTTPBody("order-broken", nil), "order-broken")
	request.Body = io.NopCloser(errorReader{})
	response := httptest.NewRecorder()
	adapter.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("status=%d body=%q", response.Code, response.Body.String())
	}
}

type errorReader struct{}

func (errorReader) Read([]byte) (int, error) { return 0, errors.New("read failed") }
