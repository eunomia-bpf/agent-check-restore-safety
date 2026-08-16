package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/certcheck"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/payment"
)

const (
	adminToken     = "admin-token-0000000000000000000000000000"
	operationToken = "operation-token-000000000000000000000000"
)

type blockingResponseWriter struct {
	header  http.Header
	entered chan struct{}
	release chan struct{}
	once    sync.Once
	status  int
	body    bytes.Buffer
}

func newBlockingResponseWriter() *blockingResponseWriter {
	return &blockingResponseWriter{
		header: make(http.Header), entered: make(chan struct{}), release: make(chan struct{}),
	}
}

func (writer *blockingResponseWriter) Header() http.Header {
	return writer.header
}

func (writer *blockingResponseWriter) WriteHeader(status int) {
	writer.once.Do(func() { close(writer.entered) })
	<-writer.release
	writer.status = status
}

func (writer *blockingResponseWriter) Write(body []byte) (int, error) {
	return writer.body.Write(body)
}

func (writer *blockingResponseWriter) Flush() {}

func testRequirement(id, target string) kernel.Requirement {
	return kernel.Requirement{
		ID:         id,
		Results:    map[string]uint32{"done": 1},
		Capacities: map[string]uint32{"slot": 1},
		Kinds: map[string]kernel.KindSpec{
			"finish": {
				Costs:              map[string]uint32{"slot": 1},
				Produces:           map[string]uint32{"done": 1},
				RetrySafe:          true,
				Target:             target,
				Method:             http.MethodPost,
				ResponseClassifier: gateway.ResponseReceiptV1,
			},
			"waste": {
				Costs:              map[string]uint32{"slot": 1},
				Produces:           map[string]uint32{"wasted": 1},
				Target:             target,
				Method:             http.MethodPost,
				ResponseClassifier: gateway.ResponseReceiptV1,
			},
		},
	}
}

func testQueryableRequirement(id, target, queryTarget string) kernel.Requirement {
	requirement := testRequirement(id, target)
	spec := requirement.Kinds["finish"]
	spec.RetrySafe = false
	spec.Queryable = true
	spec.QueryTarget = queryTarget
	spec.QueryMethod = http.MethodPost
	spec.QueryClassifier = gateway.OperationObservationV1
	requirement.Kinds["finish"] = spec
	return requirement
}

func testCredentials() Credentials {
	return Credentials{
		AdminToken: adminToken,
		Adapters: []AdapterCredential{{
			Token: operationToken, Domain: "test-adapter", Kinds: []string{"finish", "waste"},
		}},
	}
}

func postJSON(t *testing.T, client *http.Client, url, token string, value any, target any) int {
	t.Helper()
	body, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	request, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Content-Type", "application/json")
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if target != nil {
		if err := json.NewDecoder(response.Body).Decode(target); err != nil {
			t.Fatal(err)
		}
	}
	return response.StatusCode
}

