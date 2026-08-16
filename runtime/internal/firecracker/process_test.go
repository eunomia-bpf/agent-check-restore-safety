package firecracker

import (
	"context"
	"flag"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestHelperFirecrackerProcess(t *testing.T) {
	if os.Getenv("GO_WANT_FIRECRACKER_HELPER") != "1" {
		return
	}
	var socket string
	exitAfterAccept := false
	for index, arg := range os.Args {
		if arg == "--api-sock" && index+1 < len(os.Args) {
			socket = os.Args[index+1]
		}
		if arg == "--helper-exit-after-accept" {
			exitAfterAccept = true
		}
	}
	if socket == "" {
		os.Exit(22)
	}
	listener, err := net.Listen("unix", socket)
	if err != nil {
		os.Exit(23)
	}
	defer listener.Close()
	for {
		connection, err := listener.Accept()
		if err != nil {
			return
		}
		_ = connection.Close()
		if exitAfterAccept {
			return
		}
	}
}

func testExecutableSHA256(t *testing.T, path string) string {
	t.Helper()
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	hash, err := sha256OpenFile(file)
	if err != nil {
		t.Fatal(err)
	}
	return hash
}

func TestStartProcessVerifiesIdentityWaitsSocketAndTerminates(t *testing.T) {
	if flag.Lookup("test.run") == nil {
		t.Skip("not running under go test")
	}
	socket := filepath.Join(t.TempDir(), "firecracker.sock")
	process, err := StartProcess(context.Background(), ProcessConfig{
		Binary: os.Args[0], ExecutableSHA256: testExecutableSHA256(t, os.Args[0]), APISocket: socket, ID: "vm-1",
		Args:           []string{"-test.run=^TestHelperFirecrackerProcess$", "--"},
		Env:            append(os.Environ(), "GO_WANT_FIRECRACKER_HELPER=1"),
		StartupTimeout: time.Second, TerminationTimeout: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	identity := process.Identity()
	if identity.PID <= 0 || identity.Executable == "" || identity.Inode == 0 || len(identity.ExecutableSHA256) != 64 || identity.StartTimeTicks == 0 {
		t.Fatalf("identity = %+v", identity)
	}
	if err := process.VerifyIdentity(); err != nil {
		t.Fatal(err)
	}
	info, err := os.Lstat(socket)
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("API socket protection = %v, %v", info, err)
	}
	disposition, err := process.TerminateWithDisposition(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if disposition != TerminationBySupervisor {
		t.Fatalf("termination disposition = %q", disposition)
	}
	select {
	case <-process.waitDone:
	default:
		t.Fatal("process was not reaped")
	}
}

func TestVerifyIdentityRejectsHashAndStartTimeChanges(t *testing.T) {
	socket := filepath.Join(t.TempDir(), "firecracker.sock")
	process, err := StartProcess(context.Background(), ProcessConfig{
		Binary: os.Args[0], ExecutableSHA256: testExecutableSHA256(t, os.Args[0]), APISocket: socket, ID: "vm-identity",
		Args: []string{"-test.run=^TestHelperFirecrackerProcess$", "--"}, Env: append(os.Environ(), "GO_WANT_FIRECRACKER_HELPER=1"),
		StartupTimeout: time.Second, TerminationTimeout: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer process.Terminate(context.Background())
	process.mu.Lock()
	hash := process.identity.ExecutableSHA256
	process.identity.ExecutableSHA256 = strings.Repeat("0", 64)
	process.mu.Unlock()
	if err := process.VerifyIdentity(); err == nil {
		t.Fatal("VerifyIdentity accepted a changed executable hash")
	}
	process.mu.Lock()
	process.identity.ExecutableSHA256 = hash
	startTime := process.identity.StartTimeTicks
	process.identity.StartTimeTicks++
	process.mu.Unlock()
	if err := process.VerifyIdentity(); err == nil {
		t.Fatal("VerifyIdentity accepted a changed start time")
	}
	process.mu.Lock()
	process.identity.StartTimeTicks = startTime
	process.mu.Unlock()
	if err := process.VerifyIdentity(); err != nil {
		t.Fatalf("restored identity rejected: %v", err)
	}
}

func TestStartProcessRejectsExistingSocket(t *testing.T) {
	socket := filepath.Join(t.TempDir(), "existing.sock")
	listener, err := net.Listen("unix", socket)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	_, err = StartProcess(context.Background(), ProcessConfig{Binary: os.Args[0], ExecutableSHA256: testExecutableSHA256(t, os.Args[0]), APISocket: socket, ID: "vm-1"})
	if err == nil {
		t.Fatal("pre-existing socket was accepted")
	}
}

func TestReservedArgumentsCannotChangeIdentityOrSeccomp(t *testing.T) {
	for _, argument := range []string{
		"--api-sock", "--api-sock=/tmp/other.sock", "--id=other",
		"--no-seccomp", "--no-seccomp=true", "--seccomp-filter",
		"--seccomp-filter=/tmp/filter.json",
	} {
		if err := rejectReservedArgs([]string{argument}); err == nil {
			t.Errorf("reserved argument %q was accepted", argument)
		}
	}
}

func TestStartProcessRejectsSocketParentWithSymlinkAncestor(t *testing.T) {
	base := t.TempDir()
	target := filepath.Join(base, "target")
	if err := os.Mkdir(target, 0o700); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(base, "link")
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
	_, err := StartProcess(context.Background(), ProcessConfig{Binary: os.Args[0], ExecutableSHA256: testExecutableSHA256(t, os.Args[0]), APISocket: filepath.Join(link, "api.sock"), ID: "vm-link"})
	if err == nil || !strings.Contains(err.Error(), "traverse a symlink") {
		t.Fatalf("symlink ancestor error = %v", err)
	}
}

func TestStartProcessExecutesSealedVerifiedCopy(t *testing.T) {
	directory := t.TempDir()
	binary := filepath.Join(directory, "firecracker")
	contents, err := os.ReadFile(os.Args[0])
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(binary, contents, 0o700); err != nil {
		t.Fatal(err)
	}
	process, err := StartProcess(context.Background(), ProcessConfig{
		Binary: binary, ExecutableSHA256: testExecutableSHA256(t, binary),
		APISocket: filepath.Join(directory, "api.sock"), ID: "vm-sealed",
		Args:           []string{"-test.run=^TestHelperFirecrackerProcess$", "--"},
		Env:            append(os.Environ(), "GO_WANT_FIRECRACKER_HELPER=1"),
		StartupTimeout: time.Second, TerminationTimeout: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer process.Terminate(context.Background())
	if err := os.WriteFile(binary, []byte("#!/bin/sh\nexit 0\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := process.VerifyIdentity(); err != nil {
		t.Fatalf("sealed executable identity changed with source path: %v", err)
	}
}

func TestTerminateObservesCleanPriorExit(t *testing.T) {
	socket := filepath.Join(t.TempDir(), "firecracker.sock")
	process, err := StartProcess(context.Background(), ProcessConfig{
		Binary: os.Args[0], ExecutableSHA256: testExecutableSHA256(t, os.Args[0]), APISocket: socket, ID: "vm-self-exit",
		Args:           []string{"-test.run=^TestHelperFirecrackerProcess$", "--", "--helper-exit-after-accept"},
		Env:            append(os.Environ(), "GO_WANT_FIRECRACKER_HELPER=1"),
		StartupTimeout: time.Second, TerminationTimeout: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	select {
	case <-process.waitDone:
	case <-time.After(3 * time.Second):
		t.Fatal("helper did not exit")
	}
	disposition, err := process.TerminateWithDisposition(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if disposition != TerminationAlreadyExited {
		t.Fatalf("termination disposition = %q", disposition)
	}
}

func TestStartProcessRejectsExecutableHashMismatch(t *testing.T) {
	_, err := StartProcess(context.Background(), ProcessConfig{
		Binary: os.Args[0], ExecutableSHA256: strings.Repeat("0", 64),
		APISocket: filepath.Join(t.TempDir(), "api.sock"), ID: "vm-wrong-hash",
	})
	if err == nil || !strings.Contains(err.Error(), "SHA-256") {
		t.Fatalf("hash mismatch error = %v", err)
	}
}
