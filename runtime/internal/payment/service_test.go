package payment

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
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
