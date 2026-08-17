package provideradapter

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

const (
	testOperationID = "op-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	testRequestHash = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
)

type stubDriver struct {
	effectResult Result
	effectErr    error
	queryResult  Result
	queryErr     error
	effect       Effect
	query        Query
	executeCalls atomic.Int32
	observeCalls atomic.Int32
}

func (driver *stubDriver) Execute(_ context.Context, effect Effect) (Result, error) {
	driver.executeCalls.Add(1)
	driver.effect = effect
	return driver.effectResult, driver.effectErr
}

func (driver *stubDriver) Observe(_ context.Context, query Query) (Result, error) {
	driver.observeCalls.Add(1)
	driver.query = query
	return driver.queryResult, driver.queryErr
}

func newTestHandler(t *testing.T, driver Driver, limit int64) *Handler {
	t.Helper()
	handler, err := NewHandler(Config{
		EffectPath: "/v1/payment", QueryPath: "/v1/payment/query",
		MaxRequestBytes: limit,
	}, driver)
	if err != nil {
		t.Fatal(err)
	}
	return handler
}

func effectRequest(body string) *http.Request {
	request := httptest.NewRequest(http.MethodPost, "http://adapter.test/v1/payment", strings.NewReader(body))
	request.Header.Set(HeaderOperationID, testOperationID)
	request.Header.Set(HeaderIdempotencyKey, testOperationID)
	request.Header.Set(HeaderOperationRequestHash, testRequestHash)
	request.Header.Set("Content-Type", "application/json; charset=utf-8")
	return request
}

func queryRequest(body string) *http.Request {
	request := httptest.NewRequest(http.MethodPost, "http://adapter.test/v1/payment/query", strings.NewReader(body))
	request.Header.Set(HeaderOperationID, testOperationID)
	request.Header.Set(HeaderOperationRequestHash, testRequestHash)
	request.Header.Set("Content-Type", "application/json; charset=utf-8")
	return request
}

func TestHandlerWritesStrictReceiptAndObservation(t *testing.T) {
	factHash := HashFact([]byte("provider fact"))
	driver := &stubDriver{
		effectResult: Result{
			Outcome: Succeeded, FactHash: factHash, RemoteReference: "provider/charge-7",
		},
		queryResult: Result{
			Outcome: Failed, FactHash: factHash, RemoteReference: "provider/decline-7",
		},
	}
	handler := newTestHandler(t, driver, 0)
	body := `{"invoice":"A-17","amount":4200}`

	effectRecorder := httptest.NewRecorder()
	handler.ServeHTTP(effectRecorder, effectRequest(body))
	if effectRecorder.Code != http.StatusOK {
		t.Fatalf("effect status = %d, body = %s", effectRecorder.Code, effectRecorder.Body.String())
	}
	wantReceipt := `{"schema":1,"operation_id":"` + testOperationID +
		`","outcome":"succeeded","result_hash":"` + factHash +
		`","remote_reference":"provider/charge-7"}`
	if got := effectRecorder.Body.String(); got != wantReceipt {
		t.Fatalf("receipt = %s, want %s", got, wantReceipt)
	}
	if got := effectRecorder.Header().Get("Content-Type"); got != "application/json" {
		t.Fatalf("receipt Content-Type = %q", got)
	}
	if effectRecorder.Header().Get("Cache-Control") != "no-store" ||
		effectRecorder.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Fatal("security response headers are missing")
	}
	if driver.effect.OperationID != testOperationID || driver.effect.IdempotencyKey != testOperationID ||
		driver.effect.RequestHash != testRequestHash ||
		driver.effect.ContentType != "application/json; charset=utf-8" || string(driver.effect.Body) != body {
		t.Fatalf("Driver received effect %+v", driver.effect)
	}

	queryRecorder := httptest.NewRecorder()
	handler.ServeHTTP(queryRecorder, queryRequest(body))
	if queryRecorder.Code != http.StatusOK {
		t.Fatalf("query status = %d, body = %s", queryRecorder.Code, queryRecorder.Body.String())
	}
	wantObservation := `{"schema":1,"operation_id":"` + testOperationID +
		`","request_hash":"` + testRequestHash +
		`","outcome":"failed","fact_hash":"` + factHash +
		`","remote_reference":"provider/decline-7"}`
	if got := queryRecorder.Body.String(); got != wantObservation {
		t.Fatalf("observation = %s, want %s", got, wantObservation)
	}
	if driver.query.OperationID != testOperationID || driver.query.RequestHash != testRequestHash ||
		driver.query.ContentType != "application/json; charset=utf-8" || string(driver.query.Body) != body {
		t.Fatalf("Driver received query %+v", driver.query)
	}
}

