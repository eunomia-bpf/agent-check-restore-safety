package firecracker

import (
	"bufio"
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
	"sync/atomic"
	"testing"
	"time"
)

func TestRelayForwardsOnlyFirecrackerPeerAndAudits(t *testing.T) {
	directory := privateDirectory(t)
	sandboxPath, sandboxPID := childEchoSocket(t, directory, "sandbox.sock")
	var audit bytes.Buffer
	relay, err := Arm(RelayConfig{
		Generation: 7, BasePath: filepath.Join(directory, "fc-v7"), Port: 17007,
		FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier, SandboxSocket: sandboxPath, AuditLog: &audit,
		DrainTimeout: 100 * time.Millisecond,
	})
	if err != nil {
		t.Fatalf("Arm: %v", err)
	}
	defer relay.Close()
	if want := filepath.Join(directory, "fc-v7_17007"); relay.SocketPath() != want {
		t.Fatalf("relay path=%q, want %q", relay.SocketPath(), want)
	}
	info, err := os.Lstat(relay.SocketPath())
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 || info.Mode()&os.ModeSocket == 0 {
		t.Fatalf("relay socket mode=%v, want private Unix socket", info.Mode())
	}

	client, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: relay.SocketPath(), Net: "unix"})
	if err != nil {
		t.Fatalf("dial relay: %v", err)
	}
	if _, err := client.Write([]byte("guest request")); err != nil {
		t.Fatal(err)
	}
	if err := client.CloseWrite(); err != nil {
		t.Fatal(err)
	}
	got, err := io.ReadAll(client)
	if err != nil {
		t.Fatal(err)
	}
	_ = client.Close()
	if string(got) != "guest request" {
		t.Fatalf("reply=%q", got)
	}
	if err := relay.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}
	var events []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(audit.String()), "\n") {
		var event map[string]any
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			t.Fatalf("invalid JSONL %q: %v", line, err)
		}
		events = append(events, event)
	}
	if !hasEvent(events, "accept") || !hasEvent(events, "bytes") {
		t.Fatalf("audit events=%v, want accept and bytes", events)
	}
	for _, event := range events {
		if event["sandbox_device"].(float64) <= 0 || event["sandbox_inode"].(float64) <= 0 {
			t.Fatalf("audit event lacks pinned sandbox identity: %v", event)
		}
		if event["event"] == "bytes" {
			peerPID := int(event["sandbox_peer_pid"].(float64))
			if peerPID != sandboxPID || peerPID == os.Getpid() {
				t.Fatalf("sandbox peer PID=%d, want child server %d distinct from Firecracker peer %d", peerPID, sandboxPID, os.Getpid())
			}
		}
	}
}

func TestRelaySandboxHelperProcess(t *testing.T) {
	path := os.Getenv("FIRECRACKER_RELAY_SANDBOX_HELPER")
	if path == "" {
		return
	}
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	listener.SetUnlinkOnClose(false)
	defer func() { _ = listener.Close(); _ = os.Remove(path) }()
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stdout.Write([]byte("READY\n")); err != nil {
		t.Fatal(err)
	}
	connection, err := listener.AcceptUnix()
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	_, _ = io.Copy(connection, connection)
}

// This documents the Linux kernel fact the relay relies on: SO_PEERCRED on
// an accepted AF_UNIX stream identifies the connecting host process. The
// Firecracker vsock UDS backend is that connecting host process, not the
// guest. A change in that kernel behaviour must fail closed in verifyPeer.
func TestSOPEERCREDReportsConnectingProcessPID(t *testing.T) {
	directory := privateDirectory(t)
	path := filepath.Join(directory, "credential.sock")
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	listener.SetUnlinkOnClose(false)
	defer func() { _ = listener.Close(); _ = os.Remove(path) }()
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}
	accepted := make(chan *net.UnixConn, 1)
	go func() { connection, _ := listener.AcceptUnix(); accepted <- connection }()
	client, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	server := <-accepted
	defer server.Close()
	relay := &Relay{config: RelayConfig{FirecrackerPID: os.Getpid()}}
	if err := relay.verifyPeer(server); err != nil {
		t.Fatalf("SO_PEERCRED did not report the connector pid %d: %v", os.Getpid(), err)
	}
	pid, err := unixPeerPID(client)
	if err != nil {
		t.Fatalf("read server peer PID: %v", err)
	}
	if pid != os.Getpid() {
		t.Fatalf("server peer PID = %d, want %d", pid, os.Getpid())
	}
	relay.config.FirecrackerPID++
	if err := relay.verifyPeer(server); err == nil {
		t.Fatal("verifyPeer accepted a different PID")
	}
}

