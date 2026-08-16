// Package sandboxhost owns the host side of sandbox-only HTTP channels.
package sandboxhost

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"golang.org/x/sys/unix"

	controlapi "github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
)

const (
	readHeaderTimeout = 5 * time.Second
	writeTimeout      = 60 * time.Second
	idleTimeout       = 5 * time.Second
)

// Endpoint is one host-owned listener bound to one concrete sandbox generation.
// Its handler captures the binding; requests cannot select or forge it. A new
// Cutover immediately makes the old handler stale even before it is drained.
type Endpoint struct {
	control    *control.Control
	binding    control.SandboxBinding
	listener   net.Listener
	server     *http.Server
	done       chan error
	socketPath string
	socketInfo os.FileInfo
	attached   bool
	started    bool

	closeOnce  sync.Once
	removeOnce sync.Once
	closeErr   error
	removeErr  error
}

// Listen creates and attaches a sandbox-only endpoint. The listener is limited
// to host loopback so a VM monitor or a namespace-local proxy can be the only
// route into it. The finite WriteTimeout bounds how long response delivery can
// delay a Rule-and-sandbox cutover.
func Listen(
	controller *control.Control,
	serverAPI *controlapi.Server,
	binding control.SandboxBinding,
	address string,
) (*Endpoint, error) {
	if controller == nil || serverAPI == nil {
		return nil, errors.New("sandbox endpoint requires control and API")
	}
	listener, err := net.Listen("tcp", address)
	if err != nil {
		return nil, err
	}
	tcpAddress, ok := listener.Addr().(*net.TCPAddr)
	if !ok || !tcpAddress.IP.IsLoopback() {
		_ = listener.Close()
		return nil, errors.New("sandbox endpoint must listen on host loopback")
	}
	endpoint, err := prepare(controller, serverAPI, binding, listener, "", nil)
	if err != nil {
		_ = listener.Close()
		return nil, err
	}
	if err := controller.AttachSandboxHost(binding); err != nil {
		_ = endpoint.abort()
		return nil, err
	}
	endpoint.attached = true
	endpoint.start()
	return endpoint, nil
}

// ListenUnix creates a credential-free sandbox endpoint on an existing,
// host-private directory. The socket path is the capability: the guest may be
// wired to it by a VM monitor, but it never receives Control credentials or a
// provider route. The parent directory must be an absolute, canonical,
// non-symlink directory owned by this process's uid with mode 0700.
func ListenUnix(
	controller *control.Control,
	serverAPI *controlapi.Server,
	binding control.SandboxBinding,
	socketPath string,
) (*Endpoint, error) {
	endpoint, err := prepareUnix(controller, serverAPI, binding, socketPath)
	if err != nil {
		return nil, err
	}
	if err := controller.AttachSandboxHost(binding); err != nil {
		_ = endpoint.abort()
		return nil, err
	}
	endpoint.attached = true
	endpoint.start()
	return endpoint, nil
}

func prepareUnix(
	controller *control.Control,
	serverAPI *controlapi.Server,
	binding control.SandboxBinding,
	socketPath string,
) (*Endpoint, error) {
	if controller == nil || serverAPI == nil {
		return nil, errors.New("sandbox endpoint requires control and API")
	}
	parentInfo, err := validateSocketParent(socketPath)
	if err != nil {
		return nil, err
	}
	if err := removeOwnedStaleSocket(socketPath); err != nil {
		return nil, err
	}
	pendingPath, err := randomSocketSibling(socketPath, ".p-")
	if err != nil {
		return nil, err
	}
	unixListener, err := net.ListenUnix("unix", &net.UnixAddr{Name: pendingPath, Net: "unix"})
	if err != nil {
		return nil, err
	}
	unixListener.SetUnlinkOnClose(false)
	ownedPath := pendingPath
	cleanup := func(socketInfo os.FileInfo) {
		_ = unixListener.Close()
		_ = removeSameSocket(ownedPath, socketInfo)
	}
	createdInfo, err := os.Lstat(pendingPath)
	if err != nil || createdInfo.Mode()&os.ModeSocket == 0 {
		_ = unixListener.Close()
		return nil, errors.New("Unix listener did not create a sandbox socket")
	}
	if err := requireCurrentOwner(createdInfo, "pending sandbox socket"); err != nil {
		cleanup(createdInfo)
		return nil, err
	}
	if err := unix.Fchmodat(unix.AT_FDCWD, pendingPath, 0o600, unix.AT_SYMLINK_NOFOLLOW); err != nil {
		cleanup(createdInfo)
		return nil, fmt.Errorf("protect sandbox socket: %w", err)
	}
	socketInfo, err := validateCreatedSocket(pendingPath, createdInfo)
	if err != nil {
		cleanup(createdInfo)
		return nil, err
	}
	currentParent, err := os.Lstat(filepath.Dir(socketPath))
	if err != nil || !os.SameFile(parentInfo, currentParent) {
		cleanup(socketInfo)
		return nil, errors.New("sandbox socket parent changed while binding")
	}
	if err := unix.Renameat2(
		unix.AT_FDCWD, pendingPath, unix.AT_FDCWD, socketPath, unix.RENAME_NOREPLACE,
	); err != nil {
		cleanup(socketInfo)
		return nil, fmt.Errorf("publish sandbox socket without replacement: %w", err)
	}
	ownedPath = socketPath
	publishedInfo, err := validateCreatedSocket(socketPath, socketInfo)
	if err != nil {
		cleanup(socketInfo)
		return nil, err
	}
	endpoint, err := prepare(controller, serverAPI, binding, unixListener, socketPath, publishedInfo)
	if err != nil {
		cleanup(publishedInfo)
		return nil, err
	}
	return endpoint, nil
}

