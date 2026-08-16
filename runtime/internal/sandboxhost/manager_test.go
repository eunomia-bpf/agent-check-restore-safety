package sandboxhost

import (
	"errors"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"

	controlapi "github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
)

func TestManagerPublishesCompletePrivateEndpointSet(t *testing.T) {
	controller, serverAPI, manager := newTestManager(t)
	defer controller.Close()
	defer manager.Close()
	bindings := []control.SandboxBinding{
		testManagerBinding("vm-a", 1, "host-a", "domain-a"),
		testManagerBinding("vm-b", 1, "host-b", "domain-b"),
	}
	commitBindings(t, controller, "manager-complete-v1", bindings)
	if err := manager.ReplaceCommitted(controller.SandboxBindings()); err != nil {
		t.Fatal(err)
	}
	for _, binding := range bindings {
		if err := controller.ValidateSandbox(binding); err != nil {
			t.Fatalf("sandbox %q is not attached: %v", binding.SandboxID, err)
		}
		path := manager.PathForSandbox(binding.SandboxID)
		info, err := os.Lstat(path)
		if err != nil {
			t.Fatal(err)
		}
		if info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0o600 {
			t.Fatalf("sandbox %q endpoint mode=%v", binding.SandboxID, info.Mode())
		}
		assertHealthyUnix(t, path)
	}
	if serverAPI == nil {
		t.Fatal("test API is nil")
	}
}

func TestManagerPrepareFailureLeavesCompleteSetUnattached(t *testing.T) {
	controller, _, manager := newTestManager(t)
	defer controller.Close()
	defer manager.Close()
	bindings := []control.SandboxBinding{
		testManagerBinding("vm-a", 1, "host-a", "domain-a"),
		testManagerBinding("vm-b", 1, "host-b", "domain-b"),
	}
	blockedPath := manager.PathForSandbox("vm-b")
	if err := os.WriteFile(blockedPath, []byte("must survive"), 0o600); err != nil {
		t.Fatal(err)
	}
	commitBindings(t, controller, "manager-prepare-failure", bindings)
	if err := manager.ReplaceCommitted(controller.SandboxBindings()); err == nil {
		t.Fatal("endpoint preparation unexpectedly succeeded")
	}
	if _, err := os.Lstat(manager.PathForSandbox("vm-a")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("first prepared socket survived batch failure: %v", err)
	}
	contents, err := os.ReadFile(blockedPath)
	if err != nil || string(contents) != "must survive" {
		t.Fatalf("blocking file changed: contents=%q err=%v", contents, err)
	}
	for _, binding := range bindings {
		if err := controller.ValidateSandbox(binding); !errors.Is(err, control.ErrSandboxNotAttached) {
			t.Fatalf("sandbox %q was partially attached: %v", binding.SandboxID, err)
		}
	}
}

func TestManagerAttachFailureRemovesEveryPreparedSocket(t *testing.T) {
	controller, _, manager := newTestManager(t)
	defer controller.Close()
	defer manager.Close()
	bindings := []control.SandboxBinding{
		testManagerBinding("vm-a", 1, "host-a", "domain-a"),
		testManagerBinding("vm-b", 1, "host-b", "domain-b"),
	}
	manager.attach = func([]control.SandboxBinding) error { return errors.New("injected atomic attach failure") }
	commitBindings(t, controller, "manager-attach-failure", bindings)
	if err := manager.ReplaceCommitted(controller.SandboxBindings()); err == nil || !strings.Contains(err.Error(), "injected") {
		t.Fatalf("attach failure=%v", err)
	}
	for _, binding := range bindings {
		if _, err := os.Lstat(manager.PathForSandbox(binding.SandboxID)); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("sandbox %q socket survived attach failure: %v", binding.SandboxID, err)
		}
		if err := controller.ValidateSandbox(binding); !errors.Is(err, control.ErrSandboxNotAttached) {
			t.Fatalf("sandbox %q was partially attached: %v", binding.SandboxID, err)
		}
	}
}

