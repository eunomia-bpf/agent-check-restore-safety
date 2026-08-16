package main

import (
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/sandboxhost"
)

func TestListenerPolicy(t *testing.T) {
	loopback := &net.TCPAddr{IP: net.ParseIP("127.0.0.1"), Port: 8787}
	remote := &net.TCPAddr{IP: net.ParseIP("172.20.0.2"), Port: 8787}
	if !listenerAllowed(loopback, false) {
		t.Fatal("loopback listener was rejected")
	}
	if listenerAllowed(remote, false) {
		t.Fatal("non-loopback listener was accepted without the explicit flag")
	}
	if !listenerAllowed(remote, true) {
		t.Fatal("explicitly allowed isolated listener was rejected")
	}
}

func TestLoadOrCreateTokenIsPrivateAndStable(t *testing.T) {
	path := filepath.Join(t.TempDir(), "control.token")
	first, err := loadOrCreateToken(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(first) != 64 {
		t.Fatalf("token length = %d", len(first))
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("token mode = %o", info.Mode().Perm())
	}
	second, err := loadOrCreateToken(path)
	if err != nil {
		t.Fatal(err)
	}
	if first != second {
		t.Fatal("token changed after reopen")
	}
}

func TestLoadOrCreateTokenRejectsSharedFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "shared.token")
	if err := os.WriteFile(path, []byte("01234567890123456789012345678901\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := loadOrCreateToken(path); err == nil {
		t.Fatal("shared token file was accepted")
	}
}

func TestEnsurePrivateSandboxDirectory(t *testing.T) {
	path := filepath.Join(t.TempDir(), "sandbox-endpoints")
	if err := ensurePrivateDirectory(path); err != nil {
		t.Fatal(err)
	}
	info, err := os.Lstat(path)
	if err != nil {
		t.Fatal(err)
	}
	if !info.IsDir() || info.Mode().Perm() != 0o700 {
		t.Fatalf("sandbox endpoint directory mode=%v", info.Mode())
	}
	if err := ensurePrivateDirectory(path); err != nil {
		t.Fatalf("existing private directory was rejected: %v", err)
	}
	if err := ensurePrivateDirectory("relative/endpoints"); err == nil {
		t.Fatal("relative sandbox endpoint directory was accepted")
	}
}

