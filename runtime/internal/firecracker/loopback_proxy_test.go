package firecracker

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

func TestLoopbackProxyForwardsToOnlyFixedTargetAndAudits(t *testing.T) {
	directory := loopbackProxyPrivateDirectory(t)
	target, accepted := loopbackProxyEchoTarget(t)
	var audit bytes.Buffer
	path := filepath.Join(directory, "sandbox.sock")
	proxy, err := StartLoopbackProxy(LoopbackProxyConfig{
		SocketPath: path, TargetAddress: target, AuditLog: &audit,
		DialTimeout: time.Second, DrainTimeout: 100 * time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	if proxy.SocketPath() != path || proxy.TargetAddress() != target {
		t.Fatalf("proxy endpoints = %q -> %q, want %q -> %q", proxy.SocketPath(), proxy.TargetAddress(), path, target)
	}
	info, err := os.Lstat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0o600 {
		t.Fatalf("proxy socket mode = %v, want private 0600 socket", info.Mode())
	}

	client, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	if err := client.SetDeadline(time.Now().Add(2 * time.Second)); err != nil {
		t.Fatal(err)
	}
	request := []byte("loopback HTTP fixture")
	if _, err := client.Write(request); err != nil {
		t.Fatal(err)
	}
	if err := client.CloseWrite(); err != nil {
		t.Fatal(err)
	}
	reply, err := io.ReadAll(client)
	if err != nil {
		t.Fatal(err)
	}
	_ = client.Close()
	if !bytes.Equal(reply, request) {
		t.Fatalf("proxy reply = %q, want %q", reply, request)
	}
	if accepted.Load() != 1 {
		t.Fatalf("fixed target accepted %d connections, want 1", accepted.Load())
	}
	if err := proxy.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("proxy socket remained after Close: %v", err)
	}

	var events []loopbackProxyAuditEvent
	for _, line := range strings.Split(strings.TrimSpace(audit.String()), "\n") {
		var event loopbackProxyAuditEvent
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			t.Fatalf("invalid proxy JSONL audit event %q: %v", line, err)
		}
		events = append(events, event)
	}
	if len(events) != 2 || events[0].Event != "accept" || events[1].Event != "bytes" {
		t.Fatalf("proxy audit events = %+v, want accept then bytes", events)
	}
	for _, event := range events {
		if event.Target != target || event.Time.IsZero() || event.SocketDevice == 0 || event.SocketInode == 0 {
			t.Fatalf("proxy audit event lacks fixed identity: %+v", event)
		}
	}
	if events[0].PID != os.Getpid() || events[0].UID != uint32(os.Geteuid()) || events[0].GID != uint32(os.Getegid()) {
		t.Fatalf("accept credentials = %d/%d/%d, want %d/%d/%d", events[0].PID, events[0].UID, events[0].GID, os.Getpid(), os.Geteuid(), os.Getegid())
	}
	if events[1].ClientToTarget != int64(len(request)) || events[1].TargetToClient != int64(len(request)) {
		t.Fatalf("byte audit = %+v, want %d bytes each way", events[1], len(request))
	}
}

func TestValidateLoopbackProxyTargetAcceptsOnlyNumericLoopback(t *testing.T) {
	for input, want := range map[string]string{
		"127.0.0.1:1":     "127.0.0.1:1",
		"127.0.0.1:00080": "127.0.0.1:80",
		"[::1]:65535":     "[::1]:65535",
	} {
		got, err := validateLoopbackProxyTarget(input)
		if err != nil || got != want {
			t.Errorf("validate target %q = %q, %v; want %q", input, got, err, want)
		}
	}

	invalid := []string{
		"", "localhost:80", "example.com:80", "127.0.0.2:80", "0.0.0.0:80",
		"[::]:80", "[::ffff:127.0.0.1]:80", "[fe80::1%lo]:80",
		"http://127.0.0.1:80", "user@127.0.0.1:80", "127.0.0.1",
		"::1:80", "127.0.0.1:0", "127.0.0.1:65536", "127.0.0.1:-1",
		"127.0.0.1:+1", "127.0.0.1:http", "127.0.0.1:80/path",
		"127.0.0.1:\x001", "127.0.0.1:\n80", "[::1%lo]:80",
	}
	for _, input := range invalid {
		if got, err := validateLoopbackProxyTarget(input); err == nil {
			t.Errorf("accepted forbidden target %q as %q", input, got)
		}
	}
}

