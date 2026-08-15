package gateway

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
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
	thirdOutcome, err := secondGateway.Execute(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	if !thirdOutcome.Reused || thirdOutcome.Phase != kernel.Succeeded ||
		thirdOutcome.StatusCode != http.StatusOK || len(thirdOutcome.Body) == 0 {
		t.Fatalf("settled retry did not reuse durable result: %+v", thirdOutcome)
	}
	mu.Lock()
	defer mu.Unlock()
	if deliveries != 2 || len(commits) != 1 {
		t.Fatalf("deliveries=%d commits=%d", deliveries, len(commits))
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

func TestStableIdentityBindsExactHTTPRequest(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
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
	if _, err := gateway.Execute(context.Background(), second); err == nil {
		t.Fatal("stable operation identity was rebound to another request")
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
	changedCaller := Request{ID: first.ID, Domain: first.Domain, Kind: "charge-v2", URL: v2Target, Body: body}
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
