//go:build linux

// Command firecracker-agent-guest is the PID 1 supervisor for an unmodified
// Codex App Server inside a Firecracker microVM.
package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"sync"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentguest"
	"golang.org/x/sys/unix"
)

const (
	configPath      = "/config.json"
	shutdownTimeout = 2 * time.Second
)

type runningCodex struct {
	stdin  io.WriteCloser
	stdout io.ReadCloser
	wait   func() error
	kill   func() error
}

type dependencies struct {
	loadConfig       func(string) (agentguest.Config, error)
	prepare          func(agentguest.Config) error
	startCodex       func(agentguest.Config, io.Writer) (runningCodex, error)
	startProxy       func(<-chan struct{}, uint32, func(uint32) (agentguest.Stream, error), *log.Logger) (<-chan error, error)
	runSession       func(context.Context, agentguest.Config, io.Writer, io.Reader, func(uint32) (agentguest.Stream, error), *log.Logger) error
	exportRepository func(func(uint32) (agentguest.Stream, error)) error
	dial             func(uint32) (agentguest.Stream, error)
}

type componentResult struct {
	component string
	err       error
}

func main() {
	logger := log.New(os.Stderr, "firecracker-agent-guest: ", log.LstdFlags|log.Lmicroseconds)
	childArguments, child, err := codexChildInvocation(os.Args)
	if child {
		if err == nil {
			err = agentguest.ExecCodexChild(childArguments)
		}
		logger.Printf("fatal Codex child launch: %v", err)
		if os.Getpid() != 1 {
			os.Exit(127)
		}
		powerOff(logger)
		return
	}
	if err := runPID1(context.Background(), productionDependencies(logger), logger); err != nil {
		logger.Printf("fatal: %v", err)
	}
	powerOff(logger)
}

func powerOff(logger *log.Logger) {
	unix.Sync()
	if err := unix.Reboot(unix.LINUX_REBOOT_CMD_POWER_OFF); err != nil {
		logger.Printf("poweroff failed: %v", err)
	}
	for {
		_ = unix.Pause()
	}
}

func codexChildInvocation(arguments []string) ([]string, bool, error) {
	if len(arguments) == 0 {
		return nil, true, errors.New("agent guest /init has no argv[0]")
	}
	if arguments[0] != agentguest.InitExecutable {
		return nil, true, errors.New("agent guest executable is not /init")
	}
	if len(arguments) == 1 {
		return nil, false, nil
	}
	if arguments[1] != agentguest.CodexChildMode {
		return nil, true, errors.New("agent guest /init received a forbidden internal mode")
	}
	childArguments := append([]string(nil), arguments[2:]...)
	if err := agentguest.ValidateCodexArguments(childArguments); err != nil {
		return nil, true, err
	}
	return childArguments, true, nil
}

func productionDependencies(logger *log.Logger) dependencies {
	return dependencies{
		loadConfig: readImmutableConfig,
		prepare:    agentguest.PrepareLinuxPID1,
		startCodex: func(config agentguest.Config, stderr io.Writer) (runningCodex, error) {
			domain, err := agentguest.NewExecutionDomain()
			if err != nil {
				return runningCodex{}, err
			}
			cgroupFD, err := domain.FD()
			if err != nil {
				return runningCodex{}, errors.Join(err, domain.Close())
			}
			command, stdin, stdout, err := agentguest.StartCodex(config, stderr, cgroupFD)
			if err != nil {
				return runningCodex{}, errors.Join(err, domain.Close())
			}
			reaper, err := startOrphanReaper(command.Process.Pid)
			if err != nil {
				domainErr := domain.FreezeAndKill(shutdownTimeout)
				killErr := error(nil)
				if domainErr != nil {
					killErr = killCommand(command)
				}
				waitErr := command.Wait()
				closeErr := errors.Join(stdin.Close(), stdout.Close())
				return runningCodex{}, errors.Join(err, domainErr, killErr, waitErr, closeErr, domain.Close())
			}
			var killOnce sync.Once
			var domainKillErr error
			return runningCodex{
				stdin: stdin, stdout: stdout,
				wait: func() error { return waitCommandWithOrphanReaper(command, reaper) },
				kill: func() error {
					killOnce.Do(func() {
						domainKillErr = domain.FreezeAndKill(shutdownTimeout)
						if domainKillErr != nil {
							domainKillErr = errors.Join(domainKillErr, killCommand(command))
						}
						domainKillErr = errors.Join(domainKillErr, domain.Close())
					})
					return domainKillErr
				},
			}, nil
		},
		startProxy: agentguest.StartModelProxy,
		runSession: agentguest.RunSession,
		exportRepository: func(dial func(uint32) (agentguest.Stream, error)) error {
			bundle, err := agentguest.ExportRepository(dial)
			if err == nil {
				logger.Printf("exported final repository tree %s with %d entries", bundle.TreeRoot, len(bundle.Entries))
			}
			return err
		},
		dial: agentguest.DialHostVsock,
	}
}

func killCommand(command *exec.Cmd) error {
	if command == nil || command.Process == nil {
		return errors.New("Codex process is unavailable")
	}
	return command.Process.Kill()
}

func readImmutableConfig(path string) (agentguest.Config, error) {
	if path != configPath {
		return agentguest.Config{}, errors.New("agent guest config path is not /config.json")
	}
	return decodeImmutableConfigFile(path)
}