func TestStartLoopbackProxyRejectsUnsafeSocketTargetsAndTimeouts(t *testing.T) {
	target := "127.0.0.1:1"
	directory := loopbackProxyPrivateDirectory(t)
	for name, config := range map[string]LoopbackProxyConfig{
		"negative dial timeout":  {SocketPath: filepath.Join(directory, "dial.sock"), TargetAddress: target, DialTimeout: -1},
		"negative drain timeout": {SocketPath: filepath.Join(directory, "drain.sock"), TargetAddress: target, DrainTimeout: -1},
		"relative path":          {SocketPath: "proxy.sock", TargetAddress: target},
		"noncanonical path":      {SocketPath: directory + "/missing/../proxy.sock", TargetAddress: target},
		"control path":           {SocketPath: filepath.Join(directory, "proxy\n.sock"), TargetAddress: target},
		"long path":              {SocketPath: "/" + strings.Repeat("a", unixSocketPathLimit), TargetAddress: target},
	} {
		t.Run(name, func(t *testing.T) {
			if proxy, err := StartLoopbackProxy(config); err == nil {
				_ = proxy.Close()
				t.Fatalf("accepted unsafe config: %+v", config)
			}
		})
	}

	publicParent := t.TempDir()
	if err := os.Chmod(publicParent, 0o755); err != nil {
		t.Fatal(err)
	}
	if proxy, err := StartLoopbackProxy(LoopbackProxyConfig{SocketPath: filepath.Join(publicParent, "proxy.sock"), TargetAddress: target}); err == nil {
		_ = proxy.Close()
		t.Fatal("accepted a non-0700 socket parent")
	}

	realParent := loopbackProxyPrivateDirectory(t)
	linkRoot := loopbackProxyPrivateDirectory(t)
	linkedParent := filepath.Join(linkRoot, "linked")
	if err := os.Symlink(realParent, linkedParent); err != nil {
		t.Fatal(err)
	}
	if proxy, err := StartLoopbackProxy(LoopbackProxyConfig{SocketPath: filepath.Join(linkedParent, "proxy.sock"), TargetAddress: target}); err == nil {
		_ = proxy.Close()
		t.Fatal("accepted a symlinked socket parent")
	}

	t.Run("existing regular file", func(t *testing.T) {
		parent := loopbackProxyPrivateDirectory(t)
		path := filepath.Join(parent, "proxy.sock")
		if err := os.WriteFile(path, []byte("retain"), 0o600); err != nil {
			t.Fatal(err)
		}
		if proxy, err := StartLoopbackProxy(LoopbackProxyConfig{SocketPath: path, TargetAddress: target}); err == nil {
			_ = proxy.Close()
			t.Fatal("replaced an existing regular file")
		}
		data, err := os.ReadFile(path)
		if err != nil || string(data) != "retain" {
			t.Fatalf("existing target changed: %q, %v", data, err)
		}
	})

	t.Run("existing symlink", func(t *testing.T) {
		parent := loopbackProxyPrivateDirectory(t)
		path := filepath.Join(parent, "proxy.sock")
		if err := os.Symlink("missing.sock", path); err != nil {
			t.Fatal(err)
		}
		if proxy, err := StartLoopbackProxy(LoopbackProxyConfig{SocketPath: path, TargetAddress: target}); err == nil {
			_ = proxy.Close()
			t.Fatal("accepted an existing symlink")
		}
		if info, err := os.Lstat(path); err != nil || info.Mode()&os.ModeSymlink == 0 {
			t.Fatalf("existing symlink changed: %v, %v", info, err)
		}
	})

	t.Run("existing socket", func(t *testing.T) {
		parent := loopbackProxyPrivateDirectory(t)
		path := filepath.Join(parent, "proxy.sock")
		listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
		if err != nil {
			t.Fatal(err)
		}
		listener.SetUnlinkOnClose(false)
		defer func() { _ = listener.Close(); _ = os.Remove(path) }()
		if err := os.Chmod(path, 0o600); err != nil {
			t.Fatal(err)
		}
		if proxy, err := StartLoopbackProxy(LoopbackProxyConfig{SocketPath: path, TargetAddress: target}); err == nil {
			_ = proxy.Close()
			t.Fatal("replaced an existing Unix socket")
		}
		connection, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: path, Net: "unix"})
		if err != nil {
			t.Fatalf("existing socket was disrupted: %v", err)
		}
		_ = connection.Close()
	})
}

