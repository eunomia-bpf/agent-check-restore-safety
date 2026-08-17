package gateway

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

func paymentRequirement(retrySafe bool, target string) kernel.Requirement {
	requirement := kernel.Requirement{
		ID:         "payment-v1",
		Results:    map[string]uint32{"paid": 1},
		Capacities: map[string]uint32{"money": 1},
		Kinds: map[string]kernel.KindSpec{
			"charge": {
				Costs:              map[string]uint32{"money": 1},
				Produces:           map[string]uint32{"paid": 1},
				RetrySafe:          retrySafe,
				Target:             target,
				Method:             http.MethodPost,
				ResponseClassifier: ResponseReceiptV1,
			},
		},
	}
	if !retrySafe {
		requirement.Kinds["safe-charge"] = kernel.KindSpec{
			Costs:              map[string]uint32{"money": 1},
			Produces:           map[string]uint32{"paid": 1},
			RetrySafe:          true,
			Target:             target,
			Method:             http.MethodPost,
			ResponseClassifier: ResponseReceiptV1,
		}
	}
	return requirement
}

func writeTestReceipt(t *testing.T, writer http.ResponseWriter, operationID string, phase kernel.Phase) {
	t.Helper()
	writer.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(writer).Encode(operationReceiptV1{
		Schema:          1,
		OperationID:     operationID,
		Outcome:         string(phase),
		ResultHash:      strings.Repeat("0", 64),
		RemoteReference: "remote-" + operationID,
	}); err != nil {
		t.Error(err)
	}
}

func openGateway(t *testing.T, path string, retrySafe bool, target string) (*control.Control, *Gateway) {
	t.Helper()
	c, err := control.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if c.Snapshot().Rule == nil {
		certificate, err := c.Compile(paymentRequirement(retrySafe, target))
		if err != nil {
			c.Close()
			t.Fatal(err)
		}
		if err := c.Activate(certificate); err != nil {
			c.Close()
			t.Fatal(err)
		}
	}
	gateway, err := New(c, nil)
	if err != nil {
		c.Close()
		t.Fatal(err)
	}
	return c, gateway
}

func queryablePaymentRequirement(retrySafe bool, target, queryTarget string) kernel.Requirement {
	return kernel.Requirement{
		ID: "queryable-payment-v1", Results: map[string]uint32{"paid": 1},
		Capacities: map[string]uint32{"money": 1},
		Kinds: map[string]kernel.KindSpec{
			"charge": {
				Costs: map[string]uint32{"money": 1}, Produces: map[string]uint32{"paid": 1},
				RetrySafe: retrySafe, Queryable: true,
				Target: target, Method: http.MethodPost, ResponseClassifier: ResponseReceiptV1,
				QueryTarget: queryTarget, QueryMethod: http.MethodPost, QueryClassifier: OperationObservationV1,
			},
		},
	}
}

func openQueryableGateway(t *testing.T, path string, retrySafe bool, target, queryTarget string) (*control.Control, *Gateway) {
	t.Helper()
	c, err := control.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if c.Snapshot().Rule == nil {
		certificate, err := c.Compile(queryablePaymentRequirement(retrySafe, target, queryTarget))
		if err != nil {
			c.Close()
			t.Fatal(err)
		}
		if err := c.Activate(certificate); err != nil {
			c.Close()
			t.Fatal(err)
		}
	}
	gateway, err := New(c, nil)
	if err != nil {
		c.Close()
		t.Fatal(err)
	}
	return c, gateway
}

func writeTestObservation(t *testing.T, writer http.ResponseWriter, operationID, requestHash, outcome, factHash string) {
	t.Helper()
	writer.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(writer).Encode(operationObservationV1{
		Schema: 1, OperationID: operationID, RequestHash: requestHash,
		Outcome: outcome, FactHash: factHash, RemoteReference: "observed-" + operationID,
	}); err != nil {
		t.Error(err)
	}
}

