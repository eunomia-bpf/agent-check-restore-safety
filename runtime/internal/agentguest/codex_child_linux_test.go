//go:build linux

package agentguest

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"testing"

	"golang.org/x/sys/unix"
)

const (
	seccompHelperEnvironment    = "SAFE_CHANGE_SECCOMP_HELPER"
	descriptorHelperEnvironment = "SAFE_CHANGE_DESCRIPTOR_HELPER"
	descriptorPathEnvironment   = "SAFE_CHANGE_DESCRIPTOR_PATH"
)

func TestExecCodexChildUsesFixedIdentityFilterPathArgumentsAndEnvironment(t *testing.T) {
	execFailure := errors.New("exec fixture returned")
	arguments := append([]string(nil), validConfig().Arguments...)
	environment := fixedCodexEnvironment()
	for left, right := 0, len(environment)-1; left < right; left, right = left+1, right-1 {
		environment[left], environment[right] = environment[right], environment[left]
	}
	var events []string
	system := validCodexChildRuntime()
	system.environment = func() []string { return environment }
	system.installFilter = func() error {
		events = append(events, "filter")
		return nil
	}
	system.sealDescriptors = func() error {
		events = append(events, "seal")
		return nil
	}
	system.exec = func(path string, argv, env []string) error {
		events = append(events, "exec")
		if path != CodexExecutable {
			t.Fatalf("exec path = %q, want %q", path, CodexExecutable)
		}
		wantArgv := append([]string{CodexExecutable}, arguments...)
		if strings.Join(argv, "\x00") != strings.Join(wantArgv, "\x00") {
			t.Fatalf("exec argv = %q, want %q", argv, wantArgv)
		}
		if strings.Join(env, "\x00") != strings.Join(fixedCodexEnvironment(), "\x00") {
			t.Fatalf("exec environment = %q", env)
		}
		return execFailure
	}
	err := execCodexChild(arguments, system)
	if !errors.Is(err, execFailure) {
		t.Fatalf("execCodexChild error = %v, want exec fixture", err)
	}
	if strings.Join(events, ",") != "filter,seal,exec" {
		t.Fatalf("child events = %v, want filter, descriptor seal, then exec", events)
	}
}

func TestExecCodexChildRejectsAuthorityBeforeFilter(t *testing.T) {
	filterCalls := 0
	execCalls := 0
	base := func() codexChildRuntime {
		system := validCodexChildRuntime()
		system.installFilter = func() error { filterCalls++; return nil }
		system.exec = func(string, []string, []string) error { execCalls++; return nil }
		return system
	}
	tests := []struct {
		name      string
		arguments []string
		mutate    func(*codexChildRuntime)
	}{
		{name: "command", arguments: []string{"sh", "-c", "id"}},
		{name: "real uid", arguments: validConfig().Arguments, mutate: func(system *codexChildRuntime) {
			system.resuid = func() (int, int, int) { return 0, agentUID, agentUID }
		}},
		{name: "saved uid", arguments: validConfig().Arguments, mutate: func(system *codexChildRuntime) {
			system.resuid = func() (int, int, int) { return agentUID, agentUID, 0 }
		}},
		{name: "group", arguments: validConfig().Arguments, mutate: func(system *codexChildRuntime) {
			system.resgid = func() (int, int, int) { return 0, agentGID, agentGID }
		}},
		{name: "parent", arguments: validConfig().Arguments, mutate: func(system *codexChildRuntime) { system.ppid = func() int { return 42 } }},
		{name: "supplementary groups", arguments: validConfig().Arguments, mutate: func(system *codexChildRuntime) {
			system.groups = func() ([]int, error) { return []int{agentGID}, nil }
		}},
		{name: "extra environment", arguments: validConfig().Arguments, mutate: func(system *codexChildRuntime) {
			system.environment = func() []string { return append(fixedCodexEnvironment(), "LD_PRELOAD=/tmp/escape.so") }
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			beforeFilter, beforeExec := filterCalls, execCalls
			system := base()
			if test.mutate != nil {
				test.mutate(&system)
			}
			if err := execCodexChild(test.arguments, system); err == nil {
				t.Fatal("forbidden child launch accepted")
			}
			if filterCalls != beforeFilter || execCalls != beforeExec {
				t.Fatalf("forbidden child reached filter/exec: filter=%d exec=%d", filterCalls-beforeFilter, execCalls-beforeExec)
			}
		})
	}
}

