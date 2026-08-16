//go:build linux

package main

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

const orphanSweepInterval = 250 * time.Millisecond

// orphanReaper reaps children adopted by PID 1 while deliberately excluding
// the direct Codex child. exec.Cmd.Wait remains the sole waiter for that PID,
// preserving its exit status and avoiding a wait4 race.
type orphanReaper struct {
	protectedPID int
	signals      chan os.Signal
	stop         chan struct{}
	done         chan struct{}
	failure      chan error
	stopOnce     sync.Once
	mu           sync.Mutex
	runError     error
}

func startOrphanReaper(protectedPID int) (*orphanReaper, error) {
	if protectedPID <= 0 {
		return nil, errors.New("orphan reaper requires a positive protected PID")
	}
	reaper := &orphanReaper{
		protectedPID: protectedPID,
		signals:      make(chan os.Signal, 1),
		stop:         make(chan struct{}),
		done:         make(chan struct{}),
		failure:      make(chan error, 1),
	}
	signal.Notify(reaper.signals, syscall.SIGCHLD)
	if _, err := reapAdoptedChildren(protectedPID); err != nil {
		signal.Stop(reaper.signals)
		return nil, fmt.Errorf("start PID 1 orphan reaper: %w", err)
	}
	go reaper.run()
	return reaper, nil
}

func (reaper *orphanReaper) run() {
	defer close(reaper.done)
	ticker := time.NewTicker(orphanSweepInterval)
	defer ticker.Stop()
	for {
		select {
		case <-reaper.signals:
		case <-ticker.C:
		case <-reaper.stop:
			return
		}
		if _, err := reapAdoptedChildren(reaper.protectedPID); err != nil {
			reaper.mu.Lock()
			reaper.runError = err
			reaper.mu.Unlock()
			select {
			case reaper.failure <- err:
			default:
			}
			return
		}
	}
}

func (reaper *orphanReaper) failures() <-chan error { return reaper.failure }

// stopAfterPrimaryWait must be called only after exec.Cmd.Wait has completed
// for protectedPID. Its final unprotected sweep is therefore unable to steal
// the direct child's status.
func (reaper *orphanReaper) stopAfterPrimaryWait() error {
	if reaper == nil {
		return errors.New("stop nil orphan reaper")
	}
	reaper.stopOnce.Do(func() {
		signal.Stop(reaper.signals)
		close(reaper.stop)
	})
	<-reaper.done
	reaper.mu.Lock()
	runErr := reaper.runError
	reaper.mu.Unlock()
	_, finalErr := reapAdoptedChildren(0)
	return errors.Join(runErr, finalErr)
}

func waitCommandWithOrphanReaper(command *exec.Cmd, reaper *orphanReaper) error {
	if command == nil || command.Process == nil || reaper == nil {
		return errors.New("wait requires a started command and orphan reaper")
	}
	if command.Process.Pid != reaper.protectedPID {
		return errors.New("orphan reaper protects a different direct child")
	}
	waited := make(chan error, 1)
	go func() { waited <- command.Wait() }()
	select {
	case waitErr := <-waited:
		return errors.Join(waitErr, reaper.stopAfterPrimaryWait())
	case reapErr := <-reaper.failures():
		killErr := command.Process.Kill()
		if errors.Is(killErr, os.ErrProcessDone) {
			killErr = nil
		}
		waitErr := <-waited
		stopErr := reaper.stopAfterPrimaryWait()
		return errors.Join(
			fmt.Errorf("PID 1 orphan reaper failed: %w", reapErr),
			killErr,
			waitErr,
			stopErr,
		)
	}
}

// reapAdoptedChildren enumerates every Linux task's direct-child list because
// Go may create the protected child from a non-leader thread. It performs only
// PID-specific WNOHANG waits and never calls wait4(-1), so protectedPID cannot
// be consumed accidentally.
func reapAdoptedChildren(protectedPID int) (int, error) {
	children, err := directChildPIDs()
	if err != nil {
		return 0, err
	}
	reaped := 0
	for _, childPID := range children {
		if childPID == protectedPID {
			continue
		}
		var status unix.WaitStatus
		waitedPID, waitErr := unix.Wait4(childPID, &status, unix.WNOHANG, nil)
		if errors.Is(waitErr, unix.ECHILD) || errors.Is(waitErr, unix.ESRCH) {
			continue
		}
		if waitErr != nil {
			return reaped, fmt.Errorf("wait for adopted child %d: %w", childPID, waitErr)
		}
		if waitedPID == childPID {
			reaped++
		} else if waitedPID != 0 {
			return reaped, fmt.Errorf("wait for child %d returned PID %d", childPID, waitedPID)
		}
	}
	return reaped, nil
}

func directChildPIDs() ([]int, error) {
	tasks, err := os.ReadDir("/proc/self/task")
	if err != nil {
		return nil, fmt.Errorf("enumerate PID 1 tasks: %w", err)
	}
	unique := make(map[int]struct{})
	for _, task := range tasks {
		if !task.IsDir() {
			continue
		}
		path := filepath.Join("/proc/self/task", task.Name(), "children")
		data, readErr := os.ReadFile(path)
		if errors.Is(readErr, os.ErrNotExist) {
			// A Go runtime thread may disappear between ReadDir and ReadFile.
			continue
		}
		if readErr != nil {
			return nil, fmt.Errorf("read task %s children: %w", task.Name(), readErr)
		}
		for _, field := range strings.Fields(string(data)) {
			pid, parseErr := strconv.Atoi(field)
			if parseErr != nil || pid <= 0 {
				return nil, fmt.Errorf("invalid child PID %q in %s", field, path)
			}
			unique[pid] = struct{}{}
		}
	}
	result := make([]int, 0, len(unique))
	for pid := range unique {
		result = append(result, pid)
	}
	sort.Ints(result)
	return result, nil
}
