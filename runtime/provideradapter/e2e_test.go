package provideradapter_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/provideradapter"
)

type providerRecord struct {
	FactHash        string `json:"fact_hash"`
	RemoteReference string `json:"remote_reference"`
}

type durableFakeProvider struct {
	mu         sync.Mutex
	secret     string
	file       *os.File
	records    map[string]providerRecord
	deliveries int
	commits    int
	queries    int
	dropNext   bool
}

func openDurableFakeProvider(t *testing.T, secret string) *durableFakeProvider {
	t.Helper()
	file, err := os.OpenFile(
		filepath.Join(t.TempDir(), "provider.commits"),
		os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600,
	)
	if err != nil {
		t.Fatal(err)
	}
	provider := &durableFakeProvider{
		secret: secret, file: file, records: make(map[string]providerRecord), dropNext: true,
	}
	t.Cleanup(func() {
		if err := file.Close(); err != nil {
			t.Error(err)
		}
	})
	return provider
}

func (provider *durableFakeProvider) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /apply", provider.apply)
	mux.HandleFunc("POST /query", provider.query)
	return mux
}

func (provider *durableFakeProvider) apply(writer http.ResponseWriter, request *http.Request) {
	if request.Header.Get("Authorization") != "Bearer "+provider.secret {
		http.Error(writer, "provider credential required", http.StatusUnauthorized)
		return
	}
	operationID := request.Header.Get(provideradapter.HeaderIdempotencyKey)
	if operationID == "" {
		http.Error(writer, "idempotency key required", http.StatusBadRequest)
		return
	}
	body, err := io.ReadAll(request.Body)
	if err != nil {
		http.Error(writer, "read provider request", http.StatusBadRequest)
		return
	}
	factHash := provideradapter.HashFact(append([]byte("charged\x00"+operationID+"\x00"), body...))
	record := providerRecord{
		FactHash: factHash, RemoteReference: "provider/charge/" + operationID,
	}

	provider.mu.Lock()
	provider.deliveries++
	prior, exists := provider.records[operationID]
	if exists && prior != record {
		provider.mu.Unlock()
		http.Error(writer, "idempotency key conflict", http.StatusConflict)
		return
	}
	if !exists {
		encoded, err := json.Marshal(struct {
			OperationID string         `json:"operation_id"`
			Record      providerRecord `json:"record"`
		}{OperationID: operationID, Record: record})
		if err == nil {
			_, err = provider.file.Write(append(encoded, '\n'))
		}
		if err == nil {
			err = provider.file.Sync()
		}
		if err != nil {
			provider.mu.Unlock()
			http.Error(writer, "persist provider commit", http.StatusInternalServerError)
			return
		}
		provider.records[operationID] = record
		provider.commits++
	}
	drop := provider.dropNext
	provider.dropNext = false
	provider.mu.Unlock()

	if drop {
		connection, _, err := writer.(http.Hijacker).Hijack()
		if err != nil {
			http.Error(writer, "drop provider response", http.StatusInternalServerError)
			return
		}
		_ = connection.Close()
		return
	}
	writeProviderJSON(writer, http.StatusOK, record)
}

func (provider *durableFakeProvider) query(writer http.ResponseWriter, request *http.Request) {
	if request.Header.Get("Authorization") != "Bearer "+provider.secret {
		http.Error(writer, "provider credential required", http.StatusUnauthorized)
		return
	}
	operationID := request.Header.Get(provideradapter.HeaderOperationID)
	provider.mu.Lock()
	provider.queries++
	record, exists := provider.records[operationID]
	provider.mu.Unlock()
	writeProviderJSON(writer, http.StatusOK, struct {
		Found bool `json:"found"`
		providerRecord
	}{Found: exists, providerRecord: record})
}

func (provider *durableFakeProvider) counts() (deliveries, commits, queries int) {
	provider.mu.Lock()
	defer provider.mu.Unlock()
	return provider.deliveries, provider.commits, provider.queries
}

func writeProviderJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}

type recoveringProviderDriver struct {
	secret string
	base   string
	client *http.Client
}

func (driver recoveringProviderDriver) Execute(ctx context.Context, effect provideradapter.Effect) (provideradapter.Result, error) {
	request, err := provideradapter.NewSingleAttemptRequest(ctx, http.MethodPost, driver.base+"/apply", effect.Body)
	if err != nil {
		return provideradapter.Result{}, err
	}
	request.Header.Set("Authorization", "Bearer "+driver.secret)
	request.Header.Set(provideradapter.HeaderIdempotencyKey, effect.IdempotencyKey)
	if effect.ContentType != "" {
		request.Header.Set("Content-Type", effect.ContentType)
	}
	record, err := driver.call(request)
	if err != nil {
		return provideradapter.Result{}, err
	}
	return provideradapter.Result{
		Outcome: provideradapter.Succeeded, FactHash: record.FactHash,
		RemoteReference: record.RemoteReference,
	}, nil
}