func TestLocalAPICompilesActivatesAndExecutes(t *testing.T) {
	var deliveries atomic.Int32
	sink := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		deliveries.Add(1)
		writer.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(writer).Encode(map[string]any{
			"schema": 1, "operation_id": request.Header.Get("X-Operation-ID"),
			"outcome": "succeeded", "result_hash": strings.Repeat("0", 64),
			"remote_reference": "test-result",
		})
	}))
	defer sink.Close()

	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	api, err := New(c, nil, testCredentials())
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(api.Handler())
	defer server.Close()

	health, err := server.Client().Get(server.URL + "/healthz")
	if err != nil {
		t.Fatal(err)
	}
	health.Body.Close()
	if health.StatusCode != http.StatusOK {
		t.Fatalf("health status = %d", health.StatusCode)
	}

	request, _ := http.NewRequest(http.MethodGet, server.URL+"/v1/state", nil)
	response, err := server.Client().Do(request)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusUnauthorized {
		t.Fatalf("unauthenticated state status = %d", response.StatusCode)
	}

	var certificate kernel.Certificate
	if status := postJSON(t, server.Client(), server.URL+"/v1/compile", adminToken, testRequirement("v1", sink.URL), &certificate); status != http.StatusOK {
		t.Fatalf("compile status = %d", status)
	}
	if certificate.Decision != kernel.Activate || certificate.Rule == nil {
		t.Fatalf("certificate = %+v", certificate)
	}
	var projection json.RawMessage
	if status := postJSON(t, server.Client(), server.URL+"/v1/certificate-state", adminToken, certificate, &projection); status != http.StatusOK {
		t.Fatalf("Certificate State status = %d", status)
	}
	certificateJSON, err := json.Marshal(certificate)
	if err != nil {
		t.Fatal(err)
	}
	verdict, err := certcheck.CheckJSON(projection, certificateJSON)
	if err != nil || !verdict.Valid || verdict.RuleVersion != 1 {
		t.Fatalf("offline Certificate verdict=%+v error=%v", verdict, err)
	}
	if status := postJSON(t, server.Client(), server.URL+"/v1/activate", operationToken, certificate, &errorBody{}); status != http.StatusUnauthorized {
		t.Fatalf("operation token activated a Rule: status=%d", status)
	}
	var state kernel.State
	if status := postJSON(t, server.Client(), server.URL+"/v1/activate", adminToken, certificate, &state); status != http.StatusOK {
		t.Fatalf("activate status = %d", status)
	}

	waste := executeRequest{CallID: "waste-1", Kind: "waste", URL: sink.URL}
	if status := postJSON(t, server.Client(), server.URL+"/v1/execute", operationToken, waste, &map[string]any{}); status != http.StatusUnprocessableEntity {
		t.Fatalf("stranding execute status = %d", status)
	}
	finish := executeRequest{CallID: "finish-1", Kind: "finish", URL: sink.URL}
	var outcome gateway.Outcome
	if status := postJSON(t, server.Client(), server.URL+"/v1/execute", operationToken, finish, &outcome); status != http.StatusOK {
		t.Fatalf("finish execute status = %d", status)
	}
	if outcome.Phase != kernel.Succeeded || deliveries.Load() != 1 {
		t.Fatalf("outcome=%+v deliveries=%d", outcome, deliveries.Load())
	}
	conflicting := finish
	conflicting.Body = []byte(`{"different":true}`)
	var conflict OperationError
	if status := postJSON(t, server.Client(), server.URL+"/v1/execute", operationToken, conflicting, &conflict); status != http.StatusConflict {
		t.Fatalf("request-conflict status=%d response=%+v", status, conflict)
	}
	if conflict.Code != OperationErrorRequestConflict || conflict.Outcome.OperationID != outcome.OperationID ||
		conflict.Outcome.Phase != kernel.Succeeded || deliveries.Load() != 1 {
		t.Fatalf("request-conflict response=%+v deliveries=%d", conflict, deliveries.Load())
	}
}

func TestAPIRecoversLostPaymentResponseAndReusesSettlement(t *testing.T) {
	service, err := payment.Open(filepath.Join(t.TempDir(), "payment.history"), true)
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	paymentServer := httptest.NewServer(service.Handler())
	defer paymentServer.Close()

	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	serverAPI, err := New(c, nil, testCredentials())
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(serverAPI.Handler())
	defer server.Close()

	requirement := testRequirement("lost-response", paymentServer.URL+"/v1/charge")
	certificate, err := c.Compile(requirement)
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Activate(certificate); err != nil {
		t.Fatal(err)
	}
	request := executeRequest{
		CallID: "payment-1", Kind: "finish", Method: http.MethodPost,
		URL: paymentServer.URL + "/v1/charge", Body: []byte(`{"amount":42}`),
	}
	var unknown struct {
		Outcome gateway.Outcome `json:"outcome"`
		Error   string          `json:"error"`
	}
	if status := postJSON(t, server.Client(), server.URL+"/v1/execute", operationToken, request, &unknown); status != http.StatusConflict {
		t.Fatalf("first execute status=%d outcome=%+v error=%q", status, unknown.Outcome, unknown.Error)
	}
	if unknown.Outcome.Phase != kernel.Unknown {
		t.Fatalf("first outcome=%+v", unknown.Outcome)
	}
	var recovered gateway.Outcome
	if status := postJSON(t, server.Client(), server.URL+"/v1/execute", operationToken, request, &recovered); status != http.StatusOK {
		t.Fatalf("recovery status=%d outcome=%+v", status, recovered)
	}
	if recovered.Phase != kernel.Succeeded || recovered.Reused {
		t.Fatalf("recovered outcome=%+v", recovered)
	}
	var reused gateway.Outcome
	if status := postJSON(t, server.Client(), server.URL+"/v1/execute", operationToken, request, &reused); status != http.StatusOK {
		t.Fatalf("reuse status=%d outcome=%+v", status, reused)
	}
	stats := service.Stats()
	if reused.Phase != kernel.Succeeded || !reused.Reused || stats.Deliveries != 2 || stats.Commits != 1 {
		t.Fatalf("reused=%+v stats=%+v", reused, stats)
	}
}

