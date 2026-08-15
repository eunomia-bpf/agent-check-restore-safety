package effectproxy

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

type recordingExecutor struct {
	mu       sync.Mutex
	requests []api.ExecuteRequest
	outcome  gateway.Outcome
	err      error
	execute  func(context.Context, api.ExecuteRequest) (gateway.Outcome, error)
}

func (e *recordingExecutor) Execute(ctx context.Context, request api.ExecuteRequest) (gateway.Outcome, error) {
	e.mu.Lock()
	e.requests = append(e.requests, request)
	e.mu.Unlock()
	if e.execute != nil {
		return e.execute(ctx, request)
	}
	return e.outcome, e.err
}

func (e *recordingExecutor) calls() []api.ExecuteRequest {
	e.mu.Lock()
	defer e.mu.Unlock()
	return append([]api.ExecuteRequest(nil), e.requests...)
}

func testConfig() Config {
	return Config{Schema: ConfigSchema, Routes: []Route{{
		Name: "charge", Kind: "charge-payment", Method: http.MethodPut,
		URL: "https://provider.internal/fixed/charge", ContentTypes: []string{"application/json"},
	}}}
}

func newTestProxy(t *testing.T, executor Executor) *Proxy {
	t.Helper()
	proxy, err := New(executor, testConfig(), Options{ExecutionTimeout: time.Second})
	if err != nil {
		t.Fatal(err)
	}
	return proxy
}

func effectRequest(body io.Reader) *http.Request {
	request := httptest.NewRequest(http.MethodPost, "/v1/effects/charge", body)
	request.Header.Set(headerCallID, "workflow/run-7/activity-3")
	request.Header.Set("Content-Type", "application/json")
	return request
}

func idempotentEffectRequest(key string, body io.Reader) *http.Request {
	request := effectRequest(body)
	request.Header.Del(headerCallID)
	request.Header.Set(headerIdempotencyKey, key)
	return request
}

func decodeError(t *testing.T, recorder *httptest.ResponseRecorder) errorBody {
	t.Helper()
	var body errorBody
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatalf("error response is not JSON: %v: %q", err, recorder.Body.String())
	}
	return body
}

func TestProxyBindsTargetAndForwardsOnlySafeContentType(t *testing.T) {
	executor := &recordingExecutor{outcome: gateway.Outcome{
		OperationID: "op-fixed", Phase: kernel.Succeeded, StatusCode: http.StatusCreated,
		Body: []byte(`{"receipt":"paid"}`), ResultHash: strings.Repeat("a", 64),
	}}
	proxy := newTestProxy(t, executor)
	request := effectRequest(strings.NewReader(`{"target":"http://attacker.invalid"}`))
	request.Host = "attacker.invalid"
	request.Header.Set("Authorization", "Bearer workload-secret")
	request.Header.Set("X-Target-URL", "http://attacker.invalid")
	request.Header.Set("Cookie", "private=true")
	recorder := httptest.NewRecorder()

	proxy.Handler().ServeHTTP(recorder, request)

	if recorder.Code != http.StatusCreated || recorder.Body.String() != `{"receipt":"paid"}` {
		t.Fatalf("response status=%d body=%q", recorder.Code, recorder.Body.String())
	}
	calls := executor.calls()
	if len(calls) != 1 {
		t.Fatalf("Execute calls = %d", len(calls))
	}
	got := calls[0]
	if got.CallID != "workflow/run-7/activity-3" || got.Kind != "charge-payment" || got.Method != http.MethodPut ||
		got.URL != "https://provider.internal/fixed/charge" {
		t.Fatalf("Execute request authority changed: %+v", got)
	}
	if len(got.Headers) != 1 || got.Headers["Content-Type"] != "application/json" {
		t.Fatalf("forwarded headers = %#v", got.Headers)
	}
	if string(got.Body) != `{"target":"http://attacker.invalid"}` {
		t.Fatalf("forwarded body = %q", got.Body)
	}
	if recorder.Header().Get(headerOperationID) != "op-fixed" || recorder.Header().Get(headerPhase) != "succeeded" ||
		recorder.Header().Get(headerResultHash) != strings.Repeat("a", 64) || recorder.Header().Get(headerReused) != "false" ||
		recorder.Header().Get(headerRecoveredByQuery) != "false" {
		t.Fatalf("metadata headers = %#v", recorder.Header())
	}
	if recorder.Header().Get("Content-Type") != "application/json" || recorder.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Fatalf("response safety headers = %#v", recorder.Header())
	}
}

