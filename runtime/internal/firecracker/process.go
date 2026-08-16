package firecracker

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

const (
	defaultProcessStartTimeout = 10 * time.Second
	defaultProcessStopTimeout  = 10 * time.Second
	maxExecutableBytes         = int64(128 << 20)
)

// ProcessConfig describes one Firecracker process.  StartProcess owns only
// the child it starts; it never removes a pre-existing API socket, avoiding
// accidental attachment to or deletion of a different microVM's control API.
type ProcessConfig struct {
	Binary             string
	ExecutableSHA256   string
	APISocket          string
	ID                 string
	Args               []string
	Env                []string
	Dir                string
	Stdout             io.Writer
	Stderr             io.Writer
	StartupTimeout     time.Duration
	TerminationTimeout time.Duration

	// InheritedFiles are made available to Firecracker as descriptors 4 and
	// above. Descriptor 3 is reserved for the already-verified executable.
	// Callers retain ownership of these files. This is used for sealed boot and
	// snapshot artifacts so Firecracker never reopens mutable pathnames.
	InheritedFiles []*os.File
}

// ProcessIdentity is the /proc identity captured after startup. Device, inode,
// content hash, and Linux start-time ticks bind the PID to the exact execution
// instance that was started. StartProcess also requires a pidfd for signaling.
type ProcessIdentity struct {
	PID              int
	Executable       string
	Device           uint64
	Inode            uint64
	ExecutableSHA256 string
	StartTimeTicks   uint64
}

// TerminationDisposition records whether the supervisor initiated process
// shutdown or merely observed that the VMM had already exited.
type TerminationDisposition string

const (
	TerminationBySupervisor  TerminationDisposition = "supervisor"
	TerminationAlreadyExited TerminationDisposition = "already-exited"
)

// Process owns one Firecracker child process.
type Process struct {
	mu                 sync.Mutex
	cmd                *exec.Cmd
	socket             string
	socketParent       os.FileInfo
	id                 string
	identity           ProcessIdentity
	pidfd              int
	terminationTimeout time.Duration
	waitDone           chan struct{}
	waitErr            error
	supervisorSIGTERM  bool
	supervisorSIGKILL  bool
}

