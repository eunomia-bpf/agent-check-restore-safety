package deathstar

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
)

const validBody = `{"hotel_id":"1","in_date":"2015-04-09","out_date":"2015-04-10","rooms":1,"username":"Cornell_1","password":"1111111111"}`

type roundTripFunc func(*http.Request) (*http.Response, error)

func (function roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}

func upstreamResponse(status int, body string) *http.Response {
	return &http.Response{
		StatusCode: status,
		Header:     make(http.Header),
		Body:       io.NopCloser(strings.NewReader(body)),
	}
}

func openTestEffect(t *testing.T, drop bool, transport http.RoundTripper) (*EffectService, string) {
	t.Helper()
	auditPath := filepath.Join(t.TempDir(), "adapter.audit.jsonl")
	service, err := OpenEffect(EffectConfig{
		FrontendURL: "http://frontend:5000", AuditPath: auditPath,
		DropFirstResponse: drop, Transport: transport,
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := service.Close(); err != nil {
			t.Error(err)
		}
	})
	return service, auditPath
}

func effectRequest(body string) *http.Request {
	request := httptest.NewRequest(http.MethodPost, "/v1/reserve", strings.NewReader(body))
	request.Header.Set("X-Operation-ID", "reserve-17")
	return request
}

func TestEffectRequiresIdentityAndStrictBody(t *testing.T) {
	var calls atomic.Int32
	service, _ := openTestEffect(t, false, roundTripFunc(func(*http.Request) (*http.Response, error) {
		calls.Add(1)
		return upstreamResponse(http.StatusOK, `{"message":"Reserve successfully!"}`), nil
	}))
	tests := []struct {
		name string
		body string
		id   string
	}{
		{name: "identity missing", body: validBody},
		{name: "unknown field", body: strings.TrimSuffix(validBody, "}") + `,"customer_name":"forged"}`, id: "reserve-17"},
		{name: "duplicate field", body: strings.TrimSuffix(validBody, "}") + `,"hotel_id":"2"}`, id: "reserve-17"},
		{name: "missing field", body: `{"hotel_id":"1"}`, id: "reserve-17"},
		{name: "multiple values", body: validBody + `{}`, id: "reserve-17"},
		{name: "invalid date interval", body: `{"hotel_id":"1","in_date":"2015-04-10","out_date":"2015-04-09","rooms":1,"username":"u","password":"p"}`, id: "reserve-17"},
		{name: "multi-night interval", body: `{"hotel_id":"1","in_date":"2015-04-09","out_date":"2015-04-11","rooms":1,"username":"u","password":"p"}`, id: "reserve-17"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			request := httptest.NewRequest(http.MethodPost, "/v1/reserve", strings.NewReader(test.body))
			if test.id != "" {
				request.Header.Set("X-Operation-ID", test.id)
			}
			response := httptest.NewRecorder()
			service.Handler().ServeHTTP(response, request)
			if response.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want 400: %s", response.Code, response.Body.String())
			}
		})
	}
	if calls.Load() != 0 {
		t.Fatalf("invalid requests reached DeathStarBench %d times", calls.Load())
	}
}

func TestEffectBindsOperationIdentityAndTranslatesOnlyExplicitSuccess(t *testing.T) {
	service, auditPath := openTestEffect(t, false, roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.Method != http.MethodGet || request.URL.Path != "/reservation" {
			t.Errorf("upstream request = %s %s", request.Method, request.URL.Path)
		}
		query := request.URL.Query()
		if query.Get("customerName") != "safe-reserve-17" || query.Get("hotelId") != "1" ||
			query.Get("inDate") != "2015-04-09" || query.Get("outDate") != "2015-04-10" ||
			query.Get("number") != "1" || query.Get("username") != "Cornell_1" || query.Get("password") != "1111111111" {
			t.Errorf("unexpected upstream query: %v", query)
		}
		return upstreamResponse(http.StatusOK, `{"message":"Reserve successfully!"}`), nil
	}))
	response := httptest.NewRecorder()
	service.Handler().ServeHTTP(response, effectRequest(validBody))
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d: %s", response.Code, response.Body.String())
	}
	var receipt struct {
		Schema          int    `json:"schema"`
		OperationID     string `json:"operation_id"`
		Outcome         string `json:"outcome"`
		ResultHash      string `json:"result_hash"`
		RemoteReference string `json:"remote_reference"`
	}
	if err := decodeStrict(response.Body.Bytes(), &receipt); err != nil {
		t.Fatal(err)
	}
	if receipt.Schema != 1 || receipt.OperationID != "reserve-17" || receipt.Outcome != "succeeded" ||
		!validDigest(receipt.ResultHash) || receipt.RemoteReference != "deathstar/reservation/reserve-17" {
		t.Fatalf("bad receipt: %+v", receipt)
	}
	data, err := os.ReadFile(auditPath)
	if err != nil {
		t.Fatal(err)
	}
	var record auditRecord
	if err := decodeStrict(bytes.TrimSpace(data), &record); err != nil {
		t.Fatal(err)
	}
	if record.Delivery != 1 || record.UpstreamStatus != http.StatusOK || !record.UpstreamOK || record.Drop || !validDigest(record.UpstreamHash) {
		t.Fatalf("bad audit record: %+v", record)
	}
}

