package order

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"sync/atomic"
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

func TestProxyReleaseSubmitsOnlyLogicalEffect(t *testing.T) {
	type observation struct {
		method  string
		path    string
		query   string
		headers http.Header
		body    []byte
	}
	observed := make(chan observation, 1)
	proxy := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Error(err)
			return
		}
		observed <- observation{
			method: request.Method, path: request.URL.Path, query: request.URL.RawQuery,
			headers: request.Header.Clone(), body: body,
		}
		writeJSON(writer, http.StatusConflict, map[string]any{
			"error": "effect outcome is not safely settled", "phase": "unknown",
		})
	}))
	defer proxy.Close()

	config := Config{Version: "v2", EffectProxyURL: proxy.URL, EffectRoute: "payment"}
	service, err := NewProxy(config, proxy.Client())
	if err != nil {
		t.Fatal(err)
	}
	recorder := submitOrder(service.Handler(), `{"order_id":"A-17","amount":42}`)
	if recorder.Code != http.StatusConflict {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.Bytes())
	}
	request := <-observed
	if request.method != http.MethodPost || request.path != "/v1/effects/payment" || request.query != "" {
		t.Fatalf("unexpected proxy request: method=%s path=%s query=%q", request.method, request.path, request.query)
	}
	if request.headers.Get("X-Safe-Change-Call-ID") != "order/A-17/payment" || request.headers.Get("Content-Type") != "application/json" {
		t.Fatalf("missing logical effect headers: %#v", request.headers)
	}
	for name := range request.headers {
		if name != "X-Safe-Change-Call-Id" && name != "Content-Type" {
			t.Fatalf("proxy request gained header %q: %#v", name, request.headers)
		}
	}
	if request.headers.Get("Authorization") != "" || bytes.Contains(request.body, []byte("charge-v2")) || bytes.Contains(request.body, []byte("/v2/charge")) {
		t.Fatalf("proxy request leaked legacy authority: headers=%#v body=%s", request.headers, request.body)
	}
	var paymentFields map[string]json.RawMessage
	if err := json.Unmarshal(request.body, &paymentFields); err != nil {
		t.Fatal(err)
	}
	if len(paymentFields) != 2 || paymentFields["order_id"] == nil || paymentFields["amount"] == nil {
		t.Fatalf("proxy payment body gained authority fields: %s", request.body)
	}
	var payment paymentRequest
	if err := json.Unmarshal(request.body, &payment); err != nil {
		t.Fatal(err)
	}
	if payment != (paymentRequest{OrderID: "A-17", Amount: 42}) {
		t.Fatalf("unexpected payment body: %+v", payment)
	}

	var response map[string]json.RawMessage
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	if len(response) != 4 || string(response["release_version"]) != `"v2"` ||
		string(response["requested_route"]) != `"payment"` || string(response["proxy"]) != "true" {
		t.Fatalf("unexpected proxy response: %s", recorder.Body.Bytes())
	}
	if _, exists := response["requested_kind"]; exists {
		t.Fatalf("proxy response exposed requested_kind: %s", recorder.Body.Bytes())
	}
	if _, exists := response["requested_target"]; exists {
		t.Fatalf("proxy response exposed requested_target: %s", recorder.Body.Bytes())
	}
}

func TestLegacyResponseWireIsUnchanged(t *testing.T) {
	control := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		_, _ = writer.Write([]byte(`{"ok":true}`))
	}))
	defer control.Close()
	service, err := New(Config{Version: "v1", Kind: "charge-v1", Target: "http://payment/v1/charge"},
		control.URL, testToken(), control.Client())
	if err != nil {
		t.Fatal(err)
	}
	recorder := submitOrder(service.Handler(), `{"order_id":"A-17","amount":42}`)
	want := "{\"release_version\":\"v1\",\"requested_kind\":\"charge-v1\",\"requested_target\":\"http://payment/v1/charge\",\"runtime\":{\"ok\":true}}\n"
	if recorder.Code != http.StatusOK || recorder.Body.String() != want {
		t.Fatalf("legacy response changed: status=%d body=%q", recorder.Code, recorder.Body.String())
	}
}

