//go:build linux

package agentguest

import (
	"errors"
	"fmt"
	"math"
	"os"
	"runtime"

	"golang.org/x/sys/unix"
)

// ExecClaudeChild installs the same no-vsock seccomp boundary used for Codex
// and invokes the pinned dynamic loader from the read-only payload.
func ExecClaudeChild(arguments []string, modelPort uint32) error {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	if len(arguments) == 0 || modelPort == 0 {
		return errors.New("Claude child arguments or model port are missing")
	}
	realUID, effectiveUID, savedUID := unix.Getresuid()
	realGID, effectiveGID, savedGID := unix.Getresgid()
	if realUID != agentUID || effectiveUID != agentUID || savedUID != agentUID || realGID != agentGID || effectiveGID != agentGID || savedGID != agentGID {
		return errors.New("Claude child did not start under the fixed unprivileged identity")
	}
	if os.Getppid() != 1 {
		return errors.New("Claude child is not a direct child of PID 1")
	}
	groups, err := os.Getgroups()
	if err != nil || len(groups) != 0 {
		return errors.New("Claude child retained supplementary groups")
	}
	environment := fixedClaudeEnvironment(modelPort)
	if err := validateExactEnvironment(os.Environ(), environment); err != nil {
		return err
	}
	if err := installCodexSocketFilter(); err != nil {
		return fmt.Errorf("install Claude socket filter: %w", err)
	}
	if err := unix.CloseRange(3, uint(math.MaxUint32), unix.CLOSE_RANGE_CLOEXEC|unix.CLOSE_RANGE_UNSHARE); err != nil {
		return fmt.Errorf("seal Claude inherited descriptors: %w", err)
	}
	argv := []string{ClaudeLoader, "--library-path", ClaudeLibraryPath, ClaudeExecutable}
	argv = append(argv, arguments...)
	if err := unix.Exec(ClaudeLoader, argv, environment); err != nil {
		return fmt.Errorf("exec fixed payload Claude: %w", err)
	}
	return errors.New("fixed payload Claude exec returned without an error")
}
