//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentguest"
)

func TestDecodeImmutableConfigFileRequiresDirectReadOnlyConfig(t *testing.T) {
	config := validGuestConfig()
	data, err := json.Marshal(config)
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	path := filepath.Join(root, "config.json")
	if err := os.WriteFile(path, data, 0o400); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o400); err != nil {
		t.Fatal(err)
	}
	got, err := decodeImmutableConfigFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if got.SessionID != config.SessionID || got.CodexSHA256 != config.CodexSHA256 || strings.Join(got.Arguments, "\x00") != strings.Join(config.Arguments, "\x00") {
		t.Fatalf("decoded config = %+v, want %+v", got, config)
	}

	if _, err := readImmutableConfig(path); err == nil || !strings.Contains(err.Error(), configPath) {
		t.Fatalf("noncanonical config path error = %v", err)
	}
	if err := os.Chmod(path, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := decodeImmutableConfigFile(path); err == nil || !strings.Contains(err.Error(), "root-only regular file") {
		t.Fatalf("writable config error = %v", err)
	}
	if err := os.Chmod(path, 0o400); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(root, "config-link.json")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	if _, err := decodeImmutableConfigFile(link); err == nil {
		t.Fatal("symlinked config accepted")
	}
}

func TestCodexChildInvocationAcceptsOnlyFixedInternalMode(t *testing.T) {
	arguments := validGuestConfig().Arguments
	childArguments, child, err := codexChildInvocation([]string{agentguest.InitExecutable})
	if err != nil || child || childArguments != nil {
		t.Fatalf("PID 1 invocation parsed as arguments=%q child=%t error=%v", childArguments, child, err)
	}
	invocation := append([]string{agentguest.InitExecutable, agentguest.CodexChildMode}, arguments...)
	childArguments, child, err = codexChildInvocation(invocation)
	if err != nil || !child || strings.Join(childArguments, "\x00") != strings.Join(arguments, "\x00") {
		t.Fatalf("child invocation parsed as arguments=%q child=%t error=%v", childArguments, child, err)
	}
	for _, forbidden := range [][]string{
		nil,
		{"/tmp/init"},
		{agentguest.InitExecutable, "--shell"},
		{agentguest.InitExecutable, agentguest.CodexChildMode, "sh", "-c", "id"},
	} {
		if _, child, err := codexChildInvocation(forbidden); err == nil || !child {
			t.Fatalf("forbidden invocation %q parsed as child=%t error=%v", forbidden, child, err)
		}
	}
}

func TestRunPID1CancelsEverythingOnSessionFailure(t *testing.T) {
	sessionFailure := errors.New("session protocol failed")
	process := newBlockingCodex()
	proxyStopped := make(chan struct{})
	var logs bytes.Buffer
	config := validGuestConfig()
	deps := dependencies{
		loadConfig: func(path string) (agentguest.Config, error) {
			if path != configPath {
				t.Fatalf("load path = %q, want %q", path, configPath)
			}
			return config, nil
		},
		prepare: func(got agentguest.Config) error {
			if got.SessionID != config.SessionID {
				t.Fatalf("prepared config = %+v", got)
			}
			return nil
		},
		startCodex: func(got agentguest.Config, stderr io.Writer) (runningCodex, error) {
			if got.CodexSHA256 != config.CodexSHA256 || stderr != &logs {
				t.Fatalf("Codex launch config=%+v stderr=%T", got, stderr)
			}
			return process.running(), nil
		},
		startProxy: func(done <-chan struct{}, port uint32, dial func(uint32) (agentguest.Stream, error), _ *log.Logger) (<-chan error, error) {
			if port != config.ModelPort {
				t.Errorf("model port = %d, want %d", port, config.ModelPort)
			}
			if _, err := dial(port); !errors.Is(err, errTestDial) {
				t.Errorf("model dial error = %v", err)
			}
			result := make(chan error, 1)
			go func() {
				<-done
				close(proxyStopped)
				result <- nil
			}()
			return result, nil
		},
		runSession: func(_ context.Context, got agentguest.Config, stdin io.Writer, stdout io.Reader, dial func(uint32) (agentguest.Stream, error), _ *log.Logger) error {
			if got.StreamPort != config.StreamPort || stdin != process.stdin || stdout != process.stdout {
				t.Errorf("session received wrong config or Codex pipes")
			}
			if _, err := dial(got.StreamPort); !errors.Is(err, errTestDial) {
				t.Errorf("stream dial error = %v", err)
			}
			return sessionFailure
		},
		exportRepository: func(func(uint32) (agentguest.Stream, error)) error {
			t.Error("failed session attempted repository export")
			return nil
		},
		dial: func(uint32) (agentguest.Stream, error) { return nil, errTestDial },
	}

	err := runPID1(context.Background(), deps, log.New(&logs, "", 0))
	if !errors.Is(err, sessionFailure) {
		t.Fatalf("runPID1 error = %v, want session failure", err)
	}
	assertClosed(t, process.killed, "Codex was not killed")
	assertClosed(t, process.waited, "Codex was not reaped")
	assertClosed(t, process.stdin.closed, "Codex stdin was not closed")
	assertClosed(t, process.stdout.closed, "Codex stdout was not closed")
	assertClosed(t, proxyStopped, "model proxy was not canceled")
}