func TestAdminRecoversOneUnknownOperationByID(t *testing.T) {
	var deliveries atomic.Int32
	effect := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		deliveries.Add(1)
		connection, _, err := writer.(http.Hijacker).Hijack()
		if err != nil {
			t.Error(err)
			return
		}
		_ = connection.Close()
	}))
	defer effect.Close()
	var queries atomic.Int32
	observer := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		queries.Add(1)
		writer.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(writer).Encode(map[string]any{
			"schema": 1, "operation_id": request.Header.Get("X-Operation-ID"),
			"request_hash": request.Header.Get("X-Operation-Request-Hash"),
			"outcome":      "succeeded", "fact_hash": strings.Repeat("a", 64),
			"remote_reference": "observer-result",
		})
	}))
	defer observer.Close()

	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	certificate, err := c.Compile(testQueryableRequirement("query-v1", effect.URL, observer.URL))
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Activate(certificate); err != nil {
		t.Fatal(err)
	}
	serverAPI, err := New(c, nil, testCredentials())
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(serverAPI.Handler())
	defer server.Close()

	var unknown struct {
		Outcome gateway.Outcome `json:"outcome"`
		Error   string          `json:"error"`
	}
	request := executeRequest{
		CallID: "order/A-17", Kind: "finish", Method: http.MethodPost, URL: effect.URL,
		Headers: map[string]string{"Content-Type": "application/json"},
		Body:    []byte(`{"order":"A-17"}`),
	}
	if status := postJSON(t, server.Client(), server.URL+"/v1/execute", operationToken, request, &unknown); status != http.StatusConflict {
		t.Fatalf("execute status=%d outcome=%+v error=%q", status, unknown.Outcome, unknown.Error)
	}
	if unknown.Outcome.Phase != kernel.Unknown || unknown.Outcome.OperationID == "" || deliveries.Load() != 1 {
		t.Fatalf("unknown outcome=%+v deliveries=%d", unknown.Outcome, deliveries.Load())
	}

	// Compile remains a read-only local calculation, even while a queryable
	// Operation is unknown.
	if _, err := c.Compile(testQueryableRequirement("query-v2", effect.URL, observer.URL)); err != nil {
		t.Fatal(err)
	}
	if queries.Load() != 0 {
		t.Fatal("Compile contacted the observer")
	}

	recoverURL := server.URL + "/v1/operations/" + unknown.Outcome.OperationID + "/recover"
	callRecover := func(token string, target any) int {
		t.Helper()
		httpRequest, err := http.NewRequest(http.MethodPost, recoverURL, nil)
		if err != nil {
			t.Fatal(err)
		}
		httpRequest.Header.Set("Authorization", "Bearer "+token)
		response, err := server.Client().Do(httpRequest)
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		if target != nil {
			if err := json.NewDecoder(response.Body).Decode(target); err != nil {
				t.Fatal(err)
			}
		}
		return response.StatusCode
	}
	var unauthorized errorBody
	if status := callRecover(operationToken, &unauthorized); status != http.StatusUnauthorized {
		t.Fatalf("adapter token recovery status=%d", status)
	}
	var recovered gateway.Outcome
	if status := callRecover(adminToken, &recovered); status != http.StatusOK {
		t.Fatalf("admin recovery status=%d outcome=%+v", status, recovered)
	}
	if recovered.Phase != kernel.Succeeded || !recovered.RecoveredByQuery || deliveries.Load() != 1 || queries.Load() != 1 {
		t.Fatalf("recovered=%+v deliveries=%d queries=%d", recovered, deliveries.Load(), queries.Load())
	}
}