func TestProxyDomainsIdempotencyKeyByLogicalRoute(t *testing.T) {
	config := testConfig()
	config.Routes = append(config.Routes, Route{
		Name: "refund", Kind: "refund-payment", Method: http.MethodPost,
		URL: "https://provider.internal/fixed/refund", ContentTypes: []string{"application/json"},
	})
	executor := &recordingExecutor{outcome: gateway.Outcome{
		OperationID: "op-fixed", Phase: kernel.Succeeded, StatusCode: http.StatusOK,
		ResultHash: strings.Repeat("a", 64),
	}}
	proxy, err := New(executor, config, Options{ExecutionTimeout: time.Second})
	if err != nil {
		t.Fatal(err)
	}

	for _, route := range []string{"charge", "refund"} {
		request := idempotentEffectRequest("order/A-17:payment", strings.NewReader(`{}`))
		request.URL.Path = "/v1/effects/" + route
		// The compatibility header is identity input, never caller-controlled
		// provider authority forwarded through ExecuteRequest.Headers.
		request.Header.Set("Authorization", "Bearer workload-secret")
		recorder := httptest.NewRecorder()
		proxy.Handler().ServeHTTP(recorder, request)
		if recorder.Code != http.StatusOK {
			t.Fatalf("route=%s status=%d body=%q", route, recorder.Code, recorder.Body.String())
		}
	}

	calls := executor.calls()
	if len(calls) != 2 {
		t.Fatalf("Execute calls = %d", len(calls))
	}
	if calls[0].CallID != "effect-route-idempotency-v1:6:charge:order/A-17:payment" {
		t.Fatalf("charge CallID = %q", calls[0].CallID)
	}
	if calls[1].CallID != "effect-route-idempotency-v1:6:refund:order/A-17:payment" {
		t.Fatalf("refund CallID = %q", calls[1].CallID)
	}
	if calls[0].CallID == calls[1].CallID {
		t.Fatal("the same Idempotency-Key crossed logical route domains")
	}
	for _, call := range calls {
		if len(call.Headers) != 1 || call.Headers["Content-Type"] != "application/json" {
			t.Fatalf("forwarded headers = %#v", call.Headers)
		}
		if _, ok := call.Headers[headerIdempotencyKey]; ok {
			t.Fatalf("Idempotency-Key was forwarded: %#v", call.Headers)
		}
	}
}

func TestProxyPreservesDedicatedCallIDWireValue(t *testing.T) {
	executor := &recordingExecutor{outcome: gateway.Outcome{
		OperationID: "op-fixed", Phase: kernel.Succeeded, StatusCode: http.StatusOK,
		ResultHash: strings.Repeat("a", 64),
	}}
	request := effectRequest(strings.NewReader(`{}`))
	request.Header.Set(headerCallID, "effect-route-idempotency-v1:6:charge:literal")
	recorder := httptest.NewRecorder()
	newTestProxy(t, executor).Handler().ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("status=%d body=%q", recorder.Code, recorder.Body.String())
	}
	calls := executor.calls()
	if len(calls) != 1 || calls[0].CallID != "effect-route-idempotency-v1:6:charge:literal" {
		t.Fatalf("Execute calls = %+v", calls)
	}
}

func TestProxyBoundsRouteScopedIdempotencyCallID(t *testing.T) {
	const prefix = "effect-route-idempotency-v1:6:charge:"
	maxKeyBytes := MaxCallIDBytes - len(prefix)
	executor := &recordingExecutor{outcome: gateway.Outcome{
		OperationID: "op-fixed", Phase: kernel.Succeeded, StatusCode: http.StatusOK,
		ResultHash: strings.Repeat("a", 64),
	}}
	proxy := newTestProxy(t, executor)

	accepted := idempotentEffectRequest(strings.Repeat("x", maxKeyBytes), strings.NewReader(`{}`))
	acceptedRecorder := httptest.NewRecorder()
	proxy.Handler().ServeHTTP(acceptedRecorder, accepted)
	if acceptedRecorder.Code != http.StatusOK {
		t.Fatalf("maximum key status=%d body=%q", acceptedRecorder.Code, acceptedRecorder.Body.String())
	}
	calls := executor.calls()
	if len(calls) != 1 || len(calls[0].CallID) != MaxCallIDBytes {
		t.Fatalf("maximum encoded CallID calls=%d length=%d", len(calls), len(calls[0].CallID))
	}

	rejected := idempotentEffectRequest(strings.Repeat("x", maxKeyBytes+1), strings.NewReader(`{}`))
	rejectedRecorder := httptest.NewRecorder()
	proxy.Handler().ServeHTTP(rejectedRecorder, rejected)
	if rejectedRecorder.Code != http.StatusBadRequest {
		t.Fatalf("oversized key status=%d body=%q", rejectedRecorder.Code, rejectedRecorder.Body.String())
	}
	if calls := executor.calls(); len(calls) != 1 {
		t.Fatalf("Execute called for oversized route-scoped identity: %d total calls", len(calls))
	}
}