func TestManagerRejectsRepositoryRootMismatch(t *testing.T) {
	controller, _, manager := newTestManager(t)
	defer controller.Close()
	defer manager.Close()
	binding := testManagerBinding("vm", 1, "host-v1", "agent")
	binding.RepositoryRoot = strings.Repeat("a", 64)
	commitBindings(t, controller, "manager-repository-root", []control.SandboxBinding{binding})
	wrong := binding
	wrong.RepositoryRoot = strings.Repeat("b", 64)
	if err := manager.ReplaceCommitted([]control.SandboxBinding{wrong}); err == nil ||
		!strings.Contains(err.Error(), "committed sandbox set") {
		t.Fatalf("repository root mismatch was accepted: %v", err)
	}
	if _, err := os.Lstat(manager.PathForSandbox(binding.SandboxID)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("mismatched endpoint was published: %v", err)
	}
}

func TestManagerReplacesFreshGenerationAtStablePath(t *testing.T) {
	controller, _, manager := newTestManager(t)
	defer controller.Close()
	defer manager.Close()
	first := testManagerBinding("vm", 1, "host-v1", "agent")
	commitBindings(t, controller, "manager-replace-v1", []control.SandboxBinding{first})
	if err := manager.ReplaceCommitted(controller.SandboxBindings()); err != nil {
		t.Fatal(err)
	}
	path := manager.PathForSandbox(first.SandboxID)
	oldEndpoint := manager.endpoints[first.SandboxID]
	second := testManagerBinding("vm", 2, "host-v2", "agent")
	commitBindings(t, controller, "manager-replace-v2", []control.SandboxBinding{second})
	if err := controller.ValidateSandbox(first); !errors.Is(err, control.ErrStaleSandboxBinding) {
		t.Fatalf("old generation remained valid after commit: %v", err)
	}
	if err := manager.ReplaceCommitted(controller.SandboxBindings()); err != nil {
		t.Fatal(err)
	}
	newEndpoint := manager.endpoints[second.SandboxID]
	if newEndpoint == oldEndpoint || newEndpoint.Binding().Generation != 2 || newEndpoint.SocketPath() != path {
		t.Fatalf("fresh endpoint=%+v old=%p new=%p", newEndpoint.Binding(), oldEndpoint, newEndpoint)
	}
	if err := controller.ValidateSandbox(second); err != nil {
		t.Fatal(err)
	}
	assertHealthyUnix(t, path)
}