// StartProcess starts binary with the supplied API socket and instance ID,
// validates that /proc/PID/exe is the executable just opened, then waits until
// the Unix API socket is a live listener.  It rejects a pre-existing socket
// rather than risking control of a process it did not create.
func StartProcess(ctx context.Context, config ProcessConfig) (*Process, error) {
	if config.Binary == "" || config.APISocket == "" || config.ID == "" {
		return nil, errors.New("Firecracker process requires binary, API socket, and ID")
	}
	if len(config.ExecutableSHA256) != 64 || strings.ToLower(config.ExecutableSHA256) != config.ExecutableSHA256 {
		return nil, errors.New("Firecracker process requires an expected executable SHA-256")
	}
	if _, err := hex.DecodeString(config.ExecutableSHA256); err != nil {
		return nil, errors.New("Firecracker process requires an expected executable SHA-256")
	}
	if !filepath.IsAbs(config.Binary) || !filepath.IsAbs(config.APISocket) {
		return nil, errors.New("Firecracker binary and API socket paths must be absolute")
	}
	if strings.IndexByte(config.APISocket, 0) >= 0 || strings.IndexByte(config.ID, 0) >= 0 {
		return nil, errors.New("Firecracker process configuration contains NUL")
	}
	if err := rejectReservedArgs(config.Args); err != nil {
		return nil, err
	}
	for index, file := range config.InheritedFiles {
		if file == nil {
			return nil, fmt.Errorf("Firecracker inherited file %d is nil", index)
		}
		if _, err := file.Stat(); err != nil {
			return nil, fmt.Errorf("inspect Firecracker inherited file %d: %w", index, err)
		}
	}
	socketParent, err := validateSocketParent(config.APISocket)
	if err != nil {
		return nil, err
	}
	if err := requireAbsentSocket(config.APISocket); err != nil {
		return nil, err
	}
	if config.StartupTimeout <= 0 {
		config.StartupTimeout = defaultProcessStartTimeout
	}
	if config.TerminationTimeout <= 0 {
		config.TerminationTimeout = defaultProcessStopTimeout
	}

	executable, executableFile, identity, err := openExecutable(config.Binary, config.ExecutableSHA256)
	if err != nil {
		return nil, err
	}
	defer executableFile.Close()
	args := make([]string, 0, len(config.Args)+4)
	args = append(args, config.Args...)
	args = append(args, "--api-sock", config.APISocket, "--id", config.ID)
	// Executing the inherited descriptor, instead of reopening a path after we
	// identified it, prevents a binary-path replacement race before exec.
	extraFiles := make([]*os.File, 0, len(config.InheritedFiles)+1)
	extraFiles = append(extraFiles, executableFile)
	extraFiles = append(extraFiles, config.InheritedFiles...)
	cmd := &exec.Cmd{
		Path: "/proc/self/fd/3", Args: append([]string{executable}, args...),
		ExtraFiles: extraFiles, Dir: config.Dir, Stdout: config.Stdout, Stderr: config.Stderr,
		// Firecracker must not survive a crashed or SIGKILLed supervisor. Go's
		// Linux fork path also self-signals if the parent dies before prctl.
		SysProcAttr: &syscall.SysProcAttr{Pdeathsig: syscall.SIGKILL},
	}
	if config.Env != nil {
		cmd.Env = append([]string(nil), config.Env...)
	}
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start Firecracker: %w", err)
	}
	process := &Process{cmd: cmd, socket: config.APISocket, socketParent: socketParent, id: config.ID, identity: identity, pidfd: -1, terminationTimeout: config.TerminationTimeout, waitDone: make(chan struct{})}
	process.identity.PID = cmd.Process.Pid
	fd, openErr := unix.PidfdOpen(cmd.Process.Pid, 0)
	if openErr != nil {
		// The child has not been waited yet, so its PID cannot be reused while
		// this best-effort cleanup signals and reaps it.
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
		return nil, fmt.Errorf("open Firecracker pidfd: %w", openErr)
	}
	process.pidfd = fd
	go func() {
		err := cmd.Wait()
		process.mu.Lock()
		process.waitErr = err
		process.mu.Unlock()
		close(process.waitDone)
	}()
	startTime, err := procStartTime(cmd.Process.Pid)
	if err != nil {
		_ = process.Terminate(context.Background())
		return nil, fmt.Errorf("read Firecracker process start time: %w", err)
	}
	process.mu.Lock()
	process.identity.StartTimeTicks = startTime
	process.mu.Unlock()
	if err := process.VerifyIdentity(); err != nil {
		_ = process.Terminate(context.Background())
		return nil, err
	}
	startupCtx, cancel := withTimeout(ctx, config.StartupTimeout)
	defer cancel()
	if err := process.waitForSocket(startupCtx); err != nil {
		_ = process.Terminate(context.Background())
		return nil, err
	}
	return process, nil
}

// Start is an alias for StartProcess for callers that use the package as the
// lifecycle owner rather than the API client.
func Start(ctx context.Context, config ProcessConfig) (*Process, error) {
	return StartProcess(ctx, config)
}

// StartProcessWithConfig is retained as an explicit spelling for integrations
// that prefer the configuration type in their lifecycle API.
func StartProcessWithConfig(ctx context.Context, config ProcessConfig) (*Process, error) {
	return StartProcess(ctx, config)
}