func TestLoopbackProxyRequiresExactSameProcessCredentials(t *testing.T) {
	proxy := &LoopbackProxy{peerPID: 101, peerUID: 202, peerGID: 303}
	if err := proxy.validatePeer(&unix.Ucred{Pid: 101, Uid: 202, Gid: 303}); err != nil {
		t.Fatalf("exact credentials rejected: %v", err)
	}
	for name, credential := range map[string]*unix.Ucred{
		"nil":       nil,
		"wrong pid": {Pid: 102, Uid: 202, Gid: 303},
		"wrong uid": {Pid: 101, Uid: 203, Gid: 303},
		"wrong gid": {Pid: 101, Uid: 202, Gid: 304},
	} {
		t.Run(name, func(t *testing.T) {
			if err := proxy.validatePeer(credential); err == nil {
				t.Fatalf("accepted credentials %+v", credential)
			}
		})
	}
}

func TestLoopbackProxyRejectsDifferentProcessBeforeTCPDial(t *testing.T) {
	directory := loopbackProxyPrivateDirectory(t)
	target, accepted := loopbackProxyEchoTarget(t)
	path := filepath.Join(directory, "proxy.sock")
	proxy, err := StartLoopbackProxy(LoopbackProxyConfig{
		SocketPath: path, TargetAddress: target, DrainTimeout: 100 * time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()

	command := exec.Command(os.Args[0], "-test.run=^TestLoopbackProxyPeerHelperProcess$")
	command.Env = append(os.Environ(), "LOOPBACK_PROXY_PEER_HELPER="+path)
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("different-process helper failed: %v: %s", err, output)
	}
	if accepted.Load() != 0 {
		t.Fatalf("different process reached TCP target %d times", accepted.Load())
	}
}

func TestLoopbackProxyPeerHelperProcess(t *testing.T) {
	path := os.Getenv("LOOPBACK_PROXY_PEER_HELPER")
	if path == "" {
		return
	}
	connection, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	_ = connection.SetDeadline(time.Now().Add(2 * time.Second))
	_, _ = connection.Write([]byte("must not reach TCP"))
	_ = connection.CloseWrite()
	_, _ = io.ReadAll(connection)
	_ = connection.Close()
}

func TestLoopbackProxyRevalidatesTargetAndSocketOnEveryConnection(t *testing.T) {
	t.Run("target became nonnumeric", func(t *testing.T) {
		directory := loopbackProxyPrivateDirectory(t)
		target, accepted := loopbackProxyEchoTarget(t)
		proxy, err := StartLoopbackProxy(LoopbackProxyConfig{
			SocketPath: filepath.Join(directory, "proxy.sock"), TargetAddress: target,
		})
		if err != nil {
			t.Fatal(err)
		}
		defer proxy.Close()
		_, port, err := net.SplitHostPort(target)
		if err != nil {
			t.Fatal(err)
		}
		proxy.endpointMu.Lock()
		proxy.config.TargetAddress = net.JoinHostPort("localhost", port)
		proxy.endpointMu.Unlock()
		loopbackProxyAttempt(t, proxy.SocketPath())
		if accepted.Load() != 0 {
			t.Fatalf("nonnumeric target was dialed %d times", accepted.Load())
		}
	})

	t.Run("socket lost private mode", func(t *testing.T) {
		directory := loopbackProxyPrivateDirectory(t)
		target, accepted := loopbackProxyEchoTarget(t)
		path := filepath.Join(directory, "proxy.sock")
		proxy, err := StartLoopbackProxy(LoopbackProxyConfig{SocketPath: path, TargetAddress: target})
		if err != nil {
			t.Fatal(err)
		}
		defer proxy.Close()
		if err := os.Chmod(path, 0o666); err != nil {
			t.Fatal(err)
		}
		loopbackProxyAttempt(t, path)
		if accepted.Load() != 0 {
			t.Fatalf("nonprivate socket forwarded %d times", accepted.Load())
		}
		if err := os.Chmod(path, 0o600); err != nil {
			t.Fatal(err)
		}
	})
}

func TestLoopbackProxyReplacementIsRejectedAndNeverRemoved(t *testing.T) {
	directory := loopbackProxyPrivateDirectory(t)
	target, accepted := loopbackProxyEchoTarget(t)
	path := filepath.Join(directory, "proxy.sock")
	proxy, err := StartLoopbackProxy(LoopbackProxyConfig{
		SocketPath: path, TargetAddress: target, DrainTimeout: 100 * time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	backup := filepath.Join(directory, "original.sock")
	if err := os.Rename(path, backup); err != nil {
		t.Fatal(err)
	}
	replacement, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	replacement.SetUnlinkOnClose(false)
	defer func() {
		_ = replacement.Close()
		_ = os.Remove(path)
		_ = os.Remove(backup)
	}()
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}

	// The original listening inode remains reachable at backup. Its handler
	// must revalidate the configured pathname and reject before the TCP dial.
	loopbackProxyAttempt(t, backup)
	if accepted.Load() != 0 {
		t.Fatalf("replaced proxy socket forwarded %d times", accepted.Load())
	}
	if err := proxy.Close(); err == nil || !strings.Contains(err.Error(), "replaced") {
		t.Fatalf("Close error = %v, want replacement refusal", err)
	}
	info, err := os.Lstat(path)
	if err != nil || info.Mode()&os.ModeSocket == 0 {
		t.Fatalf("replacement socket was removed: %v, %v", info, err)
	}
}

type loopbackProxyFailingWriter struct {
	short bool
}

func (writer loopbackProxyFailingWriter) Write(data []byte) (int, error) {
	if writer.short {
		return len(data) - 1, nil
	}
	return 0, errors.New("audit fixture failed")
}

type loopbackProxyBlockingWriter struct {
	entered chan struct{}
	release chan struct{}
	once    sync.Once
	writes  atomic.Int32
	closed  atomic.Bool
	late    atomic.Int32
}

func (writer *loopbackProxyBlockingWriter) Write(data []byte) (int, error) {
	writer.writes.Add(1)
	if writer.closed.Load() {
		writer.late.Add(1)
	}
	writer.once.Do(func() { close(writer.entered) })
	<-writer.release
	return len(data), nil
}

func TestLoopbackProxyAuditFailureFailsClosed(t *testing.T) {
	for name, writer := range map[string]io.Writer{
		"error": loopbackProxyFailingWriter{},
		"short": loopbackProxyFailingWriter{short: true},
	} {
		t.Run(name, func(t *testing.T) {
			directory := loopbackProxyPrivateDirectory(t)
			target, accepted := loopbackProxyEchoTarget(t)
			path := filepath.Join(directory, "proxy.sock")
			proxy, err := StartLoopbackProxy(LoopbackProxyConfig{
				SocketPath: path, TargetAddress: target, AuditLog: writer,
				DrainTimeout: 100 * time.Millisecond,
			})
			if err != nil {
				t.Fatal(err)
			}
			loopbackProxyAttempt(t, path)
			if accepted.Load() != 0 {
				t.Fatalf("audit failure forwarded %d connections", accepted.Load())
			}
			if err := proxy.Close(); err == nil || !strings.Contains(err.Error(), "audit") {
				t.Fatalf("Close error = %v, want audit failure", err)
			}
			if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
				t.Fatalf("failed proxy socket remained: %v", err)
			}
		})
	}
}

func TestLoopbackProxyDialAndCloseAreBounded(t *testing.T) {
	t.Run("idle", func(t *testing.T) {
		directory := loopbackProxyPrivateDirectory(t)
		target, targetAccepted, release := loopbackProxyHoldingTarget(t)
		proxy, err := StartLoopbackProxy(LoopbackProxyConfig{
			SocketPath: filepath.Join(directory, "proxy.sock"), TargetAddress: target,
			DialTimeout: time.Second, DrainTimeout: 100 * time.Millisecond,
		})
		if err != nil {
			t.Fatal(err)
		}
		defer proxy.Close()
		client, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: proxy.SocketPath(), Net: "unix"})
		if err != nil {
			t.Fatal(err)
		}
		if _, err := client.Write([]byte("held stream")); err != nil {
			t.Fatal(err)
		}
		select {
		case <-targetAccepted:
		case <-time.After(time.Second):
			t.Fatal("proxy did not establish held stream")
		}
		shortContext, shortCancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
		if err := proxy.WaitIdle(shortContext); !errors.Is(err, context.DeadlineExceeded) {
			shortCancel()
			t.Fatalf("WaitIdle with active pair = %v, want deadline", err)
		}
		shortCancel()
		_ = client.Close()
		close(release)
		idleContext, idleCancel := context.WithTimeout(context.Background(), time.Second)
		defer idleCancel()
		if err := proxy.WaitIdle(idleContext); err != nil {
			t.Fatalf("WaitIdle after pair completion = %v", err)
		}
	})

	t.Run("dial", func(t *testing.T) {
		directory := loopbackProxyPrivateDirectory(t)
		proxy, err := StartLoopbackProxy(LoopbackProxyConfig{
			SocketPath: filepath.Join(directory, "proxy.sock"), TargetAddress: "127.0.0.1:1",
			DialTimeout: 25 * time.Millisecond, DrainTimeout: 100 * time.Millisecond,
		})
		if err != nil {
			t.Fatal(err)
		}
		defer proxy.Close()
		entered := make(chan struct{})
		proxy.endpointMu.Lock()
		proxy.dial = func(ctx context.Context, _, _ string) (net.Conn, error) {
			close(entered)
			<-ctx.Done()
			return nil, ctx.Err()
		}
		proxy.endpointMu.Unlock()
		start := time.Now()
		client, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: proxy.SocketPath(), Net: "unix"})
		if err != nil {
			t.Fatal(err)
		}
		_ = client.SetDeadline(time.Now().Add(time.Second))
		_, _ = client.Write([]byte("request"))
		<-entered
		_, _ = io.ReadAll(client)
		_ = client.Close()
		elapsed := time.Since(start)
		if elapsed < 15*time.Millisecond || elapsed > 500*time.Millisecond {
			t.Fatalf("bounded dial elapsed = %v", elapsed)
		}
	})

	t.Run("close", func(t *testing.T) {
		directory := loopbackProxyPrivateDirectory(t)
		target, targetAccepted, release := loopbackProxyHoldingTarget(t)
		path := filepath.Join(directory, "proxy.sock")
		proxy, err := StartLoopbackProxy(LoopbackProxyConfig{
			SocketPath: path, TargetAddress: target,
			DialTimeout: time.Second, DrainTimeout: 30 * time.Millisecond,
		})
		if err != nil {
			t.Fatal(err)
		}
		client, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: path, Net: "unix"})
		if err != nil {
			t.Fatal(err)
		}
		defer client.Close()
		if _, err := client.Write([]byte("held stream")); err != nil {
			t.Fatal(err)
		}
		select {
		case <-targetAccepted:
		case <-time.After(time.Second):
			t.Fatal("proxy did not establish held TCP stream")
		}
		start := time.Now()
		closeErr := proxy.Close()
		elapsed := time.Since(start)
		close(release)
		if closeErr == nil || !strings.Contains(closeErr.Error(), "drain timed out") {
			t.Fatalf("Close error = %v, want bounded drain timeout", closeErr)
		}
		if elapsed < 20*time.Millisecond || elapsed > 500*time.Millisecond {
			t.Fatalf("bounded Close elapsed = %v", elapsed)
		}
		if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("socket remained after bounded Close: %v", err)
		}
	})

	t.Run("blocked audit writer", func(t *testing.T) {
		directory := loopbackProxyPrivateDirectory(t)
		writer := &loopbackProxyBlockingWriter{entered: make(chan struct{}), release: make(chan struct{})}
		path := filepath.Join(directory, "proxy.sock")
		proxy, err := StartLoopbackProxy(LoopbackProxyConfig{
			SocketPath: path, TargetAddress: "127.0.0.1:1", AuditLog: writer,
			DialTimeout: time.Second, DrainTimeout: 30 * time.Millisecond,
		})
		if err != nil {
			t.Fatal(err)
		}
		client, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: path, Net: "unix"})
		if err != nil {
			t.Fatal(err)
		}
		defer client.Close()
		select {
		case <-writer.entered:
		case <-time.After(time.Second):
			t.Fatal("proxy did not enter audit writer")
		}
		start := time.Now()
		closeErr := proxy.Close()
		elapsed := time.Since(start)
		if closeErr == nil || !strings.Contains(closeErr.Error(), "drain timed out") {
			t.Fatalf("Close error = %v, want blocked-handler timeout", closeErr)
		}
		if elapsed < 20*time.Millisecond || elapsed > 500*time.Millisecond {
			t.Fatalf("Close with blocked audit elapsed = %v", elapsed)
		}
		if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("socket remained after blocked-audit Close: %v", err)
		}
		shortContext, shortCancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
		if err := proxy.Wait(shortContext); !errors.Is(err, context.DeadlineExceeded) {
			shortCancel()
			t.Fatalf("Wait before audit release = %v, want deadline", err)
		}
		shortCancel()
		close(writer.release)
		waitContext, waitCancel := context.WithTimeout(context.Background(), time.Second)
		if err := proxy.Wait(waitContext); err != nil {
			waitCancel()
			t.Fatalf("Wait after audit release = %v", err)
		}
		waitCancel()
		writer.closed.Store(true)
		time.Sleep(10 * time.Millisecond)
		if writer.late.Load() != 0 || writer.writes.Load() == 0 {
			t.Fatalf("audit writes total=%d after Wait=%d", writer.writes.Load(), writer.late.Load())
		}
	})
}