func TestExecCodexChildFilterFailurePreventsExec(t *testing.T) {
	filterFailure := errors.New("seccomp unavailable")
	execCalled := false
	system := validCodexChildRuntime()
	system.installFilter = func() error { return filterFailure }
	system.exec = func(string, []string, []string) error { execCalled = true; return nil }
	err := execCodexChild(validConfig().Arguments, system)
	if !errors.Is(err, filterFailure) || execCalled {
		t.Fatalf("execCodexChild error=%v execCalled=%t", err, execCalled)
	}
}

func TestExecCodexChildDescriptorFailurePreventsExec(t *testing.T) {
	sealFailure := errors.New("close_range unavailable")
	execCalled := false
	system := validCodexChildRuntime()
	system.sealDescriptors = func() error { return sealFailure }
	system.exec = func(string, []string, []string) error { execCalled = true; return nil }
	err := execCodexChild(validConfig().Arguments, system)
	if !errors.Is(err, sealFailure) || execCalled {
		t.Fatalf("execCodexChild error=%v execCalled=%t", err, execCalled)
	}
}

func TestCodexSocketFilterDecisions(t *testing.T) {
	deny := uint32(unix.SECCOMP_RET_ERRNO) | uint32(unix.EPERM)
	tests := []struct {
		name       string
		arch       uint32
		number     uint32
		argument0  uint32
		wantAction uint32
	}{
		{name: "vsock socket", arch: unix.AUDIT_ARCH_X86_64, number: unix.SYS_SOCKET, argument0: unix.AF_VSOCK, wantAction: deny},
		{name: "inet socket", arch: unix.AUDIT_ARCH_X86_64, number: unix.SYS_SOCKET, argument0: unix.AF_INET, wantAction: unix.SECCOMP_RET_ALLOW},
		{name: "vsock socketpair", arch: unix.AUDIT_ARCH_X86_64, number: unix.SYS_SOCKETPAIR, argument0: unix.AF_VSOCK, wantAction: deny},
		{name: "unix socketpair", arch: unix.AUDIT_ARCH_X86_64, number: unix.SYS_SOCKETPAIR, argument0: unix.AF_UNIX, wantAction: unix.SECCOMP_RET_ALLOW},
		{name: "stdio write", arch: unix.AUDIT_ARCH_X86_64, number: unix.SYS_WRITE, wantAction: unix.SECCOMP_RET_ALLOW},
		{name: "io uring setup", arch: unix.AUDIT_ARCH_X86_64, number: unix.SYS_IO_URING_SETUP, wantAction: deny},
		{name: "io uring enter", arch: unix.AUDIT_ARCH_X86_64, number: unix.SYS_IO_URING_ENTER, wantAction: deny},
		{name: "io uring register", arch: unix.AUDIT_ARCH_X86_64, number: unix.SYS_IO_URING_REGISTER, wantAction: deny},
		{name: "x32 syscall", arch: unix.AUDIT_ARCH_X86_64, number: x32SyscallBit | unix.SYS_WRITE, wantAction: deny},
		{name: "wrong architecture", arch: 0x40000003, number: unix.SYS_WRITE, wantAction: unix.SECCOMP_RET_KILL_PROCESS},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got := evaluateCodexFilter(t, test.arch, test.number, test.argument0)
			if got != test.wantAction {
				t.Fatalf("filter action = %#x, want %#x", got, test.wantAction)
			}
		})
	}
}

func TestCodexSocketFilterKernelEnforcement(t *testing.T) {
	if os.Getenv(seccompHelperEnvironment) == "1" {
		runSeccompHelper()
		return
	}
	if runtime.GOARCH != "amd64" {
		t.Skip("Codex guest seccomp contract is x86_64")
	}
	command := exec.Command(os.Args[0], "-test.run=^TestCodexSocketFilterKernelEnforcement$")
	command.Env = append(withoutEnvironment(os.Environ(), seccompHelperEnvironment), seccompHelperEnvironment+"=1")
	var stdout, stderr bytes.Buffer
	command.Stdout, command.Stderr = &stdout, &stderr
	if err := command.Run(); err != nil {
		t.Fatalf("seccomp helper: %v\nstderr: %s", err, stderr.String())
	}
	if stdout.String() != "stdio-ok\n" {
		t.Fatalf("seccomp helper stdout = %q", stdout.String())
	}
}