func TestReceiptClassifierUsesDeclaredFactAndRejectsAmbiguousJSON(t *testing.T) {
	operationID := "operation-7"
	factHash := strings.Repeat("a", 64)
	valid := fmt.Sprintf(
		`{"schema":1,"operation_id":%q,"outcome":"succeeded","result_hash":%q,"remote_reference":"remote-7"}`,
		operationID, factHash,
	)
	response := &http.Response{
		StatusCode: http.StatusOK,
		Header:     http.Header{"Content-Type": []string{"application/json"}},
	}
	phase, gotHash, reference, err := classifyResponse(
		ResponseReceiptV1, operationID, response, []byte(valid),
	)
	if err != nil || phase != kernel.Succeeded || gotHash != factHash || reference != "remote-7" {
		t.Fatalf("valid receipt rejected: phase=%s hash=%q reference=%q error=%v", phase, gotHash, reference, err)
	}

	tests := []struct {
		name string
		body string
	}{
		{name: "identity mismatch", body: strings.Replace(valid, operationID, "operation-8", 1)},
		{name: "extra field", body: strings.Replace(valid, `}`, `,"guess":true}`, 1)},
		{name: "missing field", body: strings.Replace(valid, `,"result_hash":"`+factHash+`"`, ``, 1)},
		{name: "duplicate field", body: strings.Replace(valid, `"schema":1`, `"schema":1,"schema":1`, 1)},
		{name: "null field", body: strings.Replace(valid, `"result_hash":"`+factHash+`"`, `"result_hash":null`, 1)},
		{name: "uppercase hash", body: strings.Replace(valid, factHash, strings.Repeat("A", 64), 1)},
		{name: "unsettled", body: strings.Replace(valid, `"outcome":"succeeded"`, `"outcome":"inconclusive"`, 1)},
		{name: "multiple values", body: valid + `{}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if _, _, _, err := classifyResponse(
				ResponseReceiptV1, operationID, response, []byte(test.body),
			); err == nil {
				t.Fatal("invalid receipt was accepted")
			}
		})
	}

	failedWithoutReference := fmt.Sprintf(
		`{"schema":1,"operation_id":%q,"outcome":"failed","result_hash":%q}`,
		operationID, factHash,
	)
	phase, gotHash, reference, err = classifyResponse(
		ResponseReceiptV1, operationID, response, []byte(failedWithoutReference),
	)
	if err != nil || phase != kernel.Failed || gotHash != factHash || reference != "" {
		t.Fatalf("valid failed receipt rejected: phase=%s hash=%q reference=%q error=%v", phase, gotHash, reference, err)
	}
}

func TestObservationClassifierRejectsAmbiguousOrMismatchedFacts(t *testing.T) {
	operationID := "operation-7"
	requestHash := strings.Repeat("b", 64)
	factHash := strings.Repeat("a", 64)
	valid := fmt.Sprintf(`{"schema":1,"operation_id":%q,"request_hash":%q,"outcome":"succeeded","fact_hash":%q,"remote_reference":"remote-7"}`,
		operationID, requestHash, factHash)
	tests := []struct {
		name string
		body string
	}{
		{name: "identity mismatch", body: strings.Replace(valid, operationID, "operation-8", 1)},
		{name: "request mismatch", body: strings.Replace(valid, requestHash, strings.Repeat("c", 64), 1)},
		{name: "bad request hash", body: strings.Replace(valid, requestHash, "not-a-hash", 1)},
		{name: "extra field", body: strings.Replace(valid, `}`, `,"guess":true}`, 1)},
		{name: "missing field", body: strings.Replace(valid, `,"remote_reference":"remote-7"`, ``, 1)},
		{name: "duplicate field", body: strings.Replace(valid, `"schema":1`, `"schema":1,"schema":1`, 1)},
		{name: "bad fact hash", body: strings.Replace(valid, factHash, "not-a-hash", 1)},
		{name: "uppercase fact hash", body: strings.Replace(valid, factHash, strings.Repeat("A", 64), 1)},
		{name: "null remote reference", body: strings.Replace(valid, `"remote_reference":"remote-7"`, `"remote_reference":null`, 1)},
		{name: "unknown outcome", body: strings.Replace(valid, `"outcome":"succeeded"`, `"outcome":"unknown"`, 1)},
		{name: "inconclusive fact", body: strings.Replace(valid, `"outcome":"succeeded"`, `"outcome":"inconclusive"`, 1)},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			response := &http.Response{StatusCode: http.StatusOK, Header: http.Header{"Content-Type": []string{"application/json"}}}
			if _, _, _, err := classifyObservation(OperationObservationV1, operationID, requestHash, response, []byte(test.body)); err == nil {
				t.Fatal("invalid observation was accepted")
			}
		})
	}
	response := &http.Response{StatusCode: http.StatusOK, Header: http.Header{"Content-Type": []string{"application/json"}}}
	phase, gotHash, reference, err := classifyObservation(OperationObservationV1, operationID, requestHash, response, []byte(valid))
	if err != nil || phase != kernel.Succeeded || gotHash != factHash || reference != "remote-7" {
		t.Fatalf("valid observation rejected: phase=%s hash=%q reference=%q error=%v", phase, gotHash, reference, err)
	}
	failed := strings.Replace(valid, `"outcome":"succeeded"`, `"outcome":"failed"`, 1)
	if phase, _, _, err := classifyObservation(OperationObservationV1, operationID, requestHash, response, []byte(failed)); err != nil || phase != kernel.Failed {
		t.Fatalf("valid failed observation rejected: phase=%s error=%v", phase, err)
	}
	inconclusive := strings.Replace(valid, `"outcome":"succeeded","fact_hash":"`+factHash+`"`, `"outcome":"inconclusive","fact_hash":""`, 1)
	if phase, gotHash, _, err := classifyObservation(OperationObservationV1, operationID, requestHash, response, []byte(inconclusive)); err != nil || phase != kernel.Unknown || gotHash != "" {
		t.Fatalf("valid inconclusive observation rejected: phase=%s hash=%q error=%v", phase, gotHash, err)
	}
}

func TestLostResponseRetryUsesOneRemoteOperation(t *testing.T) {
	var mu sync.Mutex
	deliveries := 0
	commits := make(map[string]bool)
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		id := request.Header.Get("X-Operation-ID")
		mu.Lock()
		deliveries++
		first := !commits[id]
		commits[id] = true
		mu.Unlock()
		if first {
			hijacker, ok := writer.(http.Hijacker)
			if !ok {
				t.Error("test server cannot drop response")
				return
			}
			connection, _, err := hijacker.Hijack()
			if err != nil {
				t.Error(err)
				return
			}
			_ = connection.Close()
			return
		}
		writeTestReceipt(t, writer, id, kernel.Succeeded)
	}))
	defer server.Close()

	path := filepath.Join(t.TempDir(), "runtime.history")
	firstControl, firstGateway := openGateway(t, path, true, server.URL)
	request := Request{
		ID:     "payment-42",
		Domain: "microservice",
		Kind:   "charge",
		URL:    server.URL,
		Body:   []byte(`{"amount":42}`),
	}
	firstOutcome, err := firstGateway.Execute(context.Background(), request)
	if !errors.Is(err, ErrOutcomeUnknown) || firstOutcome.Phase != kernel.Unknown {
		t.Fatalf("first outcome = %+v, error = %v", firstOutcome, err)
	}
	if got := firstControl.Snapshot().Operations[request.ID].Phase; got != kernel.Unknown {
		t.Fatalf("durable phase = %s", got)
	}
	if err := firstControl.Close(); err != nil {
		t.Fatal(err)
	}

	secondControl, secondGateway := openGateway(t, path, true, server.URL)
	defer secondControl.Close()
	secondOutcome, err := secondGateway.Execute(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	if secondOutcome.Phase != kernel.Succeeded || secondOutcome.StatusCode != http.StatusOK {
		t.Fatalf("second outcome = %+v", secondOutcome)
	}
	if secondOutcome.ResultHash != strings.Repeat("0", 64) {
		t.Fatalf("direct settlement ignored provider fact hash: %+v", secondOutcome)
	}
	thirdOutcome, err := secondGateway.Execute(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	if !thirdOutcome.Reused || thirdOutcome.Phase != kernel.Succeeded ||
		thirdOutcome.StatusCode != http.StatusOK || len(thirdOutcome.Body) == 0 ||
		thirdOutcome.ResultHash != secondOutcome.ResultHash {
		t.Fatalf("settled retry did not reuse durable result: %+v", thirdOutcome)
	}
	mu.Lock()
	defer mu.Unlock()
	if deliveries != 2 || len(commits) != 1 {
		t.Fatalf("deliveries=%d commits=%d", deliveries, len(commits))
	}
}

func TestEffectReceivesRecordedRequestHash(t *testing.T) {
	var observed string
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		observed = request.Header.Get("X-Operation-Request-Hash")
		writeTestReceipt(t, writer, request.Header.Get("X-Operation-ID"), kernel.Succeeded)
	}))
	defer server.Close()

	c, gateway := openGateway(t, filepath.Join(t.TempDir(), "runtime.history"), true, server.URL)
	defer c.Close()
	request := Request{
		ID: "request-hash-42", Domain: "microservice", Kind: "charge", URL: server.URL,
		Headers: map[string]string{"Content-Type": "application/json"}, Body: []byte(`{"amount":42}`),
	}
	if outcome, err := gateway.Execute(context.Background(), request); err != nil || outcome.Phase != kernel.Succeeded {
		t.Fatalf("outcome=%+v error=%v", outcome, err)
	}
	operation := c.Snapshot().Operations[request.ID]
	if observed == "" || observed != operation.RequestHash {
		t.Fatalf("effect request hash=%q, recorded=%q", observed, operation.RequestHash)
	}
}

func TestOneExecuteCannotBeReplayedInsideHTTPTransport(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	var deliveries atomic.Int32
	serverDone := make(chan error, 1)
	go func() {
		firstConnection, err := listener.Accept()
		if err != nil {
			serverDone <- err
			return
		}
		reader := bufio.NewReader(firstConnection)
		first, err := http.ReadRequest(reader)
		if err != nil {
			_ = firstConnection.Close()
			serverDone <- err
			return
		}
		_, _ = io.Copy(io.Discard, first.Body)
		_ = first.Body.Close()
		deliveries.Add(1)
		if err := writeRawReceipt(firstConnection, first.Header.Get("X-Operation-ID"), false); err != nil {
			_ = firstConnection.Close()
			serverDone <- err
			return
		}
		second, err := http.ReadRequest(reader)
		if err != nil {
			_ = firstConnection.Close()
			serverDone <- err
			return
		}
		_, _ = io.Copy(io.Discard, second.Body)
		_ = second.Body.Close()
		deliveries.Add(1)
		// The provider committed the second request, but the reused connection
		// disappeared before a response. A replayable net/http request would be
		// silently sent again on the next connection by this same Client.Do.
		_ = firstConnection.Close()

		tcpListener := listener.(*net.TCPListener)
		if err := tcpListener.SetDeadline(time.Now().Add(500 * time.Millisecond)); err != nil {
			serverDone <- err
			return
		}
		retryConnection, err := listener.Accept()
		if timeout, ok := err.(net.Error); ok && timeout.Timeout() {
			serverDone <- nil
			return
		}
		if err != nil {
			serverDone <- err
			return
		}
		defer retryConnection.Close()
		retried, err := http.ReadRequest(bufio.NewReader(retryConnection))
		if err != nil {
			serverDone <- err
			return
		}
		_, _ = io.Copy(io.Discard, retried.Body)
		_ = retried.Body.Close()
		deliveries.Add(1)
		serverDone <- writeRawReceipt(retryConnection, retried.Header.Get("X-Operation-ID"), true)
	}()

	target := "http://" + listener.Addr().String() + "/charge"
	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	requirement := paymentRequirement(true, target)
	requirement.Results["paid"] = 2
	requirement.Capacities["money"] = 2
	certificate, err := c.Compile(requirement)
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Activate(certificate); err != nil {
		t.Fatal(err)
	}
	transport := &http.Transport{}
	defer transport.CloseIdleConnections()
	gateway, err := New(c, &http.Client{Transport: transport, Timeout: 2 * time.Second})
	if err != nil {
		t.Fatal(err)
	}
	first := Request{ID: "warm-connection", Domain: "orders", Kind: "charge", URL: target, Body: []byte(`{"amount":1}`)}
	if outcome, err := gateway.Execute(context.Background(), first); err != nil || outcome.Phase != kernel.Succeeded {
		t.Fatalf("warm request outcome=%+v error=%v", outcome, err)
	}
	second := Request{ID: "lost-response", Domain: "orders", Kind: "charge", URL: target, Body: []byte(`{"amount":2}`)}
	if outcome, err := gateway.Execute(context.Background(), second); !errors.Is(err, ErrOutcomeUnknown) || outcome.Phase != kernel.Unknown {
		t.Fatalf("one Execute hid a transport replay: outcome=%+v error=%v", outcome, err)
	}
	if err := <-serverDone; err != nil {
		t.Fatal(err)
	}
	if got := deliveries.Load(); got != 2 {
		t.Fatalf("one Execute produced an implicit retry: deliveries=%d, want 2 total", got)
	}
}

func writeRawReceipt(connection net.Conn, operationID string, closeConnection bool) error {
	body, err := json.Marshal(operationReceiptV1{
		Schema: 1, OperationID: operationID, Outcome: string(kernel.Succeeded),
		ResultHash: strings.Repeat("0", 64), RemoteReference: "remote-" + operationID,
	})
	if err != nil {
		return err
	}
	connectionHeader := "keep-alive"
	if closeConnection {
		connectionHeader = "close"
	}
	_, err = fmt.Fprintf(connection,
		"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: %s\r\n\r\n%s",
		len(body), connectionHeader, body,
	)
	return err
}

func TestLostResponseRecoveredByQueryWithoutRedispatch(t *testing.T) {
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
	var observedBody []byte
	var observedContentType, observedOperationID, observedRequestHash, leakedHeader string
	observer := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		queries.Add(1)
		observedBody, _ = io.ReadAll(request.Body)
		observedContentType = request.Header.Get("Content-Type")
		observedOperationID = request.Header.Get("X-Operation-ID")
		observedRequestHash = request.Header.Get("X-Operation-Request-Hash")
		leakedHeader = request.Header.Get("X-Caller-Secret")
		writeTestObservation(t, writer, observedOperationID, observedRequestHash, "succeeded", strings.Repeat("a", 64))
	}))
	defer observer.Close()

	path := filepath.Join(t.TempDir(), "runtime.history")
	firstControl, firstGateway := openQueryableGateway(t, path, false, effect.URL, observer.URL)
	body := []byte(`{"hotel":"H1","rooms":1}`)
	request := Request{
		ID: "stay-42", Domain: "hotel", Kind: "charge", URL: effect.URL, Body: body,
		Headers: map[string]string{"Content-Type": "application/json", "X-Caller-Secret": "do-not-copy"},
	}
	if outcome, err := firstGateway.Execute(context.Background(), request); !errors.Is(err, ErrOutcomeUnknown) || outcome.Phase != kernel.Unknown {
		t.Fatalf("first outcome=%+v error=%v", outcome, err)
	}
	wantRequestHash := firstControl.Snapshot().Operations[request.ID].RequestHash
	if err := firstControl.Close(); err != nil {
		t.Fatal(err)
	}

	secondControl, secondGateway := openQueryableGateway(t, path, false, effect.URL, observer.URL)
	replacementRequest := Request{
		ID: request.ID, Domain: request.Domain, Kind: "replacement-kind",
		URL: "http://replacement.invalid/v2", Body: body,
		Headers: map[string]string{"Content-Type": "application/json", "X-Caller-Secret": "do-not-copy"},
	}
	outcome, err := secondGateway.Execute(context.Background(), replacementRequest)
	if err != nil {
		t.Fatal(err)
	}
	if outcome.Phase != kernel.Succeeded || !outcome.RecoveredByQuery || outcome.ResultHash != strings.Repeat("a", 64) {
		t.Fatalf("query recovery outcome=%+v", outcome)
	}
	if deliveries.Load() != 1 || queries.Load() != 1 {
		t.Fatalf("deliveries=%d queries=%d", deliveries.Load(), queries.Load())
	}
	if string(observedBody) != string(body) || observedContentType != "application/json" ||
		observedOperationID != request.ID || observedRequestHash != wantRequestHash || leakedHeader != "" {
		t.Fatalf("query request body=%q content-type=%q id=%q hash=%q leaked=%q", observedBody, observedContentType, observedOperationID, observedRequestHash, leakedHeader)
	}
	if secondControl.Snapshot().Operations[request.ID].Settlement != kernel.SettlementQuery {
		t.Fatal("query settlement was not recorded")
	}
	if err := secondControl.Close(); err != nil {
		t.Fatal(err)
	}
	thirdControl, thirdGateway := openQueryableGateway(t, path, false, effect.URL, observer.URL)
	defer thirdControl.Close()
	reused, err := thirdGateway.Execute(context.Background(), Request{
		ID: request.ID, Domain: request.Domain, Body: body,
		Headers: map[string]string{"Content-Type": "application/json", "X-Caller-Secret": "do-not-copy"},
	})
	if err != nil || !reused.Reused || !reused.RecoveredByQuery {
		t.Fatalf("durable query result was not reused: %+v error=%v", reused, err)
	}
	if queries.Load() != 1 || thirdControl.Snapshot().Operations[request.ID].Settlement != kernel.SettlementQuery {
		t.Fatal("query settlement was not durably reused")
	}
}

func TestRecoverUnknownByIDUsesStoredRequestAfterRestart(t *testing.T) {
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
	var observedBody []byte
	observer := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		queries.Add(1)
		observedBody, _ = io.ReadAll(request.Body)
		writeTestObservation(
			t, writer, request.Header.Get("X-Operation-ID"),
			request.Header.Get("X-Operation-Request-Hash"), "succeeded", strings.Repeat("c", 64),
		)
	}))
	defer observer.Close()

	path := filepath.Join(t.TempDir(), "runtime.history")
	firstControl, firstGateway := openQueryableGateway(t, path, false, effect.URL, observer.URL)
	body := []byte(`{"order":"A-17","amount":42}`)
	request := Request{
		ID: "recover-by-id", Domain: "orders", Kind: "charge", URL: effect.URL,
		Headers: map[string]string{"Content-Type": "application/json"}, Body: body,
	}
	if outcome, err := firstGateway.Execute(context.Background(), request); !errors.Is(err, ErrOutcomeUnknown) || outcome.Phase != kernel.Unknown {
		t.Fatalf("first outcome=%+v error=%v", outcome, err)
	}
	if err := firstControl.Close(); err != nil {
		t.Fatal(err)
	}

	secondControl, secondGateway := openQueryableGateway(t, path, false, effect.URL, observer.URL)
	defer secondControl.Close()
	outcome, err := secondGateway.Recover(context.Background(), request.ID)
	if err != nil || outcome.Phase != kernel.Succeeded || !outcome.RecoveredByQuery {
		t.Fatalf("recovery outcome=%+v error=%v", outcome, err)
	}
	if deliveries.Load() != 1 || queries.Load() != 1 || string(observedBody) != string(body) {
		t.Fatalf("deliveries=%d queries=%d observed body=%q", deliveries.Load(), queries.Load(), observedBody)
	}
	operation := secondControl.Snapshot().Operations[request.ID]
	if operation.Settlement != kernel.SettlementQuery || !operation.RequestStored {
		t.Fatalf("recovered Operation=%+v", operation)
	}
}

func TestRecoverRejectsMissingMismatchedOrIneligibleStoredRequest(t *testing.T) {
	var queries atomic.Int32
	observer := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		queries.Add(1)
		t.Error("invalid recovery reached observer")
	}))
	defer observer.Close()
	effect := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		t.Error("query-only recovery reached effect")
	}))
	defer effect.Close()

	moveUnknown := func(t *testing.T, control *control.Control, id string) {
		t.Helper()
		if err := control.Move(id, kernel.OperationUpdate{
			Phase: kernel.Dispatched, DispatchOwner: "test-boot", DispatchGeneration: 1,
		}); err != nil {
			t.Fatal(err)
		}
		if err := control.Move(id, kernel.OperationUpdate{Phase: kernel.Unknown}); err != nil {
			t.Fatal(err)
		}
	}

	t.Run("missing", func(t *testing.T) {
		c, gateway := openQueryableGateway(t, filepath.Join(t.TempDir(), "runtime.history"), false, effect.URL, observer.URL)
		defer c.Close()
		if _, err := c.Prepare("legacy-operation", "orders", "charge", strings.Repeat("a", 64)); err != nil {
			t.Fatal(err)
		}
		moveUnknown(t, c, "legacy-operation")
		if _, err := gateway.Recover(context.Background(), "legacy-operation"); !errors.Is(err, ErrStoredRequestUnavailable) {
			t.Fatalf("missing request error=%v", err)
		}
	})

	t.Run("mismatched", func(t *testing.T) {
		c, gateway := openQueryableGateway(t, filepath.Join(t.TempDir(), "runtime.history"), false, effect.URL, observer.URL)
		defer c.Close()
		if _, err := c.PrepareWithRequest(
			"tampered-operation", "orders", "charge", strings.Repeat("b", 64),
			map[string]string{"Content-Type": "application/json"}, []byte(`{"amount":42}`),
		); err != nil {
			t.Fatal(err)
		}
		moveUnknown(t, c, "tampered-operation")
		if _, err := gateway.Recover(context.Background(), "tampered-operation"); !errors.Is(err, ErrStoredRequestMismatch) {
			t.Fatalf("mismatched request error=%v", err)
		}
	})

	t.Run("wrong-phase", func(t *testing.T) {
		c, gateway := openQueryableGateway(t, filepath.Join(t.TempDir(), "runtime.history"), false, effect.URL, observer.URL)
		defer c.Close()
		if _, err := c.PrepareWithRequest(
			"prepared-operation", "orders", "charge", strings.Repeat("c", 64), nil, nil,
		); err != nil {
			t.Fatal(err)
		}
		if _, err := gateway.Recover(context.Background(), "prepared-operation"); !errors.Is(err, ErrOperationNotRecoverable) {
			t.Fatalf("prepared recovery error=%v", err)
		}
	})

	t.Run("not-queryable", func(t *testing.T) {
		c, gateway := openGateway(t, filepath.Join(t.TempDir(), "runtime.history"), true, effect.URL)
		defer c.Close()
		if _, err := c.PrepareWithRequest(
			"retry-only-operation", "orders", "charge", strings.Repeat("d", 64), nil, nil,
		); err != nil {
			t.Fatal(err)
		}
		moveUnknown(t, c, "retry-only-operation")
		if _, err := gateway.Recover(context.Background(), "retry-only-operation"); !errors.Is(err, ErrOperationNotRecoverable) {
			t.Fatalf("non-queryable recovery error=%v", err)
		}
	})

	if queries.Load() != 0 {
		t.Fatalf("rejected recoveries issued %d observer queries", queries.Load())
	}
}

func TestInconclusiveQueryAllowsOnlyRetrySafeRedispatch(t *testing.T) {
	for _, retrySafe := range []bool{false, true} {
		t.Run(fmt.Sprintf("retry-safe-%t", retrySafe), func(t *testing.T) {
			var deliveries atomic.Int32
			effect := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
				if deliveries.Add(1) == 1 {
					connection, _, err := writer.(http.Hijacker).Hijack()
					if err != nil {
						t.Error(err)
						return
					}
					_ = connection.Close()
					return
				}
				writeTestReceipt(t, writer, request.Header.Get("X-Operation-ID"), kernel.Succeeded)
			}))
			defer effect.Close()
			var queries atomic.Int32
			observer := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
				queries.Add(1)
				writeTestObservation(t, writer, request.Header.Get("X-Operation-ID"), request.Header.Get("X-Operation-Request-Hash"), "inconclusive", "")
			}))
			defer observer.Close()
			c, gateway := openQueryableGateway(t, filepath.Join(t.TempDir(), "runtime.history"), retrySafe, effect.URL, observer.URL)
			defer c.Close()
			request := Request{ID: "charge-inconclusive", Domain: "payment", Kind: "charge", URL: effect.URL}
			if _, err := gateway.Execute(context.Background(), request); !errors.Is(err, ErrOutcomeUnknown) {
				t.Fatalf("first error=%v", err)
			}
			outcome, err := gateway.Execute(context.Background(), request)
			if retrySafe {
				if err != nil || outcome.Phase != kernel.Succeeded || outcome.RecoveredByQuery {
					t.Fatalf("retry-safe outcome=%+v error=%v", outcome, err)
				}
				if deliveries.Load() != 2 {
					t.Fatalf("retry-safe deliveries=%d", deliveries.Load())
				}
			} else {
				if !errors.Is(err, ErrOutcomeUnknown) || outcome.Phase != kernel.Unknown {
					t.Fatalf("query-only outcome=%+v error=%v", outcome, err)
				}
				if deliveries.Load() != 1 {
					t.Fatalf("query-only operation was redispatched %d times", deliveries.Load())
				}
			}
			if queries.Load() != 1 {
				t.Fatalf("queries=%d", queries.Load())
			}
		})
	}
}

func TestMalformedObservationNeverSettlesOrUnlocksRetry(t *testing.T) {
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
	observer := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(`{"schema":1,"operation_id":"wrong","request_hash":"wrong","outcome":"inconclusive","fact_hash":"","remote_reference":""}`))
	}))
	defer observer.Close()
	c, gateway := openQueryableGateway(t, filepath.Join(t.TempDir(), "runtime.history"), true, effect.URL, observer.URL)
	defer c.Close()
	request := Request{ID: "malformed-query", Domain: "payment", Kind: "charge", URL: effect.URL}
	if _, err := gateway.Execute(context.Background(), request); !errors.Is(err, ErrOutcomeUnknown) {
		t.Fatalf("first error=%v", err)
	}
	if outcome, err := gateway.Execute(context.Background(), request); !errors.Is(err, ErrOutcomeUnknown) || outcome.Phase != kernel.Unknown {
		t.Fatalf("malformed query outcome=%+v error=%v", outcome, err)
	}
	if deliveries.Load() != 1 || c.Snapshot().Operations[request.ID].Phase != kernel.Unknown {
		t.Fatal("malformed observation unlocked a retry or settled the Operation")
	}
}

func TestNonRetryableOperationCannotCrossGateway(t *testing.T) {
	var deliveries atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		deliveries.Add(1)
		hijacker := writer.(http.Hijacker)
		connection, _, err := hijacker.Hijack()
		if err != nil {
			t.Error(err)
			return
		}
		_ = connection.Close()
	}))
	defer server.Close()

	path := filepath.Join(t.TempDir(), "runtime.history")
	c, gateway := openGateway(t, path, false, server.URL)
	defer c.Close()
	request := Request{ID: "wire-1", Domain: "vm", Kind: "charge", URL: server.URL}
	if _, err := gateway.Execute(context.Background(), request); err == nil {
		t.Fatal("non-recoverable request crossed the gateway")
	}
	if deliveries.Load() != 0 {
		t.Fatalf("unsafe retry crossed gateway: deliveries=%d", deliveries.Load())
	}
}

func TestStableIdentityRejectsReplacementBytes(t *testing.T) {
	var deliveries atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		deliveries.Add(1)
		writeTestReceipt(t, writer, request.Header.Get("X-Operation-ID"), kernel.Succeeded)
	}))
	defer server.Close()
	c, gateway := openGateway(t, filepath.Join(t.TempDir(), "runtime.history"), true, server.URL)
	defer c.Close()

	first := Request{ID: "charge-1", Domain: "agent", Kind: "charge", URL: server.URL, Body: []byte("a")}
	if _, err := gateway.Execute(context.Background(), first); err != nil {
		t.Fatal(err)
	}
	second := first
	second.Body = []byte("b")
	second.Headers = map[string]string{"X-Replacement": "ignored"}
	outcome, err := gateway.Execute(context.Background(), second)
	if !errors.Is(err, ErrOperationRequestConflict) || outcome.Reused || outcome.Phase != kernel.Succeeded {
		t.Fatalf("settled Operation accepted replacement bytes: outcome=%+v error=%v", outcome, err)
	}
	if deliveries.Load() != 1 {
		t.Fatalf("replacement caller caused %d deliveries", deliveries.Load())
	}
	retry := first
	retry.Kind = "new-release-kind"
	retry.URL = "http://new-release.invalid/charge"
	outcome, err = gateway.Execute(context.Background(), retry)
	if err != nil || !outcome.Reused || outcome.Phase != kernel.Succeeded {
		t.Fatalf("matching retry did not reuse frozen Operation: outcome=%+v error=%v", outcome, err)
	}
}

func TestRegisteredTargetCannotRedirectGateway(t *testing.T) {
	var redirectedDeliveries atomic.Int32
	redirected := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		redirectedDeliveries.Add(1)
		writer.WriteHeader(http.StatusOK)
	}))
	defer redirected.Close()

	registered := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		http.Redirect(writer, request, redirected.URL, http.StatusTemporaryRedirect)
	}))
	defer registered.Close()

	c, gateway := openGateway(t, filepath.Join(t.TempDir(), "runtime.history"), true, registered.URL)
	defer c.Close()
	outcome, err := gateway.Execute(context.Background(), Request{
		ID: "charge-redirect", Domain: "microservice", Kind: "charge", URL: registered.URL,
	})
	if !errors.Is(err, ErrOutcomeUnknown) {
		t.Fatalf("redirect error = %v", err)
	}
	if outcome.Phase != kernel.Unknown || outcome.StatusCode != http.StatusTemporaryRedirect {
		t.Fatalf("redirect outcome = %+v", outcome)
	}
	if redirectedDeliveries.Load() != 0 {
		t.Fatalf("gateway followed redirect to an unregistered target: deliveries=%d", redirectedDeliveries.Load())
	}
}

func TestHTTPStatusAloneNeverSettlesOperation(t *testing.T) {
	tests := []struct {
		name        string
		status      int
		contentType string
		body        string
	}{
		{name: "accepted", status: http.StatusAccepted, contentType: "application/json", body: `{}`},
		{name: "server error after possible commit", status: http.StatusInternalServerError, contentType: "application/json", body: `{}`},
		{name: "unrecognized success body", status: http.StatusOK, contentType: "application/json", body: `{"done":true}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
				writer.Header().Set("Content-Type", test.contentType)
				writer.WriteHeader(test.status)
				_, _ = writer.Write([]byte(test.body))
			}))
			defer server.Close()
			c, gateway := openGateway(t, filepath.Join(t.TempDir(), "runtime.history"), true, server.URL)
			defer c.Close()
			outcome, err := gateway.Execute(context.Background(), Request{
				ID: "uncertain-1", Domain: "service", Kind: "charge", URL: server.URL,
			})
			if !errors.Is(err, ErrOutcomeUnknown) || outcome.Phase != kernel.Unknown {
				t.Fatalf("outcome=%+v error=%v", outcome, err)
			}
			if got := c.Snapshot().Operations["uncertain-1"].Phase; got != kernel.Unknown {
				t.Fatalf("durable phase = %s", got)
			}
		})
	}
}

