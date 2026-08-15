package workerapp

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/deploy/temporal/app/internal/harness"
)

func TestActivitiesKeepPaymentAndCompletionEndpointsSeparate(t *testing.T) {
	newEndpoint := func(wantPath, wantOperation string) *httptest.Server {
		t.Helper()
		return httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
			if request.URL.Path != wantPath {
				t.Errorf("path = %q, want %q", request.URL.Path, wantPath)
			}
			if request.Header.Get("X-Operation-ID") != wantOperation ||
				request.Header.Get("Idempotency-Key") != wantOperation {
				t.Errorf("operation headers do not contain %q", wantOperation)
			}
			_ = json.NewEncoder(writer).Encode(harness.EffectReceipt{
				Schema: 1, OperationID: wantOperation, Outcome: "succeeded",
				ResultHash: "result-hash", RemoteReference: "provider/" + wantOperation,
			})
		}))
	}

	payment := newEndpoint("/v1/charge", "payment-op")
	defer payment.Close()
	completion := newEndpoint("/v1/complete", "completion-op")
	defer completion.Close()

	activities := NewActivities(payment.URL, completion.URL)
	if _, err := activities.ChargePayment(context.Background(), harness.EffectRequest{
		OrderID: "order-1", AmountCents: 4200, OperationID: "payment-op",
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := activities.CompleteOrder(context.Background(), harness.EffectRequest{
		OrderID: "order-1", AmountCents: 4200, OperationID: "completion-op",
	}); err != nil {
		t.Fatal(err)
	}
}

func TestQueryPaymentBindsOriginalChargeContract(t *testing.T) {
	input := harness.EffectRequest{
		OrderID: "order-1", AmountCents: 4200, OperationID: "payment-op",
	}
	wantBody := []byte(`{"order_id":"order-1","amount_cents":4200}`)
	wantHash := independentRequestHash(http.MethodPost, "/v1/charge", wantBody)
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodPost || request.URL.Path != "/v1/query" {
			t.Errorf("query target = %s %s, want POST /v1/query", request.Method, request.URL.Path)
		}
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Errorf("read query body: %v", err)
		}
		if !bytes.Equal(body, wantBody) {
			t.Errorf("query body = %q, want exact charge body %q", body, wantBody)
		}
		if request.Header.Get("Content-Type") != "application/json" ||
			request.Header.Get("Accept") != "application/json" {
			t.Errorf("query media headers = Content-Type %q Accept %q", request.Header.Get("Content-Type"), request.Header.Get("Accept"))
		}
		if request.Header.Get("X-Operation-ID") != input.OperationID {
			t.Errorf("query Operation ID = %q, want %q", request.Header.Get("X-Operation-ID"), input.OperationID)
		}
		if request.Header.Get("X-Operation-Request-Hash") != wantHash {
			t.Errorf("query request hash = %q, want %q", request.Header.Get("X-Operation-Request-Hash"), wantHash)
		}
		writer.Header().Set("Content-Type", "application/json; charset=utf-8")
		_ = json.NewEncoder(writer).Encode(harness.PaymentObservation{
			Schema: 1, OperationID: input.OperationID, RequestHash: wantHash,
			Outcome: "succeeded", FactHash: strings.Repeat("a", 64),
			RemoteReference: "payment/payment-op",
		})
	}))
	defer server.Close()

	got, err := NewActivities(server.URL, server.URL).QueryPayment(context.Background(), input)
	if err != nil {
		t.Fatal(err)
	}
	if got.Outcome != "succeeded" || got.OperationID != input.OperationID ||
		got.RequestHash != wantHash || got.FactHash != strings.Repeat("a", 64) ||
		got.RemoteReference != "payment/payment-op" {
		t.Fatalf("unexpected payment observation: %+v", got)
	}
}

func TestQueryPaymentPreservesValidInconclusiveObservation(t *testing.T) {
	input := harness.EffectRequest{OrderID: "order-1", AmountCents: 4200, OperationID: "payment-op"}
	body := []byte(`{"order_id":"order-1","amount_cents":4200}`)
	requestHash := independentRequestHash(http.MethodPost, "/v1/charge", body)
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(writer).Encode(harness.PaymentObservation{
			Schema: 1, OperationID: input.OperationID, RequestHash: requestHash,
			Outcome: "inconclusive", FactHash: "", RemoteReference: "payment/payment-op/count=0",
		})
	}))
	defer server.Close()

	got, err := NewActivities(server.URL, server.URL).QueryPayment(context.Background(), input)
	if err != nil {
		t.Fatal(err)
	}
	if got.Outcome != "inconclusive" || got.FactHash != "" {
		t.Fatalf("unexpected inconclusive observation: %+v", got)
	}
}

func TestQueryPaymentRejectsUnboundOrMalformedObservation(t *testing.T) {
	input := harness.EffectRequest{OrderID: "order-1", AmountCents: 4200, OperationID: "payment-op"}
	body := []byte(`{"order_id":"order-1","amount_cents":4200}`)
	requestHash := independentRequestHash(http.MethodPost, "/v1/charge", body)
	factHash := strings.Repeat("a", 64)
	valid := fmt.Sprintf(
		`{"schema":1,"operation_id":"payment-op","request_hash":%q,"outcome":"succeeded","fact_hash":%q,"remote_reference":"payment/payment-op"}`,
		requestHash, factHash,
	)
	tests := []struct {
		name        string
		contentType string
		body        string
	}{
		{name: "wrong content type", contentType: "text/plain", body: valid},
		{name: "wrong operation", contentType: "application/json", body: strings.Replace(valid, `"payment-op"`, `"another-op"`, 1)},
		{name: "wrong request hash", contentType: "application/json", body: strings.Replace(valid, requestHash, strings.Repeat("b", 64), 1)},
		{name: "unknown field", contentType: "application/json", body: strings.TrimSuffix(valid, "}") + `,"extra":true}`},
		{name: "duplicate field", contentType: "application/json", body: strings.Replace(valid, `"schema":1`, `"schema":1,"schema":1`, 1)},
		{name: "invalid settled hash", contentType: "application/json", body: strings.Replace(valid, factHash, "not-a-hash", 1)},
		{name: "inconclusive with fact", contentType: "application/json", body: strings.Replace(valid, `"outcome":"succeeded"`, `"outcome":"inconclusive"`, 1)},
		{name: "multiple values", contentType: "application/json", body: valid + `{}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
				writer.Header().Set("Content-Type", test.contentType)
				_, _ = io.WriteString(writer, test.body)
			}))
			defer server.Close()
			if _, err := NewActivities(server.URL, server.URL).QueryPayment(context.Background(), input); err == nil {
				t.Fatal("malformed observation was accepted")
			}
		})
	}
}

func independentRequestHash(method, path string, body []byte) string {
	input := make([]byte, 0, len(method)+len(path)+len(body)+2)
	input = append(input, method...)
	input = append(input, 0)
	input = append(input, path...)
	input = append(input, 0)
	input = append(input, body...)
	digest := sha256.Sum256(input)
	return fmt.Sprintf("%x", digest[:])
}
