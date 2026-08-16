// Package firecracker contains host-side primitives used when a Firecracker
// guest is given a vsock device.  It deliberately does not configure
// Firecracker itself: the caller wires Relay.SocketPath into the Firecracker
// vsock UDS setting for the matching guest port.
package firecracker

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

const (
	unixSocketPathLimit = 108 // includes the terminating NUL in sockaddr_un
	defaultDrainTimeout = 5 * time.Second
)

// RelayConfig describes one guest port for one already-selected sandbox
// generation. BasePath and Port form the Firecracker UDS name BasePath_Port.
// SandboxSocket must be the control-owned UDS for that same generation.
//
// FirecrackerPID is checked with SO_PEERCRED on every accepted connection. On
// Linux, a Unix-domain connection made by Firecracker's vsock backend reports
// the Firecracker process as its peer; the guest never obtains a host UDS
// credential of its own.
type RelayConfig struct {
	Generation     uint64
	BasePath       string
	Port           uint32
	FirecrackerPID int
	// VerifyProcess must prove that FirecrackerPID still names the exact VMM
	// generation this relay was armed for. It prevents an unrelated process
	// reusing the PID from passing SO_PEERCRED alone.
	VerifyProcess func() error
	SandboxSocket string

	// SandboxSocketPath is accepted as a spelling-compatible alternative to
	// SandboxSocket. Supplying both with different values is rejected.
	SandboxSocketPath string

	// AuditLog receives one JSON object per line. Events are "accept",
	// "bytes", and "error". It is owned by the caller and is never closed.
	AuditLog io.Writer

	// DrainTimeout bounds Close. Zero selects a conservative default.
	DrainTimeout time.Duration
}

// Relay forwards one generation-specific Firecracker vsock UDS to one fixed
// control-owned sandbox UDS. It has no authority to select another endpoint.
type Relay struct {
	config       RelayConfig
	socketPath   string
	listener     *net.UnixListener
	listenerInfo os.FileInfo
	sandboxInfo  os.FileInfo
	parentInfo   os.FileInfo

	logMu    sync.Mutex
	auditErr error
	mu       sync.Mutex
	open     map[*relayConnection]struct{}
	stop     bool
	handlers sync.WaitGroup

	serveDone chan struct{}
	done      chan struct{}
	closeOnce sync.Once
	closeErr  error
}

type relayConnection struct {
	guest   *net.UnixConn
	sandbox *net.UnixConn
}

type auditEvent struct {
	Event         string    `json:"event"`
	Time          time.Time `json:"time"`
	Generation    uint64    `json:"generation"`
	Port          uint32    `json:"port"`
	PID           int       `json:"pid,omitempty"`
	SandboxPID    int       `json:"sandbox_peer_pid,omitempty"`
	SandboxDevice uint64    `json:"sandbox_device"`
	SandboxInode  uint64    `json:"sandbox_inode"`
	GuestToHost   int64     `json:"guest_to_host_bytes"`
	HostToGuest   int64     `json:"host_to_guest_bytes"`
	Error         string    `json:"error,omitempty"`
}

// Arm validates both endpoints, fixes the sandbox device/inode, and begins
// accepting on BasePath_Port. The relay path's parent must already exist and
// be owned by the current uid with mode 0700; this is intentionally not a
// convenience function that creates a possibly shared runtime directory.
func Arm(config RelayConfig) (*Relay, error) {
	if config.Generation == 0 {
		return nil, errors.New("Firecracker relay requires a non-zero generation")
	}
	if config.FirecrackerPID <= 0 {
		return nil, errors.New("Firecracker relay requires a positive Firecracker PID")
	}
	if config.VerifyProcess == nil {
		return nil, errors.New("Firecracker relay requires a process identity verifier")
	}
	if err := config.VerifyProcess(); err != nil {
		return nil, fmt.Errorf("verify Firecracker process before arming relay: %w", err)
	}
	if config.Port == 0 {
		return nil, errors.New("Firecracker relay requires a non-zero vsock port")
	}
	if config.SandboxSocket != "" && config.SandboxSocketPath != "" && config.SandboxSocket != config.SandboxSocketPath {
		return nil, errors.New("Firecracker relay received two different sandbox socket paths")
	}
	if config.SandboxSocket == "" {
		config.SandboxSocket = config.SandboxSocketPath
	}
	if config.DrainTimeout < 0 {
		return nil, errors.New("Firecracker relay drain timeout cannot be negative")
	}
	if config.DrainTimeout == 0 {
		config.DrainTimeout = defaultDrainTimeout
	}

	socketPath, parentInfo, err := relaySocketPath(config.BasePath, config.Port)
	if err != nil {
		return nil, err
	}
	sandboxInfo, err := validatePrivateSocket(config.SandboxSocket, "sandbox socket")
	if err != nil {
		return nil, err
	}
	if err := removeStaleRelaySocket(socketPath); err != nil {
		return nil, err
	}

	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: socketPath, Net: "unix"})
	if err != nil {
		return nil, fmt.Errorf("listen Firecracker relay: %w", err)
	}
	listener.SetUnlinkOnClose(false)
	createdInfo, err := privateCreatedSocket(socketPath, nil)
	if err != nil {
		_ = listener.Close()
		return nil, err
	}
	if currentParent, err := validatePrivateParent(socketPath); err != nil || !os.SameFile(parentInfo, currentParent) {
		_ = listener.Close()
		_ = removeSameSocket(socketPath, createdInfo)
		return nil, errors.New("Firecracker relay parent changed while binding")
	}

	r := &Relay{
		config: config, socketPath: socketPath, listener: listener,
		listenerInfo: createdInfo, sandboxInfo: sandboxInfo, parentInfo: parentInfo,
		open: make(map[*relayConnection]struct{}), serveDone: make(chan struct{}), done: make(chan struct{}),
	}
	go r.serve()
	go r.awaitDone()
	return r, nil
}

