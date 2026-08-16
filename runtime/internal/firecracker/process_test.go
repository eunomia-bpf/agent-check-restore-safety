package firecracker

import (
	"context"
	"errors"
	"flag"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
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

func TestKillUsesPidfdAndTreatsSIGKILLAsSuccessfulLifecycle(t *testing.T) {
	process := startLifecycleTestProcess(t)
	actualPID := process.cmd.Process.Pid
	// Deliberately make the recorded numeric PID unusable. Kill must still
	// terminate the actual child through the pidfd and never consult this PID.
	process.mu.Lock()
	process.identity.PID = 1 << 30
	process.mu.Unlock()

	disposition, err := process.Kill(context.Background())
	if err != nil {
		t.Fatalf("Kill returned the SIGKILL exit status as an API failure: %v", err)
	}
	if disposition != TerminationBySupervisor {
		t.Fatalf("Kill disposition = %q", disposition)
	}
	if process.cmd.ProcessState == nil || process.cmd.ProcessState.Pid() != actualPID {
		t.Fatalf("reaped process state = %v, actual PID = %d", process.cmd.ProcessState, actualPID)
	}
	if signal := lifecycleExitSignal(t, process.Wait()); signal != syscall.SIGKILL {
		t.Fatalf("child exit signal = %v, want SIGKILL", signal)
	}
	process.mu.Lock()
	pidfd := process.pidfd
	process.mu.Unlock()
	if pidfd != -1 {
		t.Fatalf("pidfd remained open after reap: %d", pidfd)
	}
}

func TestKillReportsAlreadyExited(t *testing.T) {
	process := startLifecycleTestProcess(t, "--helper-exit-after-accept")
	select {
	case <-process.waitDone:
	case <-time.After(3 * time.Second):
		t.Fatal("helper did not exit")
	}
	disposition, err := process.Kill(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if disposition != TerminationAlreadyExited {
		t.Fatalf("Kill disposition = %q", disposition)
	}
	if err := process.Wait(); err != nil {
		t.Fatalf("clean prior exit = %v", err)
	}
}

func TestKillHonorsContextCanceledBeforeSignal(t *testing.T) {
	process := startLifecycleTestProcess(t)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	disposition, err := process.Kill(ctx)
	if disposition != "" || !errors.Is(err, context.Canceled) {
		t.Fatalf("Kill with canceled context = (%q, %v)", disposition, err)
	}
	select {
	case <-process.waitDone:
		t.Fatal("canceled Kill terminated the child")
	default:
	}
	if err := process.VerifyIdentity(); err != nil {
		t.Fatalf("child was not live after canceled Kill: %v", err)
	}
}

func TestConcurrentKillTerminateAndWait(t *testing.T) {
	process := startLifecycleTestProcess(t)
	const callers = 30
	type callResult struct {
		operation   string
		disposition TerminationDisposition
		err         error
	}
	start := make(chan struct{})
	results := make(chan callResult, callers)
	var group sync.WaitGroup
	for index := 0; index < callers; index++ {
		group.Add(1)
		go func(operation int) {
			defer group.Done()
			<-start
			switch operation % 3 {
			case 0:
				disposition, err := process.Kill(context.Background())
				results <- callResult{operation: "Kill", disposition: disposition, err: err}
			case 1:
				disposition, err := process.TerminateWithDisposition(context.Background())
				results <- callResult{operation: "Terminate", disposition: disposition, err: err}
			default:
				results <- callResult{operation: "Wait", err: process.Wait()}
			}
		}(index)
	}
	close(start)
	done := make(chan struct{})
	go func() {
		group.Wait()
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("concurrent lifecycle calls did not finish")
	}
	close(results)

	supervisorResults := 0
	for result := range results {
		switch result.operation {
		case "Kill", "Terminate":
			if result.err != nil {
				t.Errorf("%s error = %v", result.operation, result.err)
			}
			if result.disposition != TerminationBySupervisor && result.disposition != TerminationAlreadyExited {
				t.Errorf("%s disposition = %q", result.operation, result.disposition)
			}
			if result.disposition == TerminationBySupervisor {
				supervisorResults++
			}
		case "Wait":
			signal := lifecycleExitSignal(t, result.err)
			if signal != syscall.SIGTERM && signal != syscall.SIGKILL {
				t.Errorf("Wait exit signal = %v", signal)
			}
		}
	}
	if supervisorResults == 0 {
		t.Fatal("no lifecycle caller reported sending a signal")
	}
	process.mu.Lock()
	pidfd := process.pidfd
	process.mu.Unlock()
	if pidfd != -1 {
		t.Fatalf("pidfd remained open after concurrent reap: %d", pidfd)
	}
}

func TestProcessDoneAndWaitContextObserveExactReap(t *testing.T) {
	process := startLifecycleTestProcess(t)
	shortContext, shortCancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	if err := process.WaitContext(shortContext); !errors.Is(err, context.DeadlineExceeded) {
		shortCancel()
		t.Fatalf("WaitContext before exit = %v, want deadline", err)
	}
	shortCancel()
	if disposition, err := process.Kill(context.Background()); err != nil || disposition != TerminationBySupervisor {
		t.Fatalf("Kill disposition=%q err=%v", disposition, err)
	}
	select {
	case <-process.Done():
	case <-time.After(time.Second):
		t.Fatal("Done did not close after exact child reap")
	}
	if err := process.WaitContext(context.Background()); lifecycleExitSignal(t, err) != syscall.SIGKILL {
		t.Fatalf("WaitContext exit = %v", err)
	}
	if err := (*Process)(nil).WaitContext(context.Background()); err == nil {
		t.Fatal("nil process WaitContext succeeded")
	}
}

func startLifecycleTestProcess(t *testing.T, helperArguments ...string) *Process {
	t.Helper()
	arguments := []string{"-test.run=^TestHelperFirecrackerProcess$", "--"}
	arguments = append(arguments, helperArguments...)
	process, err := StartProcess(context.Background(), ProcessConfig{
		Binary: os.Args[0], ExecutableSHA256: testExecutableSHA256(t, os.Args[0]),
		APISocket: filepath.Join(t.TempDir(), "firecracker.sock"), ID: "lifecycle-test",
		Args: arguments, Env: append(os.Environ(), "GO_WANT_FIRECRACKER_HELPER=1"),
		StartupTimeout: time.Second, TerminationTimeout: time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = process.Kill(context.Background())
	})
	return process
}

func lifecycleExitSignal(t *testing.T, err error) syscall.Signal {
	t.Helper()
	var exitError *exec.ExitError
	if !errors.As(err, &exitError) {
		t.Fatalf("Wait error = %v, want exec.ExitError", err)
	}
	status, ok := exitError.Sys().(syscall.WaitStatus)
	if !ok || !status.Signaled() {
		t.Fatalf("Wait status = %v, want signal exit", exitError.Sys())
	}
	return status.Signal()
}