func TestLoadConfigSelectsExactlyOneMode(t *testing.T) {
	proxyURL := "http://effect-proxy.internal:8788"
	validPath := writeRelease(t, fmt.Sprintf(`{"version":"v2","effect_proxy_url":%q,"effect_route":"payment"}`, proxyURL))
	config, err := LoadConfig(validPath)
	if err != nil {
		t.Fatal(err)
	}
	if !config.UsesEffectProxy() || config.EffectProxyURL != proxyURL || config.EffectRoute != "payment" {
		t.Fatalf("unexpected config: %+v", config)
	}

	tests := []struct {
		name string
		body string
	}{
		{"mixed modes", fmt.Sprintf(`{"version":"v2","kind":"charge-v2","target":"http://payment/v2/charge","effect_proxy_url":%q,"effect_route":"payment"}`, proxyURL)},
		{"missing route", fmt.Sprintf(`{"version":"v2","effect_proxy_url":%q}`, proxyURL)},
		{"missing URL", `{"version":"v2","effect_route":"payment"}`},
		{"URL path", `{"version":"v2","effect_proxy_url":"http://proxy/internal","effect_route":"payment"}`},
		{"URL query", `{"version":"v2","effect_proxy_url":"http://proxy?target=payment","effect_route":"payment"}`},
		{"URL credentials", `{"version":"v2","effect_proxy_url":"http://user:password@proxy","effect_route":"payment"}`},
		{"route slash", fmt.Sprintf(`{"version":"v2","effect_proxy_url":%q,"effect_route":"payments/v2"}`, proxyURL)},
		{"route leading punctuation", fmt.Sprintf(`{"version":"v2","effect_proxy_url":%q,"effect_route":"-payment"}`, proxyURL)},
		{"route escaping", fmt.Sprintf(`{"version":"v2","effect_proxy_url":%q,"effect_route":"payment%%2fadmin"}`, proxyURL)},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if _, err := LoadConfig(writeRelease(t, test.body)); err == nil {
				t.Fatal("unsafe or ambiguous release config was accepted")
			}
		})
	}
}

func TestConstructorsRejectMixedModes(t *testing.T) {
	mixed := Config{
		Version: "v2", Kind: "charge-v2", Target: "http://payment/v2/charge",
		EffectProxyURL: "http://effect-proxy:8788", EffectRoute: "payment",
	}
	if _, err := New(mixed, "http://control:8787", testToken(), nil); err == nil {
		t.Fatal("legacy constructor accepted proxy authority")
	}
	if _, err := NewProxy(mixed, nil); err == nil {
		t.Fatal("proxy constructor accepted legacy authority")
	}
}

func TestProxyRefusesRedirects(t *testing.T) {
	var destinationCalls atomic.Int32
	destination := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		destinationCalls.Add(1)
		writeJSON(writer, http.StatusOK, map[string]bool{"followed": true})
	}))
	defer destination.Close()
	redirect := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writer.Header().Set("Location", destination.URL)
		writeJSON(writer, http.StatusTemporaryRedirect, map[string]bool{"redirect": true})
	}))
	defer redirect.Close()
	service, err := NewProxy(Config{Version: "v2", EffectProxyURL: redirect.URL, EffectRoute: "payment"}, redirect.Client())
	if err != nil {
		t.Fatal(err)
	}
	recorder := submitOrder(service.Handler(), `{"order_id":"A-17","amount":42}`)
	if recorder.Code != http.StatusTemporaryRedirect || destinationCalls.Load() != 0 {
		t.Fatalf("redirect was followed: status=%d destination_calls=%d", recorder.Code, destinationCalls.Load())
	}
}

func TestProxyTransportIgnoresAmbientProxy(t *testing.T) {
	ambient := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writeJSON(writer, http.StatusOK, map[string]bool{"ambient": true})
	}))
	defer ambient.Close()
	t.Setenv("HTTP_PROXY", ambient.URL)
	t.Setenv("HTTPS_PROXY", ambient.URL)
	t.Setenv("http_proxy", ambient.URL)
	t.Setenv("https_proxy", ambient.URL)
	t.Setenv("NO_PROXY", "")
	t.Setenv("no_proxy", "")
	service, err := NewProxy(Config{
		Version: "v2", EffectProxyURL: "http://effect-proxy.invalid", EffectRoute: "payment",
	}, nil)
	if err != nil {
		t.Fatal(err)
	}
	transport, ok := service.client.Transport.(*http.Transport)
	if !ok || transport.Proxy != nil {
		t.Fatalf("proxy transport retained ambient proxy support: %#v", service.client.Transport)
	}
}