// NewRelay is an alias for Arm.
func NewRelay(config RelayConfig) (*Relay, error) { return Arm(config) }

// SocketPath is the exact UDS path to configure in Firecracker for Port.
func (r *Relay) SocketPath() string { return r.socketPath }

// Address is an alias for SocketPath, matching net.Listener-style callers.
func (r *Relay) Address() string { return r.socketPath }

func (r *Relay) serve() {
	defer close(r.serveDone)
	for {
		connection, err := r.listener.AcceptUnix()
		if err != nil {
			if !errors.Is(err, net.ErrClosed) {
				r.auditError(err)
			}
			return
		}
		r.handlers.Add(1)
		go func() {
			defer r.handlers.Done()
			r.handle(connection)
		}()
	}
}

func (r *Relay) awaitDone() {
	<-r.serveDone
	r.handlers.Wait()
	close(r.done)
}

func (r *Relay) handle(guest *net.UnixConn) {
	if guest == nil {
		return
	}
	if err := r.auditFailure(); err != nil {
		_ = guest.Close()
		return
	}
	if err := r.verifyProcess(); err != nil {
		r.auditError(err)
		_ = guest.Close()
		return
	}
	if err := r.verifyPeer(guest); err != nil {
		r.auditError(err)
		_ = guest.Close()
		return
	}
	r.audit(auditEvent{Event: "accept", PID: r.config.FirecrackerPID})
	if err := r.auditFailure(); err != nil {
		_ = guest.Close()
		return
	}

	// The lstat before the dial prevents a replacement from being selected by
	// pathname. The second lstat below closes the just-created connection if a
	// replacement raced the dial. The directory is private as an additional
	// defence against that race.
	if err := r.verifySandbox(); err != nil {
		r.auditError(err)
		_ = guest.Close()
		return
	}
	if err := r.verifyProcess(); err != nil {
		r.auditError(err)
		_ = guest.Close()
		return
	}
	sandboxConnection, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: r.config.SandboxSocket, Net: "unix"})
	if err != nil {
		r.auditError(fmt.Errorf("dial fixed sandbox socket: %w", err))
		_ = guest.Close()
		return
	}
	if err := r.verifySandbox(); err != nil {
		r.auditError(err)
		_ = sandboxConnection.Close()
		_ = guest.Close()
		return
	}
	if err := r.verifyProcess(); err != nil {
		r.auditError(err)
		_ = sandboxConnection.Close()
		_ = guest.Close()
		return
	}
	sandboxPID, err := unixPeerPID(sandboxConnection)
	if err != nil {
		r.auditError(fmt.Errorf("read sandbox Unix peer credentials: %w", err))
		_ = sandboxConnection.Close()
		_ = guest.Close()
		return
	}

	pair := &relayConnection{guest: guest, sandbox: sandboxConnection}
	if !r.register(pair) {
		_ = pair.close()
		return
	}
	defer func() {
		r.unregister(pair)
		_ = pair.close()
	}()

	type copied struct {
		n   int64
		err error
	}
	guestToHost := make(chan copied, 1)
	hostToGuest := make(chan copied, 1)
	go func() {
		n, err := io.Copy(sandboxConnection, guest)
		closeWrite(sandboxConnection)
		guestToHost <- copied{n, err}
	}()
	go func() { n, err := io.Copy(guest, sandboxConnection); closeWrite(guest); hostToGuest <- copied{n, err} }()
	left, right := <-guestToHost, <-hostToGuest
	r.audit(auditEvent{Event: "bytes", SandboxPID: sandboxPID, GuestToHost: left.n, HostToGuest: right.n})
	if !normalCopyError(left.err) {
		r.auditError(fmt.Errorf("relay guest to sandbox: %w", left.err))
	}
	if !normalCopyError(right.err) {
		r.auditError(fmt.Errorf("relay sandbox to guest: %w", right.err))
	}
}

