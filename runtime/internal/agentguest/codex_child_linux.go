//go:build linux

package agentguest

import (
	"errors"
	"fmt"
	"math"
	"os"
	"runtime"
	"unsafe"

	"golang.org/x/sys/unix"
)

const (
	seccompDataNumberOffset    = 0
	seccompDataArchOffset      = 4
	seccompDataArgumentsOffset = 16
	x32SyscallBit              = uint32(0x40000000)
)

type codexChildRuntime struct {
	resuid          func() (int, int, int)
	resgid          func() (int, int, int)
	ppid            func() int
	groups          func() ([]int, error)
	environment     func() []string
	installFilter   func() error
	sealDescriptors func() error
	exec            func(string, []string, []string) error
}

// ExecCodexChild validates the already-dropped child identity, installs the
// inherited socket boundary on one locked OS thread, and replaces /init only
// with the fixed payload executable. Success never returns.
func ExecCodexChild(arguments []string) error {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	return execCodexChild(arguments, codexChildRuntime{
		resuid: unix.Getresuid, resgid: unix.Getresgid,
		ppid: os.Getppid, groups: os.Getgroups, environment: os.Environ,
		installFilter: installCodexSocketFilter, sealDescriptors: sealCodexDescriptors,
		exec: unix.Exec,
	})
}

func execCodexChild(arguments []string, system codexChildRuntime) error {
	if err := ValidateCodexArguments(arguments); err != nil {
		return err
	}
	if system.resuid == nil || system.resgid == nil || system.ppid == nil || system.groups == nil || system.environment == nil || system.installFilter == nil || system.sealDescriptors == nil || system.exec == nil {
		return errors.New("Codex child runtime is incomplete")
	}
	realUID, effectiveUID, savedUID := system.resuid()
	realGID, effectiveGID, savedGID := system.resgid()
	if realUID != agentUID || effectiveUID != agentUID || savedUID != agentUID || realGID != agentGID || effectiveGID != agentGID || savedGID != agentGID {
		return errors.New("Codex child did not start under the fixed unprivileged identity")
	}
	if system.ppid() != 1 {
		return errors.New("Codex child is not a direct child of PID 1")
	}
	groups, err := system.groups()
	if err != nil {
		return fmt.Errorf("read Codex child supplementary groups: %w", err)
	}
	if len(groups) != 0 {
		return errors.New("Codex child retained supplementary groups")
	}
	environment := fixedCodexEnvironment()
	if err := validateExactEnvironment(system.environment(), environment); err != nil {
		return err
	}
	if err := system.installFilter(); err != nil {
		return fmt.Errorf("install Codex socket filter: %w", err)
	}
	if err := system.sealDescriptors(); err != nil {
		return fmt.Errorf("seal Codex inherited descriptors: %w", err)
	}
	argv := make([]string, 0, len(arguments)+1)
	argv = append(argv, CodexExecutable)
	argv = append(argv, arguments...)
	if err := system.exec(CodexExecutable, argv, environment); err != nil {
		return fmt.Errorf("exec fixed payload Codex: %w", err)
	}
	return errors.New("fixed payload Codex exec returned without an error")
}

func fixedCodexEnvironment() []string {
	return []string{
		"HOME=/home/codex",
		"CODEX_HOME=" + CodexHomeDirectory,
		"CODEX_MANAGED_BY_NPM=1",
		"LANG=C.UTF-8",
		"LC_ALL=C.UTF-8",
		"PATH=/opt/codex/bin:/usr/bin:/bin",
		"TMPDIR=/tmp",
	}
}

func validateExactEnvironment(actual, expected []string) error {
	if len(actual) != len(expected) {
		return errors.New("Codex child environment differs from the fixed environment")
	}
	allowed := make(map[string]struct{}, len(expected))
	for _, entry := range expected {
		allowed[entry] = struct{}{}
	}
	seen := make(map[string]struct{}, len(actual))
	for _, entry := range actual {
		if _, ok := allowed[entry]; !ok {
			return errors.New("Codex child environment differs from the fixed environment")
		}
		if _, duplicate := seen[entry]; duplicate {
			return errors.New("Codex child environment contains a duplicate entry")
		}
		seen[entry] = struct{}{}
	}
	return nil
}