func TestConcurrentExecuteHasOneLiveDispatch(t *testing.T) {
	var deliveries atomic.Int32
	entered := make(chan struct{})
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if deliveries.Add(1) == 1 {
			close(entered)
		}
		<-release
		writeTestReceipt(t, writer, request.Header.Get("X-Operation-ID"), kernel.Succeeded)
	}))
	defer server.Close()
	c, gateway := openGateway(t, filepath.Join(t.TempDir(), "runtime.history"), true, server.URL)
	request := Request{ID: "concurrent-1", Domain: "service", Kind: "charge", URL: server.URL}
	type result struct {
		outcome Outcome
		err     error
	}
	first := make(chan result, 1)
	go func() {
		outcome, err := gateway.Execute(context.Background(), request)
		first <- result{outcome: outcome, err: err}
	}()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("first dispatch did not reach server")
	}
	second, err := gateway.Execute(context.Background(), request)
	if !errors.Is(err, ErrOperationInFlight) || second.Phase != kernel.Dispatched {
		t.Fatalf("second outcome=%+v error=%v", second, err)
	}
	if deliveries.Load() != 1 {
		t.Fatalf("concurrent deliveries = %d", deliveries.Load())
	}
	closed := make(chan error, 1)
	go func() { closed <- c.Close() }()
	select {
	case err := <-closed:
		t.Fatalf("Control closed with a live dispatch: %v", err)
	case <-time.After(50 * time.Millisecond):
	}
	close(release)
	completed := <-first
	if completed.err != nil || completed.outcome.Phase != kernel.Succeeded {
		t.Fatalf("first completion=%+v error=%v", completed.outcome, completed.err)
	}
	if err := <-closed; err != nil {
		t.Fatal(err)
	}
}