func (r *Relay) register(pair *relayConnection) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.stop {
		return false
	}
	r.open[pair] = struct{}{}
	return true
}

func (r *Relay) unregister(pair *relayConnection) {
	r.mu.Lock()
	delete(r.open, pair)
	r.mu.Unlock()
}

func (r *Relay) verifyPeer(connection *net.UnixConn) error {
	pid, err := unixPeerPID(connection)
	if err != nil {
		return fmt.Errorf("read accepted Unix peer credentials: %w", err)
	}
	if pid != r.config.FirecrackerPID {
		return fmt.Errorf("reject relay peer pid %d, want Firecracker pid %d", pid, r.config.FirecrackerPID)
	}
	return nil
}

func unixPeerPID(connection *net.UnixConn) (int, error) {
	if connection == nil {
		return 0, errors.New("Unix socket is nil")
	}
	var credential *unix.Ucred
	raw, err := connection.SyscallConn()
	if err != nil {
		return 0, fmt.Errorf("access Unix socket: %w", err)
	}
	if err := raw.Control(func(fd uintptr) {
		credential, err = unix.GetsockoptUcred(int(fd), unix.SOL_SOCKET, unix.SO_PEERCRED)
	}); err != nil {
		return 0, fmt.Errorf("access Unix socket descriptor: %w", err)
	}
	if err != nil || credential == nil {
		if err == nil {
			err = errors.New("SO_PEERCRED returned no credentials")
		}
		return 0, err
	}
	if credential.Pid <= 0 {
		return 0, fmt.Errorf("SO_PEERCRED returned invalid pid %d", credential.Pid)
	}
	return int(credential.Pid), nil
}

func (r *Relay) verifyProcess() error {
	if r == nil || r.config.VerifyProcess == nil {
		return errors.New("Firecracker relay has no process identity verifier")
	}
	if err := r.config.VerifyProcess(); err != nil {
		return fmt.Errorf("Firecracker relay process identity changed: %w", err)
	}
	return nil
}

func (r *Relay) verifySandbox() error {
	current, err := validatePrivateSocket(r.config.SandboxSocket, "sandbox socket")
	if err != nil {
		return err
	}
	if r.sandboxInfo == nil || !os.SameFile(r.sandboxInfo, current) {
		return errors.New("sandbox socket path changed after relay arm")
	}
	return nil
}

func (r *Relay) auditError(err error) {
	if err != nil {
		r.audit(auditEvent{Event: "error", Error: err.Error()})
	}
}

func (r *Relay) audit(event auditEvent) {
	if r.config.AuditLog == nil {
		return
	}
	event.Time = time.Now().UTC()
	event.Generation = r.config.Generation
	event.Port = r.config.Port
	if stat, ok := r.sandboxInfo.Sys().(*syscall.Stat_t); ok {
		event.SandboxDevice = uint64(stat.Dev)
		event.SandboxInode = stat.Ino
	}
	encoded, err := json.Marshal(event)
	if err != nil {
		return
	}
	r.logMu.Lock()
	written, err := r.config.AuditLog.Write(append(encoded, '\n'))
	if err == nil && written != len(encoded)+1 {
		err = io.ErrShortWrite
	}
	if err != nil && r.auditErr == nil {
		r.auditErr = fmt.Errorf("Firecracker relay audit write: %w", err)
	}
	r.logMu.Unlock()
}

func (r *Relay) auditFailure() error {
	r.logMu.Lock()
	defer r.logMu.Unlock()
	return r.auditErr
}

// Close stops accepting immediately and gives established streams DrainTimeout
// to complete. A timeout force-closes every pair, reports an error, and waits
// one further DrainTimeout for handlers. Callers must use Wait before closing
// the caller-owned AuditLog. Close only removes the relay socket if the path
// still names the socket originally created by this relay.
func (r *Relay) Close() error {
	return r.shutdown(false)
}