func loopbackProxyPrivateDirectory(t *testing.T) string {
	t.Helper()
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	return directory
}

func loopbackProxyEchoTarget(t *testing.T) (string, *atomic.Int32) {
	t.Helper()
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	accepted := new(atomic.Int32)
	var connections sync.WaitGroup
	acceptDone := make(chan struct{})
	go func() {
		defer close(acceptDone)
		for {
			connection, err := listener.Accept()
			if err != nil {
				return
			}
			accepted.Add(1)
			connections.Add(1)
			go func() {
				defer connections.Done()
				defer connection.Close()
				_, _ = io.Copy(connection, connection)
			}()
		}
	}()
	t.Cleanup(func() {
		_ = listener.Close()
		<-acceptDone
		connections.Wait()
	})
	return listener.Addr().String(), accepted
}

func loopbackProxyHoldingTarget(t *testing.T) (string, <-chan struct{}, chan struct{}) {
	t.Helper()
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	accepted := make(chan struct{})
	release := make(chan struct{})
	go func() {
		connection, err := listener.Accept()
		if err != nil {
			return
		}
		close(accepted)
		<-release
		_ = connection.Close()
	}()
	t.Cleanup(func() { _ = listener.Close() })
	return listener.Addr().String(), accepted, release
}

func loopbackProxyAttempt(t *testing.T, path string) {
	t.Helper()
	connection, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	_ = connection.SetDeadline(time.Now().Add(time.Second))
	_, _ = connection.Write([]byte("must not forward"))
	_ = connection.CloseWrite()
	_, _ = io.ReadAll(connection)
	_ = connection.Close()
}