func TestEffectRejectsFakeSuccess(t *testing.T) {
	tests := []struct {
		name   string
		status int
		body   string
	}{
		{name: "failure message", status: http.StatusOK, body: `{"message":"Failed. Already reserved. "}`},
		{name: "unknown JSON field", status: http.StatusOK, body: `{"message":"Reserve successfully!","forged":true}`},
		{name: "duplicate message", status: http.StatusOK, body: `{"message":"Failed","message":"Reserve successfully!"}`},
		{name: "non-200", status: http.StatusInternalServerError, body: `{"message":"Reserve successfully!"}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			service, _ := openTestEffect(t, false, roundTripFunc(func(*http.Request) (*http.Response, error) {
				return upstreamResponse(test.status, test.body), nil
			}))
			response := httptest.NewRecorder()
			service.Handler().ServeHTTP(response, effectRequest(validBody))
			if response.Code != http.StatusBadGateway {
				t.Fatalf("status = %d, want 502: %s", response.Code, response.Body.String())
			}
		})
	}
}

func TestEffectNeverUsesAuditAsRecoveryState(t *testing.T) {
	auditPath := filepath.Join(t.TempDir(), "adapter.audit.jsonl")
	prior := `{"delivery":41,"operation_id":"reserve-17","upstream_status":200,"upstream_hash":"` +
		strings.Repeat("0", 64) + `","upstream_ok":true,"drop":false}` + "\n"
	if err := os.WriteFile(auditPath, []byte(prior), 0o600); err != nil {
		t.Fatal(err)
	}
	var calls atomic.Int32
	service, err := OpenEffect(EffectConfig{
		FrontendURL: "http://frontend:5000", AuditPath: auditPath,
		Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
			calls.Add(1)
			return upstreamResponse(http.StatusOK, `{"message":"Reserve successfully!"}`), nil
		}),
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := service.Close(); err != nil {
			t.Error(err)
		}
	})
	response := httptest.NewRecorder()
	service.Handler().ServeHTTP(response, effectRequest(validBody))
	if response.Code != http.StatusOK || calls.Load() != 1 {
		t.Fatalf("prior audit suppressed delivery: status=%d calls=%d body=%s", response.Code, calls.Load(), response.Body.String())
	}
	data, err := os.ReadFile(auditPath)
	if err != nil {
		t.Fatal(err)
	}
	if lines := bytes.Count(data, []byte{'\n'}); lines != 2 {
		t.Fatalf("audit was not append-only: got %d records", lines)
	}
}

type hijackWriter struct {
	header   http.Header
	server   net.Conn
	peer     net.Conn
	onHijack func() error
}

func newHijackWriter(onHijack func() error) *hijackWriter {
	server, peer := net.Pipe()
	return &hijackWriter{header: make(http.Header), server: server, peer: peer, onHijack: onHijack}
}

func (writer *hijackWriter) Header() http.Header            { return writer.header }
func (writer *hijackWriter) WriteHeader(int)                {}
func (writer *hijackWriter) Write(body []byte) (int, error) { return len(body), nil }
func (writer *hijackWriter) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	if writer.onHijack != nil {
		if err := writer.onHijack(); err != nil {
			return nil, nil, err
		}
	}
	return writer.server, nil, nil
}