func TestFinalizedRequestRejectsAmbiguousHeaders(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		t.Fatal("ambiguous request reached network")
	}))
	defer server.Close()
	c, gateway := openGateway(t, filepath.Join(t.TempDir(), "runtime.history"), true, server.URL)
	defer c.Close()
	requests := []Request{
		{ID: "duplicate-headers", Domain: "service", Kind: "charge", URL: server.URL,
			Headers: map[string]string{"X-Mode": "a", "x-mode": "b"}},
		{ID: "reserved-header", Domain: "service", Kind: "charge", URL: server.URL,
			Headers: map[string]string{"Idempotency-Key": "attacker"}},
		{ID: "authorization-header", Domain: "service", Kind: "charge", URL: server.URL,
			Headers: map[string]string{"Authorization": "Bearer must-not-enter-History"}},
		{ID: "cookie-header", Domain: "service", Kind: "charge", URL: server.URL,
			Headers: map[string]string{"Cookie": "session=must-not-enter-History"}},
		{ID: "api-key-header", Domain: "service", Kind: "charge", URL: server.URL,
			Headers: map[string]string{"X-API-Key": "must-not-enter-History"}},
		{ID: "nul-header", Domain: "service", Kind: "charge", URL: server.URL,
			Headers: map[string]string{"X-Mode": "a\x00b"}},
	}
	for _, request := range requests {
		if _, err := gateway.Execute(context.Background(), request); err == nil {
			t.Fatalf("ambiguous request %q was accepted", request.ID)
		}
	}
}