func TestProxyRejectsMalformedAndOversizedResponses(t *testing.T) {
	tests := []struct {
		name string
		body []byte
	}{
		{"malformed", []byte(`{"phase":`)},
		{"multiple values", []byte(`{} {}`)},
		{"oversized", bytes.Repeat([]byte(" "), maxBodyBytes+1)},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			proxy := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
				writer.WriteHeader(http.StatusTeapot)
				_, _ = writer.Write(test.body)
			}))
			defer proxy.Close()
			service, err := NewProxy(Config{Version: "v2", EffectProxyURL: proxy.URL, EffectRoute: "payment"}, proxy.Client())
			if err != nil {
				t.Fatal(err)
			}
			recorder := submitOrder(service.Handler(), `{"order_id":"A-17","amount":42}`)
			if recorder.Code != http.StatusBadGateway {
				t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.Bytes())
			}
		})
	}
}

func TestProxyRejectsUnsafeCallIdentityBeforeNetwork(t *testing.T) {
	var calls atomic.Int32
	proxy := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		writeJSON(writer, http.StatusOK, map[string]bool{"ok": true})
	}))
	defer proxy.Close()
	service, err := NewProxy(Config{Version: "v2", EffectProxyURL: proxy.URL, EffectRoute: "payment"}, proxy.Client())
	if err != nil {
		t.Fatal(err)
	}
	recorder := submitOrder(service.Handler(), "{\"order_id\":\"A\\nB\",\"amount\":42}")
	if recorder.Code != http.StatusBadRequest || calls.Load() != 0 {
		t.Fatalf("unsafe call identity reached proxy: status=%d calls=%d", recorder.Code, calls.Load())
	}
	recorder = submitOrder(service.Handler(), fmt.Sprintf(
		`{"order_id":%q,"amount":42}`, strings.Repeat("A", maxCallIDBytes),
	))
	if recorder.Code != http.StatusBadRequest || calls.Load() != 0 {
		t.Fatalf("oversized call identity reached proxy: status=%d calls=%d", recorder.Code, calls.Load())
	}
}

func TestProxyConcurrentRequestsKeepIdentityBoundToBody(t *testing.T) {
	const requestCount = 64
	errorsSeen := make(chan error, requestCount)
	seen := make(map[string]bool, requestCount)
	var seenMu sync.Mutex
	proxy := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var payment paymentRequest
		if err := json.NewDecoder(request.Body).Decode(&payment); err != nil {
			errorsSeen <- err
			writeJSON(writer, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		wantCallID := "order/" + payment.OrderID + "/payment"
		if got := request.Header.Get("X-Safe-Change-Call-ID"); got != wantCallID {
			errorsSeen <- fmt.Errorf("call ID %q does not match body %+v", got, payment)
		}
		seenMu.Lock()
		if seen[wantCallID] {
			errorsSeen <- fmt.Errorf("duplicate call ID %q", wantCallID)
		}
		seen[wantCallID] = true
		seenMu.Unlock()
		writeJSON(writer, http.StatusOK, map[string]string{"phase": "succeeded"})
	}))
	defer proxy.Close()
	service, err := NewProxy(Config{Version: "v2", EffectProxyURL: proxy.URL, EffectRoute: "payment"}, proxy.Client())
	if err != nil {
		t.Fatal(err)
	}
	handler := service.Handler()
	var wait sync.WaitGroup
	for index := 0; index < requestCount; index++ {
		wait.Add(1)
		go func(index int) {
			defer wait.Done()
			body := fmt.Sprintf(`{"order_id":"A-%d","amount":%d}`, index, index+1)
			recorder := submitOrder(handler, body)
			if recorder.Code != http.StatusOK {
				errorsSeen <- fmt.Errorf("request %d: status=%d body=%s", index, recorder.Code, recorder.Body.Bytes())
			}
		}(index)
	}
	wait.Wait()
	close(errorsSeen)
	for err := range errorsSeen {
		t.Error(err)
	}
	seenMu.Lock()
	defer seenMu.Unlock()
	if len(seen) != requestCount {
		t.Fatalf("observed %d unique calls, want %d", len(seen), requestCount)
	}
}

func submitOrder(handler http.Handler, body string) *httptest.ResponseRecorder {
	request := httptest.NewRequest(http.MethodPost, "/v1/orders", strings.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)
	return recorder
}

func writeRelease(t *testing.T, body string) string {
	t.Helper()
	path := t.TempDir() + "/release.json"
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func stringsReader(value string) io.Reader { return strings.NewReader(value) }

func testToken() string { return "01234567890123456789012345678901" }