func TestDropHappensOnlyAfterUpstreamCommitAndDurableAudit(t *testing.T) {
	var committed atomic.Bool
	service, auditPath := openTestEffect(t, true, roundTripFunc(func(*http.Request) (*http.Response, error) {
		committed.Store(true)
		return upstreamResponse(http.StatusOK, `{"message":"Reserve successfully!"}`), nil
	}))
	writer := newHijackWriter(func() error {
		if !committed.Load() {
			return errors.New("response dropped before upstream commit")
		}
		data, err := os.ReadFile(auditPath)
		if err != nil {
			return err
		}
		var record auditRecord
		if err := decodeStrict(bytes.TrimSpace(data), &record); err != nil {
			return err
		}
		if !record.UpstreamOK || !record.Drop {
			return errors.New("drop was not durably audited before hijack")
		}
		return nil
	})
	service.Handler().ServeHTTP(writer, effectRequest(validBody))
	defer writer.peer.Close()
	one := make([]byte, 1)
	if count, err := writer.peer.Read(one); count != 0 || !errors.Is(err, io.EOF) {
		t.Fatalf("dropped connection read = %d, %v; want EOF", count, err)
	}
	stats := service.audit.snapshot()
	if stats.Deliveries != 1 || stats.UpstreamOK != 1 || stats.Drops != 1 {
		t.Fatalf("bad effect stats: %+v", stats)
	}
}

func TestTerminalFencePreventsEveryUpstreamDelivery(t *testing.T) {
	directory := filepath.Join(t.TempDir(), "fences")
	if err := os.Mkdir(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	var calls atomic.Int32
	service, err := OpenEffect(EffectConfig{
		FrontendURL: "http://frontend:5000", AuditPath: filepath.Join(t.TempDir(), "adapter.audit.jsonl"),
		AbortBeforeUpstream: true, TerminalFenceDirectory: directory,
		Transport: roundTripFunc(func(*http.Request) (*http.Response, error) {
			calls.Add(1)
			return upstreamResponse(http.StatusOK, `{"message":"Reserve successfully!"}`), nil
		}),
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = service.Close() })
	requestHash := digestOf("exact gateway request")
	for range 2 {
		writer := newHijackWriter(nil)
		request := effectRequest(validBody)
		request.Header.Set("X-Operation-Request-Hash", requestHash)
		service.Handler().ServeHTTP(writer, request)
		one := make([]byte, 1)
		if count, err := writer.peer.Read(one); count != 0 || !errors.Is(err, io.EOF) {
			t.Fatalf("terminal abort read = %d, %v; want EOF", count, err)
		}
		_ = writer.peer.Close()
	}
	if calls.Load() != 0 {
		t.Fatalf("terminally fenced request reached upstream %d times", calls.Load())
	}
	store, err := openTerminalFenceStore(directory)
	if err != nil {
		t.Fatal(err)
	}
	record, found, err := store.lookup("reserve-17", requestHash)
	if err != nil || !found || record.FactHash != terminalFenceFactHash("reserve-17", requestHash) {
		t.Fatalf("terminal fence = %+v, %v, %v", record, found, err)
	}
	if _, _, err := store.lookup("reserve-17", digestOf("different request")); err == nil {
		t.Fatal("terminal fence accepted a different request hash")
	}
}

type fakeStore struct {
	result QueryResult
	err    error
	last   ReservationQuery
	calls  int
}

func (store *fakeStore) FindExact(_ context.Context, query ReservationQuery) (QueryResult, error) {
	store.calls++
	store.last = query
	return store.result, store.err
}

func observerRequest(body, identity, digest string) *http.Request {
	request := httptest.NewRequest(http.MethodPost, "/v1/query", strings.NewReader(body))
	if identity != "" {
		request.Header.Set("X-Operation-ID", identity)
	}
	if digest != "" {
		request.Header.Set("X-Operation-Request-Hash", digest)
	}
	return request
}

func digestOf(value string) string {
	digest := sha256Bytes([]byte(value))
	return digest
}

func sha256Bytes(value []byte) string {
	digest := sha256.Sum256(value)
	return hex.EncodeToString(digest[:])
}

func TestObserverRequiresIdentityHashAndStrictBody(t *testing.T) {
	store := &fakeStore{}
	service, err := NewObserver(store)
	if err != nil {
		t.Fatal(err)
	}
	tests := []struct {
		name, body, identity, digest string
	}{
		{name: "identity missing", body: validBody, digest: digestOf("request")},
		{name: "hash missing", body: validBody, identity: "reserve-17"},
		{name: "hash malformed", body: validBody, identity: "reserve-17", digest: strings.Repeat("A", 64)},
		{name: "body unknown field", body: strings.TrimSuffix(validBody, "}") + `,"extra":1}`, identity: "reserve-17", digest: digestOf("request")},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			response := httptest.NewRecorder()
			service.Handler().ServeHTTP(response, observerRequest(test.body, test.identity, test.digest))
			if response.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want 400: %s", response.Code, response.Body.String())
			}
		})
	}
	if store.calls != 0 {
		t.Fatalf("invalid observations queried Mongo %d times", store.calls)
	}
}