func TestChangedCallerRetriesFrozenOperationWithoutStateMigration(t *testing.T) {
	var mu sync.Mutex
	deliveries := map[string]int{}
	committed := map[string]bool{}
	dropFirst := true
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		id := request.Header.Get("X-Operation-ID")
		mu.Lock()
		deliveries[request.URL.Path]++
		firstCommit := !committed[id]
		committed[id] = true
		drop := firstCommit && dropFirst
		if drop {
			dropFirst = false
		}
		mu.Unlock()
		if drop {
			connection, _, err := writer.(http.Hijacker).Hijack()
			if err != nil {
				t.Error(err)
				return
			}
			_ = connection.Close()
			return
		}
		writeTestReceipt(t, writer, id, kernel.Succeeded)
	}))
	defer server.Close()

	v1Target := server.URL + "/v1/charge"
	v2Target := server.URL + "/v2/charge"
	requirement := func(id, kind, target string, results uint32) kernel.Requirement {
		return kernel.Requirement{
			ID: id, Results: map[string]uint32{"paid": results},
			Capacities: map[string]uint32{"money": 2},
			Kinds: map[string]kernel.KindSpec{
				kind: {
					Costs: map[string]uint32{"money": 1}, Produces: map[string]uint32{"paid": 1},
					RetrySafe: true, Target: target, Method: http.MethodPost,
					ResponseClassifier: ResponseReceiptV1,
				},
			},
		}
	}
	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	activate := func(r kernel.Requirement) {
		certificate, err := c.Compile(r)
		if err != nil {
			t.Fatal(err)
		}
		if err := c.Activate(certificate); err != nil {
			t.Fatal(err)
		}
	}
	activate(requirement("orders-v1", "charge-v1", v1Target, 1))
	gateway, err := New(c, nil)
	if err != nil {
		t.Fatal(err)
	}
	body := []byte(`{"order":"A-17","amount":42}`)
	first := Request{ID: "order-A-17", Domain: "orders", Kind: "charge-v1", URL: v1Target, Body: body}
	if outcome, err := gateway.Execute(context.Background(), first); !errors.Is(err, ErrOutcomeUnknown) || outcome.Phase != kernel.Unknown {
		t.Fatalf("first outcome=%+v error=%v", outcome, err)
	}
	activate(requirement("orders-v2", "charge-v2", v2Target, 2))

	// The new caller knows only its global v2 configuration. The runtime finds
	// the existing ID in History and sends the original v1 Operation instead.
	changedCaller := Request{
		ID: first.ID, Domain: first.Domain, Kind: "charge-v2", URL: v2Target,
		Body: body,
	}
	if outcome, err := gateway.Execute(context.Background(), changedCaller); err != nil || outcome.Phase != kernel.Succeeded {
		t.Fatalf("changed-caller retry outcome=%+v error=%v", outcome, err)
	}
	newOrder := Request{ID: "order-B-18", Domain: "orders", Kind: "charge-v2", URL: v2Target,
		Body: []byte(`{"order":"B-18","amount":7}`)}
	if outcome, err := gateway.Execute(context.Background(), newOrder); err != nil || outcome.Phase != kernel.Succeeded {
		t.Fatalf("new v2 operation outcome=%+v error=%v", outcome, err)
	}
	mu.Lock()
	defer mu.Unlock()
	if deliveries["/v1/charge"] != 2 || deliveries["/v2/charge"] != 1 || len(committed) != 2 {
		t.Fatalf("deliveries=%v committed=%d", deliveries, len(committed))
	}
}