func TestRunPID1ExportsOnlyAfterNormalSessionAndDomainShutdown(t *testing.T) {
	process := newBlockingCodex()
	deps := baseDependencies(process)
	deps.runSession = func(context.Context, agentguest.Config, io.Writer, io.Reader, func(uint32) (agentguest.Stream, error), *log.Logger) error {
		return nil
	}
	exported := false
	deps.exportRepository = func(func(uint32) (agentguest.Stream, error)) error {
		select {
		case <-process.killed:
		default:
			t.Fatal("repository exported before the execution domain was killed")
		}
		select {
		case <-process.waited:
		default:
			t.Fatal("repository exported before the execution domain was reaped")
		}
		exported = true
		return nil
	}
	if err := runPID1(context.Background(), deps, log.New(io.Discard, "", 0)); err != nil {
		t.Fatal(err)
	}
	if !exported {
		t.Fatal("normal session did not export repository")
	}
}

func TestRunPID1PropagatesProxyAndCodexFailures(t *testing.T) {
	t.Run("proxy", func(t *testing.T) {
		proxyFailure := errors.New("proxy bind failed")
		process := newBlockingCodex()
		deps := baseDependencies(process)
		deps.startProxy = func(<-chan struct{}, uint32, func(uint32) (agentguest.Stream, error), *log.Logger) (<-chan error, error) {
			result := make(chan error, 1)
			result <- proxyFailure
			return result, nil
		}
		err := runPID1(context.Background(), deps, log.New(io.Discard, "", 0))
		if !errors.Is(err, proxyFailure) {
			t.Fatalf("runPID1 error = %v, want proxy failure", err)
		}
		assertClosed(t, process.killed, "Codex was not killed after proxy failure")
		assertClosed(t, process.waited, "Codex was not reaped after proxy failure")
	})

	t.Run("Codex", func(t *testing.T) {
		codexFailure := errors.New("Codex exited 17")
		process := newExitedCodex(codexFailure)
		deps := baseDependencies(process)
		err := runPID1(context.Background(), deps, log.New(io.Discard, "", 0))
		if !errors.Is(err, codexFailure) {
			t.Fatalf("runPID1 error = %v, want Codex failure", err)
		}
		assertClosed(t, process.killed, "Codex execution domain was not finalized")
		assertClosed(t, process.waited, "Codex exit was not observed")
	})
}

func TestRunPID1CancelsProxyWhenCodexStartFails(t *testing.T) {
	startFailure := errors.New("exec rejected")
	proxyStopped := make(chan struct{})
	deps := baseDependencies(newBlockingCodex())
	deps.startCodex = func(agentguest.Config, io.Writer) (runningCodex, error) {
		return runningCodex{}, startFailure
	}
	deps.startProxy = func(done <-chan struct{}, _ uint32, _ func(uint32) (agentguest.Stream, error), _ *log.Logger) (<-chan error, error) {
		result := make(chan error, 1)
		go func() {
			<-done
			close(proxyStopped)
			result <- nil
		}()
		return result, nil
	}
	err := runPID1(context.Background(), deps, log.New(io.Discard, "", 0))
	if !errors.Is(err, startFailure) {
		t.Fatalf("runPID1 error = %v, want start failure", err)
	}
	assertClosed(t, proxyStopped, "model proxy was not canceled after start failure")
}