func TestSealCodexDescriptorsAcrossExec(t *testing.T) {
	switch os.Getenv(descriptorHelperEnvironment) {
	case "seal":
		runDescriptorSealHelper()
		return
	case "verify":
		runDescriptorVerifyHelper()
		return
	}
	extra, err := os.CreateTemp(t.TempDir(), "inherited-fd")
	if err != nil {
		t.Fatal(err)
	}
	defer extra.Close()
	command := exec.Command(os.Args[0], "-test.run=^TestSealCodexDescriptorsAcrossExec$")
	command.ExtraFiles = []*os.File{extra}
	command.Env = append(withoutEnvironment(os.Environ(), descriptorHelperEnvironment), descriptorHelperEnvironment+"=seal", descriptorPathEnvironment+"="+extra.Name())
	var stdout, stderr bytes.Buffer
	command.Stdout, command.Stderr = &stdout, &stderr
	if err := command.Run(); err != nil {
		t.Fatalf("descriptor helper: %v\nstderr: %s", err, stderr.String())
	}
	if stdout.String() != "descriptors-ok\n" {
		t.Fatalf("descriptor helper stdout = %q", stdout.String())
	}
}

func validCodexChildRuntime() codexChildRuntime {
	return codexChildRuntime{
		resuid: func() (int, int, int) { return agentUID, agentUID, agentUID },
		resgid: func() (int, int, int) { return agentGID, agentGID, agentGID },
		ppid:   func() int { return 1 }, groups: func() ([]int, error) { return nil, nil },
		environment:   func() []string { return fixedCodexEnvironment() },
		installFilter: func() error { return nil }, sealDescriptors: func() error { return nil },
		exec: func(string, []string, []string) error { return errors.New("exec fixture") },
	}
}

func evaluateCodexFilter(t *testing.T, arch, number, argument0 uint32) uint32 {
	t.Helper()
	filter := codexSocketFilter()
	var accumulator uint32
	for pc := 0; pc < len(filter); {
		instruction := filter[pc]
		switch instruction.Code {
		case unix.BPF_LD | unix.BPF_W | unix.BPF_ABS:
			switch instruction.K {
			case seccompDataArchOffset:
				accumulator = arch
			case seccompDataNumberOffset:
				accumulator = number
			case seccompDataArgumentsOffset:
				accumulator = argument0
			default:
				t.Fatalf("unexpected BPF load offset %d", instruction.K)
			}
			pc++
		case unix.BPF_JMP | unix.BPF_JEQ | unix.BPF_K:
			jump := instruction.Jf
			if accumulator == instruction.K {
				jump = instruction.Jt
			}
			pc += int(jump) + 1
		case unix.BPF_JMP | unix.BPF_JSET | unix.BPF_K:
			jump := instruction.Jf
			if accumulator&instruction.K != 0 {
				jump = instruction.Jt
			}
			pc += int(jump) + 1
		case unix.BPF_RET | unix.BPF_K:
			return instruction.K
		default:
			t.Fatalf("unexpected BPF instruction %#x", instruction.Code)
		}
	}
	t.Fatal("BPF program terminated without RET")
	return 0
}