func testSandboxBinding(generation uint64, host string) control.SandboxBinding {
	return control.SandboxBinding{
		SandboxID: "agent-vm", Generation: generation, HostInstanceID: host,
		Domain: "sandbox-domain", AllowedKinds: []string{"charge"},
	}
}

func cutoverSandbox(
	t *testing.T,
	c *control.Control,
	requirement kernel.Requirement,
	binding control.SandboxBinding,
) {
	t.Helper()
	certificate, err := c.Compile(requirement)
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Cutover(certificate, []control.SandboxBinding{binding}); err != nil {
		t.Fatal(err)
	}
	if err := c.AttachSandboxHost(binding); err != nil {
		t.Fatal(err)
	}
}

func TestSandboxCutoverFirstRejectsBeforeOperationLookupAndProvider(t *testing.T) {
	var deliveries atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		deliveries.Add(1)
		writeTestReceipt(t, writer, request.Header.Get("X-Operation-ID"), kernel.Succeeded)
	}))
	defer server.Close()

	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	first := testSandboxBinding(1, "host-instance-1")
	second := testSandboxBinding(2, "host-instance-2")
	requirement := paymentRequirement(true, server.URL)
	cutoverSandbox(t, c, requirement, first)
	cutoverSandbox(t, c, requirement, second)
	g, err := New(c, nil)
	if err != nil {
		t.Fatal(err)
	}

	request := Request{
		ID: "sandbox-charge-1", Domain: "guest-forged-domain", Kind: "charge", URL: server.URL,
	}
	outcome, err := g.ExecuteBound(context.Background(), first, request)
	if !errors.Is(err, control.ErrStaleSandboxBinding) {
		t.Fatalf("stale sandbox outcome=%+v error=%v", outcome, err)
	}
	if !reflect.DeepEqual(outcome, Outcome{}) || deliveries.Load() != 0 {
		t.Fatalf("stale sandbox outcome=%+v deliveries=%d", outcome, deliveries.Load())
	}
	if _, exists := c.Operation(request.ID); exists {
		t.Fatal("stale sandbox reached Operation lookup/prepare")
	}

	outcome, err = g.ExecuteBound(context.Background(), second, request)
	if err != nil || outcome.Phase != kernel.Succeeded || deliveries.Load() != 1 {
		t.Fatalf("current sandbox outcome=%+v deliveries=%d error=%v", outcome, deliveries.Load(), err)
	}
	operation, exists := c.Operation(request.ID)
	if !exists || operation.Domain != second.Domain {
		t.Fatalf("host binding did not own Operation domain: %+v exists=%t", operation, exists)
	}
}

