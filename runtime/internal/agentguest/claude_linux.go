//go:build linux

package agentguest

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strconv"
	"syscall"

	"golang.org/x/sys/unix"
)

const maxClaudeBinaryBytes = int64(512 << 20)

// PrepareClaudeLinuxPID1 constructs a networkless, tmpfs-backed cell and
// verifies the two executables selected from its read-only payload.
func PrepareClaudeLinuxPID1(config ClaudeConfig) error {
	if os.Getpid() != 1 {
		return fmt.Errorf("Claude guest supervisor must run as PID 1, got %d", os.Getpid())
	}
	if err := requireStaticBuild(); err != nil {
		return err
	}
	if err := config.Validate(); err != nil {
		return err
	}
	if err := mountKernelFilesystems(); err != nil {
		return err
	}
	if err := attachConsole(); err != nil {
		return err
	}
	if err := mountMutableFilesystems(); err != nil {
		return err
	}
	if err := mountClaudePayload(config.PayloadDrive); err != nil {
		return err
	}
	if err := configureClaudeDirectories(); err != nil {
		return err
	}
	if err := bringLoopbackUp(); err != nil {
		return err
	}
	if err := verifyClaudePayloadFile(ClaudeExecutable, config.ClaudeSHA256, maxClaudeBinaryBytes, true); err != nil {
		return err
	}
	if err := verifyClaudePayloadFile(ClaudeRelayExecutable, config.RelaySHA256, maxCodexBinaryBytes, true); err != nil {
		return err
	}
	if err := verifyClaudePayloadFile(ClaudeLoader, "", maxCodexBinaryBytes, true); err != nil {
		return err
	}
	if config.Schema == ClaudeHTTPConfigSchema {
		if err := verifyClaudePayloadFile(ClaudeBusyBoxExecutable, config.BusyBoxSHA256, maxCodexBinaryBytes, true); err != nil {
			return err
		}
		if err := verifyClaudePayloadFile(ClaudeBashExecutable, config.BashSHA256, maxCodexBinaryBytes, true); err != nil {
			return err
		}
		if err := configureClaudeShell(); err != nil {
			return err
		}
	}
	return writeClaudeMCPConfig()
}

func configureClaudeShell() error {
	for _, directory := range []string{"/bin", "/usr/bin", "/lib64", "/lib/x86_64-linux-gnu"} {
		if err := os.MkdirAll(directory, 0o755); err != nil {
			return fmt.Errorf("create Claude userland directory %s: %w", directory, err)
		}
	}
	commands := []struct{ path, target string }{
		{path: "/bin/bash", target: ClaudeBashExecutable},
		{path: "/bin/sh", target: ClaudeBusyBoxExecutable},
		{path: "/lib64/ld-linux-x86-64.so.2", target: ClaudeLoader},
		{path: "/lib/x86_64-linux-gnu/libc.so.6", target: ClaudeLibraryPath + "/libc.so.6"},
		{path: "/lib/x86_64-linux-gnu/libtinfo.so.6", target: ClaudeLibraryPath + "/libtinfo.so.6"},
		{path: "/usr/bin/awk", target: ClaudeBusyBoxExecutable},
		{path: "/usr/bin/cat", target: ClaudeBusyBoxExecutable},
		{path: "/usr/bin/env", target: ClaudeBusyBoxExecutable},
		{path: "/usr/bin/grep", target: ClaudeBusyBoxExecutable},
		{path: "/usr/bin/sed", target: ClaudeBusyBoxExecutable},
		{path: "/usr/bin/uname", target: ClaudeBusyBoxExecutable},
	}
	for _, command := range commands {
		if err := os.Symlink(command.target, command.path); err != nil {
			return fmt.Errorf("publish fixed Claude userland command %s: %w", command.path, err)
		}
	}
	return nil
}

func mountClaudePayload(device string) error {
	if device != "/dev/vda" {
		return errors.New("Claude payload block device is not /dev/vda")
	}
	if err := os.MkdirAll(ClaudePayloadMount, 0o555); err != nil {
		return fmt.Errorf("create Claude payload mount point: %w", err)
	}
	flags := uintptr(unix.MS_RDONLY | unix.MS_NOSUID | unix.MS_NODEV)
	if err := unix.Mount(device, ClaudePayloadMount, "squashfs", flags, ""); err != nil {
		return fmt.Errorf("mount read-only Claude payload: %w", err)
	}
	return nil
}

func configureClaudeDirectories() error {
	for _, directory := range []string{"/home/claude", ClaudeHomeDirectory, WorkspaceDirectory} {
		if err := os.MkdirAll(directory, 0o700); err != nil {
			return fmt.Errorf("create Claude directory %s: %w", directory, err)
		}
		if err := os.Chown(directory, agentUID, agentGID); err != nil {
			return fmt.Errorf("assign Claude directory %s: %w", directory, err)
		}
		if err := os.Chmod(directory, 0o700); err != nil {
			return fmt.Errorf("protect Claude directory %s: %w", directory, err)
		}
	}
	return nil
}