func TestAPIRejectsStaleCertificate(t *testing.T) {
	sink := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writer.WriteHeader(http.StatusOK)
	}))
	defer sink.Close()
	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	api, _ := New(c, nil, testCredentials())
	server := httptest.NewServer(api.Handler())
	defer server.Close()

	first, err := c.Compile(testRequirement("v1", sink.URL))
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Activate(first); err != nil {
		t.Fatal(err)
	}
	stale, err := c.Compile(testRequirement("v2", sink.URL))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.Prepare("finish-1", "service", "finish", "request"); err != nil {
		t.Fatal(err)
	}
	var response errorBody
	if status := postJSON(t, server.Client(), server.URL+"/v1/activate", adminToken, stale, &response); status != http.StatusConflict {
		t.Fatalf("stale activate status = %d, response = %+v", status, response)
	}
}

func TestAdapterCredentialBindsDomainKindAndIdentity(t *testing.T) {
	if deriveOperationID("agent", "call-7") == deriveOperationID("vm", "call-7") {
		t.Fatal("two adapter domains produced the same Operation identity")
	}
	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	serverAPI, err := New(c, nil, testCredentials())
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(serverAPI.Handler())
	defer server.Close()

	if status := postJSON(t, server.Client(), server.URL+"/v1/execute", operationToken,
		executeRequest{CallID: "call-1", Kind: "admin-only", URL: "http://127.0.0.1"}, &errorBody{}); status != http.StatusForbidden {
		t.Fatalf("disallowed kind status = %d", status)
	}
	// Domain is not part of the adapter request schema; it comes only from the
	// authenticated credential.
	forged := map[string]any{
		"call_id": "call-1", "domain": "vm", "kind": "finish", "url": "http://127.0.0.1",
	}
	if status := postJSON(t, server.Client(), server.URL+"/v1/execute", operationToken, forged, &errorBody{}); status != http.StatusBadRequest {
		t.Fatalf("caller-supplied domain status = %d", status)
	}
}

func TestDuplicateAdapterTokenIsRejected(t *testing.T) {
	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	_, err = New(c, nil, Credentials{
		AdminToken: adminToken,
		Adapters: []AdapterCredential{
			{Token: operationToken, Domain: "agent", Kinds: []string{"finish"}},
			{Token: operationToken, Domain: "vm", Kinds: []string{"finish"}},
		},
	})
	if err == nil {
		t.Fatal("one token was bound to two adapter domains")
	}
}