func TestObservationMayBeInconclusiveButEffectCannot(t *testing.T) {
	driver := &stubDriver{
		effectResult: Result{Outcome: Inconclusive, RemoteReference: "provider/search"},
		queryResult:  Result{Outcome: Inconclusive, RemoteReference: "provider/search"},
	}
	handler := newTestHandler(t, driver, 0)

	effectRecorder := httptest.NewRecorder()
	handler.ServeHTTP(effectRecorder, effectRequest(`{}`))
	if effectRecorder.Code != http.StatusInternalServerError || strings.Contains(effectRecorder.Body.String(), "inconclusive") {
		t.Fatalf("inconclusive effect response = %d %s", effectRecorder.Code, effectRecorder.Body.String())
	}

	queryRecorder := httptest.NewRecorder()
	handler.ServeHTTP(queryRecorder, queryRequest(`{}`))
	if queryRecorder.Code != http.StatusOK {
		t.Fatalf("inconclusive observation response = %d %s", queryRecorder.Code, queryRecorder.Body.String())
	}
	var observation observationV1
	if err := json.Unmarshal(queryRecorder.Body.Bytes(), &observation); err != nil {
		t.Fatal(err)
	}
	if observation.Outcome != Inconclusive || observation.FactHash != "" || observation.RequestHash != testRequestHash {
		t.Fatalf("inconclusive observation = %+v", observation)
	}
}

func TestDriverErrorsAreSanitized(t *testing.T) {
	const secret = "provider-secret-must-not-cross-adapter-boundary"
	driver := &stubDriver{
		effectErr: errors.New("provider rejected credential " + secret),
		queryErr:  errors.New("provider query used credential " + secret),
	}
	handler := newTestHandler(t, driver, 0)
	for _, request := range []*http.Request{effectRequest(`{}`), queryRequest(`{}`)} {
		request.Header.Set("Authorization", "Bearer "+secret)
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, request)
		if recorder.Code != http.StatusBadGateway {
			t.Fatalf("sanitized error status = %d, body = %s", recorder.Code, recorder.Body.String())
		}
		if strings.Contains(recorder.Body.String(), secret) || strings.Contains(recorder.Body.String(), "credential") {
			t.Fatalf("driver error leaked through protocol: %s", recorder.Body.String())
		}
	}
}

func TestHandlerRejectsInvalidHeadersBeforeDriver(t *testing.T) {
	tests := []struct {
		name    string
		request func() *http.Request
	}{
		{name: "missing-operation", request: func() *http.Request {
			request := effectRequest(`{}`)
			request.Header.Del(HeaderOperationID)
			return request
		}},
		{name: "noncanonical-operation", request: func() *http.Request {
			request := effectRequest(`{}`)
			request.Header.Set(HeaderOperationID, "op-"+strings.Repeat("A", 64))
			request.Header.Set(HeaderIdempotencyKey, "op-"+strings.Repeat("A", 64))
			return request
		}},
		{name: "case-duplicate-operation", request: func() *http.Request {
			request := effectRequest(`{}`)
			request.Header["x-operation-id"] = []string{testOperationID}
			return request
		}},
		{name: "duplicate-idempotency", request: func() *http.Request {
			request := effectRequest(`{}`)
			request.Header[HeaderIdempotencyKey] = []string{testOperationID, testOperationID}
			return request
		}},
		{name: "mismatched-idempotency", request: func() *http.Request {
			request := effectRequest(`{}`)
			request.Header.Set(HeaderIdempotencyKey, "op-"+strings.Repeat("c", 64))
			return request
		}},
		{name: "effect-missing-request-hash", request: func() *http.Request {
			request := effectRequest(`{}`)
			request.Header.Del(HeaderOperationRequestHash)
			return request
		}},
		{name: "effect-noncanonical-request-hash", request: func() *http.Request {
			request := effectRequest(`{}`)
			request.Header.Set(HeaderOperationRequestHash, strings.Repeat("B", 64))
			return request
		}},
		{name: "duplicate-content-type", request: func() *http.Request {
			request := effectRequest(`{}`)
			request.Header["content-type"] = []string{"application/json"}
			return request
		}},
		{name: "malformed-content-type", request: func() *http.Request {
			request := effectRequest(`{}`)
			request.Header.Set("Content-Type", "not a media type")
			return request
		}},
		{name: "query-missing-request-hash", request: func() *http.Request {
			request := queryRequest(`{}`)
			request.Header.Del(HeaderOperationRequestHash)
			return request
		}},
		{name: "query-noncanonical-request-hash", request: func() *http.Request {
			request := queryRequest(`{}`)
			request.Header.Set(HeaderOperationRequestHash, strings.Repeat("B", 64))
			return request
		}},
		{name: "query-idempotency-key", request: func() *http.Request {
			request := queryRequest(`{}`)
			request.Header.Set(HeaderIdempotencyKey, testOperationID)
			return request
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			driver := &stubDriver{effectResult: validSuccess(), queryResult: validSuccess()}
			handler := newTestHandler(t, driver, 0)
			recorder := httptest.NewRecorder()
			handler.ServeHTTP(recorder, test.request())
			if recorder.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
			}
			if driver.executeCalls.Load() != 0 || driver.observeCalls.Load() != 0 {
				t.Fatal("invalid request reached Driver")
			}
		})
	}
}