func openExecutable(binary, expectedSHA256 string) (string, *os.File, ProcessIdentity, error) {
	resolved, err := filepath.EvalSymlinks(binary)
	if err != nil {
		return "", nil, ProcessIdentity{}, fmt.Errorf("resolve Firecracker binary: %w", err)
	}
	if !filepath.IsAbs(resolved) {
		return "", nil, ProcessIdentity{}, errors.New("resolved Firecracker binary is not absolute")
	}
	fd, err := unix.Open(resolved, unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return "", nil, ProcessIdentity{}, fmt.Errorf("open Firecracker binary: %w", err)
	}
	source := os.NewFile(uintptr(fd), resolved)
	if source == nil {
		_ = unix.Close(fd)
		return "", nil, ProcessIdentity{}, errors.New("wrap Firecracker binary descriptor")
	}
	defer source.Close()
	info, err := source.Stat()
	if err != nil {
		return "", nil, ProcessIdentity{}, fmt.Errorf("stat Firecracker binary: %w", err)
	}
	if !info.Mode().IsRegular() || info.Mode()&0o111 == 0 || info.Size() <= 0 || info.Size() > maxExecutableBytes {
		return "", nil, ProcessIdentity{}, errors.New("Firecracker binary is not an executable regular file")
	}
	sealedFD, err := unix.MemfdCreate("verified-firecracker", unix.MFD_CLOEXEC|unix.MFD_ALLOW_SEALING)
	if err != nil {
		return "", nil, ProcessIdentity{}, fmt.Errorf("create sealed Firecracker executable: %w", err)
	}
	sealed := os.NewFile(uintptr(sealedFD), "sealed-firecracker")
	if sealed == nil {
		_ = unix.Close(sealedFD)
		return "", nil, ProcessIdentity{}, errors.New("wrap sealed Firecracker executable")
	}
	fail := func(failure error) (string, *os.File, ProcessIdentity, error) {
		_ = sealed.Close()
		return "", nil, ProcessIdentity{}, failure
	}
	digest := sha256.New()
	written, err := io.CopyN(io.MultiWriter(sealed, digest), source, info.Size())
	if err != nil {
		return fail(fmt.Errorf("copy Firecracker into sealed executable: %w", err))
	}
	if written != info.Size() {
		return fail(fmt.Errorf("copy Firecracker into sealed executable: copied %d of %d bytes", written, info.Size()))
	}
	hash := hex.EncodeToString(digest.Sum(nil))
	if hash != expectedSHA256 {
		return fail(fmt.Errorf("Firecracker executable SHA-256 is %s, require %s", hash, expectedSHA256))
	}
	if err := unix.Fchmod(sealedFD, 0o500); err != nil {
		return fail(fmt.Errorf("make sealed Firecracker executable: %w", err))
	}
	wantedSeals := unix.F_SEAL_SEAL | unix.F_SEAL_SHRINK | unix.F_SEAL_GROW | unix.F_SEAL_WRITE
	if _, err := unix.FcntlInt(sealed.Fd(), unix.F_ADD_SEALS, wantedSeals); err != nil {
		return fail(fmt.Errorf("seal Firecracker executable: %w", err))
	}
	actualSeals, err := unix.FcntlInt(sealed.Fd(), unix.F_GET_SEALS, 0)
	if err != nil || actualSeals != wantedSeals {
		return fail(errors.New("Firecracker executable seals differ"))
	}
	sealedInfo, err := sealed.Stat()
	if err != nil {
		return fail(fmt.Errorf("stat sealed Firecracker executable: %w", err))
	}
	stat, ok := sealedInfo.Sys().(*syscall.Stat_t)
	if !ok {
		return fail(errors.New("sealed Firecracker executable has no Linux stat identity"))
	}
	return resolved, sealed, ProcessIdentity{Executable: resolved, Device: uint64(stat.Dev), Inode: stat.Ino, ExecutableSHA256: hash}, nil
}

func sha256OpenFile(file *os.File) (string, error) {
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return "", err
	}
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

// procStartTime returns field 22 (starttime) from proc(5)'s /proc/PID/stat.
// comm is parenthesized and may itself contain spaces, so parsing begins after
// its final ')' instead of treating the whole file as ordinary whitespace data.
func procStartTime(pid int) (uint64, error) {
	data, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	if err != nil {
		return 0, err
	}
	endComm := strings.LastIndexByte(string(data), ')')
	if endComm < 0 || endComm+2 > len(data) {
		return 0, errors.New("malformed proc stat")
	}
	fields := strings.Fields(string(data[endComm+1:]))
	if len(fields) <= 19 {
		return 0, errors.New("truncated proc stat")
	}
	startTime, err := strconv.ParseUint(fields[19], 10, 64)
	if err != nil {
		return 0, fmt.Errorf("parse proc stat start time: %w", err)
	}
	return startTime, nil
}