func TestHostBoundSandboxNeedsNoCredentialAndCannotReachAdmin(t *testing.T) {
	var deliveries atomic.Int32
	sink := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		deliveries.Add(1)
		writer.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(writer).Encode(map[string]any{
			"schema": 1, "operation_id": request.Header.Get("X-Operation-ID"),
			"outcome": "succeeded", "result_hash": strings.Repeat("a", 64),
			"remote_reference": "sandbox-result",
		})
	}))
	defer sink.Close()

	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	serverAPI, err := New(c, nil, testCredentials())
	if err != nil {
		t.Fatal(err)
	}
	adminServer := httptest.NewServer(serverAPI.Handler())
	defer adminServer.Close()

	first := control.SandboxBinding{
		SandboxID: "codex-vm", Generation: 1, HostInstanceID: "host-vm-1",
		Domain: "test-adapter", AllowedKinds: []string{"finish"},
	}
	certificate, err := c.Compile(testRequirement("sandbox-v1", sink.URL))
	if err != nil {
		t.Fatal(err)
	}
	var cutover CutoverResponse
	if status := postJSON(t, adminServer.Client(), adminServer.URL+"/v1/cutover", adminToken,
		CutoverRequest{Certificate: certificate, Bindings: []control.SandboxBinding{first}}, &cutover); status != http.StatusOK {
		t.Fatalf("cutover status=%d response=%+v", status, cutover)
	}
	if cutover.State == nil || cutover.State.Rule == nil || len(cutover.Bindings) != 1 ||
		cutover.Bindings[0].HostInstanceID != first.HostInstanceID {
		t.Fatalf("cutover response=%+v", cutover)
	}

	sandboxHandler, err := serverAPI.HandlerForSandbox(first)
	if err != nil {
		t.Fatal(err)
	}
	sandboxServer := httptest.NewServer(sandboxHandler)
	defer sandboxServer.Close()
	request := sandboxExecuteRequest{CallID: "order/A-17/payment", Kind: "finish"}
	var outcome gateway.Outcome
	if status := postJSON(t, sandboxServer.Client(), sandboxServer.URL+"/v1/execute", "", request, &outcome); status != http.StatusOK {
		t.Fatalf("credential-free sandbox execute status=%d outcome=%+v", status, outcome)
	}
	if outcome.Phase != kernel.Succeeded || deliveries.Load() != 1 {
		t.Fatalf("sandbox outcome=%+v deliveries=%d", outcome, deliveries.Load())
	}
	var bypass OperationError
	if status := postJSON(t, adminServer.Client(), adminServer.URL+"/v1/execute", operationToken, request, &bypass); status != http.StatusConflict {
		t.Fatalf("bearer bypass status=%d response=%+v", status, bypass)
	}
	if bypass.Code != OperationErrorSandboxStale || deliveries.Load() != 1 {
		t.Fatalf("bearer bypass response=%+v deliveries=%d", bypass, deliveries.Load())
	}

	adminRequest, err := http.NewRequest(http.MethodGet, sandboxServer.URL+"/v1/state", nil)
	if err != nil {
		t.Fatal(err)
	}
	adminRequest.Header.Set("Authorization", "Bearer "+adminToken)
	adminResponse, err := sandboxServer.Client().Do(adminRequest)
	if err != nil {
		t.Fatal(err)
	}
	adminResponse.Body.Close()
	if adminResponse.StatusCode != http.StatusNotFound {
		t.Fatalf("sandbox endpoint exposed admin route: status=%d", adminResponse.StatusCode)
	}

	forged := map[string]any{
		"call_id": "order/A-18/payment", "kind": "finish", "url": sink.URL,
		"sandbox_id": "other", "generation": 999, "domain": "other",
	}
	if status := postJSON(t, sandboxServer.Client(), sandboxServer.URL+"/v1/execute", "", forged, &errorBody{}); status != http.StatusBadRequest {
		t.Fatalf("guest-supplied binding fields status=%d", status)
	}
	withTarget := map[string]any{
		"call_id": "order/A-18/payment", "kind": "finish", "url": sink.URL,
	}
	if status := postJSON(t, sandboxServer.Client(), sandboxServer.URL+"/v1/execute", "", withTarget, &errorBody{}); status != http.StatusBadRequest {
		t.Fatalf("guest-supplied provider target status=%d", status)
	}
	if status := postJSON(t, sandboxServer.Client(), sandboxServer.URL+"/v1/execute", operationToken, request, &errorBody{}); status != http.StatusBadRequest {
		t.Fatalf("sandbox endpoint accepted a guest bearer token: status=%d", status)
	}

	second := first
	second.Generation = 2
	second.HostInstanceID = "host-vm-2"
	secondCertificate, err := c.Compile(testRequirement("sandbox-v2", sink.URL))
	if err != nil {
		t.Fatal(err)
	}
	if status := postJSON(t, adminServer.Client(), adminServer.URL+"/v1/cutover", adminToken,
		CutoverRequest{Certificate: secondCertificate, Bindings: []control.SandboxBinding{second}}, &CutoverResponse{}); status != http.StatusOK {
		t.Fatalf("second cutover status=%d", status)
	}
	var stale OperationError
	if status := postJSON(t, sandboxServer.Client(), sandboxServer.URL+"/v1/execute", "", request, &stale); status != http.StatusConflict {
		t.Fatalf("stale sandbox status=%d response=%+v", status, stale)
	}
	if stale.Code != OperationErrorSandboxStale || deliveries.Load() != 1 {
		t.Fatalf("stale sandbox response=%+v deliveries=%d", stale, deliveries.Load())
	}

	currentHandler, err := serverAPI.HandlerForSandbox(second)
	if err != nil {
		t.Fatal(err)
	}
	currentServer := httptest.NewServer(currentHandler)
	defer currentServer.Close()
	var reused gateway.Outcome
	if status := postJSON(t, currentServer.Client(), currentServer.URL+"/v1/execute", "", request, &reused); status != http.StatusOK {
		t.Fatalf("current sandbox reuse status=%d outcome=%+v", status, reused)
	}
	if !reused.Reused || reused.Phase != kernel.Succeeded || deliveries.Load() != 1 {
		t.Fatalf("current sandbox outcome=%+v deliveries=%d", reused, deliveries.Load())
	}
}