// Abort is the restore-boundary form of Close for protocols that intentionally
// keep streams open while idle. It closes every authenticated current-
// generation stream immediately, waits until no handler can write AuditLog,
// and removes the relay socket. Unlike Close, the intentional cut is not
// reported as a drain timeout.
func (r *Relay) Abort() error {
	return r.shutdown(true)
}

func (r *Relay) shutdown(immediate bool) error {
	r.closeOnce.Do(func() {
		r.mu.Lock()
		r.stop = true
		r.mu.Unlock()
		listenerErr := r.listener.Close()
		if immediate {
			r.closeConnections()
			if !waitLoopbackProxyUntil(r.done, time.Now().Add(r.config.DrainTimeout)) {
				r.closeErr = errors.Join(r.closeErr, errors.New("Firecracker relay abort timed out"))
			}
		} else {
			deadline := time.Now().Add(r.config.DrainTimeout)
			if !waitLoopbackProxyUntil(r.done, deadline) {
				r.closeConnections()
				r.closeErr = errors.Join(r.closeErr, errors.New("Firecracker relay connection drain timed out"))
				forcedDeadline := time.Now().Add(r.config.DrainTimeout)
				if !waitLoopbackProxyUntil(r.done, forcedDeadline) {
					r.closeErr = errors.Join(r.closeErr, errors.New("Firecracker relay forced shutdown timed out"))
				}
			}
		}
		removeErr := removeSameSocket(r.socketPath, r.listenerInfo)
		r.closeErr = errors.Join(r.closeErr, ignoreClosed(listenerErr), removeErr, r.auditFailure())
	})
	return r.closeErr
}

