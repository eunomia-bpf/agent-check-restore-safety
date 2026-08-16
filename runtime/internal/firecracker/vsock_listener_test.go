package firecracker

import (
	"context"
	"errors"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestVsockListenerAcceptsOnlyConfiguredProcess(t *testing.T) {
	directory := gatePrivateDirectory(t)
	listener, err := ArmVsockListener(VsockListenerConfig{
		BasePath: filepath.Join(directory, "agent"), Port: 7000,
		FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	if listener.SocketPath() != filepath.Join(directory, "agent_7000") {
		t.Fatalf("socket path = %q", listener.SocketPath())
	}
	client, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: listener.SocketPath(), Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	accepted, err := listener.Accept(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer accepted.Close()
	if _, err := client.Write([]byte("x")); err != nil {
		t.Fatal(err)
	}
	buffer := make([]byte, 1)
	if _, err := accepted.Read(buffer); err != nil || string(buffer) != "x" {
		t.Fatalf("accepted stream read %q err=%v", buffer, err)
	}
}

func TestVsockListenerRejectsWrongPIDAndIdentityLoss(t *testing.T) {
	directory := gatePrivateDirectory(t)
	wrong, err := ArmVsockListener(VsockListenerConfig{
		BasePath: filepath.Join(directory, "wrong"), Port: 7001,
		FirecrackerPID: os.Getpid() + 100000, VerifyProcess: testProcessVerifier,
	})
	if err != nil {
		t.Fatal(err)
	}
	client, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: wrong.SocketPath(), Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if _, err := wrong.Accept(ctx); err == nil || !strings.Contains(err.Error(), "peer PID") {
		t.Fatalf("wrong PID accept = %v", err)
	}
	_ = client.Close()
	_ = wrong.Close()

	live := true
	verify := func() error {
		if !live {
			return errors.New("identity lost")
		}
		return nil
	}
	lost, err := ArmVsockListener(VsockListenerConfig{
		BasePath: filepath.Join(directory, "lost"), Port: 7002,
		FirecrackerPID: os.Getpid(), VerifyProcess: verify,
	})
	if err != nil {
		t.Fatal(err)
	}
	live = false
	if _, err := lost.Accept(ctx); err == nil || !strings.Contains(err.Error(), "identity lost") {
		t.Fatalf("identity-loss accept = %v", err)
	}
	_ = lost.Close()
}

func TestVsockListenerContextCloseAndReplacementSafety(t *testing.T) {
	directory := gatePrivateDirectory(t)
	listener, err := ArmVsockListener(VsockListenerConfig{
		BasePath: filepath.Join(directory, "agent"), Port: 7003,
		FirecrackerPID: os.Getpid(), VerifyProcess: testProcessVerifier,
	})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if _, err := listener.Accept(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Accept timeout = %v", err)
	}

	original := listener.SocketPath()
	old := filepath.Join(directory, "old.sock")
	if err := os.Rename(original, old); err != nil {
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
	defer func() {
		_ = replacement.Close()
		_ = os.Remove(original)
		_ = os.Remove(old)
	}()
	if err := listener.Close(); err == nil {
		t.Fatal("Close accepted a replacement socket")
	}
	if info, err := os.Lstat(original); err != nil || info.Mode()&os.ModeSocket == 0 {
		t.Fatalf("replacement removed: info=%v err=%v", info, err)
	}
}