func runSeccompHelper() {
	runtime.LockOSThread()
	fail := func(format string, arguments ...any) {
		_, _ = fmt.Fprintf(os.Stderr, format+"\n", arguments...)
		os.Exit(2)
	}
	if err := installCodexSocketFilter(); err != nil {
		fail("install filter: %v", err)
	}
	value, err := unix.PrctlRetInt(unix.PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0)
	if err != nil || value != 1 {
		fail("no_new_privs=%d error=%v", value, err)
	}
	if descriptor, err := unix.Socket(unix.AF_VSOCK, unix.SOCK_STREAM|unix.SOCK_CLOEXEC, 0); !errors.Is(err, unix.EPERM) {
		if err == nil {
			_ = unix.Close(descriptor)
		}
		fail("AF_VSOCK socket error=%v, want EPERM", err)
	}
	if descriptors, err := unix.Socketpair(unix.AF_VSOCK, unix.SOCK_STREAM|unix.SOCK_CLOEXEC, 0); !errors.Is(err, unix.EPERM) {
		if err == nil {
			_ = unix.Close(descriptors[0])
			_ = unix.Close(descriptors[1])
		}
		fail("AF_VSOCK socketpair error=%v, want EPERM", err)
	}
	if _, _, errno := unix.RawSyscall6(unix.SYS_SOCKET, uintptr(uint64(1)<<32|uint64(unix.AF_VSOCK)), unix.SOCK_STREAM, 0, 0, 0, 0); errno != unix.EPERM {
		fail("high-word AF_VSOCK socket errno=%v, want EPERM", errno)
	}
	inet, err := unix.Socket(unix.AF_INET, unix.SOCK_STREAM|unix.SOCK_CLOEXEC, 0)
	if err != nil {
		fail("AF_INET socket: %v", err)
	}
	_ = unix.Close(inet)
	pair, err := unix.Socketpair(unix.AF_UNIX, unix.SOCK_STREAM|unix.SOCK_CLOEXEC, 0)
	if err != nil {
		fail("AF_UNIX socketpair: %v", err)
	}
	_ = unix.Close(pair[0])
	_ = unix.Close(pair[1])
	if _, _, errno := unix.RawSyscall(unix.SYS_IO_URING_SETUP, 1, 0, 0); errno != unix.EPERM {
		fail("io_uring_setup errno=%v, want EPERM", errno)
	}
	if _, _, errno := unix.RawSyscall6(unix.SYS_IO_URING_ENTER, ^uintptr(0), 0, 0, 0, 0, 0); errno != unix.EPERM {
		fail("io_uring_enter errno=%v, want EPERM", errno)
	}
	if _, _, errno := unix.RawSyscall6(unix.SYS_IO_URING_REGISTER, ^uintptr(0), 0, 0, 0, 0, 0); errno != unix.EPERM {
		fail("io_uring_register errno=%v, want EPERM", errno)
	}
	if _, err := unix.Write(unix.Stdout, []byte("stdio-ok\n")); err != nil {
		fail("write stdout: %v", err)
	}
	os.Exit(0)
}

func withoutEnvironment(environment []string, key string) []string {
	prefix := key + "="
	result := make([]string, 0, len(environment))
	for _, entry := range environment {
		if !strings.HasPrefix(entry, prefix) {
			result = append(result, entry)
		}
	}
	return result
}

func runDescriptorSealHelper() {
	runtime.LockOSThread()
	if target, err := os.Readlink("/proc/self/fd/3"); err != nil || target != os.Getenv(descriptorPathEnvironment) {
		_, _ = fmt.Fprintf(os.Stderr, "inherited fd3 before seal targets %q: %v\n", target, err)
		os.Exit(2)
	}
	if err := sealCodexDescriptors(); err != nil {
		_, _ = fmt.Fprintf(os.Stderr, "seal descriptors: %v\n", err)
		os.Exit(2)
	}
	environment := append(withoutEnvironment(os.Environ(), descriptorHelperEnvironment), descriptorHelperEnvironment+"=verify")
	if err := unix.Exec("/proc/self/exe", []string{"/proc/self/exe", "-test.run=^TestSealCodexDescriptorsAcrossExec$"}, environment); err != nil {
		_, _ = fmt.Fprintf(os.Stderr, "exec descriptor verifier: %v\n", err)
		os.Exit(2)
	}
}

func runDescriptorVerifyHelper() {
	wantPath := os.Getenv(descriptorPathEnvironment)
	entries, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		_, _ = fmt.Fprintf(os.Stderr, "read verifier descriptors: %v\n", err)
		os.Exit(2)
	}
	for _, entry := range entries {
		target, readErr := os.Readlink("/proc/self/fd/" + entry.Name())
		if readErr == nil && target == wantPath {
			_, _ = fmt.Fprintf(os.Stderr, "injected descriptor survived exec as fd%s\n", entry.Name())
			os.Exit(2)
		}
	}
	for descriptor := 0; descriptor <= 2; descriptor++ {
		if _, err := unix.FcntlInt(uintptr(descriptor), unix.F_GETFD, 0); err != nil {
			_, _ = fmt.Fprintf(os.Stderr, "stdio fd%d missing: %v\n", descriptor, err)
			os.Exit(2)
		}
	}
	_, _ = os.Stdout.WriteString("descriptors-ok\n")
	os.Exit(0)
}