// Wait reports when no accept or connection handler can write AuditLog again.
func (r *Relay) Wait(ctx context.Context) error {
	if r == nil {
		return nil
	}
	if ctx == nil {
		return errors.New("Firecracker relay wait context is nil")
	}
	select {
	case <-r.done:
		return r.auditFailure()
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (r *Relay) closeConnections() {
	r.mu.Lock()
	connections := make([]*relayConnection, 0, len(r.open))
	for connection := range r.open {
		connections = append(connections, connection)
	}
	r.mu.Unlock()
	for _, connection := range connections {
		_ = connection.close()
	}
}

func (c *relayConnection) close() error {
	return errors.Join(c.guest.Close(), c.sandbox.Close())
}

func closeWrite(connection *net.UnixConn) {
	_ = connection.CloseWrite()
}

func normalCopyError(err error) bool {
	return err == nil || errors.Is(err, io.EOF) || errors.Is(err, net.ErrClosed) ||
		errors.Is(err, os.ErrClosed) || errors.Is(err, syscall.EPIPE) || errors.Is(err, syscall.ECONNRESET)
}

func ignoreClosed(err error) error {
	if errors.Is(err, net.ErrClosed) || errors.Is(err, os.ErrClosed) {
		return nil
	}
	return err
}

func relaySocketPath(base string, port uint32) (string, os.FileInfo, error) {
	if base == "" || !filepath.IsAbs(base) || filepath.Clean(base) != base {
		return "", nil, errors.New("Firecracker relay base path must be absolute and canonical")
	}
	if filepath.Base(base) == "." || filepath.Base(base) == ".." {
		return "", nil, errors.New("Firecracker relay base path must name a file")
	}
	path := base + "_" + strconv.FormatUint(uint64(port), 10)
	if len([]byte(path)) >= unixSocketPathLimit {
		return "", nil, fmt.Errorf("Firecracker relay socket path is too long: %q", path)
	}
	parent, err := validatePrivateParent(path)
	if err != nil {
		return "", nil, err
	}
	return path, parent, nil
}

func validatePrivateParent(path string) (os.FileInfo, error) {
	if path == "" || !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return nil, errors.New("Unix socket path must be absolute and canonical")
	}
	parent := filepath.Dir(path)
	info, err := os.Lstat(parent)
	if err != nil {
		return nil, fmt.Errorf("inspect Unix socket parent: %w", err)
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("Unix socket parent must be a real directory")
	}
	resolved, err := filepath.EvalSymlinks(parent)
	if err != nil || resolved != parent {
		return nil, errors.New("Unix socket parent must not traverse symlinks")
	}
	if info.Mode().Perm() != 0o700 {
		return nil, fmt.Errorf("Unix socket parent mode is %04o, want 0700", info.Mode().Perm())
	}
	if err := requireCurrentOwner(info, "Unix socket parent"); err != nil {
		return nil, err
	}
	return info, nil
}

func validatePrivateSocket(path, label string) (os.FileInfo, error) {
	if len([]byte(path)) >= unixSocketPathLimit {
		return nil, fmt.Errorf("%s path is too long", label)
	}
	if _, err := validatePrivateParent(path); err != nil {
		return nil, err
	}
	info, err := os.Lstat(path)
	if err != nil {
		return nil, fmt.Errorf("inspect %s: %w", label, err)
	}
	if info.Mode()&os.ModeSymlink != 0 || info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0o600 {
		return nil, fmt.Errorf("%s must be a private Unix socket", label)
	}
	if err := requireCurrentOwner(info, label); err != nil {
		return nil, err
	}
	return info, nil
}

func privateCreatedSocket(path string, expected os.FileInfo) (os.FileInfo, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, fmt.Errorf("inspect Firecracker relay socket: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || info.Mode()&os.ModeSocket == 0 || (expected != nil && !os.SameFile(info, expected)) {
		return nil, errors.New("Firecracker relay socket path changed while binding")
	}
	if err := requireCurrentOwner(info, "Firecracker relay socket"); err != nil {
		return nil, err
	}
	if err := unix.Fchmodat(unix.AT_FDCWD, path, 0o600, unix.AT_SYMLINK_NOFOLLOW); err != nil {
		return nil, fmt.Errorf("protect Firecracker relay socket: %w", err)
	}
	updated, err := os.Lstat(path)
	if err != nil || !os.SameFile(info, updated) || updated.Mode()&os.ModeSocket == 0 || updated.Mode().Perm() != 0o600 {
		return nil, errors.New("Firecracker relay socket path changed while protecting")
	}
	return updated, nil
}

func removeStaleRelaySocket(path string) error {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("inspect existing Firecracker relay socket: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || info.Mode()&os.ModeSocket == 0 {
		return errors.New("refusing to replace a non-socket Firecracker relay path")
	}
	if info.Mode().Perm() != 0o600 {
		return errors.New("refusing to replace a non-private Firecracker relay socket")
	}
	if err := requireCurrentOwner(info, "existing Firecracker relay socket"); err != nil {
		return err
	}
	connection, dialErr := net.DialTimeout("unix", path, 100*time.Millisecond)
	if dialErr == nil {
		_ = connection.Close()
		return errors.New("refusing to replace an active Firecracker relay socket")
	}
	if !errors.Is(dialErr, syscall.ECONNREFUSED) && !errors.Is(dialErr, os.ErrNotExist) {
		return fmt.Errorf("cannot prove existing Firecracker relay socket is stale: %w", dialErr)
	}
	current, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil || !os.SameFile(info, current) {
		return errors.New("existing Firecracker relay socket changed during stale check")
	}
	return removeSameSocket(path, current)
}

func removeSameSocket(path string, expected os.FileInfo) error {
	if path == "" {
		return nil
	}
	current, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if expected == nil || current.Mode()&os.ModeSymlink != 0 || current.Mode()&os.ModeSocket == 0 || !os.SameFile(expected, current) {
		return errors.New("Unix socket path was replaced; refusing to remove it")
	}
	quarantine, err := randomSocketSibling(path, ".r-")
	if err != nil {
		return err
	}
	if err := unix.Renameat2(unix.AT_FDCWD, path, unix.AT_FDCWD, quarantine, unix.RENAME_NOREPLACE); errors.Is(err, os.ErrNotExist) {
		return nil
	} else if err != nil {
		return fmt.Errorf("quarantine Unix socket: %w", err)
	}
	moved, err := os.Lstat(quarantine)
	if err != nil || moved.Mode()&os.ModeSymlink != 0 || moved.Mode()&os.ModeSocket == 0 || !os.SameFile(expected, moved) {
		return fmt.Errorf("Unix socket changed while quarantining; refusing to remove %q", quarantine)
	}
	if err := os.Remove(quarantine); err != nil {
		return fmt.Errorf("remove quarantined Unix socket: %w", err)
	}
	return nil
}

func randomSocketSibling(path, prefix string) (string, error) {
	random := make([]byte, 8)
	if _, err := rand.Read(random); err != nil {
		return "", fmt.Errorf("make private Unix socket name: %w", err)
	}
	return filepath.Join(filepath.Dir(path), prefix+hex.EncodeToString(random)), nil
}

func requireCurrentOwner(info os.FileInfo, label string) error {
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(stat.Uid) != os.Geteuid() {
		return fmt.Errorf("%s must be owned by the current uid", label)
	}
	return nil
}
