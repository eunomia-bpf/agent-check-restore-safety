package payment

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
	"time"
)

func sendCharge(t *testing.T, client *http.Client, target, id string, body []byte) (*http.Response, error) {
	t.Helper()
	request, err := http.NewRequest(http.MethodPost, target, bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("X-Operation-ID", id)
	request.Header.Set("Idempotency-Key", id)
	return client.Do(request)
}

func observePayment(t *testing.T, client *http.Client, target, id, requestHash string, body []byte) *http.Response {
	t.Helper()
	request, err := http.NewRequest(http.MethodPost, target, bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("X-Operation-ID", id)
	request.Header.Set("X-Operation-Request-Hash", requestHash)
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	return response
}

func testDigest(value string) string {
	digest := sha256.Sum256([]byte(value))
	return hex.EncodeToString(digest[:])
}

func waitForStats(t *testing.T, service *Service, wantDeliveries, wantCommits int) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		stats := service.Stats()
		if stats.Deliveries == wantDeliveries && stats.Commits == wantCommits {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("stats did not reach deliveries=%d commits=%d: %+v", wantDeliveries, wantCommits, service.Stats())
}

func TestPaymentCommitsOnceAcrossLostResponseAndRestart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "payment.history")
	service, err := Open(path, true)
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(service.Handler())
	body := []byte(`{"order_id":"A-17","amount":42}`)
	if response, err := sendCharge(t, server.Client(), server.URL+"/v1/charge", "op-A-17", body); err == nil {
		response.Body.Close()
		t.Fatal("the injected lost response unexpectedly arrived")
	}
	response, err := sendCharge(t, server.Client(), server.URL+"/v1/charge", "op-A-17", body)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		data, _ := io.ReadAll(response.Body)
		t.Fatalf("retry status=%d body=%s", response.StatusCode, data)
	}
	var receipt map[string]any
	if err := json.NewDecoder(response.Body).Decode(&receipt); err != nil {
		t.Fatal(err)
	}
	if receipt["operation_id"] != "op-A-17" || receipt["outcome"] != "succeeded" {
		t.Fatalf("unexpected receipt: %v", receipt)
	}
	stats := service.Stats()
	if stats.Deliveries != 2 || stats.Commits != 1 || stats.Paths["/v1/charge"] != 2 {
		t.Fatalf("unexpected stats: %+v", stats)
	}
	server.Close()
	if err := service.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := Open(path, true)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	secondServer := httptest.NewServer(reopened.Handler())
	defer secondServer.Close()
	response, err = sendCharge(t, secondServer.Client(), secondServer.URL+"/v1/charge", "op-A-17", body)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusOK || reopened.Stats().Commits != 1 {
		t.Fatalf("reopened status=%d stats=%+v", response.StatusCode, reopened.Stats())
	}
}

func TestPaymentIdentityBindsEndpointAndBody(t *testing.T) {
	service, err := Open(filepath.Join(t.TempDir(), "payment.history"), false)
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	server := httptest.NewServer(service.Handler())
	defer server.Close()
	client := server.Client()
	body := []byte(`{"order_id":"A-17","amount":42}`)
	response, err := sendCharge(t, client, server.URL+"/v1/charge", "op-A-17", body)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	response, err = sendCharge(t, client, server.URL+"/v2/charge", "op-A-17", body)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusConflict || service.Stats().Commits != 1 {
		t.Fatalf("identity conflict status=%d stats=%+v", response.StatusCode, service.Stats())
	}
}

func TestAlwaysDropBeforeCommitNeverCreatesRecord(t *testing.T) {
	path := filepath.Join(t.TempDir(), "payment.history")
	service, err := OpenWithOptions(path, Options{AlwaysDropBeforeCommit: true})
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(service.Handler())
	body := []byte(`{"order_id":"A-17","amount":42}`)
	for range 2 {
		if response, err := sendCharge(t, server.Client(), server.URL+"/v1/charge", "op-A-17", body); err == nil {
			response.Body.Close()
			t.Fatal("the before-commit fault unexpectedly returned a response")
		}
	}
	if stats := service.Stats(); stats.Deliveries != 2 || stats.Commits != 0 {
		t.Fatalf("unexpected stats before restart: %+v", stats)
	}
	server.Close()
	if err := service.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := OpenWithOptions(path, Options{AlwaysDropBeforeCommit: true})
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	secondServer := httptest.NewServer(reopened.Handler())
	defer secondServer.Close()
	if response, err := sendCharge(t, secondServer.Client(), secondServer.URL+"/v1/charge", "op-A-17", body); err == nil {
		response.Body.Close()
		t.Fatal("the restarted before-commit fault unexpectedly returned a response")
	}
	if stats := reopened.Stats(); stats.Deliveries != 1 || stats.Commits != 0 {
		t.Fatalf("unexpected stats after restart: %+v", stats)
	}
}

