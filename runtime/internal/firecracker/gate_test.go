package firecracker

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

type failingAuditWriter struct{ short bool }

func (w failingAuditWriter) Write([]byte) (int, error) {
	if w.short {
		return 0, nil
	}
	return 0, errors.New("audit disk failed")
}

func TestGateWaitReadyAllowAndWaitResult(t *testing.T) {
	directory := gatePrivateDirectory(t)
	var audit bytes.Buffer
	gate, err := ArmGate(GateConfig{
		Generation: 3, BasePath: filepath.Join(directory, "guest-v3"),
		FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier, AuditLog: &audit, DrainTimeout: 100 * time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer gate.Close()
	if want := filepath.Join(directory, "guest-v3_8000"); gate.SocketPath() != want {
		t.Fatalf("SocketPath=%q, want %q", gate.SocketPath(), want)
	}
	info, err := os.Lstat(gate.SocketPath())
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 || info.Mode()&os.ModeSocket == 0 {
		t.Fatalf("gate socket mode=%v, want private Unix socket", info.Mode())
	}

	ready := gateDial(t, gate)
	if _, err := ready.Write([]byte("READY\n")); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := gate.WaitReady(ctx); err != nil {
		t.Fatalf("WaitReady: %v", err)
	}
	if err := gate.Allow(); err != nil {
		t.Fatalf("Allow: %v", err)
	}
	goLine, err := io.ReadAll(ready)
	if err != nil {
		t.Fatal(err)
	}
	_ = ready.Close()
	if string(goLine) != "GO 3\n" {
		t.Fatalf("gate reply=%q, want GO 3", goLine)
	}

	resultConnection := gateDial(t, gate)
	if _, err := resultConnection.Write([]byte("{\"event\":\"RESULT\",\"status\":200,\"body\":{\"ok\":true}}\n")); err != nil {
		t.Fatal(err)
	}
	_ = resultConnection.Close()
	result, err := gate.WaitResult(ctx)
	if err != nil {
		t.Fatalf("WaitResult: %v", err)
	}
	if result.Event != "RESULT" || result.Status != 200 || string(result.Body) != `{"ok":true}` {
		t.Fatalf("result=%+v", result)
	}
	if err := gate.Close(); err != nil {
		t.Fatal(err)
	}
	var events []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(audit.String()), "\n") {
		var event map[string]any
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			t.Fatalf("invalid JSONL %q: %v", line, err)
		}
		events = append(events, event)
	}
	for _, want := range []string{"accept", "ready", "allow", "go", "result"} {
		if !hasEvent(events, want) {
			t.Fatalf("audit events=%v, missing %q", events, want)
		}
	}
}

func TestGateAllowBeforeReady(t *testing.T) {
	gate, err := ArmGate(GateConfig{Generation: 1, BasePath: filepath.Join(gatePrivateDirectory(t), "guest"), FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier})
	if err != nil {
		t.Fatal(err)
	}
	defer gate.Close()
	if err := gate.Allow(); err != nil {
		t.Fatal(err)
	}
	connection := gateDial(t, gate)
	if _, err := connection.Write([]byte("READY\n")); err != nil {
		t.Fatal(err)
	}
	line, err := io.ReadAll(connection)
	_ = connection.Close()
	if err != nil {
		t.Fatal(err)
	}
	if string(line) != "GO 1\n" {
		t.Fatalf("reply=%q", line)
	}
}

func TestGateRejectsWrongPeerAndStrictResult(t *testing.T) {
	directory := gatePrivateDirectory(t)
	wrong, err := ArmGate(GateConfig{Generation: 1, BasePath: filepath.Join(directory, "wrong"), FirecrackerPID: os.Getpid() + 100000, VerifyProcess: testProcessVerifier})
	if err != nil {
		t.Fatal(err)
	}
	connection := gateDial(t, wrong)
	_, _ = connection.Write([]byte("READY\n"))
	_ = connection.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	if err := wrong.WaitReady(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("wrong peer WaitReady error=%v", err)
	}
	_ = wrong.Close()

	gate, err := ArmGate(GateConfig{Generation: 1, BasePath: filepath.Join(directory, "strict"), FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier})
	if err != nil {
		t.Fatal(err)
	}
	defer gate.Close()
	ready := gateDial(t, gate)
	if _, err := ready.Write([]byte("READY\n")); err != nil {
		t.Fatal(err)
	}
	openCtx, openCancel := context.WithTimeout(context.Background(), time.Second)
	defer openCancel()
	if err := gate.WaitReady(openCtx); err != nil {
		t.Fatal(err)
	}
	if err := gate.Allow(); err != nil {
		t.Fatal(err)
	}
	if got, err := io.ReadAll(ready); err != nil || string(got) != "GO 1\n" {
		t.Fatalf("open gate reply=%q err=%v", got, err)
	}
	_ = ready.Close()
	connection = gateDial(t, gate)
	_, _ = connection.Write([]byte("{\"event\":\"RESULT\",\"status\":200,\"body\":{},\"extra\":1}\n"))
	_ = connection.Close()
	ctx, cancel = context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	if _, err := gate.WaitResult(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("unknown RESULT field was accepted: %v", err)
	}
	connection = gateDial(t, gate)
	_, _ = connection.Write([]byte("{\"event\":\"RESULT\",\"event\":\"RESULT\",\"status\":200,\"body\":{}}\n"))
	_ = connection.Close()
	ctx, cancel = context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	if _, err := gate.WaitResult(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("duplicate RESULT field was accepted: %v", err)
	}
}

