package postgresoutbox_test

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/postgresoutbox"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/provideradapter"
	"github.com/jackc/pgx/v5/pgxpool"
)

const integrationDSNEnvironment = "POSTGRES_OUTBOX_TEST_DSN"

func TestPostgresOutboxIntegration(t *testing.T) {
	dsn := os.Getenv(integrationDSNEnvironment)
	if dsn == "" {
		t.Skipf("set %s to run the real PostgreSQL integration test", integrationDSNEnvironment)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	driver, err := postgresoutbox.Open(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer driver.Close()

	t.Run("concurrent identical execute commits one exact row", func(t *testing.T) {
		operationID := integrationOperationID(t)
		effect := provideradapter.Effect{
			OperationID: operationID, IdempotencyKey: operationID,
			ContentType: "application/json", Body: []byte(`{"job":"concurrent"}`),
		}
		const callers = 32
		results := make(chan provideradapter.Result, callers)
		errorsFound := make(chan error, callers)
		var workers sync.WaitGroup
		for range callers {
			workers.Add(1)
			go func() {
				defer workers.Done()
				result, executeErr := driver.Execute(ctx, effect)
				results <- result
				errorsFound <- executeErr
			}()
		}
		workers.Wait()
		close(results)
		close(errorsFound)
		for executeErr := range errorsFound {
			if executeErr != nil {
				t.Fatal(executeErr)
			}
		}
		var first provideradapter.Result
		for result := range results {
			if first == (provideradapter.Result{}) {
				first = result
			}
			if result != first || result.Outcome != provideradapter.Succeeded {
				t.Fatalf("concurrent Execute result = %+v, first = %+v", result, first)
			}
		}
		if count := countRows(t, ctx, dsn, operationID); count != 1 {
			t.Fatalf("durable rows = %d, want 1", count)
		}

		conflicting := effect
		conflicting.Body = []byte(`{"job":"different"}`)
		if _, err := driver.Execute(ctx, conflicting); !errors.Is(err, postgresoutbox.ErrConflict) {
			t.Fatalf("conflicting Execute error = %v, want ErrConflict", err)
		}
	})

	t.Run("lost response recovers by observation after control restart", func(t *testing.T) {
		operationID := integrationOperationID(t)
		body := []byte(`{"job":"recover-after-loss"}`)
		effectPath := "/v1/outbox/effects"
		observationPath := "/v1/outbox/observations"
		adapter, err := provideradapter.NewHandler(provideradapter.Config{
			EffectPath: effectPath, QueryPath: observationPath,
		}, driver)
		if err != nil {
			t.Fatal(err)
		}
		loss := &responseLossBoundary{
			next: adapter, effectPath: effectPath, observationPath: observationPath,
		}
		adapterServer := httptest.NewServer(loss)
		defer adapterServer.Close()

		historyPath := filepath.Join(t.TempDir(), "runtime.history")
		firstControl := openActivatedControl(
			t, historyPath, adapterServer.URL, effectPath, observationPath,
		)
		firstGateway := openGateway(t, firstControl)
		request := gateway.Request{
			ID: operationID, Domain: "postgres-outbox", Kind: "enqueue",
			Method: http.MethodPost, URL: adapterServer.URL + effectPath,
			Headers: map[string]string{"Content-Type": "application/json"}, Body: body,
		}

		first, err := firstGateway.Execute(context.Background(), request)
		if !errors.Is(err, gateway.ErrOutcomeUnknown) || first.Phase != kernel.Unknown {
			t.Fatalf("lost response outcome = %+v, error = %v", first, err)
		}
		if err := firstControl.Close(); err != nil {
			t.Fatal(err)
		}

		secondControl, err := control.Open(historyPath)
		if err != nil {
			t.Fatal(err)
		}
		defer secondControl.Close()
		secondGateway := openGateway(t, secondControl)
		recovered, err := secondGateway.Execute(context.Background(), request)
		if err != nil {
			t.Fatal(err)
		}
		wantFactHash := postgresoutbox.FactHash(operationID, "application/json", body)
		if recovered.Phase != kernel.Succeeded || !recovered.RecoveredByQuery ||
			recovered.ResultHash != wantFactHash {
			t.Fatalf("recovered outcome = %+v, want fact %s", recovered, wantFactHash)
		}
		if effects, observations, dropped := loss.counts(); effects != 1 || observations != 1 || dropped != 1 {
			t.Fatalf(
				"adapter requests: effects=%d observations=%d dropped=%d, want 1, 1, and 1",
				effects, observations, dropped,
			)
		}
		if count := countRows(t, ctx, dsn, operationID); count != 1 {
			t.Fatalf("durable rows = %d, want 1", count)
		}

		history, err := os.ReadFile(historyPath)
		if err != nil {
			t.Fatal(err)
		}
		if bytes.Contains(history, []byte(dsn)) ||
			bytes.Contains(history, []byte("postgres-outbox-integration-password")) {
			t.Fatal("PostgreSQL credential crossed the adapter boundary into History")
		}
	})

	t.Run("missing observation is inconclusive", func(t *testing.T) {
		operationID := integrationOperationID(t)
		result, err := driver.Observe(ctx, provideradapter.Query{
			OperationID: operationID, RequestHash: strings.Repeat("a", 64),
			ContentType: "application/json", Body: []byte(`{"job":"missing"}`),
		})
		if err != nil {
			t.Fatal(err)
		}
		if result != (provideradapter.Result{Outcome: provideradapter.Inconclusive}) {
			t.Fatalf("missing observation = %+v, want inconclusive", result)
		}
	})
}

func integrationOperationID(t *testing.T) string {
	t.Helper()
	var identity [32]byte
	if _, err := rand.Read(identity[:]); err != nil {
		t.Fatal(err)
	}
	return "op-" + hex.EncodeToString(identity[:])
}

func openActivatedControl(t *testing.T, historyPath, adapterURL, effectPath, observationPath string) *control.Control {
	t.Helper()
	runtimeControl, err := control.Open(historyPath)
	if err != nil {
		t.Fatal(err)
	}
	requirement := kernel.Requirement{
		ID:         "postgres-outbox-integration",
		Results:    map[string]uint32{"enqueued": 1},
		Capacities: map[string]uint32{"outbox_write": 1},
		Kinds: map[string]kernel.KindSpec{
			"enqueue": {
				Costs:     map[string]uint32{"outbox_write": 1},
				Produces:  map[string]uint32{"enqueued": 1},
				RetrySafe: false, Queryable: true,
				Target: adapterURL + effectPath, Method: http.MethodPost,
				ResponseClassifier: gateway.ResponseReceiptV1,
				QueryTarget:        adapterURL + observationPath, QueryMethod: http.MethodPost,
				QueryClassifier: gateway.OperationObservationV1,
			},
		},
	}
	certificate, err := runtimeControl.Compile(requirement)
	if err != nil {
		_ = runtimeControl.Close()
		t.Fatal(err)
	}
	if err := runtimeControl.Activate(certificate); err != nil {
		_ = runtimeControl.Close()
		t.Fatal(err)
	}
	return runtimeControl
}

func openGateway(t *testing.T, runtimeControl *control.Control) *gateway.Gateway {
	t.Helper()
	transport := &http.Transport{Proxy: nil}
	t.Cleanup(transport.CloseIdleConnections)
	runtimeGateway, err := gateway.New(runtimeControl, &http.Client{
		Transport: transport, Timeout: 5 * time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	return runtimeGateway
}

func countRows(t *testing.T, ctx context.Context, dsn, operationID string) int {
	t.Helper()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var count int
	if err := pool.QueryRow(ctx,
		"SELECT count(*) FROM public.safe_change_outbox WHERE operation_id = $1",
		operationID,
	).Scan(&count); err != nil {
		t.Fatal(err)
	}
	return count
}

type responseLossBoundary struct {
	next            http.Handler
	effectPath      string
	observationPath string
	dropNext        atomic.Bool
	dropped         atomic.Int32
	effects         atomic.Int32
	observations    atomic.Int32
}

func (boundary *responseLossBoundary) ServeHTTP(writer http.ResponseWriter, request *http.Request) {
	switch request.URL.Path {
	case boundary.effectPath:
		boundary.effects.Add(1)
	case boundary.observationPath:
		boundary.observations.Add(1)
	}
	recorder := httptest.NewRecorder()
	boundary.next.ServeHTTP(recorder, request)
	if request.URL.Path == boundary.effectPath && recorder.Code == http.StatusOK &&
		boundary.dropNext.CompareAndSwap(false, true) {
		connection, _, err := writer.(http.Hijacker).Hijack()
		if err == nil {
			boundary.dropped.Add(1)
			_ = connection.Close()
			return
		}
		http.Error(writer, "could not inject response loss", http.StatusInternalServerError)
		return
	}
	for name, values := range recorder.Header() {
		for _, value := range values {
			writer.Header().Add(name, value)
		}
	}
	writer.WriteHeader(recorder.Code)
	_, _ = io.Copy(writer, recorder.Body)
}

func (boundary *responseLossBoundary) counts() (int32, int32, int32) {
	return boundary.effects.Load(), boundary.observations.Load(), boundary.dropped.Load()
}