func TestRunPID1DoesNotLaunchCodexBeforeProxyBindSucceeds(t *testing.T) {
	bindFailure := errors.New("loopback address already in use")
	startedCodex := false
	deps := baseDependencies(newBlockingCodex())
	deps.startProxy = func(<-chan struct{}, uint32, func(uint32) (agentguest.Stream, error), *log.Logger) (<-chan error, error) {
		return nil, bindFailure
	}
	deps.startCodex = func(agentguest.Config, io.Writer) (runningCodex, error) {
		startedCodex = true
		return runningCodex{}, errors.New("must not run")
	}
	err := runPID1(context.Background(), deps, log.New(io.Discard, "", 0))
	if !errors.Is(err, bindFailure) {
		t.Fatalf("runPID1 error = %v, want bind failure", err)
	}
	if startedCodex {
		t.Fatal("Codex launched before the model proxy listener was ready")
	}
}

var errTestDial = errors.New("test dial")

func validGuestConfig() agentguest.Config {
	return agentguest.Config{
		Schema: agentguest.ConfigSchema, SessionID: strings.Repeat("1", 32), CodexSHA256: strings.Repeat("a", 64),
		Arguments:  []string{"app-server", "--stdio", "-c", `model_provider="safe_change"`},
		StreamPort: agentguest.DefaultStreamPort, ModelPort: 45678, PayloadDrive: "/dev/vda",
		RepositoryDrive: agentguest.RepositoryDrive, RepositorySize: 512,
		RepositorySHA256: strings.Repeat("b", 64), RepositoryTreeRoot: strings.Repeat("c", 64),
	}
}

func baseDependencies(process *fakeCodex) dependencies {
	config := validGuestConfig()
	return dependencies{
		loadConfig: func(string) (agentguest.Config, error) { return config, nil },
		prepare:    func(agentguest.Config) error { return nil },
		startCodex: func(agentguest.Config, io.Writer) (runningCodex, error) { return process.running(), nil },
		startProxy: func(done <-chan struct{}, _ uint32, _ func(uint32) (agentguest.Stream, error), _ *log.Logger) (<-chan error, error) {
			result := make(chan error, 1)
			go func() {
				<-done
				result <- nil
			}()
			return result, nil
		},
		runSession: func(ctx context.Context, _ agentguest.Config, _ io.Writer, _ io.Reader, _ func(uint32) (agentguest.Stream, error), _ *log.Logger) error {
			<-ctx.Done()
			return ctx.Err()
		},
		exportRepository: func(func(uint32) (agentguest.Stream, error)) error { return nil },
		dial:             func(uint32) (agentguest.Stream, error) { return nil, errTestDial },
	}
}

type fakeCodex struct {
	stdin  *trackedWriteCloser
	stdout *trackedReadCloser
	killed chan struct{}
	waited chan struct{}
	wait   func() error
	kill   func() error
}

func newBlockingCodex() *fakeCodex {
	process := &fakeCodex{
		stdin: &trackedWriteCloser{closed: make(chan struct{})}, stdout: &trackedReadCloser{closed: make(chan struct{})},
		killed: make(chan struct{}), waited: make(chan struct{}),
	}
	var killOnce sync.Once
	var waitOnce sync.Once
	process.kill = func() error {
		killOnce.Do(func() { close(process.killed) })
		return nil
	}
	process.wait = func() error {
		<-process.killed
		waitOnce.Do(func() { close(process.waited) })
		return errors.New("killed")
	}
	return process
}

func newExitedCodex(exitError error) *fakeCodex {
	process := &fakeCodex{
		stdin: &trackedWriteCloser{closed: make(chan struct{})}, stdout: &trackedReadCloser{closed: make(chan struct{})},
		killed: make(chan struct{}), waited: make(chan struct{}),
	}
	var waitOnce sync.Once
	process.kill = func() error {
		close(process.killed)
		return nil
	}
	process.wait = func() error {
		waitOnce.Do(func() { close(process.waited) })
		return exitError
	}
	return process
}

func (process *fakeCodex) running() runningCodex {
	return runningCodex{stdin: process.stdin, stdout: process.stdout, wait: process.wait, kill: process.kill}
}

type trackedWriteCloser struct {
	bytes.Buffer
	closed chan struct{}
	once   sync.Once
}

func (writer *trackedWriteCloser) Close() error {
	writer.once.Do(func() { close(writer.closed) })
	return nil
}

type trackedReadCloser struct {
	closed chan struct{}
	once   sync.Once
}

func (reader *trackedReadCloser) Read([]byte) (int, error) { return 0, io.EOF }
func (reader *trackedReadCloser) Close() error {
	reader.once.Do(func() { close(reader.closed) })
	return nil
}

func assertClosed(t *testing.T, channel <-chan struct{}, message string) {
	t.Helper()
	select {
	case <-channel:
	default:
		t.Fatal(message)
	}
}