func writeClaudeMCPConfig() error {
	value := map[string]any{"mcpServers": map[string]any{"continuity": map[string]any{
		"type": "stdio", "command": ClaudeRelayExecutable,
		"args": []string{"-loopback-port", fmt.Sprint(DefaultMCPPort)}, "env": map[string]string{},
	}}}
	data, err := json.Marshal(value)
	if err != nil {
		return err
	}
	if err := os.WriteFile(ClaudeMCPConfigPath, data, 0o400); err != nil {
		return fmt.Errorf("write fixed Claude MCP config: %w", err)
	}
	return os.Chown(ClaudeMCPConfigPath, agentUID, agentGID)
}

func verifyClaudePayloadFile(path, expectedSHA256 string, maxBytes int64, executable bool) error {
	descriptor, err := unix.Open(path, unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return fmt.Errorf("open Claude payload file %s: %w", path, err)
	}
	file := os.NewFile(uintptr(descriptor), path)
	if file == nil {
		_ = unix.Close(descriptor)
		return errors.New("wrap Claude payload file")
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() <= 0 || info.Size() > maxBytes || (executable && info.Mode()&0o111 == 0) {
		return fmt.Errorf("Claude payload file %s is not a bounded executable regular file", path)
	}
	if expectedSHA256 == "" {
		return nil
	}
	digest := sha256.New()
	if _, err := io.Copy(digest, file); err != nil {
		return fmt.Errorf("hash Claude payload file %s: %w", path, err)
	}
	actual := hex.EncodeToString(digest.Sum(nil))
	if actual != expectedSHA256 {
		return fmt.Errorf("Claude payload file %s SHA-256 is %s, require %s", path, actual, expectedSHA256)
	}
	return nil
}

func StartClaude(config ClaudeConfig, stderr io.Writer, cgroupFD int) (*exec.Cmd, io.ReadCloser, error) {
	if err := config.Validate(); err != nil {
		return nil, nil, err
	}
	if stderr == nil || cgroupFD < 0 {
		return nil, nil, errors.New("Claude launch requires stderr and a cgroup descriptor")
	}
	arguments := []string{
		ClaudeChildMode,
		strconv.Itoa(config.Schema),
		strconv.FormatUint(uint64(config.ModelPort), 10),
		config.SessionID,
		strconv.FormatUint(uint64(config.EgressPort), 10),
	}
	arguments = append(arguments, config.Arguments()...)
	command := exec.Command(InitExecutable, arguments...)
	command.Dir = WorkspaceDirectory
	command.Env = fixedClaudeEnvironment(config.Schema, config.ModelPort, config.SessionID, config.EgressPort)
	command.Stdin = nil
	command.Stderr = stderr
	command.SysProcAttr = &syscall.SysProcAttr{
		Credential: &syscall.Credential{Uid: agentUID, Gid: agentGID, Groups: []uint32{}},
		Pdeathsig:  syscall.SIGKILL, UseCgroupFD: true, CgroupFD: cgroupFD,
	}
	stdout, err := command.StdoutPipe()
	if err != nil {
		return nil, nil, fmt.Errorf("create Claude stdout pipe: %w", err)
	}
	if err := command.Start(); err != nil {
		_ = stdout.Close()
		return nil, nil, fmt.Errorf("start payload Claude child: %w", err)
	}
	return command, stdout, nil
}

func fixedClaudeEnvironment(schema int, modelPort uint32, sessionID string, egressPort uint32) []string {
	environment := []string{
		"HOME=/home/claude", "CLAUDE_CONFIG_DIR=" + ClaudeHomeDirectory,
		fmt.Sprintf("ANTHROPIC_BASE_URL=http://127.0.0.1:%d", modelPort),
		"ANTHROPIC_API_KEY=fixture-credential", "ANTHROPIC_MODEL=claude-fixture-1",
		"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1", "CLAUDE_CODE_SKIP_PROMPT_HISTORY=1",
		"DISABLE_AUTOUPDATER=1", "DISABLE_TELEMETRY=1",
		"LANG=C", "LC_ALL=C", "NO_PROXY=127.0.0.1,localhost", "no_proxy=127.0.0.1,localhost",
		"PATH=/opt/claude/bin:/usr/bin:/bin", "TMPDIR=/tmp",
	}
	if schema == ClaudeHTTPConfigSchema {
		environment = append(environment,
			"SAFE_CHANGE_CALL_ID="+sessionID,
			fmt.Sprintf("SAFE_CHANGE_EGRESS_URL=http://127.0.0.1:%d/v1/reserve", egressPort),
		)
	}
	return environment
}
