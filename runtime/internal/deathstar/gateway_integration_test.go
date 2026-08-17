package deathstar_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/deathstar"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

func TestGatewayRequestHashCrossesDeathStarEffectBoundary(t *testing.T) {
	frontend := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		_, _ = writer.Write([]byte(`{"message":"Reserve successfully!"}`))
	}))
	defer frontend.Close()

	root := t.TempDir()
	fences := filepath.Join(root, "fences")
	if err := os.Mkdir(fences, 0o700); err != nil {
		t.Fatal(err)
	}
	effect, err := deathstar.OpenEffect(deathstar.EffectConfig{
		FrontendURL: frontend.URL, AuditPath: filepath.Join(root, "audit.jsonl"),
		TerminalFenceDirectory: fences,
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = effect.Close() })
	effectServer := httptest.NewServer(effect.Handler())
	defer effectServer.Close()

	runtimeControl, err := control.Open(filepath.Join(root, "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer runtimeControl.Close()
	requirement := kernel.Requirement{
		ID: "deathstar-request-hash", Results: map[string]uint32{"reserved": 1},
		Capacities: map[string]uint32{"reservation": 1},
		Kinds: map[string]kernel.KindSpec{"reserve": {
			Costs: map[string]uint32{"reservation": 1}, Produces: map[string]uint32{"reserved": 1},
			RetrySafe: true, Target: effectServer.URL + "/v1/reserve", Method: http.MethodPost,
			ResponseClassifier: gateway.ResponseReceiptV1,
		}},
	}
	certificate, err := runtimeControl.Compile(requirement)
	if err != nil {
		t.Fatal(err)
	}
	if err := runtimeControl.Activate(certificate); err != nil {
		t.Fatal(err)
	}
	runtimeGateway, err := gateway.New(runtimeControl, nil)
	if err != nil {
		t.Fatal(err)
	}
	operationID := "op-" + strings.Repeat("a", 64)
	outcome, err := runtimeGateway.Execute(context.Background(), gateway.Request{
		ID: operationID, Domain: "deathstar", Kind: "reserve", URL: effectServer.URL + "/v1/reserve",
		Headers: map[string]string{"Content-Type": "application/json"},
		Body:    []byte(`{"hotel_id":"1","in_date":"2015-04-09","out_date":"2015-04-10","rooms":1,"username":"Cornell_30","password":"0000000000"}`),
	})
	if err != nil || outcome.Phase != kernel.Succeeded {
		t.Fatalf("outcome=%+v error=%v", outcome, err)
	}
	operation := runtimeControl.Snapshot().Operations[operationID]
	if operation.RequestHash == "" || outcome.OperationID != operationID {
		t.Fatalf("Operation is not bound to its request: operation=%+v outcome=%+v", operation, outcome)
	}
}
