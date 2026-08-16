//go:build linux

package main

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

const reaperHelperRole = "SAFE_CHANGE_REAPER_HELPER_ROLE"

func TestOrphanReaperReapsDaemonizedGrandchildWithoutStealingPrimary(t *testing.T) {
	switch os.Getenv(reaperHelperRole) {
	case "supervisor":
		os.Exit(runReaperSupervisor())
	case "primary":
		os.Exit(runReaperPrimary())
	case "middle":
		os.Exit(runReaperMiddle())
	case "orphan":
		if _, err := unix.Setsid(); err != nil {
			_, _ = fmt.Fprintf(os.Stderr, "daemon setsid: %v\n", err)
			os.Exit(2)
		}
		for {
			_ = unix.Pause()
		}
	}

	command := reaperTestCommand("supervisor")
	var stdout, stderr bytes.Buffer
	command.Stdout, command.Stderr = &stdout, &stderr
	if err := command.Run(); err != nil {
		t.Fatalf("real orphan-reaper helper: %v\nstderr: %s", err, stderr.String())
	}
	if stdout.String() != "orphan-reaped-primary-waited\n" {
		t.Fatalf("helper stdout = %q; stderr = %q", stdout.String(), stderr.String())
	}
}

func runReaperSupervisor() int {
	fail := func(format string, arguments ...any) int {
		_, _ = fmt.Fprintf(os.Stderr, format+"\n", arguments...)
		return 2
	}
	if err := unix.Prctl(unix.PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0); err != nil {
		return fail("set child subreaper: %v", err)
	}
	primary := reaperTestCommand("primary")
	stdin, err := primary.StdinPipe()
	if err != nil {
		return fail("primary stdin: %v", err)
	}
	stdout, err := primary.StdoutPipe()
	if err != nil {
		return fail("primary stdout: %v", err)
	}
	primary.Stderr = os.Stderr
	if err := primary.Start(); err != nil {
		return fail("start primary: %v", err)
	}
	reaper, err := startOrphanReaper(primary.Process.Pid)
	if err != nil {
		_ = primary.Process.Kill()
		_ = primary.Wait()
		return fail("start orphan reaper: %v", err)
	}
	finished := false
	defer func() {
		if finished {
			return
		}
		_ = primary.Process.Kill()
		_ = primary.Wait()
		_ = reaper.stopAfterPrimaryWait()
	}()

	pidLine := make(chan string, 1)
	readError := make(chan error, 1)
	go func() {
		line, readErr := bufio.NewReader(stdout).ReadString('\n')
		if readErr != nil {
			readError <- readErr
			return
		}
		pidLine <- strings.TrimSpace(line)
	}()
	var rawPID string
	select {
	case rawPID = <-pidLine:
	case readErr := <-readError:
		return fail("read orphan PID: %v", readErr)
	case <-time.After(3 * time.Second):
		return fail("timed out reading orphan PID")
	}
	orphanPID, err := strconv.Atoi(rawPID)
	if err != nil || orphanPID <= 0 {
		return fail("invalid orphan PID %q", rawPID)
	}
	if err := waitForParent(orphanPID, os.Getpid(), 3*time.Second); err != nil {
		_ = unix.Kill(orphanPID, unix.SIGKILL)
		return fail("grandchild was not adopted: %v", err)
	}
	if err := unix.Kill(orphanPID, unix.SIGTERM); err != nil {
		return fail("terminate adopted grandchild: %v", err)
	}
	if err := waitForProcessGone(orphanPID, 3*time.Second); err != nil {
		return fail("adopted grandchild was not reaped: %v", err)
	}
	if err := stdin.Close(); err != nil {
		return fail("release primary: %v", err)
	}
	waitErr := waitCommandWithOrphanReaper(primary, reaper)
	finished = true
	if waitErr != nil {
		return fail("direct primary wait failed or was stolen: %v", waitErr)
	}
	_, _ = os.Stdout.WriteString("orphan-reaped-primary-waited\n")
	return 0
}

func runReaperPrimary() int {
	middle := reaperTestCommand("middle")
	middle.Stdout, middle.Stderr = os.Stdout, os.Stderr
	if err := middle.Run(); err != nil {
		_, _ = fmt.Fprintf(os.Stderr, "middle: %v\n", err)
		return 2
	}
	if _, err := io.Copy(io.Discard, os.Stdin); err != nil {
		_, _ = fmt.Fprintf(os.Stderr, "wait for supervisor release: %v\n", err)
		return 2
	}
	return 0
}

func runReaperMiddle() int {
	orphan := reaperTestCommand("orphan")
	orphan.Stdin, orphan.Stdout, orphan.Stderr = nil, os.Stderr, os.Stderr
	if err := orphan.Start(); err != nil {
		_, _ = fmt.Fprintf(os.Stderr, "start orphan: %v\n", err)
		return 2
	}
	_, _ = fmt.Fprintf(os.Stdout, "%d\n", orphan.Process.Pid)
	return 0
}

func reaperTestCommand(role string) *exec.Cmd {
	command := exec.Command(
		os.Args[0],
		"-test.run=^TestOrphanReaperReapsDaemonizedGrandchildWithoutStealingPrimary$",
	)
	command.Env = replaceEnvironment(os.Environ(), reaperHelperRole, role)
	return command
}

func replaceEnvironment(environment []string, key, value string) []string {
	prefix := key + "="
	result := make([]string, 0, len(environment)+1)
	for _, entry := range environment {
		if !strings.HasPrefix(entry, prefix) {
			result = append(result, entry)
		}
	}
	return append(result, prefix+value)
}

func waitForParent(pid, parent int, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		data, err := os.ReadFile(filepath.Join("/proc", strconv.Itoa(pid), "status"))
		if err == nil {
			for _, line := range strings.Split(string(data), "\n") {
				if strings.HasPrefix(line, "PPid:") {
					observed, parseErr := strconv.Atoi(strings.TrimSpace(strings.TrimPrefix(line, "PPid:")))
					if parseErr == nil && observed == parent {
						return nil
					}
				}
			}
		} else if !errors.Is(err, os.ErrNotExist) {
			return err
		}
		time.Sleep(10 * time.Millisecond)
	}
	return errors.New("parent PID did not become the supervisor")
}

func waitForProcessGone(pid int, timeout time.Duration) error {
	path := filepath.Join("/proc", strconv.Itoa(pid))
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		_, err := os.Stat(path)
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		if err != nil {
			return err
		}
		time.Sleep(10 * time.Millisecond)
	}
	return syscall.ETIMEDOUT
}
