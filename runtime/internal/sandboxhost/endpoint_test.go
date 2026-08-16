package sandboxhost

import (
	"context"
	"errors"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
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

func TestUnixEndpointIsPrivateAndRemovedOnClose(t *testing.T) {
	controller, serverAPI, binding := configuredSandbox(t, "sandbox-unix-private", 1)
	defer controller.Close()
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	socketPath := filepath.Join(directory, "vm.sock")
	endpoint, err := ListenUnix(controller, serverAPI, binding, socketPath)
	if err != nil {
		t.Fatal(err)
	}
	if endpoint.SocketPath() != socketPath || endpoint.Address() != socketPath {
		t.Fatalf("Unix endpoint address=%q socket=%q", endpoint.Address(), endpoint.SocketPath())
	}
	info, err := os.Lstat(socketPath)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0o600 {
		t.Fatalf("Unix endpoint mode=%v", info.Mode())
	}
	assertHealthyUnix(t, socketPath)
	if _, err := endpoint.Port(); err == nil {
		t.Fatal("Unix endpoint reported a TCP port")
	}
	closeContext, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := endpoint.Close(closeContext); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(socketPath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("closed Unix socket still exists: %v", err)
	}
	if err := controller.ValidateSandbox(binding); !errors.Is(err, control.ErrSandboxNotAttached) {
		t.Fatalf("closed Unix binding validation=%v", err)
	}
}

func TestUnixEndpointReopenRequiresFreshCutover(t *testing.T) {
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	historyPath := filepath.Join(directory, "runtime.history")
	socketPath := filepath.Join(directory, "vm.sock")
	first, err := control.Open(historyPath)
	if err != nil {
		t.Fatal(err)
	}
	firstAPI, err := controlapi.New(first, nil, controlapi.Credentials{AdminToken: testAdminToken})
	if err != nil {
		t.Fatal(err)
	}
	old := control.SandboxBinding{
		SandboxID: "vm", Generation: 1, HostInstanceID: "qemu-host-1",
		Domain: "agent", AllowedKinds: []string{"finish"},
	}
	certificate, err := first.Compile(testRequirement("sandbox-unix-v1"))
	if err != nil {
		t.Fatal(err)
	}
	if err := first.Cutover(certificate, []control.SandboxBinding{old}); err != nil {
		t.Fatal(err)
	}
	endpoint, err := ListenUnix(first, firstAPI, old, socketPath)
	if err != nil {
		t.Fatal(err)
	}
	closeContext, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	if err := endpoint.Close(closeContext); err != nil {
		cancel()
		t.Fatal(err)
	}
	cancel()
	if err := first.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := control.Open(historyPath)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	reopenedAPI, err := controlapi.New(reopened, nil, controlapi.Credentials{AdminToken: testAdminToken})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := ListenUnix(reopened, reopenedAPI, old, socketPath); !errors.Is(err, control.ErrStaleSandboxBinding) {
		t.Fatalf("replayed generation was attached: %v", err)
	}
	if _, err := os.Lstat(socketPath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("failed attach left Unix socket: %v", err)
	}
	fresh := old
	fresh.Generation = 2
	fresh.HostInstanceID = "qemu-host-2"
	certificate, err = reopened.Compile(testRequirement("sandbox-unix-v2"))
	if err != nil {
		t.Fatal(err)
	}
	if err := reopened.Cutover(certificate, []control.SandboxBinding{fresh}); err != nil {
		t.Fatal(err)
	}
	freshEndpoint, err := ListenUnix(reopened, reopenedAPI, fresh, socketPath)
	if err != nil {
		t.Fatal(err)
	}
	closeContext, cancel = context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := freshEndpoint.Close(closeContext); err != nil {
		t.Fatal(err)
	}
}

func TestUnixEndpointRejectsUnsafeOrActivePaths(t *testing.T) {
	controller, serverAPI, binding := configuredSandbox(t, "sandbox-unix-reject", 1)
	defer controller.Close()
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := ListenUnix(controller, serverAPI, binding, filepath.Join(directory, "vm.sock")); err == nil {
		t.Fatal("world-searchable socket parent was accepted")
	}
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	filePath := filepath.Join(directory, "not-a-socket")
	if err := os.WriteFile(filePath, []byte("do not replace"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := ListenUnix(controller, serverAPI, binding, filePath); err == nil {
		t.Fatal("regular file was replaced")
	}
	if contents, err := os.ReadFile(filePath); err != nil || string(contents) != "do not replace" {
		t.Fatalf("regular file changed: contents=%q err=%v", contents, err)
	}
	activePath := filepath.Join(directory, "active.sock")
	active, err := net.ListenUnix("unix", &net.UnixAddr{Name: activePath, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	active.SetUnlinkOnClose(false)
	if _, err := ListenUnix(controller, serverAPI, binding, activePath); err == nil || !strings.Contains(err.Error(), "active") {
		active.Close()
		t.Fatalf("active socket was replaced: %v", err)
	}
	if err := active.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(activePath); err != nil {
		t.Fatal(err)
	}
	if err := controller.ValidateSandbox(binding); !errors.Is(err, control.ErrSandboxNotAttached) {
		t.Fatalf("rejected paths attached binding: %v", err)
	}
}

func TestUnixEndpointReplacesOnlyOwnedStaleSocket(t *testing.T) {
	controller, serverAPI, binding := configuredSandbox(t, "sandbox-unix-stale", 1)
	defer controller.Close()
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	socketPath := filepath.Join(directory, "vm.sock")
	stale, err := net.ListenUnix("unix", &net.UnixAddr{Name: socketPath, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	stale.SetUnlinkOnClose(false)
	if err := stale.Close(); err != nil {
		t.Fatal(err)
	}
	endpoint, err := ListenUnix(controller, serverAPI, binding, socketPath)
	if err != nil {
		t.Fatal(err)
	}
	assertHealthyUnix(t, socketPath)
	closeContext, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := endpoint.Close(closeContext); err != nil {
		t.Fatal(err)
	}
}

func TestUnixEndpointCloseDoesNotRemoveReplacement(t *testing.T) {
	controller, serverAPI, binding := configuredSandbox(t, "sandbox-unix-replaced", 1)
	defer controller.Close()
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	socketPath := filepath.Join(directory, "vm.sock")
	endpoint, err := ListenUnix(controller, serverAPI, binding, socketPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(socketPath); err != nil {
		t.Fatal(err)
	}
	replacement, err := net.ListenUnix("unix", &net.UnixAddr{Name: socketPath, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	replacement.SetUnlinkOnClose(false)
	closeContext, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	err = endpoint.Close(closeContext)
	cancel()
	if err == nil || !strings.Contains(err.Error(), "replaced") {
		t.Fatalf("replacement was not detected: %v", err)
	}
	if _, err := os.Lstat(socketPath); err != nil {
		t.Fatalf("replacement socket was removed: %v", err)
	}
	if err := replacement.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(socketPath); err != nil {
		t.Fatal(err)
	}
}

func TestUnixEndpointCloseDoesNotFollowReplacementSymlink(t *testing.T) {
	controller, serverAPI, binding := configuredSandbox(t, "sandbox-unix-symlink-replaced", 1)
	defer controller.Close()
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	socketPath := filepath.Join(directory, "vm.sock")
	endpoint, err := ListenUnix(controller, serverAPI, binding, socketPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(socketPath); err != nil {
		t.Fatal(err)
	}
	targetPath := filepath.Join(directory, "target")
	if err := os.WriteFile(targetPath, []byte("must survive"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(targetPath, socketPath); err != nil {
		t.Fatal(err)
	}
	closeContext, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	err = endpoint.Close(closeContext)
	cancel()
	if err == nil || !strings.Contains(err.Error(), "replaced") {
		t.Fatalf("replacement symlink was not detected: %v", err)
	}
	info, err := os.Lstat(socketPath)
	if err != nil {
		t.Fatalf("replacement symlink was removed: %v", err)
	}
	if info.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("replacement symlink mode=%v", info.Mode())
	}
	contents, err := os.ReadFile(targetPath)
	if err != nil || string(contents) != "must survive" {
		t.Fatalf("symlink target changed: contents=%q err=%v", contents, err)
	}
}

func configuredSandbox(t *testing.T, requirementID string, generation uint64) (*control.Control, *controlapi.Server, control.SandboxBinding) {
	t.Helper()
	controller, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	serverAPI, err := controlapi.New(controller, nil, controlapi.Credentials{AdminToken: testAdminToken})
	if err != nil {
		controller.Close()
		t.Fatal(err)
	}
	binding := control.SandboxBinding{
		SandboxID: "vm", Generation: generation, HostInstanceID: "qemu-host-1",
		Domain: "agent", AllowedKinds: []string{"finish"},
	}
	certificate, err := controller.Compile(testRequirement(requirementID))
	if err != nil {
		controller.Close()
		t.Fatal(err)
	}
	if err := controller.Cutover(certificate, []control.SandboxBinding{binding}); err != nil {
		controller.Close()
		t.Fatal(err)
	}
	return controller, serverAPI, binding
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

func assertHealthyUnix(t *testing.T, socketPath string) {
	t.Helper()
	transport := &http.Transport{
		DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			return (&net.Dialer{}).DialContext(ctx, "unix", socketPath)
		},
	}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 2 * time.Second}
	response, err := client.Get("http://sandbox/healthz")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("Unix health status = %d", response.StatusCode)
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
