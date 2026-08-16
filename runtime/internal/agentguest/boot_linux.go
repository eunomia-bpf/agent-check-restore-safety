//go:build linux

package agentguest

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/exec"
	"runtime/debug"
	"sync"
	"syscall"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repobundle"
	"golang.org/x/sys/unix"
)

const (
	agentUID                  = 1000
	agentGID                  = 1000
	hostCID                   = uint32(2)
	maxCodexBinaryBytes       = int64(512 << 20)
	maxModelConnections       = 64
	vsockConnectTimeout       = time.Second
	modelProxyShutdownTimeout = 2 * time.Second
)

// PrepareLinuxPID1 constructs the deliberately small mutable guest
// environment and verifies the exact Codex executable from the read-only
// payload. It must run as PID 1 in the initramfs.
func PrepareLinuxPID1(config Config) error {
	if os.Getpid() != 1 {
		return fmt.Errorf("agent guest supervisor must run as PID 1, got %d", os.Getpid())
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
	if err := mountPayload(config.PayloadDrive); err != nil {
		return err
	}
	if err := configureAgentDirectories(); err != nil {
		return err
	}
	if err := MaterializeRepository(config); err != nil {
		return err
	}
	if err := bringLoopbackUp(); err != nil {
		return err
	}
	if err := VerifyCodexExecutable(CodexExecutable, config.CodexSHA256); err != nil {
		return err
	}
	return nil
}

func requireStaticBuild() error {
	info, ok := debug.ReadBuildInfo()
	if !ok {
		return errors.New("agent guest supervisor has no Go build information")
	}
	for _, setting := range info.Settings {
		if setting.Key == "CGO_ENABLED" {
			if setting.Value != "0" {
				return fmt.Errorf("agent guest supervisor must use CGO_ENABLED=0, got %q", setting.Value)
			}
			return nil
		}
	}
	return errors.New("agent guest supervisor does not record CGO_ENABLED")
}

func mountKernelFilesystems() error {
	mounts := []struct {
		source, target, kind, data string
		flags                      uintptr
	}{
		{source: "devtmpfs", target: "/dev", kind: "devtmpfs", flags: unix.MS_NOSUID, data: "mode=0755"},
		{source: "proc", target: "/proc", kind: "proc", flags: unix.MS_NOSUID | unix.MS_NODEV | unix.MS_NOEXEC},
		{source: "sysfs", target: "/sys", kind: "sysfs", flags: unix.MS_NOSUID | unix.MS_NODEV | unix.MS_NOEXEC},
		{source: "none", target: "/sys/fs/cgroup", kind: "cgroup2", flags: unix.MS_NOSUID | unix.MS_NODEV | unix.MS_NOEXEC},
	}
	for _, mount := range mounts {
		if err := os.MkdirAll(mount.target, 0o755); err != nil {
			return fmt.Errorf("create mount point %s: %w", mount.target, err)
		}
		if err := unix.Mount(mount.source, mount.target, mount.kind, mount.flags, mount.data); err != nil && !errors.Is(err, unix.EBUSY) {
			return fmt.Errorf("mount %s on %s: %w", mount.kind, mount.target, err)
		}
	}
	return nil
}

func attachConsole() error {
	console, err := unix.Open("/dev/console", unix.O_RDWR|unix.O_CLOEXEC|unix.O_NOCTTY, 0)
	if errors.Is(err, unix.ENOENT) || errors.Is(err, unix.ENXIO) {
		console, err = unix.Open("/dev/ttyS0", unix.O_RDWR|unix.O_CLOEXEC|unix.O_NOCTTY, 0)
	}
	if err != nil {
		return fmt.Errorf("open agent guest console: %w", err)
	}
	if console <= unix.Stderr {
		duplicate, duplicateErr := unix.FcntlInt(uintptr(console), unix.F_DUPFD_CLOEXEC, unix.Stderr+1)
		if duplicateErr != nil {
			_ = unix.Close(console)
			return fmt.Errorf("duplicate agent guest console: %w", duplicateErr)
		}
		_ = unix.Close(console)
		console = duplicate
	}
	defer unix.Close(console)
	for _, descriptor := range []int{unix.Stdin, unix.Stdout, unix.Stderr} {
		if err := unix.Dup3(console, descriptor, 0); err != nil {
			return fmt.Errorf("attach agent guest console to fd %d: %w", descriptor, err)
		}
	}
	return nil
}

func mountMutableFilesystems() error {
	mounts := []struct {
		target string
		mode   os.FileMode
		data   string
	}{
		{target: "/run", mode: 0o755, data: "mode=0755,size=16m"},
		{target: "/tmp", mode: 0o1777, data: "mode=1777,size=128m"},
		{target: WorkspaceDirectory, mode: 0o755, data: "mode=0755,size=128m"},
		{target: "/home", mode: 0o755, data: "mode=0755,size=128m"},
	}
	for _, mount := range mounts {
		if err := os.MkdirAll(mount.target, mount.mode); err != nil {
			return fmt.Errorf("create mutable mount point %s: %w", mount.target, err)
		}
		if err := unix.Mount("tmpfs", mount.target, "tmpfs", unix.MS_NOSUID|unix.MS_NODEV, mount.data); err != nil {
			return fmt.Errorf("mount tmpfs on %s: %w", mount.target, err)
		}
	}
	return nil
}

func mountPayload(device string) error {
	if device != "/dev/vda" {
		return errors.New("payload block device is not /dev/vda")
	}
	if err := os.MkdirAll(PayloadMount, 0o555); err != nil {
		return fmt.Errorf("create payload mount point: %w", err)
	}
	flags := uintptr(unix.MS_RDONLY | unix.MS_NOSUID | unix.MS_NODEV)
	if err := unix.Mount(device, PayloadMount, "squashfs", flags, ""); err != nil {
		return fmt.Errorf("mount read-only Codex payload: %w", err)
	}
	return nil
}

func configureAgentDirectories() error {
	for _, directory := range []string{"/home/codex", CodexHomeDirectory, WorkspaceDirectory} {
		if err := os.MkdirAll(directory, 0o700); err != nil {
			return fmt.Errorf("create agent directory %s: %w", directory, err)
		}
		if err := os.Chown(directory, agentUID, agentGID); err != nil {
			return fmt.Errorf("assign agent directory %s: %w", directory, err)
		}
		if err := os.Chmod(directory, 0o700); err != nil {
			return fmt.Errorf("protect agent directory %s: %w", directory, err)
		}
	}
	return nil
}

// MaterializeRepository verifies the complete immutable repository block
// image before creating any agent-visible path.
func MaterializeRepository(config Config) error {
	if config.RepositoryDrive != RepositoryDrive {
		return errors.New("repository block device is not /dev/vdb")
	}
	descriptor, err := unix.Open(config.RepositoryDrive, unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return fmt.Errorf("open read-only repository drive: %w", err)
	}
	file := os.NewFile(uintptr(descriptor), config.RepositoryDrive)
	if file == nil {
		_ = unix.Close(descriptor)
		return errors.New("wrap repository drive descriptor")
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return fmt.Errorf("inspect repository drive: %w", err)
	}
	if info.Mode()&os.ModeDevice == 0 || info.Mode()&os.ModeCharDevice != 0 {
		return errors.New("repository drive is not a block device")
	}
	bundle, err := DecodeRepository(file, config.RepositorySize, config.RepositorySHA256, config.RepositoryTreeRoot)
	if err != nil {
		return err
	}
	if err := bundle.MaterializeOwned(WorkspaceDirectory, agentUID, agentGID); err != nil {
		return fmt.Errorf("materialize verified repository: %w", err)
	}
	return nil
}

// DecodeRepository validates both the byte image and its semantic tree. The
// size-bounded view makes a block device behave like the exact bundle file and
// prevents trailing sectors from becoming an alternate representation.
func DecodeRepository(reader io.Reader, size uint64, expectedSHA256, expectedTreeRoot string) (repobundle.Bundle, error) {
	if reader == nil {
		return repobundle.Bundle{}, errors.New("repository reader is nil")
	}
	if size == 0 || size > MaxRepositoryBytes || size%512 != 0 {
		return repobundle.Bundle{}, errors.New("repository size is outside the guest limit or not block aligned")
	}
	if err := validateLowerHexDigest(expectedSHA256, "repository_sha256"); err != nil {
		return repobundle.Bundle{}, err
	}
	if err := validateLowerHexDigest(expectedTreeRoot, "repository_tree_root"); err != nil {
		return repobundle.Bundle{}, err
	}
	digest := sha256.New()
	exact := io.LimitReader(reader, int64(size))
	bundle, err := repobundle.Decode(io.TeeReader(exact, digest), repobundle.DefaultLimits())
	if err != nil {
		return repobundle.Bundle{}, fmt.Errorf("decode repository drive: %w", err)
	}
	actualSHA256 := hex.EncodeToString(digest.Sum(nil))
	if actualSHA256 != expectedSHA256 {
		return repobundle.Bundle{}, fmt.Errorf("repository drive SHA-256 is %s, require %s", actualSHA256, expectedSHA256)
	}
	if bundle.TreeRoot.String() != expectedTreeRoot {
		return repobundle.Bundle{}, fmt.Errorf("repository tree root is %s, require %s", bundle.TreeRoot, expectedTreeRoot)
	}
	return bundle, nil
}

func bringLoopbackUp() error {
	descriptor, err := unix.Socket(unix.AF_INET, unix.SOCK_DGRAM|unix.SOCK_CLOEXEC, 0)
	if err != nil {
		return fmt.Errorf("open loopback control socket: %w", err)
	}
	defer unix.Close(descriptor)
	request, err := unix.NewIfreq("lo")
	if err != nil {
		return fmt.Errorf("create loopback interface request: %w", err)
	}
	if err := unix.IoctlIfreq(descriptor, unix.SIOCGIFFLAGS, request); err != nil {
		return fmt.Errorf("read loopback flags: %w", err)
	}
	request.SetUint16(request.Uint16() | unix.IFF_UP | unix.IFF_RUNNING)
	if err := unix.IoctlIfreq(descriptor, unix.SIOCSIFFLAGS, request); err != nil {
		return fmt.Errorf("enable loopback: %w", err)
	}
	return nil
}

// VerifyCodexExecutable reads the payload executable through O_NOFOLLOW and
// binds execution to the hash embedded in the initramfs configuration.
func VerifyCodexExecutable(path, expectedSHA256 string) error {
	if path != CodexExecutable {
		return errors.New("Codex executable path differs from the fixed payload path")
	}
	if len(expectedSHA256) != 64 {
		return errors.New("expected Codex SHA-256 is malformed")
	}
	descriptor, err := unix.Open(path, unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return fmt.Errorf("open payload Codex executable: %w", err)
	}
	file := os.NewFile(uintptr(descriptor), path)
	if file == nil {
		_ = unix.Close(descriptor)
		return errors.New("wrap payload Codex executable")
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return fmt.Errorf("inspect payload Codex executable: %w", err)
	}
	if !info.Mode().IsRegular() || info.Mode()&0o111 == 0 || info.Size() <= 0 || info.Size() > maxCodexBinaryBytes {
		return errors.New("payload Codex is not a bounded executable regular file")
	}
	digest := sha256.New()
	written, err := io.Copy(digest, file)
	if err != nil {
		return fmt.Errorf("hash payload Codex executable: %w", err)
	}
	if written != info.Size() {
		return errors.New("payload Codex changed while hashing")
	}
	actual := hex.EncodeToString(digest.Sum(nil))
	if actual != expectedSHA256 {
		return fmt.Errorf("payload Codex SHA-256 is %s, require %s", actual, expectedSHA256)
	}
	return nil
}

// StartCodex launches the fixed /init child mode under an unprivileged numeric
// identity. That child installs the Codex-only seccomp boundary before it
// replaces itself with the fixed payload executable.
func StartCodex(config Config, stderr io.Writer, cgroupFD int) (*exec.Cmd, io.WriteCloser, io.ReadCloser, error) {
	command, err := codexCommand(config, stderr, cgroupFD)
	if err != nil {
		return nil, nil, nil, err
	}
	stdin, err := command.StdinPipe()
	if err != nil {
		return nil, nil, nil, fmt.Errorf("create Codex stdin pipe: %w", err)
	}
	stdout, err := command.StdoutPipe()
	if err != nil {
		_ = stdin.Close()
		return nil, nil, nil, fmt.Errorf("create Codex stdout pipe: %w", err)
	}
	if err := command.Start(); err != nil {
		_ = stdin.Close()
		_ = stdout.Close()
		return nil, nil, nil, fmt.Errorf("start payload Codex child: %w", err)
	}
	return command, stdin, stdout, nil
}

func codexCommand(config Config, stderr io.Writer, cgroupFD int) (*exec.Cmd, error) {
	if err := config.Validate(); err != nil {
		return nil, err
	}
	if stderr == nil {
		return nil, errors.New("Codex stderr writer is nil")
	}
	if cgroupFD < 0 {
		return nil, errors.New("Codex execution cgroup descriptor is invalid")
	}
	arguments := make([]string, 0, len(config.Arguments)+1)
	arguments = append(arguments, CodexChildMode)
	arguments = append(arguments, config.Arguments...)
	command := exec.Command(InitExecutable, arguments...)
	command.Dir = WorkspaceDirectory
	command.Env = fixedCodexEnvironment()
	command.Stderr = stderr
	command.SysProcAttr = &syscall.SysProcAttr{
		Credential:  &syscall.Credential{Uid: agentUID, Gid: agentGID, Groups: []uint32{}},
		Pdeathsig:   syscall.SIGKILL,
		UseCgroupFD: true,
		CgroupFD:    cgroupFD,
	}
	return command, nil
}

// Stream is the minimum transport contract shared by AF_VSOCK and test pipes.
type Stream interface {
	io.Reader
	io.Writer
	io.Closer
}

// DialHostVsock connects one guest service to the fixed host CID.
func DialHostVsock(port uint32) (Stream, error) {
	if port == 0 {
		return nil, errors.New("host vsock port is zero")
	}
	descriptor, err := unix.Socket(unix.AF_VSOCK, unix.SOCK_STREAM|unix.SOCK_CLOEXEC|unix.SOCK_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	if err := connectNonblocking(descriptor, &unix.SockaddrVM{CID: hostCID, Port: port}, vsockConnectTimeout); err != nil {
		_ = unix.Close(descriptor)
		return nil, err
	}
	return newVsockStream(descriptor)
}

func connectNonblocking(descriptor int, address unix.Sockaddr, timeout time.Duration) error {
	err := unix.Connect(descriptor, address)
	if err == nil || errors.Is(err, unix.EISCONN) {
		return nil
	}
	if !errors.Is(err, unix.EINPROGRESS) && !errors.Is(err, unix.EALREADY) {
		return err
	}
	deadline := time.Now().Add(timeout)
	for {
		remaining := time.Until(deadline)
		if remaining <= 0 {
			return unix.ETIMEDOUT
		}
		milliseconds := int((remaining + time.Millisecond - 1) / time.Millisecond)
		poll := []unix.PollFd{{Fd: int32(descriptor), Events: unix.POLLOUT | unix.POLLERR | unix.POLLHUP}}
		count, pollErr := unix.Poll(poll, milliseconds)
		if errors.Is(pollErr, unix.EINTR) {
			continue
		}
		if pollErr != nil {
			return pollErr
		}
		if count == 0 {
			return unix.ETIMEDOUT
		}
		socketError, socketErr := unix.GetsockoptInt(descriptor, unix.SOL_SOCKET, unix.SO_ERROR)
		if socketErr != nil {
			return socketErr
		}
		if socketError != 0 {
			return syscall.Errno(socketError)
		}
		return nil
	}
}

// StartModelProxy binds the loopback listener before returning, then serves it
// in a goroutine. A caller can therefore launch Codex only after the model
// endpoint is ready, without relying on goroutine scheduling around exec.
func StartModelProxy(ctxDone <-chan struct{}, port uint32, dial func(uint32) (Stream, error), logger *log.Logger) (<-chan error, error) {
	if ctxDone == nil || port == 0 || port > 65535 || dial == nil || logger == nil {
		return nil, errors.New("model proxy requires cancellation, a valid port, dialer, and logger")
	}
	listener, err := net.Listen("tcp4", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		return nil, fmt.Errorf("listen on guest model loopback: %w", err)
	}
	result := make(chan error, 1)
	go func() {
		result <- serveModelProxy(ctxDone, port, listener, dial, logger)
		close(result)
	}()
	return result, nil
}

// ServeModelProxy exposes one loopback-only TCP port inside the guest and
// opens a fresh host-vsock stream for every accepted HTTP connection.
func ServeModelProxy(ctxDone <-chan struct{}, port uint32, dial func(uint32) (Stream, error), logger *log.Logger) error {
	result, err := StartModelProxy(ctxDone, port, dial, logger)
	if err != nil {
		return err
	}
	return <-result
}

func serveModelProxy(ctxDone <-chan struct{}, port uint32, listener net.Listener, dial func(uint32) (Stream, error), logger *log.Logger) (returnErr error) {
	if listener == nil {
		return errors.New("model proxy requires a valid port, dialer, and logger")
	}
	connections := &modelProxyConnections{active: make(map[*modelProxyPair]struct{})}
	var handlers sync.WaitGroup
	defer func() {
		_ = listener.Close()
		connections.Close()
		stopped := make(chan struct{})
		go func() {
			handlers.Wait()
			close(stopped)
		}()
		select {
		case <-stopped:
		case <-time.After(modelProxyShutdownTimeout):
			returnErr = errors.Join(returnErr, errors.New("model proxy handlers did not stop after connection shutdown"))
		}
	}()
	stopCancellation := make(chan struct{})
	defer close(stopCancellation)
	go func() {
		select {
		case <-ctxDone:
			_ = listener.Close()
			connections.Close()
		case <-stopCancellation:
		}
	}()
	semaphore := make(chan struct{}, maxModelConnections)
	for {
		connection, err := listener.Accept()
		if err != nil {
			select {
			case <-ctxDone:
				return nil
			default:
				return fmt.Errorf("accept guest model connection: %w", err)
			}
		}
		select {
		case semaphore <- struct{}{}:
			pair := connections.Add(connection)
			if pair == nil {
				<-semaphore
				continue
			}
			handlers.Add(1)
			go func(pair *modelProxyPair) {
				defer handlers.Done()
				defer func() { <-semaphore }()
				defer connections.Remove(pair)
				proxyModelPair(pair, port, dial, logger)
			}(pair)
		default:
			logger.Printf("model proxy refused connection: concurrency limit reached")
			_ = connection.Close()
		}
	}
}

func proxyModelConnection(guest net.Conn, port uint32, dial func(uint32) (Stream, error), logger *log.Logger) {
	proxyModelPair(newModelProxyPair(guest), port, dial, logger)
}

func proxyModelPair(pair *modelProxyPair, port uint32, dial func(uint32) (Stream, error), logger *log.Logger) {
	if pair == nil {
		return
	}
	defer pair.Close()
	host, err := dial(port)
	if err != nil {
		logger.Printf("model proxy host-vsock dial failed: %v", err)
		return
	}
	if host == nil {
		logger.Printf("model proxy host-vsock dial returned a nil stream")
		return
	}
	if !pair.SetHost(host) {
		return
	}
	var wait sync.WaitGroup
	wait.Add(2)
	copyOne := func(destination io.Writer, source io.Reader) {
		defer wait.Done()
		_, _ = io.Copy(destination, source)
		if closer, ok := destination.(interface{ CloseWrite() error }); ok {
			_ = closer.CloseWrite()
		}
	}
	go copyOne(host, pair.guest)
	go copyOne(pair.guest, host)
	wait.Wait()
}

type modelProxyConnections struct {
	mu     sync.Mutex
	closed bool
	active map[*modelProxyPair]struct{}
}

func (connections *modelProxyConnections) Add(guest net.Conn) *modelProxyPair {
	pair := newModelProxyPair(guest)
	connections.mu.Lock()
	if connections.closed {
		connections.mu.Unlock()
		_ = pair.Close()
		return nil
	}
	connections.active[pair] = struct{}{}
	connections.mu.Unlock()
	return pair
}

func (connections *modelProxyConnections) Remove(pair *modelProxyPair) {
	connections.mu.Lock()
	delete(connections.active, pair)
	connections.mu.Unlock()
}

func (connections *modelProxyConnections) Close() {
	connections.mu.Lock()
	if connections.closed {
		connections.mu.Unlock()
		return
	}
	connections.closed = true
	pairs := make([]*modelProxyPair, 0, len(connections.active))
	for pair := range connections.active {
		pairs = append(pairs, pair)
	}
	connections.mu.Unlock()
	for _, pair := range pairs {
		_ = pair.Close()
	}
}

type modelProxyPair struct {
	mu     sync.Mutex
	guest  net.Conn
	host   Stream
	closed bool
}

func newModelProxyPair(guest net.Conn) *modelProxyPair {
	return &modelProxyPair{guest: guest}
}

func (pair *modelProxyPair) SetHost(host Stream) bool {
	pair.mu.Lock()
	if pair.closed {
		pair.mu.Unlock()
		_ = host.Close()
		return false
	}
	pair.host = host
	pair.mu.Unlock()
	return true
}

func (pair *modelProxyPair) Close() error {
	if pair == nil {
		return nil
	}
	pair.mu.Lock()
	if pair.closed {
		pair.mu.Unlock()
		return nil
	}
	pair.closed = true
	guest, host := pair.guest, pair.host
	pair.mu.Unlock()
	var errs []error
	if guest != nil {
		errs = append(errs, guest.Close())
	}
	if host != nil {
		errs = append(errs, host.Close())
	}
	return errors.Join(errs...)
}

type vsockStream struct {
	file *os.File
}

func (connection *vsockStream) Read(data []byte) (int, error) {
	if connection == nil || connection.file == nil {
		return 0, os.ErrInvalid
	}
	return connection.file.Read(data)
}

func (connection *vsockStream) Write(data []byte) (int, error) {
	if connection == nil || connection.file == nil {
		return 0, os.ErrInvalid
	}
	return connection.file.Write(data)
}

func (connection *vsockStream) CloseWrite() error {
	if connection == nil || connection.file == nil {
		return os.ErrInvalid
	}
	raw, err := connection.file.SyscallConn()
	if err != nil {
		return err
	}
	var shutdownErr error
	controlErr := raw.Control(func(descriptor uintptr) {
		shutdownErr = unix.Shutdown(int(descriptor), unix.SHUT_WR)
	})
	return errors.Join(controlErr, shutdownErr)
}

func (connection *vsockStream) Close() error {
	if connection == nil || connection.file == nil {
		return os.ErrInvalid
	}
	return connection.file.Close()
}

func newVsockStream(descriptor int) (*vsockStream, error) {
	if descriptor < 0 {
		return nil, errors.New("vsock descriptor is invalid")
	}
	file := os.NewFile(uintptr(descriptor), "guest-vsock")
	if file == nil {
		_ = unix.Close(descriptor)
		return nil, errors.New("wrap guest vsock descriptor")
	}
	return &vsockStream{file: file}, nil
}