func TestProxyFailsClosedWithoutRetry(t *testing.T) {
	tests := []struct {
		name    string
		outcome gateway.Outcome
		err     error
		status  int
	}{
		{"unknown-sentinel", gateway.Outcome{OperationID: "op-1", Phase: kernel.Unknown}, gateway.ErrOutcomeUnknown, http.StatusConflict},
		{"unknown-phase", gateway.Outcome{OperationID: "op-2", Phase: kernel.Unknown}, errors.New("remote control error"), http.StatusConflict},
		{"in-flight", gateway.Outcome{OperationID: "op-3", Phase: kernel.Dispatched}, errors.New("already in flight"), http.StatusConflict},
		{"request-conflict", gateway.Outcome{OperationID: "op-4", Phase: kernel.Succeeded}, gateway.ErrOperationRequestConflict, http.StatusConflict},
		{"control-failure", gateway.Outcome{}, errors.New("control unavailable"), http.StatusBadGateway},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			executor := &recordingExecutor{outcome: test.outcome, err: test.err}
			recorder := httptest.NewRecorder()
			newTestProxy(t, executor).Handler().ServeHTTP(recorder, effectRequest(strings.NewReader(`{}`)))
			if recorder.Code != test.status || !strings.HasPrefix(recorder.Header().Get("Content-Type"), "application/json") {
				t.Fatalf("status=%d headers=%#v body=%q", recorder.Code, recorder.Header(), recorder.Body.String())
			}
			body := decodeError(t, recorder)
			if body.Error == "" || body.Detail != test.err.Error() {
				t.Fatalf("error body = %+v", body)
			}
			if calls := executor.calls(); len(calls) != 1 {
				t.Fatalf("Execute calls = %d; proxy must not retry", len(calls))
			}
		})
	}
}

func TestProxyReturnsSettledProviderFailureVerbatim(t *testing.T) {
	executor := &recordingExecutor{outcome: gateway.Outcome{
		OperationID: "op-declined", Phase: kernel.Failed, StatusCode: http.StatusPaymentRequired,
		Body: []byte("declined"), ResultHash: strings.Repeat("b", 64), Reused: true,
	}}
	recorder := httptest.NewRecorder()
	newTestProxy(t, executor).Handler().ServeHTTP(recorder, effectRequest(strings.NewReader(`{}`)))
	if recorder.Code != http.StatusPaymentRequired || recorder.Body.String() != "declined" ||
		recorder.Header().Get(headerPhase) != "failed" || recorder.Header().Get(headerReused) != "true" {
		t.Fatalf("response status=%d headers=%#v body=%q", recorder.Code, recorder.Header(), recorder.Body.String())
	}
}

