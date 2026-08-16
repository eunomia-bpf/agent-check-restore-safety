package firecracker

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestClientLifecycleAndPausedSnapshot(t *testing.T) {
	listener, err := net.Listen("unix", filepath.Join(t.TempDir(), "firecracker.sock"))
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	if err := os.Chmod(listener.Addr().String(), 0o600); err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	requests := make(map[string]json.RawMessage)
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		mu.Lock()
		requests[r.Method+" "+r.URL.Path] = append([]byte(nil), body...)
		mu.Unlock()
		if r.Method == http.MethodGet && r.URL.Path == "/" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"app_name":"Firecracker","id":"vm-1","state":"Paused","vmm_version":"1.16.1"}`))
			return
		}
		w.WriteHeader(http.StatusNoContent)
	})}
	go server.Serve(listener)
	defer server.Shutdown(context.Background())
	var trace bytes.Buffer
	client, err := NewClient(ClientConfig{SocketPath: listener.Addr().String(), Timeout: time.Second, MaxResponseBytes: 1024, Trace: &trace, ExpectedPeerPID: os.Getpid()})
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	if err := client.Configure(ctx, MachineConfig{VCPUCount: 2, MemSizeMiB: 128, TrackDirtyPages: true}, BootSource{KernelImagePath: "/kernel", BootArgs: "console=ttyS0"}, VsockDevice{GuestCID: 3, UDSPath: "/tmp/v.sock"}); err != nil {
		t.Fatal(err)
	}
	if err := client.Start(ctx); err != nil {
		t.Fatal(err)
	}
	if state, err := client.State(ctx); err != nil || state.State != StatePaused {
		t.Fatalf("State() = %q, %v", state, err)
	}
	if err := client.Pause(ctx); err != nil {
		t.Fatal(err)
	}
	if err := client.Resume(ctx); err != nil {
		t.Fatal(err)
	}
	if err := client.CreateFullSnapshot(ctx, "/snapshot", "/memory"); err != nil {
		t.Fatal(err)
	}
	if err := client.LoadSnapshotPaused(ctx, LoadSnapshotConfig{SnapshotPath: "/snapshot", MemoryBackend: MemoryBackend{BackendType: "File", BackendPath: "/memory"}, VsockOverride: &VsockOverride{UDSPath: "/tmp/restored.sock"}}); err != nil {
		t.Fatal(err)
	}
	mu.Lock()
	load := append([]byte(nil), requests[http.MethodPut+" /snapshot/load"]...)
	vsock := append([]byte(nil), requests[http.MethodPut+" /vsock"]...)
	wrongVsockPath := requests[http.MethodPut+" /vsocks/vsock0"]
	mu.Unlock()
	if len(vsock) == 0 || len(wrongVsockPath) != 0 {
		t.Fatalf("vsock endpoint payloads: /vsock=%q /vsocks/vsock0=%q", vsock, wrongVsockPath)
	}
	var got map[string]any
	if err := json.Unmarshal(load, &got); err != nil {
		t.Fatal(err)
	}
	if got["resume_vm"] != false {
		t.Fatalf("resume_vm = %#v, want false", got["resume_vm"])
	}
	backend := got["mem_backend"].(map[string]any)
	if backend["backend_type"] != "File" {
		t.Fatalf("mem_backend = %#v", backend)
	}
	if got["vsock_override"].(map[string]any)["uds_path"] != "/tmp/restored.sock" {
		t.Fatalf("vsock_override = %#v", got["vsock_override"])
	}
	var lines []json.RawMessage
	for _, line := range bytes.Split(bytes.TrimSpace(trace.Bytes()), []byte{'\n'}) {
		lines = append(lines, line)
	}
	if len(lines) != 9 {
		t.Fatalf("trace records = %d, want 9: %s", len(lines), trace.String())
	}
	for _, line := range lines {
		if !json.Valid(line) {
			t.Fatalf("invalid trace line %q", line)
		}
	}
}

func TestConfigureDriveUsesExactEndpointAndPayload(t *testing.T) {
	listener, err := net.Listen("unix", filepath.Join(t.TempDir(), "firecracker.sock"))
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	if err := os.Chmod(listener.Addr().String(), 0o600); err != nil {
		t.Fatal(err)
	}
	type observedRequest struct {
		method      string
		path        string
		contentType string
		body        string
	}
	observed := make(chan observedRequest, 4)
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		observed <- observedRequest{
			method:      r.Method,
			path:        r.URL.Path,
			contentType: r.Header.Get("Content-Type"),
			body:        string(body),
		}
		w.WriteHeader(http.StatusNoContent)
	})}
	go server.Serve(listener)
	defer server.Shutdown(context.Background())
	client, err := NewClient(ClientConfig{
		SocketPath: listener.Addr().String(), ExpectedPeerPID: os.Getpid(),
	})
	if err != nil {
		t.Fatal(err)
	}
	tests := []struct {
		drive   Drive
		path    string
		payload string
	}{
		{
			drive:   Drive{DriveID: "rootfs_0", PathOnHost: "/proc/self/fd/6", IsRootDevice: true, IsReadOnly: false},
			path:    "/drives/rootfs_0",
			payload: `{"drive_id":"rootfs_0","path_on_host":"/proc/self/fd/6","is_root_device":true,"is_read_only":false}`,
		},
		{
			drive:   Drive{DriveID: "root-ro", PathOnHost: "/images/root.ext4", IsRootDevice: true, IsReadOnly: true},
			path:    "/drives/root-ro",
			payload: `{"drive_id":"root-ro","path_on_host":"/images/root.ext4","is_root_device":true,"is_read_only":true}`,
		},
		{
			drive:   Drive{DriveID: "data_ro", PathOnHost: "/images/data.img", IsRootDevice: false, IsReadOnly: true},
			path:    "/drives/data_ro",
			payload: `{"drive_id":"data_ro","path_on_host":"/images/data.img","is_root_device":false,"is_read_only":true}`,
		},
		{
			drive:   Drive{DriveID: "scratch9", PathOnHost: "/images/scratch.img", IsRootDevice: false, IsReadOnly: false},
			path:    "/drives/scratch9",
			payload: `{"drive_id":"scratch9","path_on_host":"/images/scratch.img","is_root_device":false,"is_read_only":false}`,
		},
	}
	for _, test := range tests {
		if err := client.ConfigureDrive(context.Background(), test.drive); err != nil {
			t.Fatalf("ConfigureDrive(%+v): %v", test.drive, err)
		}
		request := <-observed
		if request.method != http.MethodPut || request.path != test.path || request.contentType != "application/json" || request.body != test.payload {
			t.Fatalf("ConfigureDrive(%+v) request = %+v, want PUT %s application/json %s", test.drive, request, test.path, test.payload)
		}
	}
}

func TestConfigureDriveRejectsUnsafeIDAndHostPath(t *testing.T) {
	listener, err := net.Listen("unix", filepath.Join(t.TempDir(), "firecracker.sock"))
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	if err := os.Chmod(listener.Addr().String(), 0o600); err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	requests := 0
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		mu.Lock()
		requests++
		mu.Unlock()
		w.WriteHeader(http.StatusNoContent)
	})}
	go server.Serve(listener)
	defer server.Shutdown(context.Background())
	client, err := NewClient(ClientConfig{
		SocketPath: listener.Addr().String(), ExpectedPeerPID: os.Getpid(),
	})
	if err != nil {
		t.Fatal(err)
	}
	tests := []struct {
		name  string
		drive Drive
	}{
		{name: "empty ID", drive: Drive{PathOnHost: "/images/root.img"}},
		{name: "dot ID", drive: Drive{DriveID: ".", PathOnHost: "/images/root.img"}},
		{name: "dot-dot ID", drive: Drive{DriveID: "..", PathOnHost: "/images/root.img"}},
		{name: "path traversal ID", drive: Drive{DriveID: "../root", PathOnHost: "/images/root.img"}},
		{name: "slash ID", drive: Drive{DriveID: "root/drive", PathOnHost: "/images/root.img"}},
		{name: "backslash ID", drive: Drive{DriveID: `root\drive`, PathOnHost: "/images/root.img"}},
		{name: "encoded slash ID", drive: Drive{DriveID: "root%2fdrive", PathOnHost: "/images/root.img"}},
		{name: "query ID", drive: Drive{DriveID: "root?x=1", PathOnHost: "/images/root.img"}},
		{name: "fragment ID", drive: Drive{DriveID: "root#x", PathOnHost: "/images/root.img"}},
		{name: "space ID", drive: Drive{DriveID: "root drive", PathOnHost: "/images/root.img"}},
		{name: "control ID", drive: Drive{DriveID: "root\n", PathOnHost: "/images/root.img"}},
		{name: "NUL ID", drive: Drive{DriveID: "root\x00drive", PathOnHost: "/images/root.img"}},
		{name: "non-ASCII ID", drive: Drive{DriveID: "røøt", PathOnHost: "/images/root.img"}},
		{name: "empty host path", drive: Drive{DriveID: "root"}},
		{name: "relative host path", drive: Drive{DriveID: "root", PathOnHost: "images/root.img"}},
		{name: "relative traversal host path", drive: Drive{DriveID: "root", PathOnHost: "../root.img"}},
		{name: "absolute traversal host path", drive: Drive{DriveID: "root", PathOnHost: "/images/../root.img"}},
		{name: "double-slash host path", drive: Drive{DriveID: "root", PathOnHost: "/images//root.img"}},
		{name: "trailing-slash host path", drive: Drive{DriveID: "root", PathOnHost: "/images/root.img/"}},
		{name: "NUL host path", drive: Drive{DriveID: "root", PathOnHost: "/images/root\x00.img"}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if err := client.ConfigureDrive(context.Background(), test.drive); err == nil {
				t.Fatalf("ConfigureDrive(%+v) accepted unsafe input", test.drive)
			}
		})
	}
	mu.Lock()
	defer mu.Unlock()
	if requests != 0 {
		t.Fatalf("invalid drive configurations made %d API requests", requests)
	}
}

func TestClientRejectsOversizedAndWrongStatus(t *testing.T) {
	listener, err := net.Listen("unix", filepath.Join(t.TempDir(), "api.sock"))
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	if err := os.Chmod(listener.Addr().String(), 0o600); err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/machine-config" {
			w.WriteHeader(http.StatusConflict)
			_, _ = w.Write([]byte(`conflict`))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(bytes.Repeat([]byte{'x'}, 33))
	})}
	go server.Serve(listener)
	defer server.Shutdown(context.Background())
	client, err := NewClient(ClientConfig{SocketPath: listener.Addr().String(), Timeout: time.Second, MaxResponseBytes: 32, ExpectedPeerPID: os.Getpid()})
	if err != nil {
		t.Fatal(err)
	}
	err = client.ConfigureMachine(context.Background(), MachineConfig{VCPUCount: 1, MemSizeMiB: 1})
	var httpErr *HTTPError
	if !errorsAs(err, &httpErr) || httpErr.StatusCode != http.StatusConflict {
		t.Fatalf("wrong-status error = %v", err)
	}
	_, err = client.State(context.Background())
	var tooLarge *ResponseTooLargeError
	if !errorsAs(err, &tooLarge) {
		t.Fatalf("oversized response error = %v", err)
	}
}

// Keeping this local avoids obscuring the behavior being asserted above with
// another imported helper package.
func errorsAs(err error, target any) bool {
	return errors.As(err, target)
}

func TestLoadSnapshotPausedRejectsResumeAndNonFileMemory(t *testing.T) {
	listener, err := net.Listen("unix", filepath.Join(t.TempDir(), "api.sock"))
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	if err := os.Chmod(listener.Addr().String(), 0o600); err != nil {
		t.Fatal(err)
	}
	client, err := NewClient(ClientConfig{SocketPath: listener.Addr().String(), ExpectedPeerPID: os.Getpid()})
	if err != nil {
		t.Fatal(err)
	}
	if err := client.LoadSnapshotPaused(context.Background(), LoadSnapshotConfig{Resume: true, SnapshotPath: "a", MemoryBackend: MemoryBackend{BackendType: "File", BackendPath: "b"}}); err == nil {
		t.Fatal("resume=true was accepted")
	}
	if err := client.LoadSnapshotPaused(context.Background(), LoadSnapshotConfig{SnapshotPath: "a", MemoryBackend: MemoryBackend{BackendType: "Uffd", BackendPath: "b"}}); err == nil {
		t.Fatal("non-File memory backend was accepted")
	}
}

func TestClientRejectsSocketReplacementAndWrongPeerPID(t *testing.T) {
	path := filepath.Join(t.TempDir(), "api.sock")
	listener, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}
	client, err := NewClient(ClientConfig{SocketPath: path, ExpectedPeerPID: os.Getpid()})
	if err != nil {
		t.Fatal(err)
	}
	listener.(*net.UnixListener).SetUnlinkOnClose(false)
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	replacement, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer replacement.Close()
	defer listener.Close()
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}
	_, err = client.State(context.Background())
	if err == nil || !strings.Contains(err.Error(), "identity changed") {
		t.Fatalf("replacement error = %v", err)
	}

	wrongPeer, err := NewClient(ClientConfig{SocketPath: path, ExpectedPeerPID: os.Getpid() + 1})
	if err != nil {
		t.Fatal(err)
	}
	_, err = wrongPeer.State(context.Background())
	if err == nil || !strings.Contains(err.Error(), "peer PID") {
		t.Fatalf("wrong peer PID error = %v", err)
	}
}

type failingTraceWriter struct{ calls int }

func (w *failingTraceWriter) Write([]byte) (int, error) {
	w.calls++
	return 0, errors.New("trace storage unavailable")
}

type shortTraceWriter struct{}

func (shortTraceWriter) Write(data []byte) (int, error) { return len(data) - 1, nil }

func TestClientTraceFailureStopsWithoutRetry(t *testing.T) {
	listener, err := net.Listen("unix", filepath.Join(t.TempDir(), "api.sock"))
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	if err := os.Chmod(listener.Addr().String(), 0o600); err != nil {
		t.Fatal(err)
	}
	var calls int
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { calls++; w.WriteHeader(http.StatusNoContent) })}
	go server.Serve(listener)
	defer server.Shutdown(context.Background())
	writer := &failingTraceWriter{}
	client, err := NewClient(ClientConfig{SocketPath: listener.Addr().String(), ExpectedPeerPID: os.Getpid(), Trace: writer})
	if err != nil {
		t.Fatal(err)
	}
	err = client.ConfigureMachine(context.Background(), MachineConfig{VCPUCount: 1, MemSizeMiB: 1})
	var traceErr *TraceError
	if !errors.As(err, &traceErr) || calls != 1 {
		t.Fatalf("first trace failure = %v, calls=%d", err, calls)
	}
	if err := client.ConfigureMachine(context.Background(), MachineConfig{VCPUCount: 1, MemSizeMiB: 1}); !errors.As(err, &traceErr) || calls != 1 {
		t.Fatalf("later call = %v, calls=%d", err, calls)
	}
	if err := client.Close(); !errors.As(err, &traceErr) {
		t.Fatalf("Close() = %v", err)
	}
}

func TestClientTraceShortWriteStops(t *testing.T) {
	listener, err := net.Listen("unix", filepath.Join(t.TempDir(), "api.sock"))
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	if err := os.Chmod(listener.Addr().String(), 0o600); err != nil {
		t.Fatal(err)
	}
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNoContent) })}
	go server.Serve(listener)
	defer server.Shutdown(context.Background())
	client, err := NewClient(ClientConfig{SocketPath: listener.Addr().String(), ExpectedPeerPID: os.Getpid(), Trace: shortTraceWriter{}})
	if err != nil {
		t.Fatal(err)
	}
	err = client.ConfigureMachine(context.Background(), MachineConfig{VCPUCount: 1, MemSizeMiB: 1})
	var traceErr *TraceError
	if !errors.As(err, &traceErr) || !errors.Is(err, io.ErrShortWrite) {
		t.Fatalf("short trace write = %v", err)
	}
}

func TestMain(m *testing.M) { os.Exit(m.Run()) }