func TestObserverZeroAndMultipleRowsAreInconclusive(t *testing.T) {
	for _, count := range []int64{0, 2} {
		t.Run(strconv.FormatInt(count, 10), func(t *testing.T) {
			fact := ReservationFact{
				CustomerName: "safe-reserve-17", HotelID: "1", InDate: "2015-04-09",
				OutDate: "2015-04-10", Rooms: 1,
			}
			facts := make([]ReservationFact, count)
			for index := range facts {
				facts[index] = fact
			}
			store := &fakeStore{result: QueryResult{Count: count, Facts: facts}}
			service, err := NewObserver(store)
			if err != nil {
				t.Fatal(err)
			}
			response := httptest.NewRecorder()
			digest := digestOf("request")
			service.Handler().ServeHTTP(response, observerRequest(validBody, "reserve-17", digest))
			if response.Code != http.StatusOK {
				t.Fatalf("status = %d: %s", response.Code, response.Body.String())
			}
			var observation Observation
			if err := decodeStrict(response.Body.Bytes(), &observation); err != nil {
				t.Fatal(err)
			}
			if observation.Outcome != "inconclusive" || observation.FactHash != "" ||
				observation.RequestHash != digest || !strings.Contains(observation.RemoteReference, "count="+strconv.FormatInt(count, 10)) {
				t.Fatalf("bad inconclusive observation: %+v", observation)
			}
			if !strings.Contains(response.Body.String(), `"fact_hash":""`) {
				t.Fatalf("inconclusive observation omitted the required empty fact_hash: %s", response.Body.String())
			}
			if store.last != (ReservationQuery{
				CustomerName: "safe-reserve-17", HotelID: "1", InDate: "2015-04-09",
				OutDate: "2015-04-10", Rooms: 1,
			}) {
				t.Fatalf("query did not exactly bind request: %+v", store.last)
			}
			factsResponse := httptest.NewRecorder()
			service.Handler().ServeHTTP(factsResponse, httptest.NewRequest(http.MethodGet, "/v1/stats/facts", nil))
			if factsResponse.Code != http.StatusOK ||
				!strings.Contains(factsResponse.Body.String(), `"facts_hash":"`+canonicalFactHash(facts)+`"`) ||
				!strings.Contains(factsResponse.Body.String(), `"observed_time_ns":`) ||
				(count == 0 && !strings.Contains(factsResponse.Body.String(), `"facts":[]`)) ||
				(count == 2 && strings.Count(factsResponse.Body.String(), `"customer_name":"safe-reserve-17"`) != 2) {
				t.Fatalf("inconclusive evidence omitted its retained Mongo facts: %s", factsResponse.Body.String())
			}
		})
	}
}

func TestObserverSettlesZeroRowsOnlyWithExactTerminalFence(t *testing.T) {
	directory := filepath.Join(t.TempDir(), "fences")
	if err := os.Mkdir(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	fences, err := openTerminalFenceStore(directory)
	if err != nil {
		t.Fatal(err)
	}
	requestHash := digestOf("request")
	fence, err := fences.record("reserve-17", requestHash)
	if err != nil {
		t.Fatal(err)
	}
	service, err := NewObserverWithTerminalFences(&fakeStore{result: QueryResult{Count: 0, Facts: []ReservationFact{}}}, directory)
	if err != nil {
		t.Fatal(err)
	}
	response := httptest.NewRecorder()
	service.Handler().ServeHTTP(response, observerRequest(validBody, "reserve-17", requestHash))
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d: %s", response.Code, response.Body.String())
	}
	var observation Observation
	if err := decodeStrict(response.Body.Bytes(), &observation); err != nil {
		t.Fatal(err)
	}
	if observation.Outcome != "failed" || observation.FactHash != fence.FactHash ||
		!strings.Contains(observation.RemoteReference, "terminal-pre-upstream-abort=") {
		t.Fatalf("terminal observation = %+v", observation)
	}

	contradiction, err := NewObserverWithTerminalFences(&fakeStore{result: QueryResult{Count: 1, Facts: []ReservationFact{{
		CustomerName: "safe-reserve-17", HotelID: "1", InDate: "2015-04-09", OutDate: "2015-04-10", Rooms: 1,
	}}}}, directory)
	if err != nil {
		t.Fatal(err)
	}
	response = httptest.NewRecorder()
	contradiction.Handler().ServeHTTP(response, observerRequest(validBody, "reserve-17", requestHash))
	if response.Code != http.StatusInternalServerError {
		t.Fatalf("fence/application contradiction status = %d, want 500", response.Code)
	}
}

