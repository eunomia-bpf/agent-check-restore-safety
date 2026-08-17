package mcpoperation

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

func TestSandboxExecutorRecoversUnknownWithSameCredentialFreeRequest(t *testing.T) {
	directory := filepath.Join(t.TempDir(), "private")
	if err := os.Mkdir(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	socketPath := filepath.Join(directory, "sandbox.sock")
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: socketPath, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	listener.SetUnlinkOnClose(true)
	if err := os.Chmod(socketPath, 0o600); err != nil {
		t.Fatal(err)
	}
	var attempts atomic.Int32
	var first sandboxExecuteRequest
	server := &http.Server{Handler: http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/v1/execute" || request.Header.Get("Authorization") != "" {
			t.Errorf("sandbox request path=%q Authorization=%q", request.URL.Path, request.Header.Get("Authorization"))
		}
		var current sandboxExecuteRequest
		if err := json.NewDecoder(request.Body).Decode(&current); err != nil {
			t.Error(err)
		}
		attempt := attempts.Add(1)
		if attempt == 1 {
			first = current
			writer.Header().Set("Content-Type", "application/json")
			writer.WriteHeader(http.StatusConflict)
			_ = json.NewEncoder(writer).Encode(api.OperationError{
				Outcome: gateway.Outcome{
					OperationID: "op-" + strings.Repeat("a", 64), Phase: kernel.Unknown,
				},
				Error: gateway.ErrOutcomeUnknown.Error(), Code: api.OperationErrorOutcomeUnknown,
			})
			return
		}
		if current.CallID != first.CallID || current.Kind != first.Kind || string(current.Body) != string(first.Body) {
			t.Errorf("recovery changed request: first=%+v current=%+v", first, current)
		}
		writer.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(writer).Encode(gateway.Outcome{
			OperationID: "op-" + strings.Repeat("a", 64), Phase: kernel.Succeeded,
			ResultHash: strings.Repeat("b", 64), Reused: true, RecoveredByQuery: true,
		})
	})}
	serveDone := make(chan error, 1)
	go func() { serveDone <- server.Serve(listener) }()
	t.Cleanup(func() {
		shutdown, cancel := context.WithTimeout(context.Background(), time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
		<-serveDone
	})

	executor, err := NewSandboxExecutor(socketPath, SandboxExecutorOptions{})
	if err != nil {
		t.Fatal(err)
	}
	outcome, err := executor.Execute(context.Background(), "mcp-call-v1:4:test:1", "protected_commit", []byte(`{"effect_id":"A-17"}`))
	if err != nil {
		t.Fatal(err)
	}
	if attempts.Load() != 2 || outcome.Phase != kernel.Succeeded || !outcome.Reused || !outcome.RecoveredByQuery {
		t.Fatalf("attempts=%d outcome=%+v", attempts.Load(), outcome)
	}
}

func TestSandboxExecutorRejectsUnsafeSocketBoundary(t *testing.T) {
	publicDirectory := filepath.Join(t.TempDir(), "public")
	if err := os.Mkdir(publicDirectory, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(publicDirectory, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := NewSandboxExecutor(filepath.Join(publicDirectory, "sandbox.sock"), SandboxExecutorOptions{}); err == nil {
		t.Fatal("world-searchable socket directory accepted")
	}
	if _, err := NewSandboxExecutor("relative.sock", SandboxExecutorOptions{}); err == nil {
		t.Fatal("relative socket path accepted")
	}

	privateDirectory := filepath.Join(t.TempDir(), "private")
	if err := os.Mkdir(privateDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	regularPath := filepath.Join(privateDirectory, "not-a-socket")
	if err := os.WriteFile(regularPath, []byte("not a socket"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := NewSandboxExecutor(regularPath, SandboxExecutorOptions{}); err == nil {
		t.Fatal("regular file accepted as a sandbox endpoint")
	}
}

func TestSandboxExecutorRejectsReplacedGenerationSocket(t *testing.T) {
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, "sandbox.sock")
	first, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}
	executor, err := NewSandboxExecutor(path, SandboxExecutorOptions{})
	if err != nil {
		t.Fatal(err)
	}
	defer executor.Close()
	if err := first.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		t.Fatal(err)
	}
	second, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}
	_, err = executor.Execute(context.Background(), "call", "kind", []byte(`{}`))
	if err == nil || !strings.Contains(err.Error(), "generation changed") {
		t.Fatalf("Execute error=%v, want generation-change rejection", err)
	}
}