func TestPaymentObserverReturnsSucceededOnlyForMatchingDurableWork(t *testing.T) {
	service, err := Open(filepath.Join(t.TempDir(), "payment.history"), false)
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	server := httptest.NewServer(service.Handler())
	defer server.Close()
	body := []byte(`{"order_id":"A-17","amount":42}`)
	response, err := sendCharge(t, server.Client(), server.URL+"/v1/charge", "op-A-17", body)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()

	frozenHash := testDigest("gateway-frozen-request")
	response = observePayment(t, server.Client(), server.URL+"/v1/query", "op-A-17", frozenHash, body)
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		data, _ := io.ReadAll(response.Body)
		t.Fatalf("observation status=%d body=%s", response.StatusCode, data)
	}
	var got operationObservationV1
	if err := json.NewDecoder(response.Body).Decode(&got); err != nil {
		t.Fatal(err)
	}
	if got.Schema != 1 || got.OperationID != "op-A-17" || got.RequestHash != frozenHash ||
		got.Outcome != "succeeded" || !validDigest(got.FactHash) || got.RemoteReference != "payment/op-A-17" {
		t.Fatalf("unexpected observation: %+v", got)
	}

	mismatch := observePayment(t, server.Client(), server.URL+"/v1/query", "op-A-17", frozenHash,
		[]byte(`{"order_id":"A-17","amount":43}`))
	mismatch.Body.Close()
	if mismatch.StatusCode != http.StatusConflict {
		t.Fatalf("mismatched body status=%d, want 409", mismatch.StatusCode)
	}

	missing := observePayment(t, server.Client(), server.URL+"/v1/query", "op-missing", frozenHash, body)
	defer missing.Body.Close()
	if missing.StatusCode != http.StatusOK {
		t.Fatalf("missing observation status=%d", missing.StatusCode)
	}
	got = operationObservationV1{}
	if err := json.NewDecoder(missing.Body).Decode(&got); err != nil {
		t.Fatal(err)
	}
	if got.Outcome != "inconclusive" || got.FactHash != "" || got.OperationID != "op-missing" || got.RequestHash != frozenHash {
		t.Fatalf("unexpected missing observation: %+v", got)
	}
}