func TestObserverUniqueRowProducesStableFactHash(t *testing.T) {
	fact := ReservationFact{
		CustomerName: "safe-reserve-17", HotelID: "1", InDate: "2015-04-09",
		OutDate: "2015-04-10", Rooms: 1,
	}
	store := &fakeStore{result: QueryResult{Count: 1, Facts: []ReservationFact{fact}}}
	service, err := NewObserver(store)
	if err != nil {
		t.Fatal(err)
	}
	digest := digestOf("request")
	var hashes []string
	for range 2 {
		response := httptest.NewRecorder()
		service.Handler().ServeHTTP(response, observerRequest(validBody, "reserve-17", digest))
		if response.Code != http.StatusOK {
			t.Fatalf("status = %d: %s", response.Code, response.Body.String())
		}
		var observation Observation
		if err := decodeStrict(response.Body.Bytes(), &observation); err != nil {
			t.Fatal(err)
		}
		if observation.Outcome != "succeeded" || !validDigest(observation.FactHash) || observation.OperationID != "reserve-17" {
			t.Fatalf("bad settled observation: %+v", observation)
		}
		hashes = append(hashes, observation.FactHash)
	}
	if hashes[0] != hashes[1] || hashes[0] != canonicalFactHash([]ReservationFact{fact}) {
		t.Fatalf("fact hash is unstable: %v", hashes)
	}
	left := ReservationFact{CustomerName: "b", HotelID: "2", InDate: "2015-01-01", OutDate: "2015-01-02", Rooms: 1}
	right := ReservationFact{CustomerName: "a", HotelID: "1", InDate: "2015-01-01", OutDate: "2015-01-02", Rooms: 2}
	if canonicalFactHash([]ReservationFact{left, right}) != canonicalFactHash([]ReservationFact{right, left}) {
		t.Fatal("canonical fact hash depends on Mongo document order")
	}
	factsResponse := httptest.NewRecorder()
	service.Handler().ServeHTTP(factsResponse, httptest.NewRequest(http.MethodGet, "/v1/stats/facts", nil))
	if factsResponse.Code != http.StatusOK || !strings.Contains(factsResponse.Body.String(), `"queries":2`) ||
		!strings.Contains(factsResponse.Body.String(), `"customer_name":"safe-reserve-17"`) {
		t.Fatalf("facts endpoint omitted evidence: %s", factsResponse.Body.String())
	}
}

func TestObserverDoesNotSettleOnStoreFailureOrInconsistentResult(t *testing.T) {
	tests := []struct {
		name   string
		store  *fakeStore
		status int
	}{
		{name: "store failure", store: &fakeStore{err: errors.New("mongo unavailable")}, status: http.StatusBadGateway},
		{name: "count without unique fact", store: &fakeStore{result: QueryResult{Count: 1}}, status: http.StatusInternalServerError},
		{name: "facts on multiple", store: &fakeStore{result: QueryResult{Count: 2, Facts: []ReservationFact{{HotelID: "1"}}}}, status: http.StatusInternalServerError},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			service, err := NewObserver(test.store)
			if err != nil {
				t.Fatal(err)
			}
			response := httptest.NewRecorder()
			service.Handler().ServeHTTP(response, observerRequest(validBody, "reserve-17", digestOf("request")))
			if response.Code != test.status {
				t.Fatalf("status = %d, want %d: %s", response.Code, test.status, response.Body.String())
			}
		})
	}
}

func TestHealthAndStatsRoutesAreReadOnly(t *testing.T) {
	service, _ := openTestEffect(t, false, roundTripFunc(func(*http.Request) (*http.Response, error) {
		t.Fatal("read-only route called upstream")
		return nil, nil
	}))
	for _, path := range []string{"/healthz", "/v1/stats/facts"} {
		response := httptest.NewRecorder()
		service.Handler().ServeHTTP(response, httptest.NewRequest(http.MethodGet, path, nil))
		if response.Code != http.StatusOK {
			t.Fatalf("GET %s = %d", path, response.Code)
		}
	}
}
