package workerapp

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
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