func TestHandlerEnforcesBodyBoundsBeforeDriver(t *testing.T) {
	for _, test := range []struct {
		name    string
		request func() *http.Request
	}{
		{name: "known-length", request: func() *http.Request { return effectRequest("12345") }},
		{name: "streamed", request: func() *http.Request {
			request := effectRequest("")
			request.Body = io.NopCloser(strings.NewReader("12345"))
			request.ContentLength = -1
			return request
		}},
	} {
		t.Run(test.name, func(t *testing.T) {
			driver := &stubDriver{effectResult: validSuccess()}
			handler := newTestHandler(t, driver, 4)
			recorder := httptest.NewRecorder()
			handler.ServeHTTP(recorder, test.request())
			if recorder.Code != http.StatusRequestEntityTooLarge {
				t.Fatalf("status = %d, body = %s", recorder.Code, recorder.Body.String())
			}
			if driver.executeCalls.Load() != 0 {
				t.Fatal("oversized body reached Driver")
			}
		})
	}
}

type failingReader struct {
	secret string
}

func (reader failingReader) Read([]byte) (int, error) { return 0, errors.New(reader.secret) }
func (failingReader) Close() error                    { return nil }

func TestBodyReadErrorIsSanitized(t *testing.T) {
	const secret = "body-reader-secret"
	driver := &stubDriver{effectResult: validSuccess()}
	handler := newTestHandler(t, driver, 0)
	request := effectRequest("")
	request.Body = failingReader{secret: secret}
	request.ContentLength = -1
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	if recorder.Code != http.StatusBadRequest || strings.Contains(recorder.Body.String(), secret) {
		t.Fatalf("body error response = %d %s", recorder.Code, recorder.Body.String())
	}
	if driver.executeCalls.Load() != 0 {
		t.Fatal("unreadable body reached Driver")
	}
}

func TestHandlerRoutesAndConfigurationAreFixed(t *testing.T) {
	driver := &stubDriver{effectResult: validSuccess(), queryResult: validSuccess()}
	handler := newTestHandler(t, driver, 0)
	for _, test := range []struct {
		method string
		target string
		want   int
	}{
		{method: http.MethodGet, target: "/healthz", want: http.StatusOK},
		{method: http.MethodPost, target: "/healthz", want: http.StatusMethodNotAllowed},
		{method: http.MethodGet, target: "/v1/payment", want: http.StatusMethodNotAllowed},
		{method: http.MethodPost, target: "/v1/payment?next=v2", want: http.StatusBadRequest},
		{method: http.MethodPost, target: "/v2/payment", want: http.StatusNotFound},
	} {
		request := httptest.NewRequest(test.method, "http://adapter.test"+test.target, nil)
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, request)
		if recorder.Code != test.want {
			t.Fatalf("%s %s status = %d, want %d", test.method, test.target, recorder.Code, test.want)
		}
	}

	for _, config := range []Config{
		{},
		{EffectPath: "relative", QueryPath: "/v1/query"},
		{EffectPath: "/v1/effect", QueryPath: "/v1/effect"},
		{EffectPath: "/healthz", QueryPath: "/v1/query"},
		{EffectPath: "/v1/../effect", QueryPath: "/v1/query"},
		{EffectPath: "/v1/effect", QueryPath: "/v1/query", MaxRequestBytes: -1},
		{EffectPath: "/v1/effect", QueryPath: "/v1/query", MaxRequestBytes: MaxRequestBytes + 1},
	} {
		if _, err := NewHandler(config, driver); err == nil {
			t.Fatalf("invalid config %+v was accepted", config)
		}
	}
	if _, err := NewHandler(Config{EffectPath: "/v1/effect", QueryPath: "/v1/query"}, nil); err == nil {
		t.Fatal("nil Driver was accepted")
	}
}