func TestPureSandboxServerNeedsNoAdapterCredential(t *testing.T) {
	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	serverAPI, err := New(c, nil, Credentials{AdminToken: adminToken})
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(http.MethodPost, "/v1/execute", strings.NewReader(`{}`))
	recorder := httptest.NewRecorder()
	serverAPI.Handler().ServeHTTP(recorder, request)
	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("credential-free legacy execute status = %d", recorder.Code)
	}
}

func TestSandboxResponseWriteCompletesBeforeCutover(t *testing.T) {
	var deliveries atomic.Int32
	sink := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		deliveries.Add(1)
		writer.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(writer).Encode(map[string]any{
			"schema": 1, "operation_id": request.Header.Get("X-Operation-ID"),
			"outcome": "succeeded", "result_hash": strings.Repeat("a", 64),
			"remote_reference": "response-lease-result",
		})
	}))
	defer sink.Close()

	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	serverAPI, err := New(c, nil, Credentials{AdminToken: adminToken})
	if err != nil {
		t.Fatal(err)
	}
	first := control.SandboxBinding{
		SandboxID: "vm", Generation: 1, HostInstanceID: "vm-host-1",
		Domain: "agent", AllowedKinds: []string{"finish"},
	}
	certificate, err := c.Compile(testRequirement("response-v1", sink.URL))
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Cutover(certificate, []control.SandboxBinding{first}); err != nil {
		t.Fatal(err)
	}
	handler, err := serverAPI.HandlerForSandbox(first)
	if err != nil {
		t.Fatal(err)
	}
	body, err := json.Marshal(sandboxExecuteRequest{CallID: "call-1", Kind: "finish"})
	if err != nil {
		t.Fatal(err)
	}
	call := func(writer http.ResponseWriter) {
		request := httptest.NewRequest(http.MethodPost, "/v1/execute", bytes.NewReader(body))
		request.Header.Set("Content-Type", "application/json")
		handler.ServeHTTP(writer, request)
	}
	firstResponse := httptest.NewRecorder()
	call(firstResponse)
	if firstResponse.Code != http.StatusOK || deliveries.Load() != 1 {
		t.Fatalf("first response=%d deliveries=%d", firstResponse.Code, deliveries.Load())
	}

	secondCertificate, err := c.Compile(testRequirement("response-v2", sink.URL))
	if err != nil {
		t.Fatal(err)
	}
	second := first
	second.Generation = 2
	second.HostInstanceID = "vm-host-2"
	blocked := newBlockingResponseWriter()
	handlerDone := make(chan struct{})
	go func() {
		call(blocked)
		close(handlerDone)
	}()
	select {
	case <-blocked.entered:
	case <-time.After(5 * time.Second):
		close(blocked.release)
		t.Fatal("sandbox response did not reach the transport")
	}
	cutoverStarted := make(chan struct{})
	cutoverDone := make(chan error, 1)
	go func() {
		close(cutoverStarted)
		cutoverDone <- c.Cutover(secondCertificate, []control.SandboxBinding{second})
	}()
	<-cutoverStarted
	select {
	case err := <-cutoverDone:
		close(blocked.release)
		<-handlerDone
		t.Fatalf("cutover crossed response commit: %v", err)
	case <-time.After(50 * time.Millisecond):
	}
	close(blocked.release)
	<-handlerDone
	if blocked.status != http.StatusOK {
		t.Fatalf("blocked response status = %d", blocked.status)
	}
	if err := <-cutoverDone; err != nil {
		t.Fatal(err)
	}
	if deliveries.Load() != 1 {
		t.Fatalf("settled response was redispatched: deliveries=%d", deliveries.Load())
	}
}
