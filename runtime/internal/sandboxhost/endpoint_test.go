package sandboxhost

import (
	"context"
	"errors"
	"net/http"
	"path/filepath"
	"testing"
	"time"

	controlapi "github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const testAdminToken = "sandbox-host-admin-token-0000000000000000"

func TestEndpointRebindsOnlyAfterFreshCutover(t *testing.T) {
	controller, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer controller.Close()
	serverAPI, err := controlapi.New(controller, nil, controlapi.Credentials{AdminToken: testAdminToken})
	if err != nil {
		t.Fatal(err)
	}
	first := control.SandboxBinding{
		SandboxID: "vm", Generation: 1, HostInstanceID: "qemu-host-1",
		Domain: "agent", AllowedKinds: []string{"finish"},
	}
	firstCertificate, err := controller.Compile(testRequirement("sandbox-host-v1"))
	if err != nil {
		t.Fatal(err)
	}
	if err := controller.Cutover(firstCertificate, []control.SandboxBinding{first}); err != nil {
		t.Fatal(err)
	}
	firstEndpoint, err := Listen(controller, serverAPI, first, "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := firstEndpoint.Address()
	assertHealthy(t, address)
	closeContext, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	if err := firstEndpoint.Close(closeContext); err != nil {
		cancel()
		t.Fatal(err)
	}
	cancel()
	if err := controller.ValidateSandbox(first); !errors.Is(err, control.ErrSandboxNotAttached) {
		t.Fatalf("closed binding validation = %v", err)
	}
	if _, err := Listen(controller, serverAPI, first, address); !errors.Is(err, control.ErrStaleSandboxBinding) {
		t.Fatalf("closed generation was reattached: %v", err)
	}

	second := first
	second.Generation = 2
	second.HostInstanceID = "qemu-host-2"
	secondCertificate, err := controller.Compile(testRequirement("sandbox-host-v2"))
	if err != nil {
		t.Fatal(err)
	}
	if err := controller.Cutover(secondCertificate, []control.SandboxBinding{second}); err != nil {
		t.Fatal(err)
	}
	if err := controller.ValidateSandbox(first); !errors.Is(err, control.ErrStaleSandboxBinding) {
		t.Fatalf("old generation validation = %v", err)
	}
	secondEndpoint, err := Listen(controller, serverAPI, second, address)
	if err != nil {
		t.Fatal(err)
	}
	assertHealthy(t, address)
	closeContext, cancel = context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := secondEndpoint.Close(closeContext); err != nil {
		t.Fatal(err)
	}
}

func TestEndpointRejectsNonLoopbackListener(t *testing.T) {
	controller, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer controller.Close()
	serverAPI, err := controlapi.New(controller, nil, controlapi.Credentials{AdminToken: testAdminToken})
	if err != nil {
		t.Fatal(err)
	}
	binding := control.SandboxBinding{
		SandboxID: "vm", Generation: 1, HostInstanceID: "qemu-host-1",
		Domain: "agent", AllowedKinds: []string{"finish"},
	}
	certificate, err := controller.Compile(testRequirement("sandbox-host-public"))
	if err != nil {
		t.Fatal(err)
	}
	if err := controller.Cutover(certificate, []control.SandboxBinding{binding}); err != nil {
		t.Fatal(err)
	}
	if _, err := Listen(controller, serverAPI, binding, "0.0.0.0:0"); err == nil {
		t.Fatal("non-loopback endpoint was accepted")
	}
	if err := controller.ValidateSandbox(binding); !errors.Is(err, control.ErrSandboxNotAttached) {
		t.Fatalf("rejected listener attached the sandbox: %v", err)
	}
}

func assertHealthy(t *testing.T, address string) {
	t.Helper()
	client := &http.Client{Timeout: 2 * time.Second}
	response, err := client.Get("http://" + address + "/healthz")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("health status = %d", response.StatusCode)
	}
}

func testRequirement(id string) kernel.Requirement {
	return kernel.Requirement{
		ID: id, Results: map[string]uint32{"done": 1}, Capacities: map[string]uint32{"slot": 1},
		Kinds: map[string]kernel.KindSpec{
			"finish": {
				Costs: map[string]uint32{"slot": 1}, Produces: map[string]uint32{"done": 1},
				RetrySafe: true, Target: "http://127.0.0.1:1/v1/effect", Method: http.MethodPost,
				ResponseClassifier: gateway.ResponseReceiptV1,
			},
		},
	}
}