func installCodexSocketFilter() error {
	if runtime.GOARCH != "amd64" {
		return fmt.Errorf("Codex socket filter requires amd64, got %s", runtime.GOARCH)
	}
	if err := unix.Prctl(unix.PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0); err != nil {
		return fmt.Errorf("set no_new_privs: %w", err)
	}
	filter := codexSocketFilter()
	program := unix.SockFprog{Len: uint16(len(filter)), Filter: &filter[0]}
	result, _, errno := unix.Syscall(unix.SYS_SECCOMP, unix.SECCOMP_SET_MODE_FILTER, unix.SECCOMP_FILTER_FLAG_TSYNC, uintptr(unsafe.Pointer(&program)))
	if errno != 0 {
		return fmt.Errorf("activate synchronized seccomp filter: %w", errno)
	}
	if result != 0 {
		return fmt.Errorf("synchronize seccomp filter failed on thread %d", result)
	}
	runtime.KeepAlive(filter)
	noNewPrivileges, err := unix.PrctlRetInt(unix.PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0)
	if err != nil || noNewPrivileges != 1 {
		return fmt.Errorf("verify no_new_privs: value %d: %w", noNewPrivileges, err)
	}
	mode, err := unix.PrctlRetInt(unix.PR_GET_SECCOMP, 0, 0, 0, 0)
	if err != nil || mode != unix.SECCOMP_MODE_FILTER {
		return fmt.Errorf("verify seccomp mode: value %d: %w", mode, err)
	}
	return nil
}

func sealCodexDescriptors() error {
	return unix.CloseRange(3, uint(math.MaxUint32), unix.CLOSE_RANGE_CLOEXEC|unix.CLOSE_RANGE_UNSHARE)
}

func codexSocketFilter() []unix.SockFilter {
	deny := uint32(unix.SECCOMP_RET_ERRNO) | uint32(unix.EPERM)&uint32(unix.SECCOMP_RET_DATA)
	return []unix.SockFilter{
		bpfStatement(unix.BPF_LD|unix.BPF_W|unix.BPF_ABS, seccompDataArchOffset),
		bpfJump(unix.BPF_JMP|unix.BPF_JEQ|unix.BPF_K, unix.AUDIT_ARCH_X86_64, 1, 0),
		bpfStatement(unix.BPF_RET|unix.BPF_K, unix.SECCOMP_RET_KILL_PROCESS),
		bpfStatement(unix.BPF_LD|unix.BPF_W|unix.BPF_ABS, seccompDataNumberOffset),
		bpfJump(unix.BPF_JMP|unix.BPF_JSET|unix.BPF_K, x32SyscallBit, 0, 1),
		bpfStatement(unix.BPF_RET|unix.BPF_K, deny),
		bpfJump(unix.BPF_JMP|unix.BPF_JEQ|unix.BPF_K, uint32(unix.SYS_SOCKET), 5, 0),
		bpfJump(unix.BPF_JMP|unix.BPF_JEQ|unix.BPF_K, uint32(unix.SYS_SOCKETPAIR), 4, 0),
		bpfJump(unix.BPF_JMP|unix.BPF_JEQ|unix.BPF_K, uint32(unix.SYS_IO_URING_SETUP), 6, 0),
		bpfJump(unix.BPF_JMP|unix.BPF_JEQ|unix.BPF_K, uint32(unix.SYS_IO_URING_ENTER), 5, 0),
		bpfJump(unix.BPF_JMP|unix.BPF_JEQ|unix.BPF_K, uint32(unix.SYS_IO_URING_REGISTER), 4, 0),
		bpfStatement(unix.BPF_RET|unix.BPF_K, unix.SECCOMP_RET_ALLOW),
		bpfStatement(unix.BPF_LD|unix.BPF_W|unix.BPF_ABS, seccompDataArgumentsOffset),
		bpfJump(unix.BPF_JMP|unix.BPF_JEQ|unix.BPF_K, uint32(unix.AF_VSOCK), 1, 0),
		bpfStatement(unix.BPF_RET|unix.BPF_K, unix.SECCOMP_RET_ALLOW),
		bpfStatement(unix.BPF_RET|unix.BPF_K, deny),
	}
}

func bpfStatement(code uint16, value uint32) unix.SockFilter {
	return unix.SockFilter{Code: code, K: value}
}

func bpfJump(code uint16, value uint32, yes, no uint8) unix.SockFilter {
	return unix.SockFilter{Code: code, Jt: yes, Jf: no, K: value}
}