func prepare(
	controller *control.Control,
	serverAPI *controlapi.Server,
	binding control.SandboxBinding,
	listener net.Listener,
	socketPath string,
	socketInfo os.FileInfo,
) (*Endpoint, error) {
	handler, err := serverAPI.HandlerForSandbox(binding)
	if err != nil {
		return nil, err
	}
	endpoint := &Endpoint{
		control:    controller,
		binding:    cloneBinding(binding),
		listener:   listener,
		done:       make(chan error, 1),
		socketPath: socketPath,
		socketInfo: socketInfo,
	}
	endpoint.server = &http.Server{
		Handler:           handler,
		ReadHeaderTimeout: readHeaderTimeout,
		WriteTimeout:      writeTimeout,
		IdleTimeout:       idleTimeout,
	}
	return endpoint, nil
}

func (e *Endpoint) start() {
	if e.started {
		panic("sandbox endpoint started twice")
	}
	e.started = true
	go func() {
		err := e.server.Serve(e.listener)
		if errors.Is(err, http.ErrServerClosed) {
			err = nil
		}
		if e.attached {
			detachErr := e.control.DetachSandboxHost(e.binding)
			if errors.Is(detachErr, control.ErrSandboxNotAttached) || errors.Is(detachErr, control.ErrStaleSandboxBinding) {
				detachErr = nil
			}
			err = errors.Join(err, detachErr)
		}
		e.removeSocket()
		err = errors.Join(err, e.removeErr)
		e.done <- err
		close(e.done)
	}()
}

func (e *Endpoint) removeSocket() {
	e.removeOnce.Do(func() {
		e.removeErr = removeSameSocket(e.socketPath, e.socketInfo)
	})
}

func (e *Endpoint) abort() error {
	listenerErr := e.listener.Close()
	e.removeSocket()
	return errors.Join(listenerErr, e.removeErr)
}

func validateSocketParent(socketPath string) (os.FileInfo, error) {
	if socketPath == "" || !filepath.IsAbs(socketPath) || filepath.Clean(socketPath) != socketPath {
		return nil, errors.New("sandbox socket path must be absolute and canonical")
	}
	parent := filepath.Dir(socketPath)
	info, err := os.Lstat(parent)
	if err != nil {
		return nil, fmt.Errorf("inspect sandbox socket parent: %w", err)
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("sandbox socket parent must be a real directory")
	}
	resolved, err := filepath.EvalSymlinks(parent)
	if err != nil || resolved != parent {
		return nil, errors.New("sandbox socket parent must not traverse symlinks")
	}
	if info.Mode().Perm() != 0o700 {
		return nil, fmt.Errorf("sandbox socket parent mode is %04o, want 0700", info.Mode().Perm())
	}
	if err := requireCurrentOwner(info, "sandbox socket parent"); err != nil {
		return nil, err
	}
	return info, nil
}

func validateCreatedSocket(socketPath string, expected os.FileInfo) (os.FileInfo, error) {
	info, err := os.Lstat(socketPath)
	if err != nil {
		return nil, fmt.Errorf("inspect sandbox socket: %w", err)
	}
	if expected == nil || info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0o600 ||
		!os.SameFile(expected, info) {
		return nil, errors.New("sandbox endpoint is not a private Unix socket")
	}
	if err := requireCurrentOwner(info, "sandbox socket"); err != nil {
		return nil, err
	}
	return info, nil
}