func TestNonIdempotentPaymentPersistsEveryDeliveryAndObserverRefusesDuplicates(t *testing.T) {
	path := filepath.Join(t.TempDir(), "payment.history")
	service, err := OpenWithOptions(path, Options{NonIdempotent: true})
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(service.Handler())
	body := []byte(`{"order_id":"A-17","amount":42}`)
	var references []string
	for range 2 {
		response, err := sendCharge(t, server.Client(), server.URL+"/v1/charge", "op-A-17", body)
		if err != nil {
			t.Fatal(err)
		}
		var receipt struct {
			RemoteReference string `json:"remote_reference"`
		}
		if err := json.NewDecoder(response.Body).Decode(&receipt); err != nil {
			response.Body.Close()
			t.Fatal(err)
		}
		response.Body.Close()
		references = append(references, receipt.RemoteReference)
	}
	if references[0] == references[1] {
		t.Fatalf("independent durable charges share a reference: %v", references)
	}
	if stats := service.Stats(); stats.Deliveries != 2 || stats.Commits != 2 {
		t.Fatalf("non-idempotent stats: %+v", stats)
	}
	response := observePayment(t, server.Client(), server.URL+"/v1/query", "op-A-17", testDigest("frozen"), body)
	var got operationObservationV1
	if err := json.NewDecoder(response.Body).Decode(&got); err != nil {
		response.Body.Close()
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusOK || got.Outcome != "inconclusive" || got.FactHash != "" ||
		got.RemoteReference != "payment/op-A-17/count=2" {
		t.Fatalf("duplicate observation status=%d body=%+v", response.StatusCode, got)
	}

	server.Close()
	if err := service.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := OpenWithOptions(path, Options{NonIdempotent: true})
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if stats := reopened.Stats(); stats.Commits != 2 {
		t.Fatalf("restart lost duplicate durable charges: %+v", stats)
	}
}

func TestHoldFaultsExposeCommitBoundaryAndWaitForCancellation(t *testing.T) {
	for _, test := range []struct {
		name        string
		options     Options
		wantCommits int
		release     bool
	}{
		{name: "before commit", options: Options{HoldBeforeCommit: true}, wantCommits: 0},
		{name: "after commit", options: Options{HoldAfterCommit: true}, wantCommits: 1, release: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			service, err := OpenWithOptions(filepath.Join(t.TempDir(), "payment.history"), test.options)
			if err != nil {
				t.Fatal(err)
			}
			defer service.Close()
			server := httptest.NewServer(service.Handler())
			defer server.Close()
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			request, err := http.NewRequestWithContext(ctx, http.MethodPost, server.URL+"/v1/charge",
				bytes.NewReader([]byte(`{"order_id":"A-17","amount":42}`)))
			if err != nil {
				t.Fatal(err)
			}
			request.Header.Set("X-Operation-ID", "op-A-17")
			request.Header.Set("Idempotency-Key", "op-A-17")
			done := make(chan error, 1)
			go func() {
				response, err := server.Client().Do(request)
				if response != nil {
					response.Body.Close()
				}
				done <- err
			}()
			waitForStats(t, service, 1, test.wantCommits)
			select {
			case err := <-done:
				t.Fatalf("held request returned before cancellation: %v", err)
			default:
			}
			if test.release {
				if !service.ReleaseHeldAfterCommit() || service.ReleaseHeldAfterCommit() {
					t.Fatal("post-commit hold did not release exactly once")
				}
			} else {
				cancel()
			}
			select {
			case err := <-done:
				if test.release && err != nil {
					t.Fatalf("released request failed: %v", err)
				}
				if !test.release && err == nil {
					t.Fatal("held request returned an HTTP response")
				}
			case <-time.After(2 * time.Second):
				t.Fatal("held request did not exit after connection cancellation")
			}
		})
	}
}

func TestPaymentResponseLossModesAreExclusive(t *testing.T) {
	_, err := OpenWithOptions(filepath.Join(t.TempDir(), "payment.history"), Options{
		DropFirstResponse: true, HoldAfterCommit: true,
	})
	if err == nil {
		t.Fatal("mutually exclusive response-loss modes were accepted")
	}
}

func TestCompletionEndpointUsesIndependentReferencePrefix(t *testing.T) {
	path := filepath.Join(t.TempDir(), "completion.history")
	service, err := OpenWithOptions(path, Options{
		ReferencePrefix: "completion",
	})
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	server := httptest.NewServer(service.Handler())
	defer server.Close()
	response, err := sendCharge(t, server.Client(), server.URL+"/v1/complete", "op-finish-A-17",
		[]byte(`{"order_id":"A-17","status":"DELIVERED"}`))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	var receipt struct {
		RemoteReference string `json:"remote_reference"`
	}
	if err := json.NewDecoder(response.Body).Decode(&receipt); err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != http.StatusOK || receipt.RemoteReference != "completion/op-finish-A-17" {
		t.Fatalf("completion status=%d reference=%q", response.StatusCode, receipt.RemoteReference)
	}
	if stats := service.Stats(); stats.Deliveries != 1 || stats.Commits != 1 || stats.Paths["/v1/complete"] != 1 {
		t.Fatalf("completion stats: %+v", stats)
	}
	server.Close()
	if err := service.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := OpenWithOptions(path, Options{ReferencePrefix: "completion"})
	if err != nil {
		t.Fatalf("reopen durable completion state: %v", err)
	}
	defer reopened.Close()
	if stats := reopened.Stats(); stats.Deliveries != 0 || stats.Commits != 1 {
		t.Fatalf("reopened completion stats: %+v", stats)
	}
}

func TestReferencePrefixIsValidated(t *testing.T) {
	_, err := OpenWithOptions(filepath.Join(t.TempDir(), "payment.history"), Options{ReferencePrefix: "../bad"})
	if err == nil {
		t.Fatal("invalid remote-reference prefix was accepted")
	}
}