func TestRelayRejectsWrongPeerBeforeDialingSandbox(t *testing.T) {
	directory := privateDirectory(t)
	sandboxPath, accepted := echoSocket(t, directory, "sandbox.sock")
	relay, err := Arm(RelayConfig{
		Generation: 1, BasePath: filepath.Join(directory, "fc"), Port: 77,
		FirecrackerPID: os.Getpid() + 100000, VerifyProcess: testProcessVerifier, SandboxSocket: sandboxPath,
		DrainTimeout: 20 * time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer relay.Close()
	client, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: relay.SocketPath(), Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	_, _ = client.Write([]byte("must not reach sandbox"))
	_ = client.Close()
	time.Sleep(40 * time.Millisecond)
	if accepted.Load() != 0 {
		t.Fatalf("wrong peer reached sandbox %d times", accepted.Load())
	}
}

func TestRelayRejectsSandboxReplacementAfterArm(t *testing.T) {
	directory := privateDirectory(t)
	sandboxPath, oldAccepted := echoSocket(t, directory, "sandbox.sock")
	relay, err := Arm(RelayConfig{
		Generation: 2, BasePath: filepath.Join(directory, "fc"), Port: 78,
		FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier, SandboxSocket: sandboxPath, DrainTimeout: 20 * time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer relay.Close()
	backup := filepath.Join(directory, "old.sock")
	if err := os.Rename(sandboxPath, backup); err != nil {
		t.Fatal(err)
	}
	_, newAccepted := echoSocket(t, directory, "sandbox.sock")
	client, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: relay.SocketPath(), Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	_, _ = client.Write([]byte("must not reach replacement"))
	_ = client.Close()
	time.Sleep(40 * time.Millisecond)
	if oldAccepted.Load() != 0 || newAccepted.Load() != 0 {
		t.Fatalf("relay dialed replaced sandbox: old=%d new=%d", oldAccepted.Load(), newAccepted.Load())
	}
}

func TestArmRejectsUnsafeParentsAndPaths(t *testing.T) {
	directory := privateDirectory(t)
	sandboxPath, _ := echoSocket(t, directory, "sandbox.sock")
	config := RelayConfig{Generation: 1, BasePath: filepath.Join(directory, "fc"), Port: 9, FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier, SandboxSocket: sandboxPath}

	if err := os.Chmod(directory, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := Arm(config); err == nil {
		t.Fatal("Arm accepted a non-private parent")
	}
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	symlink := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(directory, symlink); err != nil {
		t.Fatal(err)
	}
	config.BasePath = filepath.Join(symlink, "fc")
	if _, err := Arm(config); err == nil {
		t.Fatal("Arm accepted a symlinked parent")
	}
	config.BasePath = "/" + strings.Repeat("a", unixSocketPathLimit)
	if _, err := Arm(config); err == nil {
		t.Fatal("Arm accepted a too-long path")
	}
}

func TestRelayAuditWriteFailureStopsForwardingAndCloseCleansUp(t *testing.T) {
	directory := privateDirectory(t)
	sandboxPath, accepted := echoSocket(t, directory, "sandbox.sock")
	relay, err := Arm(RelayConfig{
		Generation: 1, BasePath: filepath.Join(directory, "fc"), Port: 79,
		FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier, SandboxSocket: sandboxPath, AuditLog: failingAuditWriter{},
		DrainTimeout: 50 * time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	path := relay.SocketPath()
	connection, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	_, _ = connection.Write([]byte("must not forward after audit failure"))
	_ = connection.Close()
	time.Sleep(40 * time.Millisecond)
	if accepted.Load() != 0 {
		t.Fatalf("relay forwarded after audit failure: %d", accepted.Load())
	}
	if err := relay.Close(); err == nil || !strings.Contains(err.Error(), "audit") {
		t.Fatalf("Close error=%v, want audit failure", err)
	}
	if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("relay socket remained after failed audit cleanup: %v", err)
	}
}

func TestRelayRefusesReusedPIDBeforeSandboxDial(t *testing.T) {
	directory := privateDirectory(t)
	sandboxPath, accepted := echoSocket(t, directory, "sandbox.sock")
	var live atomic.Bool
	live.Store(true)
	verify := func() error {
		if !live.Load() {
			return errors.New("original VMM exited; PID was reused")
		}
		return nil
	}
	relay, err := Arm(RelayConfig{
		Generation: 1, BasePath: filepath.Join(directory, "fc"), Port: 80,
		FirecrackerPID: os.Getpid(), VerifyProcess: verify, SandboxSocket: sandboxPath,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer relay.Close()
	live.Store(false)
	client, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: relay.SocketPath(), Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	_, _ = client.Write([]byte("must not reach sandbox after PID reuse"))
	_ = client.Close()
	time.Sleep(40 * time.Millisecond)
	if accepted.Load() != 0 {
		t.Fatalf("reused PID reached sandbox %d times", accepted.Load())
	}
}

func TestArmRelayRequiresProcessVerifier(t *testing.T) {
	_, err := Arm(RelayConfig{
		Generation: 1, BasePath: filepath.Join(privateDirectory(t), "fc"), Port: 81,
		FirecrackerPID: os.Getpid(),
	})
	if err == nil || !strings.Contains(err.Error(), "identity verifier") {
		t.Fatalf("Arm relay without process verifier = %v, want refusal", err)
	}
}

func TestRelayCloseReportsForcedDrainAndWaitsForAuditSafety(t *testing.T) {
	directory := privateDirectory(t)
	sandboxPath, accepted := echoSocket(t, directory, "sandbox.sock")
	relay, err := Arm(RelayConfig{
		Generation: 1, BasePath: filepath.Join(directory, "fc"), Port: 82,
		FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier,
		SandboxSocket: sandboxPath, DrainTimeout: 20 * time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	client, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: relay.SocketPath(), Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	if _, err := client.Write([]byte("held relay stream")); err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(time.Second)
	for accepted.Load() == 0 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if accepted.Load() != 1 {
		t.Fatal("relay did not establish the held sandbox stream")
	}
	if err := relay.Close(); err == nil || !strings.Contains(err.Error(), "drain timed out") {
		t.Fatalf("Close error = %v, want forced-drain refusal", err)
	}
	waitContext, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := relay.Wait(waitContext); err != nil {
		t.Fatalf("Wait after forced pair close = %v", err)
	}
}

func privateDirectory(t *testing.T) string {
	t.Helper()
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	return directory
}

func echoSocket(t *testing.T, directory, name string) (string, *atomic.Int32) {
	t.Helper()
	path := filepath.Join(directory, name)
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	listener.SetUnlinkOnClose(false)
	if err := os.Chmod(path, 0o600); err != nil {
		_ = listener.Close()
		t.Fatal(err)
	}
	accepted := new(atomic.Int32)
	go func() {
		for {
			connection, err := listener.AcceptUnix()
			if err != nil {
				return
			}
			accepted.Add(1)
			go func() { _, _ = io.Copy(connection, connection); _ = connection.Close() }()
		}
	}()
	t.Cleanup(func() { _ = listener.Close(); _ = os.Remove(path) })
	return path, accepted
}

func childEchoSocket(t *testing.T, directory, name string) (string, int) {
	t.Helper()
	path := filepath.Join(directory, name)
	command := exec.Command(os.Args[0], "-test.run=^TestRelaySandboxHelperProcess$")
	command.Env = append(os.Environ(), "FIRECRACKER_RELAY_SANDBOX_HELPER="+path)
	stdout, err := command.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	var stderr bytes.Buffer
	command.Stderr = &stderr
	if err := command.Start(); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- command.Wait() }()
	t.Cleanup(func() {
		select {
		case err := <-done:
			if err != nil {
				t.Errorf("sandbox helper failed: %v: %s", err, stderr.Bytes())
			}
		case <-time.After(2 * time.Second):
			_ = command.Process.Kill()
			<-done
			t.Errorf("sandbox helper did not exit")
		}
	})
	ready := make(chan error, 1)
	go func() {
		line, err := bufio.NewReader(stdout).ReadString('\n')
		if err == nil && line != "READY\n" {
			err = errors.New("sandbox helper emitted an invalid readiness record")
		}
		ready <- err
	}()
	select {
	case err := <-ready:
		if err != nil {
			t.Fatalf("start sandbox helper: %v: %s", err, stderr.Bytes())
		}
	case <-time.After(2 * time.Second):
		t.Fatal("sandbox helper did not become ready")
	}
	return path, command.Process.Pid
}

func hasEvent(events []map[string]any, want string) bool {
	for _, event := range events {
		if event["event"] == want {
			return true
		}
	}
	return false
}