type providerBackedDriver struct {
	secret   string
	target   string
	client   *http.Client
	factHash string
}

func (driver providerBackedDriver) Execute(ctx context.Context, effect Effect) (Result, error) {
	request, err := NewSingleAttemptRequest(ctx, http.MethodPost, driver.target+"/apply", effect.Body)
	if err != nil {
		return Result{}, err
	}
	request.Header.Set("Authorization", "Bearer "+driver.secret)
	request.Header.Set(HeaderIdempotencyKey, effect.IdempotencyKey)
	request.Header.Set("Content-Type", effect.ContentType)
	response, err := driver.client.Do(request)
	if err != nil {
		return Result{}, err
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, response.Body)
	if response.StatusCode != http.StatusOK {
		return Result{}, errors.New("provider did not settle request")
	}
	return Result{
		Outcome: Succeeded, FactHash: driver.factHash,
		RemoteReference: "provider/object-17",
	}, nil
}

func (driver providerBackedDriver) Observe(ctx context.Context, query Query) (Result, error) {
	request, err := NewSingleAttemptRequest(ctx, http.MethodPost, driver.target+"/query", query.Body)
	if err != nil {
		return Result{}, err
	}
	request.Header.Set("Authorization", "Bearer "+driver.secret)
	request.Header.Set(HeaderOperationID, query.OperationID)
	response, err := driver.client.Do(request)
	if err != nil {
		return Result{}, err
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, response.Body)
	if response.StatusCode != http.StatusOK {
		return Result{}, errors.New("provider query did not settle request")
	}
	return Result{
		Outcome: Succeeded, FactHash: driver.factHash,
		RemoteReference: "provider/object-17",
	}, nil
}

func TestProviderSecretExistsOnlyBeyondAdapterProtocol(t *testing.T) {
	const providerSecret = "real-provider-secret-outside-history"
	const inboundSecret = "untrusted-inbound-header-secret"
	var providerCalls atomic.Int32
	provider := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		providerCalls.Add(1)
		if request.Header.Get("Authorization") != "Bearer "+providerSecret {
			t.Error("provider did not receive its private credential")
		}
		if request.Header.Get("Authorization") == "Bearer "+inboundSecret {
			t.Error("adapter forwarded an inbound credential")
		}
		writer.WriteHeader(http.StatusOK)
	}))
	defer provider.Close()
	client, err := NewHTTPClient(nil, 2*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	handler := newTestHandler(t, providerBackedDriver{
		secret: providerSecret, target: provider.URL, client: client,
		factHash: HashFact([]byte("stable-provider-fact")),
	}, 0)

	for _, request := range []*http.Request{effectRequest(`{"invoice":"A-17"}`), queryRequest(`{"invoice":"A-17"}`)} {
		request.Header.Set("Authorization", "Bearer "+inboundSecret)
		recorder := httptest.NewRecorder()
		handler.ServeHTTP(recorder, request)
		if recorder.Code != http.StatusOK {
			t.Fatalf("adapter response = %d %s", recorder.Code, recorder.Body.String())
		}
		for _, secret := range []string{providerSecret, inboundSecret} {
			if bytes.Contains(recorder.Body.Bytes(), []byte(secret)) {
				t.Fatalf("secret %q crossed the adapter protocol: %s", secret, recorder.Body.String())
			}
		}
	}
	if providerCalls.Load() != 2 {
		t.Fatalf("provider calls = %d, want 2", providerCalls.Load())
	}
}

func validSuccess() Result {
	return Result{
		Outcome: Succeeded, FactHash: HashFact([]byte("fact")),
		RemoteReference: "provider/object",
	}
}