func decodeImmutableConfigFile(path string) (agentguest.Config, error) {
	descriptor, err := unix.Open(path, unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return agentguest.Config{}, fmt.Errorf("open immutable agent guest config: %w", err)
	}
	file := os.NewFile(uintptr(descriptor), path)
	if file == nil {
		_ = unix.Close(descriptor)
		return agentguest.Config{}, errors.New("wrap immutable agent guest config")
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return agentguest.Config{}, fmt.Errorf("inspect immutable agent guest config: %w", err)
	}
	if !info.Mode().IsRegular() || info.Mode().Perm() != 0o400 || info.Size() <= 0 || info.Size() > agentguest.MaxConfigBytes {
		return agentguest.Config{}, errors.New("agent guest config must be a nonempty root-only regular file of bounded size")
	}
	config, err := agentguest.DecodeConfig(file)
	if err != nil {
		return agentguest.Config{}, fmt.Errorf("decode immutable agent guest config: %w", err)
	}
	return config, nil
}

func runPID1(ctx context.Context, deps dependencies, logger *log.Logger) error {
	if ctx == nil {
		return errors.New("agent guest supervisor context is nil")
	}
	if logger == nil {
		return errors.New("agent guest supervisor logger is nil")
	}
	if err := deps.validate(); err != nil {
		return err
	}
	config, err := deps.loadConfig(configPath)
	if err != nil {
		return err
	}
	if err := config.Validate(); err != nil {
		return fmt.Errorf("validate immutable agent guest config: %w", err)
	}
	if err := deps.prepare(config); err != nil {
		return fmt.Errorf("prepare agent guest PID 1: %w", err)
	}
	if err := ctx.Err(); err != nil {
		return err
	}

	runContext, cancel := context.WithCancel(ctx)
	defer cancel()
	results := make(chan componentResult, 3)
	proxyResult, err := deps.startProxy(runContext.Done(), config.ModelPort, deps.dial, logger)
	if err != nil {
		return fmt.Errorf("start guest model proxy: %w", err)
	}
	if proxyResult == nil {
		return errors.New("guest model proxy returned no completion channel")
	}
	go func() {
		results <- componentResult{
			component: "model proxy",
			err:       <-proxyResult,
		}
	}()

	codex, err := deps.startCodex(config, logger.Writer())
	if err != nil {
		cancel()
		if !waitForShutdown(results, 1) {
			return errors.Join(fmt.Errorf("start payload Codex: %w", err), errors.New("model proxy did not stop after cancellation"))
		}
		return fmt.Errorf("start payload Codex: %w", err)
	}
	if err := codex.validate(); err != nil {
		cancel()
		_ = codex.closePipes()
		if !waitForShutdown(results, 1) {
			return errors.Join(err, errors.New("model proxy did not stop after cancellation"))
		}
		return err
	}

	go func() {
		results <- componentResult{
			component: "agent stream session",
			err:       deps.runSession(runContext, config, codex.stdin, codex.stdout, deps.dial, logger),
		}
	}()
	go func() {
		results <- componentResult{component: "Codex process", err: codex.wait()}
	}()

	var first componentResult
	select {
	case first = <-results:
		if first.component == "agent stream session" && first.err == nil {
			err = nil
		} else {
			err = componentFailure(first)
		}
	case <-ctx.Done():
		err = ctx.Err()
	}
	cancel()
	_ = codex.stdin.Close()
	if killErr := codex.kill(); killErr != nil && !errors.Is(killErr, os.ErrProcessDone) {
		err = errors.Join(err, fmt.Errorf("freeze and kill payload Codex domain: %w", killErr))
	}
	_ = codex.stdout.Close()

	remaining := 3
	if first.component != "" {
		remaining--
	}
	if !waitForShutdown(results, remaining) {
		err = errors.Join(err, errors.New("agent guest components did not stop after cancellation"))
	}
	if err == nil {
		if exportErr := deps.exportRepository(deps.dial); exportErr != nil {
			err = fmt.Errorf("export stable final repository: %w", exportErr)
		}
	}
	return err
}

func (deps dependencies) validate() error {
	if deps.loadConfig == nil || deps.prepare == nil || deps.startCodex == nil || deps.startProxy == nil || deps.runSession == nil || deps.exportRepository == nil || deps.dial == nil {
		return errors.New("agent guest supervisor dependencies are incomplete")
	}
	return nil
}

func (codex runningCodex) validate() error {
	if codex.stdin == nil || codex.stdout == nil || codex.wait == nil || codex.kill == nil {
		return errors.New("payload Codex returned incomplete process handles")
	}
	return nil
}

func (codex runningCodex) closePipes() error {
	var errs []error
	if codex.stdin != nil {
		errs = append(errs, codex.stdin.Close())
	}
	if codex.stdout != nil {
		errs = append(errs, codex.stdout.Close())
	}
	return errors.Join(errs...)
}

func componentFailure(result componentResult) error {
	if result.err == nil {
		return fmt.Errorf("%s stopped unexpectedly", result.component)
	}
	return fmt.Errorf("%s failed: %w", result.component, result.err)
}

func waitForShutdown(results <-chan componentResult, count int) bool {
	if count == 0 {
		return true
	}
	timer := time.NewTimer(shutdownTimeout)
	defer timer.Stop()
	for count > 0 {
		select {
		case <-results:
			count--
		case <-timer.C:
			return false
		}
	}
	return true
}