func (driver recoveringProviderDriver) Observe(ctx context.Context, query provideradapter.Query) (provideradapter.Result, error) {
	request, err := provideradapter.NewSingleAttemptRequest(ctx, http.MethodPost, driver.base+"/query", query.Body)
	if err != nil {
		return provideradapter.Result{}, err
	}
	request.Header.Set("Authorization", "Bearer "+driver.secret)
	request.Header.Set(provideradapter.HeaderOperationID, query.OperationID)
	response, err := driver.client.Do(request)
	if err != nil {
		return provideradapter.Result{}, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return provideradapter.Result{}, errors.New("provider query was not successful")
	}
	var result struct {
		Found bool `json:"found"`
		providerRecord
	}
	decoder := json.NewDecoder(io.LimitReader(response.Body, 64<<10))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&result); err != nil {
		return provideradapter.Result{}, err
	}
	if !result.Found {
		return provideradapter.Result{Outcome: provideradapter.Inconclusive}, nil
	}
	return provideradapter.Result{
		Outcome: provideradapter.Succeeded, FactHash: result.FactHash,
		RemoteReference: result.RemoteReference,
	}, nil
}

func (driver recoveringProviderDriver) call(request *http.Request) (providerRecord, error) {
	response, err := driver.client.Do(request)
	if err != nil {
		return providerRecord{}, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return providerRecord{}, errors.New("provider effect was not successful")
	}
	var record providerRecord
	decoder := json.NewDecoder(io.LimitReader(response.Body, 64<<10))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&record); err != nil {
		return providerRecord{}, err
	}
	return record, nil
}

func TestGatewayRecoversProviderCommitWithoutPersistingProviderSecret(t *testing.T) {
	const providerSecret = "provider-live-secret-never-in-runtime-history"
	operationID := "op-" + strings.Repeat("d", 64)
	requestBody := []byte(`{"invoice":"A-17","amount":4200}`)
	factHash := provideradapter.HashFact(append([]byte("charged\x00"+operationID+"\x00"), requestBody...))

	provider := openDurableFakeProvider(t, providerSecret)
	providerServer := httptest.NewServer(provider.Handler())
	defer providerServer.Close()
	providerClient, err := provideradapter.NewHTTPClient(nil, 2*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	adapter, err := provideradapter.NewHandler(provideradapter.Config{
		EffectPath: "/v1/payment", QueryPath: "/v1/payment/query",
	}, recoveringProviderDriver{
		secret: providerSecret, base: providerServer.URL, client: providerClient,
	})
	if err != nil {
		t.Fatal(err)
	}
	adapterServer := httptest.NewServer(adapter)
	defer adapterServer.Close()

	historyPath := filepath.Join(t.TempDir(), "runtime.history")
	runtimeControl, err := control.Open(historyPath)
	if err != nil {
		t.Fatal(err)
	}
	defer runtimeControl.Close()
	requirement := kernel.Requirement{
		ID:         "provider-adapter-e2e",
		Results:    map[string]uint32{"charged": 1},
		Capacities: map[string]uint32{"payment_attempt": 1},
		Kinds: map[string]kernel.KindSpec{
			"charge": {
				Costs: map[string]uint32{"payment_attempt": 1}, Produces: map[string]uint32{"charged": 1},
				RetrySafe: false, Queryable: true,
				Target: adapterServer.URL + "/v1/payment", Method: http.MethodPost,
				ResponseClassifier: gateway.ResponseReceiptV1,
				QueryTarget:        adapterServer.URL + "/v1/payment/query", QueryMethod: http.MethodPost,
				QueryClassifier: gateway.OperationObservationV1,
			},
		},
	}
	certificate, err := runtimeControl.Compile(requirement)
	if err != nil {
		t.Fatal(err)
	}
	if err := runtimeControl.Activate(certificate); err != nil {
		t.Fatal(err)
	}
	runtimeTransport := &http.Transport{Proxy: nil}
	defer runtimeTransport.CloseIdleConnections()
	runtimeGateway, err := gateway.New(runtimeControl, &http.Client{
		Transport: runtimeTransport, Timeout: 2 * time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	effect := gateway.Request{
		ID: operationID, Domain: "payments", Kind: "charge", Method: http.MethodPost,
		URL:     adapterServer.URL + "/v1/payment",
		Headers: map[string]string{"Content-Type": "application/json"}, Body: requestBody,
	}

	first, err := runtimeGateway.Execute(context.Background(), effect)
	if !errors.Is(err, gateway.ErrOutcomeUnknown) || first.Phase != kernel.Unknown {
		t.Fatalf("lost response outcome = %+v, error = %v", first, err)
	}
	deliveries, commits, queries := provider.counts()
	if deliveries != 1 || commits != 1 || queries != 0 {
		t.Fatalf("after loss: deliveries=%d commits=%d queries=%d", deliveries, commits, queries)
	}

	recovered, err := runtimeGateway.Execute(context.Background(), effect)
	if err != nil {
		t.Fatal(err)
	}
	if recovered.Phase != kernel.Succeeded || !recovered.RecoveredByQuery || recovered.ResultHash != factHash {
		t.Fatalf("recovered outcome = %+v, want fact hash %s", recovered, factHash)
	}
	deliveries, commits, queries = provider.counts()
	if deliveries != 1 || commits != 1 || queries != 1 {
		t.Fatalf("after recovery: deliveries=%d commits=%d queries=%d", deliveries, commits, queries)
	}

	historyBytes, err := os.ReadFile(historyPath)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(historyBytes, []byte(providerSecret)) {
		t.Fatal("provider credential crossed the adapter boundary into History")
	}
}