func TestShutdownRuntimeDrainsSandboxBeforeControl(t *testing.T) {
	stateDirectory := t.TempDir()
	endpointDirectory, err := os.MkdirTemp("/tmp", "scr-shutdown-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(endpointDirectory) })
	if err := os.Chmod(endpointDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	controller, err := control.Open(filepath.Join(stateDirectory, "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	serverAPI, err := api.New(controller, nil, api.Credentials{
		AdminToken: "shutdown-admin-token-00000000000000000000",
	})
	if err != nil {
		controller.Close()
		t.Fatal(err)
	}
	manager, err := sandboxhost.NewManager(controller, serverAPI, endpointDirectory)
	if err != nil {
		controller.Close()
		t.Fatal(err)
	}
	if err := serverAPI.SetSandboxEndpointPublisher(manager); err != nil {
		manager.Close()
		controller.Close()
		t.Fatal(err)
	}
	requirement := kernel.Requirement{
		ID: "shutdown-v1", Results: map[string]uint32{"done": 1},
		Capacities: map[string]uint32{"slot": 1},
		Kinds: map[string]kernel.KindSpec{"finish": {
			Costs: map[string]uint32{"slot": 1}, Produces: map[string]uint32{"done": 1},
			RetrySafe: true, Target: "http://127.0.0.1:1/effect", Method: http.MethodPost,
			ResponseClassifier: gateway.ResponseReceiptV1,
		}},
	}
	certificate, err := controller.Compile(requirement)
	if err != nil {
		t.Fatal(err)
	}
	binding := control.SandboxBinding{
		SandboxID: "vm", Generation: 1, HostInstanceID: "shutdown-host-v1",
		Domain: "agent", AllowedKinds: []string{"finish"},
	}
	if err := controller.Cutover(certificate, []control.SandboxBinding{binding}); err != nil {
		t.Fatal(err)
	}
	if err := manager.ReplaceCommitted(controller.SandboxBindings()); err != nil {
		t.Fatal(err)
	}
	socketPath := manager.PathForSandbox(binding.SandboxID)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: serverAPI.Handler(), ReadHeaderTimeout: time.Second}
	serveDone := make(chan error, 1)
	go func() { serveDone <- server.Serve(listener) }()
	if err := shutdownRuntime(serverAPI, server, manager, controller); err != nil {
		t.Fatal(err)
	}
	if err := <-serveDone; !errors.Is(err, http.ErrServerClosed) {
		t.Fatalf("admin server shutdown error=%v", err)
	}
	if _, err := os.Lstat(socketPath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("sandbox socket survived shutdown: %v", err)
	}
	if err := manager.Close(); err != nil {
		t.Fatalf("cached manager close error=%v", err)
	}
	if err := controller.Close(); err != nil {
		t.Fatalf("idempotent control close error=%v", err)
	}
}

func TestLoadAdaptersUsesIndependentDomainsAndPrivateTokens(t *testing.T) {
	directory := t.TempDir()
	configuration := adapterConfig{Schema: 1, Adapters: []adapterConfigEntry{
		{Domain: "orders", TokenFile: filepath.Join(directory, "orders.token"), Kinds: []string{"charge-v1", "charge-v2"}},
		{Domain: "full-linux-vm", TokenFile: filepath.Join(directory, "vm.token"), Kinds: []string{"vm-audit"}},
	}}
	data, err := json.Marshal(configuration)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, "adapters.json")
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	credentials, err := loadAdapters(path, "", "local-adapter", "", filepath.Join(directory, "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	if len(credentials) != 2 || credentials[0].Domain != "orders" || credentials[1].Domain != "full-linux-vm" {
		t.Fatalf("credentials = %+v", credentials)
	}
	if credentials[0].Token == credentials[1].Token {
		t.Fatal("independent adapters received the same token")
	}
	for _, entry := range configuration.Adapters {
		info, err := os.Stat(entry.TokenFile)
		if err != nil {
			t.Fatal(err)
		}
		if info.Mode().Perm() != 0o600 {
			t.Fatalf("token %s mode = %o", entry.TokenFile, info.Mode().Perm())
		}
	}
}

func TestSandboxOnlyRuntimeNeedsNoAdapterCredential(t *testing.T) {
	historyPath := filepath.Join(t.TempDir(), "runtime.history")
	credentials, err := loadRuntimeAdapters("", "", "local-adapter", "", historyPath, "/run/sandboxes")
	if err != nil {
		t.Fatal(err)
	}
	if len(credentials) != 0 {
		t.Fatalf("sandbox-only credentials=%+v", credentials)
	}
	if _, err := os.Lstat(historyPath + ".operation-token"); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("sandbox-only runtime created an adapter token: %v", err)
	}
}

func TestLoadAdaptersRejectsAmbiguousOrAliasedConfiguration(t *testing.T) {
	directory := t.TempDir()
	token := filepath.Join(directory, "shared.token")
	configuration := `{"schema":1,"adapters":[` +
		`{"domain":"orders","token_file":` + quoted(token) + `,"kinds":["charge"]},` +
		`{"domain":"orders","token_file":` + quoted(filepath.Join(directory, "other.token")) + `,"kinds":["audit"]}]}`
	path := filepath.Join(directory, "duplicate.json")
	if err := os.WriteFile(path, []byte(configuration), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadAdapters(path, "", "local-adapter", "", filepath.Join(directory, "runtime.history")); err == nil {
		t.Fatal("duplicate adapter domain was accepted")
	}
	if _, err := loadAdapters(path, token, "local-adapter", "", filepath.Join(directory, "runtime.history")); err == nil {
		t.Fatal("adapter config combined with a legacy token was accepted")
	}
}

func TestLoadAdaptersRejectsUnknownFields(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "unknown.json")
	data := `{"schema":1,"adapters":[{"domain":"orders","token_file":"/tmp/token",` +
		`"kinds":["charge"],"authority":"admin"}]}`
	if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadAdapters(path, "", "local-adapter", "", filepath.Join(directory, "runtime.history")); err == nil {
		t.Fatal("unknown adapter config field was accepted")
	}
}

func quoted(value string) string {
	encoded, _ := json.Marshal(value)
	return string(encoded)
}