func TestSandboxCutoverDuringDeliveryRecordsResultButFencesCaller(t *testing.T) {
	var deliveries atomic.Int32
	entered := make(chan struct{})
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if deliveries.Add(1) == 1 {
			close(entered)
		}
		<-release
		writeTestReceipt(t, writer, request.Header.Get("X-Operation-ID"), kernel.Succeeded)
	}))
	defer server.Close()

	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	first := testSandboxBinding(1, "host-instance-1")
	second := testSandboxBinding(2, "host-instance-2")
	requirement := paymentRequirement(true, server.URL)
	cutoverSandbox(t, c, requirement, first)
	g, err := New(c, nil)
	if err != nil {
		t.Fatal(err)
	}
	request := Request{ID: "sandbox-charge-2", Kind: "charge", URL: server.URL}
	type result struct {
		outcome Outcome
		err     error
	}
	completed := make(chan result, 1)
	go func() {
		outcome, err := g.ExecuteBound(context.Background(), first, request)
		completed <- result{outcome: outcome, err: err}
	}()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("sandbox dispatch did not reach provider")
	}

	// The durable Dispatched marker is already in History, so a newly
	// compiled Certificate accounts for the in-flight Operation. Its cutover
	// fences the old caller but does not prevent the host from recording the
	// provider's definitive response.
	cutoverSandbox(t, c, requirement, second)
	close(release)
	old := <-completed
	if !errors.Is(old.err, control.ErrStaleSandboxBinding) || !reflect.DeepEqual(old.outcome, Outcome{}) {
		t.Fatalf("old sandbox received result: outcome=%+v error=%v", old.outcome, old.err)
	}
	operation, exists := c.Operation(request.ID)
	if !exists || operation.Phase != kernel.Succeeded || deliveries.Load() != 1 {
		t.Fatalf("host did not retain settlement: operation=%+v exists=%t deliveries=%d", operation, exists, deliveries.Load())
	}

	current, err := g.ExecuteBound(context.Background(), second, request)
	if err != nil || current.Phase != kernel.Succeeded || !current.Reused || deliveries.Load() != 1 {
		t.Fatalf("new sandbox did not reuse result: outcome=%+v deliveries=%d error=%v", current, deliveries.Load(), err)
	}
}