func TestGateCloseIsBoundedAndDoesNotRemoveReplacement(t *testing.T) {
	directory := gatePrivateDirectory(t)
	gate, err := ArmGate(GateConfig{
		Generation: 1, BasePath: filepath.Join(directory, "guest"), FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier, DrainTimeout: 20 * time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	connection := gateDial(t, gate) // leave a partial event blocked in Read.
	start := time.Now()
	if err := gate.Close(); err != nil {
		t.Fatalf("Close with partial client: %v", err)
	}
	if elapsed := time.Since(start); elapsed > time.Second {
		t.Fatalf("Close was not bounded: %v", elapsed)
	}
	_ = connection.Close()

	gate, err = ArmGate(GateConfig{Generation: 1, BasePath: filepath.Join(directory, "replacement"), FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier})
	if err != nil {
		t.Fatal(err)
	}
	original := gate.SocketPath()
	if err := os.Rename(original, filepath.Join(directory, "old-gate.sock")); err != nil {
		t.Fatal(err)
	}
	replacement, err := net.ListenUnix("unix", &net.UnixAddr{Name: original, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	replacement.SetUnlinkOnClose(false)
	if err := os.Chmod(original, 0o600); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = replacement.Close(); _ = os.Remove(original) }()
	if err := gate.Close(); err == nil {
		t.Fatal("Close removed or accepted a replacement socket")
	}
	if info, err := os.Lstat(original); err != nil || info.Mode()&os.ModeSocket == 0 {
		t.Fatalf("replacement disappeared after Close: info=%v err=%v", info, err)
	}
}

func TestArmGateRejectsUnsafePaths(t *testing.T) {
	directory := gatePrivateDirectory(t)
	config := GateConfig{Generation: 1, BasePath: filepath.Join(directory, "guest"), FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier}
	if err := os.Chmod(directory, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := ArmGate(config); err == nil {
		t.Fatal("ArmGate accepted non-private parent")
	}
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	symlink := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(directory, symlink); err != nil {
		t.Fatal(err)
	}
	config.BasePath = filepath.Join(symlink, "guest")
	if _, err := ArmGate(config); err == nil {
		t.Fatal("ArmGate accepted symlink parent")
	}
	config.BasePath = "/" + strings.Repeat("a", unixSocketPathLimit)
	if _, err := ArmGate(config); err == nil {
		t.Fatal("ArmGate accepted a long Unix path")
	}
}

func TestGateAuditWriteFailureFailsStopAndCloseStillCleansUp(t *testing.T) {
	gate, err := ArmGate(GateConfig{Generation: 1, BasePath: filepath.Join(gatePrivateDirectory(t), "guest"), FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier, AuditLog: failingAuditWriter{short: true}})
	if err != nil {
		t.Fatal(err)
	}
	connection := gateDial(t, gate)
	_, _ = connection.Write([]byte("READY\n"))
	_ = connection.Close()
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := gate.WaitReady(ctx); err == nil || !strings.Contains(err.Error(), "audit") {
		t.Fatalf("WaitReady error=%v, want audit failure", err)
	}
	if err := gate.Allow(); err == nil || !strings.Contains(err.Error(), "audit") {
		t.Fatalf("Allow error=%v, want audit failure", err)
	}
	if _, err := gate.WaitResult(ctx); err == nil || !strings.Contains(err.Error(), "audit") {
		t.Fatalf("WaitResult error=%v, want audit failure", err)
	}
	path := gate.SocketPath()
	if err := gate.Close(); err == nil || !strings.Contains(err.Error(), "audit") {
		t.Fatalf("Close error=%v, want audit failure", err)
	}
	if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("gate socket remained after failed audit cleanup: %v", err)
	}
}

func testProcessVerifier() error { return nil }

func TestArmGateRequiresProcessVerifier(t *testing.T) {
	_, err := ArmGate(GateConfig{
		Generation: 1, BasePath: filepath.Join(gatePrivateDirectory(t), "guest"), FirecrackerPID: os.Getpid(),
	})
	if err == nil || !strings.Contains(err.Error(), "identity verifier") {
		t.Fatalf("ArmGate without process verifier = %v, want refusal", err)
	}
}

func TestArmGateRequiresGenerationRole(t *testing.T) {
	_, err := ArmGate(GateConfig{
		BasePath: filepath.Join(gatePrivateDirectory(t), "guest"), FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier,
	})
	if err == nil || !strings.Contains(err.Error(), "positive generation") {
		t.Fatalf("ArmGate without generation = %v, want refusal", err)
	}
}

func TestGateRefusesReusedPIDAfterReady(t *testing.T) {
	var live atomic.Bool
	live.Store(true)
	verify := func() error {
		if !live.Load() {
			return errors.New("original VMM exited; PID was reused")
		}
		return nil
	}
	gate, err := ArmGate(GateConfig{
		Generation: 1, BasePath: filepath.Join(gatePrivateDirectory(t), "guest"), FirecrackerPID: os.Getpid(), VerifyProcess: verify,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer gate.Close()
	connection := gateDial(t, gate)
	defer connection.Close()
	if _, err := connection.Write([]byte("READY\n")); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := gate.WaitReady(ctx); err != nil {
		t.Fatal(err)
	}
	live.Store(false)
	if err := gate.Allow(); err == nil || !strings.Contains(err.Error(), "identity changed") {
		t.Fatalf("Allow after process identity loss = %v, want refusal", err)
	}
	if err := connection.SetReadDeadline(time.Now().Add(50 * time.Millisecond)); err != nil {
		t.Fatal(err)
	}
	if data, err := io.ReadAll(connection); err == nil || len(data) != 0 {
		t.Fatalf("reused PID received gate data %q, err=%v", data, err)
	}
}

func gatePrivateDirectory(t *testing.T) string {
	t.Helper()
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	return directory
}

func gateDial(t *testing.T, gate *Gate) *net.UnixConn {
	t.Helper()
	connection, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: gate.SocketPath(), Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	return connection
}