func TestProxyRejectsRequestMutationsBeforeExecution(t *testing.T) {
	tests := map[string]func() *http.Request{
		"unknown-route": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.URL.Path = "/v1/effects/other"
			return request
		},
		"extra-path": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.URL.Path += "/other"
			return request
		},
		"caller-target-query": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.URL.RawQuery = "url=http%3A%2F%2Fattacker.invalid"
			return request
		},
		"wrong-method": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.Method = http.MethodPut
			return request
		},
		"missing-call-id": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.Header.Del(headerCallID)
			return request
		},
		"both-identity-headers": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.Header.Set(headerIdempotencyKey, "same-action")
			return request
		},
		"duplicate-call-id": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.Header.Add(headerCallID, "other")
			return request
		},
		"empty-call-id": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.Header.Set(headerCallID, "")
			return request
		},
		"control-call-id": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.Header.Set(headerCallID, "run-7\x07bell")
			return request
		},
		"oversized-call-id": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.Header.Set(headerCallID, strings.Repeat("x", MaxCallIDBytes+1))
			return request
		},
		"duplicate-idempotency-key": func() *http.Request {
			request := idempotentEffectRequest("same-action", strings.NewReader(`{}`))
			request.Header.Add(headerIdempotencyKey, "other")
			return request
		},
		"empty-idempotency-key": func() *http.Request {
			return idempotentEffectRequest("", strings.NewReader(`{}`))
		},
		"control-idempotency-key": func() *http.Request {
			return idempotentEffectRequest("same-action\x07bell", strings.NewReader(`{}`))
		},
		"unstable-idempotency-key": func() *http.Request {
			return idempotentEffectRequest(" same-action ", strings.NewReader(`{}`))
		},
		"unstable-call-id": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.Header.Set(headerCallID, " run-7 ")
			return request
		},
		"missing-content-type": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.Header.Del("Content-Type")
			return request
		},
		"unlisted-content-type": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.Header.Set("Content-Type", "text/plain")
			return request
		},
		"duplicate-content-type": func() *http.Request {
			request := effectRequest(strings.NewReader(`{}`))
			request.Header.Add("Content-Type", "application/json")
			return request
		},
		"oversized-body": func() *http.Request {
			return effectRequest(bytes.NewReader(bytes.Repeat([]byte("x"), int(MaxRequestBytes)+1)))
		},
	}
	for name, request := range tests {
		t.Run(name, func(t *testing.T) {
			executor := &recordingExecutor{outcome: gateway.Outcome{
				OperationID: "should-not-run", Phase: kernel.Succeeded, StatusCode: http.StatusOK,
			}}
			recorder := httptest.NewRecorder()
			newTestProxy(t, executor).Handler().ServeHTTP(recorder, request())
			if recorder.Code < 400 || recorder.Code > 499 {
				t.Fatalf("status=%d body=%q", recorder.Code, recorder.Body.String())
			}
			_ = decodeError(t, recorder)
			if calls := executor.calls(); len(calls) != 0 {
				t.Fatalf("Execute called %d times", len(calls))
			}
		})
	}
}

func TestProxyBoundsControlCallWithContextDeadline(t *testing.T) {
	deadlineSeen := make(chan time.Time, 1)
	executor := &recordingExecutor{execute: func(ctx context.Context, _ api.ExecuteRequest) (gateway.Outcome, error) {
		deadline, ok := ctx.Deadline()
		if !ok {
			return gateway.Outcome{}, errors.New("missing deadline")
		}
		deadlineSeen <- deadline
		<-ctx.Done()
		return gateway.Outcome{}, ctx.Err()
	}}
	proxy, err := New(executor, testConfig(), Options{ExecutionTimeout: 20 * time.Millisecond})
	if err != nil {
		t.Fatal(err)
	}
	start := time.Now()
	recorder := httptest.NewRecorder()
	proxy.Handler().ServeHTTP(recorder, effectRequest(strings.NewReader(`{}`)))
	if recorder.Code != http.StatusBadGateway || time.Since(start) > time.Second {
		t.Fatalf("status=%d elapsed=%s body=%q", recorder.Code, time.Since(start), recorder.Body.String())
	}
	if deadline := <-deadlineSeen; deadline.Before(start) || deadline.After(start.Add(time.Second)) {
		t.Fatalf("deadline = %s", deadline)
	}
}

func TestProxyHealthAndMalformedControlOutcome(t *testing.T) {
	executor := &recordingExecutor{}
	proxy := newTestProxy(t, executor)
	health := httptest.NewRecorder()
	proxy.Handler().ServeHTTP(health, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if health.Code != http.StatusOK || health.Body.String() != "{\"status\":\"ok\"}\n" || len(executor.calls()) != 0 {
		t.Fatalf("health status=%d body=%q calls=%d", health.Code, health.Body.String(), len(executor.calls()))
	}

	mutations := []gateway.Outcome{
		{OperationID: "op-1", Phase: kernel.Succeeded, StatusCode: 0},
		{OperationID: "op-1\r\nInjected: yes", Phase: kernel.Succeeded, StatusCode: http.StatusOK},
		{OperationID: "op-1\x07bell", Phase: kernel.Succeeded, StatusCode: http.StatusOK},
	}
	for _, outcome := range mutations {
		executor := &recordingExecutor{outcome: outcome}
		recorder := httptest.NewRecorder()
		newTestProxy(t, executor).Handler().ServeHTTP(recorder, effectRequest(strings.NewReader(`{}`)))
		if recorder.Code != http.StatusBadGateway {
			t.Fatalf("outcome=%+v status=%d body=%q", outcome, recorder.Code, recorder.Body.String())
		}
		_ = decodeError(t, recorder)
	}
}