func rejectReservedArgs(args []string) error {
	for _, arg := range args {
		if arg == "--api-sock" || arg == "--id" || strings.HasPrefix(arg, "--api-sock=") || strings.HasPrefix(arg, "--id=") {
			return errors.New("Firecracker arguments must not override --api-sock or --id")
		}
		if arg == "--no-seccomp" || strings.HasPrefix(arg, "--no-seccomp=") ||
			arg == "--seccomp-filter" || strings.HasPrefix(arg, "--seccomp-filter=") {
			return errors.New("Firecracker arguments must not disable or replace the built-in seccomp filter")
		}
	}
	return nil
}

func requireAbsentSocket(socket string) error {
	info, err := os.Lstat(socket)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("inspect Firecracker API socket: %w", err)
	}
	if info.Mode()&os.ModeSocket != 0 {
		return fmt.Errorf("Firecracker API socket already exists: %q", socket)
	}
	return fmt.Errorf("Firecracker API socket path already exists and is not a socket: %q", socket)
}

func validateSocketParent(socket string) (os.FileInfo, error) {
	parent := filepath.Clean(filepath.Dir(socket))
	resolved, err := filepath.EvalSymlinks(parent)
	if err != nil {
		return nil, fmt.Errorf("resolve Firecracker API socket parent: %w", err)
	}
	if filepath.Clean(resolved) != parent {
		return nil, errors.New("Firecracker API socket parent path must not traverse a symlink")
	}
	info, err := os.Lstat(parent)
	if err != nil {
		return nil, fmt.Errorf("inspect Firecracker API socket parent: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() || info.Mode().Perm() != 0o700 {
		return nil, errors.New("Firecracker API socket parent must be a private non-symlink directory with mode 0700")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != uint32(os.Geteuid()) {
		return nil, errors.New("Firecracker API socket parent must be owned by the current user")
	}
	return info, nil
}

// Identity returns a copy of the process identity captured during startup.
func (p *Process) Identity() ProcessIdentity {
	if p == nil {
		return ProcessIdentity{}
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.identity
}
func (p *Process) PID() int { return p.Identity().PID }
func (p *Process) APISocket() string {
	if p == nil {
		return ""
	}
	return p.socket
}
func (p *Process) ID() string {
	if p == nil {
		return ""
	}
	return p.id
}

// VerifyIdentity re-reads /proc/PID/exe and refuses a changed, exited, or
// recycled PID.  Terminate calls it before the fallback kill(2) path.
func (p *Process) VerifyIdentity() error {
	if p == nil || p.cmd == nil || p.Identity().PID <= 0 {
		return errors.New("Firecracker process is nil or unstarted")
	}
	select {
	case <-p.waitDone:
		return p.exitError("exited before identity verification")
	default:
	}
	identity := p.Identity()
	file, err := os.Open(fmt.Sprintf("/proc/%d/exe", identity.PID))
	if err != nil {
		return fmt.Errorf("open Firecracker /proc executable: %w", err)
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return fmt.Errorf("stat Firecracker /proc executable: %w", err)
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || uint64(stat.Dev) != identity.Device || stat.Ino != identity.Inode {
		return errors.New("Firecracker PID executable identity differs from the started binary")
	}
	hash, err := sha256OpenFile(file)
	if err != nil {
		return fmt.Errorf("hash Firecracker /proc executable: %w", err)
	}
	if hash != identity.ExecutableSHA256 {
		return errors.New("Firecracker PID executable hash differs from the started binary")
	}
	startTime, err := procStartTime(identity.PID)
	if err != nil {
		return fmt.Errorf("read Firecracker process start time: %w", err)
	}
	if startTime != identity.StartTimeTicks {
		return errors.New("Firecracker PID start time differs from the started process")
	}
	return nil
}

func (p *Process) waitForSocket(ctx context.Context) error {
	for {
		select {
		case <-p.waitDone:
			return p.exitError("exited before API socket became ready")
		default:
		}
		parent, parentErr := validateSocketParent(p.socket)
		if parentErr != nil || !os.SameFile(p.socketParent, parent) {
			return errors.New("Firecracker API socket parent identity or protection changed")
		}
		info, err := os.Lstat(p.socket)
		if err == nil && info.Mode()&os.ModeSocket != 0 {
			if chmodErr := unix.Fchmodat(unix.AT_FDCWD, p.socket, 0o600, unix.AT_SYMLINK_NOFOLLOW); chmodErr != nil {
				return fmt.Errorf("protect Firecracker API socket: %w", chmodErr)
			}
			info, err = os.Lstat(p.socket)
			if err != nil {
				continue
			}
			stat, ok := info.Sys().(*syscall.Stat_t)
			if !ok || stat.Uid != uint32(os.Geteuid()) || info.Mode().Perm() != 0o600 {
				return errors.New("Firecracker API socket must be current-user owned with mode 0600")
			}
			connection, dialErr := (&net.Dialer{Timeout: 100 * time.Millisecond}).DialContext(ctx, "unix", p.socket)
			if dialErr == nil {
				_ = connection.Close()
				return nil
			}
		} else if err != nil && !errors.Is(err, os.ErrNotExist) {
			return fmt.Errorf("inspect Firecracker API socket: %w", err)
		} else if err == nil {
			return errors.New("Firecracker API socket path was replaced by a non-socket")
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("wait for Firecracker API socket: %w", ctx.Err())
		case <-time.After(10 * time.Millisecond):
		}
	}
}

// Wait waits for this child to exit and returns its exec status. It does not
// send a signal; use Terminate for graceful shutdown or Kill for immediate
// containment.
func (p *Process) Wait() error {
	if p == nil {
		return errors.New("Firecracker process is nil")
	}
	<-p.waitDone
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.pidfd >= 0 {
		_ = unix.Close(p.pidfd)
		p.pidfd = -1
	}
	return p.waitErr
}

// Done closes only after the exact child has exited and cmd.Wait has reaped
// it. Callers can monitor unexpected VMM death without polling /proc.
func (p *Process) Done() <-chan struct{} {
	if p == nil || p.waitDone == nil {
		closed := make(chan struct{})
		close(closed)
		return closed
	}
	return p.waitDone
}

// WaitContext observes the exact child's wait status without signaling it or
// consuming lifecycle ownership such as the pidfd.
func (p *Process) WaitContext(ctx context.Context) error {
	if p == nil || p.waitDone == nil {
		return errors.New("Firecracker process is nil or unstarted")
	}
	if ctx == nil {
		return errors.New("Firecracker process wait context is nil")
	}
	select {
	case <-p.waitDone:
		p.mu.Lock()
		defer p.mu.Unlock()
		return p.waitErr
	case <-ctx.Done():
		return ctx.Err()
	}
}

// Kill sends SIGKILL through the pidfd for the exact child owned by Process,
// then waits without cancellation until cmd.Wait has reaped it. A context
// canceled before signaling prevents the kill. If pidfd_send_signal reports
// that the process has already exited, the context bounds only the diagnostic
// wait for the wait goroutine to publish that exit.
//
// A successful SIGKILL is an expected lifecycle outcome, not an API error;
// callers that need the underlying exec status can still call Wait.
func (p *Process) Kill(ctx context.Context) (TerminationDisposition, error) {
	if p == nil {
		return "", errors.New("Firecracker process is nil")
	}
	if ctx == nil {
		return "", errors.New("kill Firecracker requires a context")
	}
	select {
	case <-ctx.Done():
		return "", fmt.Errorf("kill Firecracker before signaling: %w", ctx.Err())
	default:
	}
	select {
	case <-p.waitDone:
		_ = p.Wait()
		return TerminationAlreadyExited, nil
	default:
	}
	// Check again immediately before entering the pidfd signaling critical
	// section. Cancellation racing the syscall cannot revoke a successful
	// SIGKILL, after which reaping is deliberately unconditional.
	select {
	case <-ctx.Done():
		return "", fmt.Errorf("kill Firecracker before signaling: %w", ctx.Err())
	default:
	}
	signaled, err := p.signal(syscall.SIGKILL)
	if err != nil {
		return "", err
	}
	if signaled {
		<-p.waitDone
		_ = p.Wait()
		return TerminationBySupervisor, nil
	}
	select {
	case <-p.waitDone:
		_ = p.Wait()
		return TerminationAlreadyExited, nil
	case <-ctx.Done():
		return "", fmt.Errorf("wait for already-exited Firecracker reap: %w", ctx.Err())
	}
}

// TerminateWithDisposition reliably stops the exact process started by this
// package and reports whether shutdown was supervisor-initiated. It waits for
// graceful SIGTERM until the supplied context expires, then sends SIGKILL and
// confirms reaping. StartProcess requires a pidfd, so lifecycle signaling
// never falls back to a reusable numeric PID.
func (p *Process) TerminateWithDisposition(ctx context.Context) (TerminationDisposition, error) {
	if p == nil {
		return "", errors.New("Firecracker process is nil")
	}
	select {
	case <-p.waitDone:
		if err := p.Wait(); err != nil && !p.wasSupervisorSignalExit(err) {
			return TerminationAlreadyExited, fmt.Errorf("Firecracker exited before supervisor termination: %w", err)
		}
		return TerminationAlreadyExited, nil
	default:
	}
	terminationCtx, cancel := withTimeout(ctx, p.terminationTimeout)
	defer cancel()
	signaled, err := p.signal(syscall.SIGTERM)
	if err != nil {
		return "", err
	}
	if !signaled {
		if err := p.Wait(); err != nil && !p.wasSupervisorSignalExit(err) {
			return TerminationAlreadyExited, fmt.Errorf("Firecracker exited before supervisor termination: %w", err)
		}
		return TerminationAlreadyExited, nil
	}
	select {
	case <-p.waitDone:
		_ = p.Wait()
		return TerminationBySupervisor, nil
	case <-terminationCtx.Done():
	}
	if _, err := p.signal(syscall.SIGKILL); err != nil {
		return "", err
	}
	// SIGKILL must be confirmed, not merely issued.  Do not use the expired
	// caller context here: once kill succeeds it is safe and necessary to reap.
	<-p.waitDone
	_ = p.Wait()
	return TerminationBySupervisor, nil
}

// Terminate retains the lifecycle API for callers that do not need shutdown
// provenance.
func (p *Process) Terminate(ctx context.Context) error {
	_, err := p.TerminateWithDisposition(ctx)
	return err
}

// Stop is an alias for Terminate.
func (p *Process) Stop(ctx context.Context) error { return p.Terminate(ctx) }

func (p *Process) signal(signal syscall.Signal) (bool, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.pidfd >= 0 {
		if err := unix.PidfdSendSignal(p.pidfd, unix.Signal(signal), nil, 0); err == nil {
			switch signal {
			case syscall.SIGTERM:
				p.supervisorSIGTERM = true
			case syscall.SIGKILL:
				p.supervisorSIGKILL = true
			}
			return true, nil
		} else if errors.Is(err, unix.ESRCH) {
			return false, nil
		} else {
			return false, fmt.Errorf("signal Firecracker through pidfd: %w", err)
		}
	}
	select {
	case <-p.waitDone:
		return false, nil
	default:
	}
	return false, errors.New("Firecracker process has no pidfd")
}

func (p *Process) wasSupervisorSignalExit(err error) bool {
	var exitError *exec.ExitError
	if !errors.As(err, &exitError) {
		return false
	}
	status, ok := exitError.Sys().(syscall.WaitStatus)
	if !ok || !status.Signaled() {
		return false
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	switch status.Signal() {
	case syscall.SIGTERM:
		return p.supervisorSIGTERM
	case syscall.SIGKILL:
		return p.supervisorSIGKILL
	default:
		return false
	}
}

func (p *Process) exitError(prefix string) error {
	p.mu.Lock()
	err := p.waitErr
	p.mu.Unlock()
	if err == nil {
		return errors.New(prefix)
	}
	return fmt.Errorf("Firecracker %s: %w", prefix, err)
}