func TestSandboxDispatchMarkerMakesPriorCutoverCertificateStale(t *testing.T) {
	var deliveries atomic.Int32
	entered := make(chan struct{})
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if deliveries.Add(1) == 1 {
			close(entered)
		}
		<-release
		writeTestReceipt(t, writer, request.Header.Get("X-Operation-ID"), kernel.Succeeded)
	}))
	defer server.Close()

	c, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	first := testSandboxBinding(1, "host-instance-1")
	second := testSandboxBinding(2, "host-instance-2")
	requirement := paymentRequirement(true, server.URL)
	cutoverSandbox(t, c, requirement, first)
	priorCertificate, err := c.Compile(requirement)
	if err != nil {
		t.Fatal(err)
	}
	g, err := New(c, nil)
	if err != nil {
		t.Fatal(err)
	}
	type result struct {
		outcome Outcome
		err     error
	}
	completed := make(chan result, 1)
	go func() {
		outcome, err := g.ExecuteBound(context.Background(), first, Request{
			ID: "sandbox-charge-3", Kind: "charge", URL: server.URL,
		})
		completed <- result{outcome: outcome, err: err}
	}()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("sandbox dispatch did not reach provider")
	}

	// Prepare and the pre-network Dispatched marker are already durable. A
	// Certificate from before this call cannot close the old generation as if
	// the Operation did not exist.
	if err := c.Cutover(priorCertificate, []control.SandboxBinding{second}); err == nil ||
		!strings.Contains(err.Error(), "stale") {
		close(release)
		t.Fatalf("pre-dispatch Certificate survived Operation progress: %v", err)
	}
	if err := c.ValidateSandbox(first); err != nil {
		close(release)
		t.Fatalf("failed cutover fenced the active sandbox: %v", err)
	}
	close(release)
	finished := <-completed
	if finished.err != nil || finished.outcome.Phase != kernel.Succeeded || deliveries.Load() != 1 {
		t.Fatalf("winning call outcome=%+v deliveries=%d error=%v", finished.outcome, deliveries.Load(), finished.err)
	}
}