func randomSocketSibling(socketPath, prefix string) (string, error) {
	random := make([]byte, 8)
	if _, err := rand.Read(random); err != nil {
		return "", fmt.Errorf("create private socket name: %w", err)
	}
	return filepath.Join(
		filepath.Dir(socketPath), prefix+hex.EncodeToString(random),
	), nil
}

func requireCurrentOwner(info os.FileInfo, label string) error {
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(stat.Uid) != os.Geteuid() {
		return fmt.Errorf("%s must be owned by the current uid", label)
	}
	return nil
}

func removeOwnedStaleSocket(socketPath string) error {
	info, err := os.Lstat(socketPath)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("inspect existing sandbox socket: %w", err)
	}
	if info.Mode()&os.ModeSocket == 0 {
		return errors.New("refusing to replace a non-socket sandbox path")
	}
	if err := requireCurrentOwner(info, "existing sandbox socket"); err != nil {
		return err
	}
	connection, dialErr := net.DialTimeout("unix", socketPath, 100*time.Millisecond)
	if dialErr == nil {
		_ = connection.Close()
		return errors.New("refusing to replace an active sandbox socket")
	}
	if !errors.Is(dialErr, syscall.ECONNREFUSED) && !errors.Is(dialErr, os.ErrNotExist) {
		return fmt.Errorf("cannot prove existing sandbox socket is stale: %w", dialErr)
	}
	current, err := os.Lstat(socketPath)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil || !os.SameFile(info, current) {
		return errors.New("existing sandbox socket changed during stale check")
	}
	return removeSameSocket(socketPath, current)
}

func removeSameSocket(socketPath string, expected os.FileInfo) error {
	if socketPath == "" {
		return nil
	}
	current, err := os.Lstat(socketPath)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if expected == nil || current.Mode()&os.ModeSocket == 0 || !os.SameFile(expected, current) {
		return errors.New("sandbox socket path was replaced; refusing to remove it")
	}
	quarantinePath, err := randomSocketSibling(socketPath, ".r-")
	if err != nil {
		return err
	}
	if err := unix.Renameat2(
		unix.AT_FDCWD, socketPath, unix.AT_FDCWD, quarantinePath, unix.RENAME_NOREPLACE,
	); errors.Is(err, os.ErrNotExist) {
		return nil
	} else if err != nil {
		return fmt.Errorf("quarantine sandbox socket: %w", err)
	}
	moved, err := os.Lstat(quarantinePath)
	if err != nil || moved.Mode()&os.ModeSocket == 0 || !os.SameFile(expected, moved) {
		return fmt.Errorf("sandbox socket changed while quarantining; refusing to remove %q", quarantinePath)
	}
	if err := os.Remove(quarantinePath); err != nil {
		return fmt.Errorf("remove quarantined sandbox socket: %w", err)
	}
	return nil
}

// Address returns the concrete host address suitable for a VM-owned forward.
// It is host configuration, never guest-supplied identity.
func (e *Endpoint) Address() string {
	if e.socketPath != "" {
		return e.socketPath
	}
	return e.listener.Addr().String()
}

// Binding returns an independent copy of the captured sandbox identity.
func (e *Endpoint) Binding() control.SandboxBinding {
	return cloneBinding(e.binding)
}

// Close drains the bounded HTTP server and then detaches exactly this sandbox
// generation. It is idempotent. A stale endpoint cannot detach a newer one.
func (e *Endpoint) Close(ctx context.Context) error {
	if e == nil {
		return nil
	}
	e.closeOnce.Do(func() {
		if !e.started {
			e.closeErr = e.abort()
			return
		}
		shutdownErr := e.server.Shutdown(ctx)
		if shutdownErr != nil {
			_ = e.server.Close()
		}
		serveErr := <-e.done
		e.closeErr = errors.Join(shutdownErr, serveErr)
	})
	return e.closeErr
}

// SocketPath returns the host-private Unix socket path, or an empty string for
// a TCP endpoint.
func (e *Endpoint) SocketPath() string {
	return e.socketPath
}

// Port returns the concrete TCP port used by a VM monitor forward.
func (e *Endpoint) Port() (int, error) {
	address, ok := e.listener.Addr().(*net.TCPAddr)
	if !ok || address.Port == 0 {
		return 0, fmt.Errorf("sandbox endpoint has invalid TCP address %q", e.listener.Addr())
	}
	return address.Port, nil
}

func cloneBinding(binding control.SandboxBinding) control.SandboxBinding {
	binding.AllowedKinds = append([]string(nil), binding.AllowedKinds...)
	return binding
}
