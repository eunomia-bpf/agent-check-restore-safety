//go:build linux

package agentguest

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"time"

	"golang.org/x/sys/unix"
)

const executionCgroupPath = "/sys/fs/cgroup/safe-change-agent"

// ExecutionDomain is the cgroup-v2 domain into which the kernel atomically
// creates Codex. Every descendant inherits membership and cannot escape under
// the unprivileged guest identity.
type ExecutionDomain struct {
	directory *os.File
}

func NewExecutionDomain() (*ExecutionDomain, error) {
	if err := os.Mkdir(executionCgroupPath, 0o700); err != nil {
		return nil, fmt.Errorf("create agent execution cgroup: %w", err)
	}
	descriptor, err := unix.Open(executionCgroupPath, unix.O_RDONLY|unix.O_DIRECTORY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
	if err != nil {
		_ = os.Remove(executionCgroupPath)
		return nil, fmt.Errorf("open agent execution cgroup: %w", err)
	}
	directory := os.NewFile(uintptr(descriptor), executionCgroupPath)
	if directory == nil {
		_ = unix.Close(descriptor)
		_ = os.Remove(executionCgroupPath)
		return nil, errors.New("wrap agent execution cgroup descriptor")
	}
	return &ExecutionDomain{directory: directory}, nil
}

func (domain *ExecutionDomain) FD() (int, error) {
	if domain == nil || domain.directory == nil {
		return -1, errors.New("agent execution cgroup is unavailable")
	}
	return int(domain.directory.Fd()), nil
}

// FreezeAndKill establishes a stable workspace boundary: first the kernel
// confirms that every task in the domain is frozen, then cgroup.kill signals
// the entire descendant set, and finally cgroup.events confirms it is empty.
func (domain *ExecutionDomain) FreezeAndKill(timeout time.Duration) error {
	if timeout <= 0 {
		return errors.New("agent execution cgroup timeout must be positive")
	}
	state, err := domain.events()
	if err != nil {
		return err
	}
	if !state.populated {
		return nil
	}
	deadline := time.Now().Add(timeout)
	if err := domain.writeControl("cgroup.freeze", "1"); err != nil {
		return fmt.Errorf("freeze agent execution cgroup: %w", err)
	}
	if err := domain.wait(deadline, func(value cgroupEvents) bool { return value.frozen }); err != nil {
		return fmt.Errorf("wait for frozen agent execution cgroup: %w", err)
	}
	if err := domain.writeControl("cgroup.kill", "1"); err != nil {
		return fmt.Errorf("kill agent execution cgroup: %w", err)
	}
	if err := domain.wait(deadline, func(value cgroupEvents) bool { return !value.populated }); err != nil {
		return fmt.Errorf("wait for empty agent execution cgroup: %w", err)
	}
	return nil
}

func (domain *ExecutionDomain) Close() error {
	if domain == nil {
		return nil
	}
	var closeErr error
	if domain.directory != nil {
		closeErr = domain.directory.Close()
		domain.directory = nil
	}
	removeErr := os.Remove(executionCgroupPath)
	if errors.Is(removeErr, os.ErrNotExist) {
		removeErr = nil
	}
	return errors.Join(closeErr, removeErr)
}

type cgroupEvents struct {
	populated bool
	frozen    bool
}

func (domain *ExecutionDomain) events() (cgroupEvents, error) {
	if domain == nil || domain.directory == nil {
		return cgroupEvents{}, errors.New("agent execution cgroup is unavailable")
	}
	descriptor, err := unix.Openat(int(domain.directory.Fd()), "cgroup.events", unix.O_RDONLY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
	if err != nil {
		return cgroupEvents{}, fmt.Errorf("open cgroup.events: %w", err)
	}
	file := os.NewFile(uintptr(descriptor), "cgroup.events")
	if file == nil {
		_ = unix.Close(descriptor)
		return cgroupEvents{}, errors.New("wrap cgroup.events descriptor")
	}
	data, readErr := io.ReadAll(io.LimitReader(file, 4097))
	closeErr := file.Close()
	if err := errors.Join(readErr, closeErr); err != nil {
		return cgroupEvents{}, err
	}
	if len(data) == 0 || len(data) > 4096 {
		return cgroupEvents{}, errors.New("cgroup.events is empty or oversized")
	}
	return parseCgroupEvents(string(data))
}

func parseCgroupEvents(data string) (cgroupEvents, error) {
	values := make(map[string]bool, 2)
	scanner := bufio.NewScanner(strings.NewReader(data))
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) != 2 || (fields[1] != "0" && fields[1] != "1") {
			return cgroupEvents{}, errors.New("cgroup.events contains a malformed line")
		}
		if fields[0] != "populated" && fields[0] != "frozen" {
			continue
		}
		if _, exists := values[fields[0]]; exists {
			return cgroupEvents{}, fmt.Errorf("cgroup.events repeats %s", fields[0])
		}
		value, _ := strconv.ParseBool(fields[1])
		values[fields[0]] = value
	}
	if err := scanner.Err(); err != nil {
		return cgroupEvents{}, err
	}
	populated, hasPopulated := values["populated"]
	frozen, hasFrozen := values["frozen"]
	if !hasPopulated || !hasFrozen {
		return cgroupEvents{}, errors.New("cgroup.events omits populated or frozen")
	}
	return cgroupEvents{populated: populated, frozen: frozen}, nil
}

func (domain *ExecutionDomain) writeControl(name, value string) error {
	if domain == nil || domain.directory == nil {
		return errors.New("agent execution cgroup is unavailable")
	}
	descriptor, err := unix.Openat(int(domain.directory.Fd()), name, unix.O_WRONLY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
	if err != nil {
		return err
	}
	file := os.NewFile(uintptr(descriptor), name)
	if file == nil {
		_ = unix.Close(descriptor)
		return fmt.Errorf("wrap %s descriptor", name)
	}
	written, writeErr := file.WriteString(value)
	closeErr := file.Close()
	if written != len(value) && writeErr == nil {
		writeErr = io.ErrShortWrite
	}
	return errors.Join(writeErr, closeErr)
}

func (domain *ExecutionDomain) wait(deadline time.Time, ready func(cgroupEvents) bool) error {
	for {
		state, err := domain.events()
		if err != nil {
			return err
		}
		if ready(state) {
			return nil
		}
		if time.Now().After(deadline) {
			return errors.New("timed out")
		}
		time.Sleep(5 * time.Millisecond)
	}
}