func TestManagerReopenCleansDeadSocketWithoutAttachingReplay(t *testing.T) {
	stateDirectory := t.TempDir()
	endpointDirectory := shortPrivateDir(t)
	historyPath := filepath.Join(stateDirectory, "runtime.history")
	first, err := control.Open(historyPath)
	if err != nil {
		t.Fatal(err)
	}
	binding := testManagerBinding("vm", 1, "host-v1", "agent")
	commitBindings(t, first, "manager-replay-v1", []control.SandboxBinding{binding})
	if err := first.Close(); err != nil {
		t.Fatal(err)
	}
	stalePath := filepath.Join(endpointDirectory, managedSocketName(binding.SandboxID))
	stale, err := net.ListenUnix("unix", &net.UnixAddr{Name: stalePath, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	stale.SetUnlinkOnClose(false)
	if err := stale.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := control.Open(historyPath)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	serverAPI, err := controlapi.New(reopened, nil, controlapi.Credentials{AdminToken: testAdminToken})
	if err != nil {
		t.Fatal(err)
	}
	manager, err := NewManager(reopened, serverAPI, endpointDirectory)
	if err != nil {
		t.Fatal(err)
	}
	defer manager.Close()
	if _, err := os.Lstat(stalePath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("dead managed socket was not cleaned: %v", err)
	}
	if err := reopened.ValidateSandbox(binding); !errors.Is(err, control.ErrSandboxNotAttached) {
		t.Fatalf("replayed sandbox was attached: %v", err)
	}
}

func TestManagerHashesUntrustedSandboxIDs(t *testing.T) {
	controller, _, manager := newTestManager(t)
	defer controller.Close()
	defer manager.Close()
	ids := []string{"../escape", "nested/path", strings.Repeat("x", 256)}
	seen := make(map[string]bool)
	for _, id := range ids {
		path := manager.PathForSandbox(id)
		if filepath.Dir(path) != manager.directory || seen[path] || !isManagedSocketName(filepath.Base(path)) {
			t.Fatalf("unsafe or colliding path for %q: %q", id, path)
		}
		seen[path] = true
	}
}

func TestNewManagerRejectsManagedPathSubstitution(t *testing.T) {
	controller, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer controller.Close()
	serverAPI, err := controlapi.New(controller, nil, controlapi.Credentials{AdminToken: testAdminToken})
	if err != nil {
		t.Fatal(err)
	}
	for _, variant := range []string{"regular", "symlink", "active"} {
		t.Run(variant, func(t *testing.T) {
			directory := shortPrivateDir(t)
			path := filepath.Join(directory, managedSocketName("vm"))
			target := filepath.Join(directory, "target")
			var active *net.UnixListener
			switch variant {
			case "regular":
				if err := os.WriteFile(path, []byte("must survive"), 0o600); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				if err := os.WriteFile(target, []byte("must survive"), 0o600); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(target, path); err != nil {
					t.Fatal(err)
				}
			case "active":
				active, err = net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
				if err != nil {
					t.Fatal(err)
				}
				active.SetUnlinkOnClose(false)
				defer active.Close()
			}
			if _, err := NewManager(controller, serverAPI, directory); err == nil {
				t.Fatalf("managed %s path was accepted", variant)
			}
			info, err := os.Lstat(path)
			if err != nil {
				t.Fatalf("managed %s path was removed: %v", variant, err)
			}
			if variant == "symlink" && info.Mode()&os.ModeSymlink == 0 {
				t.Fatalf("managed symlink mode=%v", info.Mode())
			}
			if variant != "active" {
				contents, err := os.ReadFile(target)
				if variant == "regular" {
					contents, err = os.ReadFile(path)
				}
				if err != nil || string(contents) != "must survive" {
					t.Fatalf("managed %s contents=%q err=%v", variant, contents, err)
				}
			}
		})
	}
}

func TestManagerCloseIsIdempotentAndDetachesBeforeControlClose(t *testing.T) {
	controller, _, manager := newTestManager(t)
	binding := testManagerBinding("vm", 1, "host-v1", "agent")
	commitBindings(t, controller, "manager-close", []control.SandboxBinding{binding})
	if err := manager.ReplaceCommitted(controller.SandboxBindings()); err != nil {
		t.Fatal(err)
	}
	path := manager.PathForSandbox(binding.SandboxID)
	if err := manager.Close(); err != nil {
		t.Fatal(err)
	}
	if err := manager.Close(); err != nil {
		t.Fatal(err)
	}
	if err := controller.ValidateSandbox(binding); !errors.Is(err, control.ErrSandboxNotAttached) {
		t.Fatalf("manager close did not detach binding: %v", err)
	}
	if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("manager close did not unlink socket: %v", err)
	}
	if err := controller.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestManagerDirectoryHasOneLiveOwner(t *testing.T) {
	controller, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer controller.Close()
	serverAPI, err := controlapi.New(controller, nil, controlapi.Credentials{AdminToken: testAdminToken})
	if err != nil {
		t.Fatal(err)
	}
	directory := shortPrivateDir(t)
	first, err := NewManager(controller, serverAPI, directory)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := NewManager(controller, serverAPI, directory); err == nil || !strings.Contains(err.Error(), "owns") {
		first.Close()
		t.Fatalf("second live manager acquired directory: %v", err)
	}
	if err := first.Close(); err != nil {
		t.Fatal(err)
	}
	second, err := NewManager(controller, serverAPI, directory)
	if err != nil {
		t.Fatalf("released manager directory was not reusable: %v", err)
	}
	if err := second.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestManagerFailsClosedIfLockedDirectoryIsReplaced(t *testing.T) {
	controller, err := control.Open(filepath.Join(t.TempDir(), "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer controller.Close()
	serverAPI, err := controlapi.New(controller, nil, controlapi.Credentials{AdminToken: testAdminToken})
	if err != nil {
		t.Fatal(err)
	}
	directory := shortPrivateDir(t)
	manager, err := NewManager(controller, serverAPI, directory)
	if err != nil {
		t.Fatal(err)
	}
	moved := directory + ".moved"
	t.Cleanup(func() { _ = os.RemoveAll(moved) })
	if err := os.Rename(directory, moved); err != nil {
		manager.Close()
		t.Fatal(err)
	}
	if err := os.Mkdir(directory, 0o700); err != nil {
		manager.Close()
		t.Fatal(err)
	}
	replacement, err := NewManager(controller, serverAPI, directory)
	if err != nil {
		manager.Close()
		t.Fatalf("new directory could not obtain its own manager: %v", err)
	}
	if err := manager.ReplaceCommitted(nil); err == nil || !strings.Contains(err.Error(), "identity changed") {
		replacement.Close()
		manager.Close()
		t.Fatalf("old manager used replacement directory: %v", err)
	}
	if err := replacement.Close(); err != nil {
		t.Fatal(err)
	}
	if err := manager.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestManagerCloseCachesFailureForEveryCaller(t *testing.T) {
	controller, _, manager := newTestManager(t)
	defer controller.Close()
	binding := testManagerBinding("vm", 1, "host-v1", "agent")
	commitBindings(t, controller, "manager-close-error", []control.SandboxBinding{binding})
	if err := manager.ReplaceCommitted(controller.SandboxBindings()); err != nil {
		t.Fatal(err)
	}
	path := manager.PathForSandbox(binding.SandboxID)
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(manager.directory, "target")
	if err := os.WriteFile(target, []byte("must survive"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, path); err != nil {
		t.Fatal(err)
	}
	firstErr := manager.Close()
	secondErr := manager.Close()
	if firstErr == nil || secondErr == nil || firstErr.Error() != secondErr.Error() {
		t.Fatalf("cached close errors differ: first=%v second=%v", firstErr, secondErr)
	}
	info, err := os.Lstat(path)
	if err != nil || info.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("close error changed replacement symlink: mode=%v err=%v", info, err)
	}
}

func newTestManager(t *testing.T) (*control.Control, *controlapi.Server, *Manager) {
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
	directory := shortPrivateDir(t)
	manager, err := NewManager(controller, serverAPI, directory)
	if err != nil {
		controller.Close()
		t.Fatal(err)
	}
	return controller, serverAPI, manager
}

func shortPrivateDir(t *testing.T) string {
	t.Helper()
	directory, err := os.MkdirTemp("/tmp", "scr-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := os.RemoveAll(directory); err != nil {
			t.Errorf("remove short private directory: %v", err)
		}
	})
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	return directory
}

func testManagerBinding(id string, generation uint64, host, domain string) control.SandboxBinding {
	return control.SandboxBinding{
		SandboxID: id, Generation: generation, HostInstanceID: host,
		Domain: domain, AllowedKinds: []string{"finish"},
	}
}

func commitBindings(t *testing.T, controller *control.Control, requirementID string, bindings []control.SandboxBinding) {
	t.Helper()
	certificate, err := controller.Compile(testRequirement(requirementID))
	if err != nil {
		t.Fatal(err)
	}
	if err := controller.Cutover(certificate, bindings); err != nil {
		t.Fatal(err)
	}
}
