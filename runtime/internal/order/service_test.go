package order

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestCurrentReleaseSubmitsStableWorkIdentity(t *testing.T) {
	var observed executeRequest
	control := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.Header.Get("Authorization") != "Bearer "+testToken() {
			t.Error("missing Operation credential")
		}
		data, err := io.ReadAll(request.Body)
		if err != nil {
			t.Error(err)
			return
		}
		if err := json.Unmarshal(data, &observed); err != nil {
			t.Error(err)
			return
		}
		writeJSON(writer, http.StatusOK, map[string]any{
			"operation_id": "op-1", "phase": "succeeded", "reused": false,
		})
	}))
	defer control.Close()
	config := Config{Version: "v2", Kind: "charge-v2", Target: "http://payment:8081/v2/charge"}
	service, err := New(config, control.URL, testToken(), control.Client())
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(service.Handler())
	defer server.Close()
	response, err := http.Post(server.URL+"/v1/orders", "application/json",
		stringsReader(`{"order_id":"A-17","amount":42}`))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		data, _ := io.ReadAll(response.Body)
		t.Fatalf("status=%d body=%s", response.StatusCode, data)
	}
	if observed.CallID != "order/A-17/payment" || observed.Kind != config.Kind || observed.URL != config.Target {
		t.Fatalf("unexpected execute request: %+v", observed)
	}
	var payment paymentRequest
	if err := json.Unmarshal(observed.Body, &payment); err != nil {
		t.Fatal(err)
	}
	if payment.OrderID != "A-17" || payment.Amount != 42 {
		t.Fatalf("unexpected payment body: %+v", payment)
	}
	var submitted submitResponse
	if err := json.NewDecoder(response.Body).Decode(&submitted); err != nil {
		t.Fatal(err)
	}
	if submitted.ReleaseVersion != "v2" || submitted.RequestedKind != "charge-v2" {
		t.Fatalf("unexpected response: %+v", submitted)
	}
}

func TestControlUnknownIsPreserved(t *testing.T) {
	control := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writeJSON(writer, http.StatusConflict, map[string]any{
			"outcome": map[string]any{"phase": "unknown"}, "error": "outcome is unknown",
		})
	}))
	defer control.Close()
	service, err := New(Config{Version: "v1", Kind: "charge-v1", Target: "http://payment/v1/charge"},
		control.URL, testToken(), control.Client())
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(service.Handler())
	defer server.Close()
	response, err := http.Post(server.URL+"/v1/orders", "application/json",
		stringsReader(`{"order_id":"A-17","amount":42}`))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusConflict {
		t.Fatalf("status=%d", response.StatusCode)
	}
	var submitted submitResponse
	if err := json.NewDecoder(response.Body).Decode(&submitted); err != nil {
		t.Fatal(err)
	}
	var runtime struct {
		Outcome struct {
			Phase string `json:"phase"`
		} `json:"outcome"`
	}
	if err := json.Unmarshal(submitted.Runtime, &runtime); err != nil {
		t.Fatal(err)
	}
	if runtime.Outcome.Phase != "unknown" {
		t.Fatalf("runtime response=%s", submitted.Runtime)
	}
}

func stringsReader(value string) io.Reader { return strings.NewReader(value) }

func testToken() string { return "01234567890123456789012345678901" }
