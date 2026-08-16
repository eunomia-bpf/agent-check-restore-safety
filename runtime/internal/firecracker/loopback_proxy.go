package firecracker

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
	"unicode"

	"golang.org/x/sys/unix"
)

const defaultLoopbackProxyDialTimeout = 5 * time.Second

// LoopbackProxyConfig fixes one private Unix socket to one numeric host
// loopback TCP endpoint. AuditLog is caller-owned and is never closed.
type LoopbackProxyConfig struct {
	SocketPath    string
	TargetAddress string
	AuditLog      io.Writer
	DialTimeout   time.Duration
	DrainTimeout  time.Duration
}

// LoopbackProxy supplies Relay with a private SandboxSocket while retaining no
// authority to select a destination other than its configured loopback port.
type LoopbackProxy struct {
	config        LoopbackProxyConfig
	socketPath    string
	targetAddress string
	listener      *net.UnixListener
	listenerInfo  os.FileInfo
	parentInfo    os.FileInfo
	peerPID       int
	peerUID       uint32
	peerGID       uint32

	ctx    context.Context
	cancel context.CancelFunc
	dial   func(context.Context, string, string) (net.Conn, error)
	// endpointMu keeps the destination spelling and dial capability consistent
	// while a handler takes its per-connection snapshot.
	endpointMu sync.RWMutex

	mu       sync.Mutex
	open     map[*loopbackProxyConnection]struct{}
	stop     bool
	active   int
	changed  chan struct{}
	handlers sync.WaitGroup

	auditWriteMu sync.Mutex
	auditStateMu sync.Mutex
	auditErr     error

	serveDone chan struct{}
	done      chan struct{}
	closeOnce sync.Once
	closeErr  error
}

type loopbackProxyConnection struct {
	mu       sync.Mutex
	client   *net.UnixConn
	upstream net.Conn
	closed   bool
}

type loopbackProxyAuditEvent struct {
	Event          string    `json:"event"`
	Time           time.Time `json:"time"`
	Target         string    `json:"target"`
	PID            int       `json:"pid"`
	UID            uint32    `json:"uid"`
	GID            uint32    `json:"gid"`
	SocketDevice   uint64    `json:"socket_device"`
	SocketInode    uint64    `json:"socket_inode"`
	ClientToTarget int64     `json:"client_to_target_bytes"`
	TargetToClient int64     `json:"target_to_client_bytes"`
	Error          string    `json:"error,omitempty"`
}

// StartLoopbackProxy creates SocketPath and begins forwarding authenticated
// same-process Unix connections to the single configured numeric loopback TCP
// endpoint. SocketPath's parent must already be a real, current-user-owned 0700
// directory, and SocketPath itself must not exist.
func StartLoopbackProxy(config LoopbackProxyConfig) (*LoopbackProxy, error) {
	if config.DialTimeout < 0 {
		return nil, errors.New("loopback proxy dial timeout cannot be negative")
	}
	if config.DialTimeout == 0 {
		config.DialTimeout = defaultLoopbackProxyDialTimeout
	}
	if config.DrainTimeout < 0 {
		return nil, errors.New("loopback proxy drain timeout cannot be negative")
	}
	if config.DrainTimeout == 0 {
		config.DrainTimeout = defaultDrainTimeout
	}
	target, err := validateLoopbackProxyTarget(config.TargetAddress)
	if err != nil {
		return nil, err
	}
	config.TargetAddress = target
	parentInfo, err := validateNewLoopbackProxySocket(config.SocketPath)
	if err != nil {
		return nil, err
	}

	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: config.SocketPath, Net: "unix"})
	if err != nil {
		return nil, fmt.Errorf("listen loopback proxy: %w", err)
	}
	listener.SetUnlinkOnClose(false)
	boundInfo, err := os.Lstat(config.SocketPath)
	if err != nil {
		_ = listener.Close()
		return nil, fmt.Errorf("inspect newly bound loopback proxy socket: %w", err)
	}
	listenerInfo, err := privateCreatedSocket(config.SocketPath, boundInfo)
	if err != nil {
		_ = listener.Close()
		return nil, errors.Join(err, removeSameSocket(config.SocketPath, boundInfo))
	}
	if currentParent, parentErr := validatePrivateParent(config.SocketPath); parentErr != nil || !os.SameFile(parentInfo, currentParent) {
		_ = listener.Close()
		_ = removeSameSocket(config.SocketPath, listenerInfo)
		return nil, errors.New("loopback proxy parent changed while binding")
	}
	if currentTarget, targetErr := validateLoopbackProxyTarget(config.TargetAddress); targetErr != nil || currentTarget != target {
		_ = listener.Close()
		_ = removeSameSocket(config.SocketPath, listenerInfo)
		return nil, errors.New("loopback proxy target changed while binding")
	}

	ctx, cancel := context.WithCancel(context.Background())
	proxy := &LoopbackProxy{
		config: config, socketPath: config.SocketPath, targetAddress: target,
		listener: listener, listenerInfo: listenerInfo, parentInfo: parentInfo,
		peerPID: os.Getpid(), peerUID: uint32(os.Geteuid()), peerGID: uint32(os.Getegid()),
		ctx: ctx, cancel: cancel, open: make(map[*loopbackProxyConnection]struct{}), changed: make(chan struct{}),
		serveDone: make(chan struct{}), done: make(chan struct{}),
	}
	dialer := &net.Dialer{}
	proxy.dial = dialer.DialContext
	go proxy.serve()
	go proxy.awaitDone()
	return proxy, nil
}

// SocketPath is the private Unix endpoint to supply as Relay.SandboxSocket.
func (p *LoopbackProxy) SocketPath() string { return p.socketPath }

// TargetAddress is the canonical numeric loopback endpoint fixed at startup.
func (p *LoopbackProxy) TargetAddress() string { return p.targetAddress }

func validateLoopbackProxyTarget(address string) (string, error) {
	if address == "" {
		return "", errors.New("loopback proxy target is empty")
	}
	if strings.IndexFunc(address, unicode.IsControl) >= 0 {
		return "", errors.New("loopback proxy target contains a control character")
	}
	host, portText, err := net.SplitHostPort(address)
	if err != nil {
		return "", fmt.Errorf("split loopback proxy target: %w", err)
	}
	if host != "127.0.0.1" && host != "::1" {
		return "", fmt.Errorf("loopback proxy target host %q is not numeric loopback", host)
	}
	if portText == "" {
		return "", errors.New("loopback proxy target port is empty")
	}
	for _, value := range []byte(portText) {
		if value < '0' || value > '9' {
			return "", errors.New("loopback proxy target port must contain only decimal digits")
		}
	}
	port, err := strconv.ParseUint(portText, 10, 16)
	if err != nil || port == 0 {
		return "", errors.New("loopback proxy target port must be between 1 and 65535")
	}
	return net.JoinHostPort(host, strconv.FormatUint(port, 10)), nil
}

func validateNewLoopbackProxySocket(path string) (os.FileInfo, error) {
	if strings.IndexFunc(path, unicode.IsControl) >= 0 {
		return nil, errors.New("loopback proxy socket path contains a control character")
	}
	if len([]byte(path)) >= unixSocketPathLimit {
		return nil, errors.New("loopback proxy socket path is too long")
	}
	parentInfo, err := validatePrivateParent(path)
	if err != nil {
		return nil, err
	}
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return parentInfo, nil
	}
	if err != nil {
		return nil, fmt.Errorf("inspect loopback proxy socket target: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("loopback proxy socket target must not be a symlink")
	}
	return nil, errors.New("loopback proxy socket target already exists")
}

func (p *LoopbackProxy) serve() {
	defer close(p.serveDone)
	for {
		connection, err := p.listener.AcceptUnix()
		if err != nil {
			if !errors.Is(err, net.ErrClosed) {
				p.auditError(fmt.Errorf("accept loopback proxy connection: %w", err))
			}
			return
		}
		p.mu.Lock()
		p.active++
		p.notifyLocked()
		p.mu.Unlock()
		p.handlers.Add(1)
		go func() {
			defer func() {
				p.mu.Lock()
				p.active--
				p.notifyLocked()
				p.mu.Unlock()
				p.handlers.Done()
			}()
			p.handle(connection)
		}()
	}
}

func (p *LoopbackProxy) awaitDone() {
	<-p.serveDone
	p.handlers.Wait()
	close(p.done)
}

func (p *LoopbackProxy) handle(client *net.UnixConn) {
	if client == nil {
		return
	}
	pair := &loopbackProxyConnection{client: client}
	if !p.register(pair) {
		_ = pair.close()
		return
	}
	defer func() {
		p.unregister(pair)
		_ = pair.close()
	}()
	if p.auditFailure() != nil {
		return
	}
	target, err := p.verifyEndpoint()
	if err != nil {
		p.auditError(err)
		return
	}
	credential, err := loopbackProxyPeerCredential(client)
	if err != nil {
		p.auditError(err)
		return
	}
	if err := p.validatePeer(credential); err != nil {
		p.auditError(err)
		return
	}
	if err := p.audit(loopbackProxyAuditEvent{
		Event: "accept", PID: int(credential.Pid), UID: credential.Uid, GID: credential.Gid,
	}); err != nil {
		return
	}
	if target, err = p.verifyEndpoint(); err != nil {
		p.auditError(err)
		return
	}

	dialContext, cancel := context.WithTimeout(p.ctx, p.config.DialTimeout)
	p.endpointMu.RLock()
	dial := p.dial
	p.endpointMu.RUnlock()
	upstream, err := dial(dialContext, "tcp", target)
	cancel()
	if err != nil {
		p.auditError(fmt.Errorf("dial fixed loopback target %q: %w", target, err))
		return
	}
	if !pair.attach(upstream) {
		return
	}
	if _, err := p.verifyEndpoint(); err != nil {
		p.auditError(err)
		return
	}

	type copied struct {
		n   int64
		err error
	}
	clientToTarget := make(chan copied, 1)
	targetToClient := make(chan copied, 1)
	go func() {
		n, copyErr := io.Copy(upstream, client)
		closeLoopbackProxyWrite(upstream)
		clientToTarget <- copied{n: n, err: copyErr}
	}()
	go func() {
		n, copyErr := io.Copy(client, upstream)
		_ = client.CloseWrite()
		targetToClient <- copied{n: n, err: copyErr}
	}()
	left, right := <-clientToTarget, <-targetToClient
	_ = p.audit(loopbackProxyAuditEvent{
		Event: "bytes", ClientToTarget: left.n, TargetToClient: right.n,
	})
	if !normalCopyError(left.err) {
		p.auditError(fmt.Errorf("copy loopback client to target: %w", left.err))
	}
	if !normalCopyError(right.err) {
		p.auditError(fmt.Errorf("copy loopback target to client: %w", right.err))
	}
}

func (p *LoopbackProxy) verifyEndpoint() (string, error) {
	parent, err := validatePrivateParent(p.socketPath)
	if err != nil {
		return "", fmt.Errorf("revalidate loopback proxy parent: %w", err)
	}
	if p.parentInfo == nil || !os.SameFile(p.parentInfo, parent) {
		return "", errors.New("loopback proxy parent identity changed")
	}
	current, err := validatePrivateSocket(p.socketPath, "loopback proxy socket")
	if err != nil {
		return "", err
	}
	if p.listenerInfo == nil || !os.SameFile(p.listenerInfo, current) {
		return "", errors.New("loopback proxy socket identity changed")
	}
	p.endpointMu.RLock()
	targetInput := p.config.TargetAddress
	p.endpointMu.RUnlock()
	target, err := validateLoopbackProxyTarget(targetInput)
	if err != nil {
		return "", fmt.Errorf("revalidate loopback proxy target: %w", err)
	}
	if target != p.targetAddress {
		return "", errors.New("loopback proxy target changed after startup")
	}
	return target, nil
}

func loopbackProxyPeerCredential(connection *net.UnixConn) (*unix.Ucred, error) {
	if connection == nil {
		return nil, errors.New("loopback proxy Unix connection is nil")
	}
	var credential *unix.Ucred
	var credentialErr error
	raw, err := connection.SyscallConn()
	if err != nil {
		return nil, fmt.Errorf("access loopback proxy Unix socket: %w", err)
	}
	if err := raw.Control(func(fd uintptr) {
		credential, credentialErr = unix.GetsockoptUcred(int(fd), unix.SOL_SOCKET, unix.SO_PEERCRED)
	}); err != nil {
		return nil, fmt.Errorf("access loopback proxy Unix socket descriptor: %w", err)
	}
	if credentialErr != nil {
		return nil, fmt.Errorf("read loopback proxy Unix peer credentials: %w", credentialErr)
	}
	if credential == nil {
		return nil, errors.New("SO_PEERCRED returned no loopback proxy credentials")
	}
	return credential, nil
}

func (p *LoopbackProxy) validatePeer(credential *unix.Ucred) error {
	if credential == nil {
		return errors.New("loopback proxy peer credentials are nil")
	}
	if int(credential.Pid) != p.peerPID || credential.Uid != p.peerUID || credential.Gid != p.peerGID {
		return fmt.Errorf(
			"reject loopback proxy peer pid/uid/gid %d/%d/%d, want %d/%d/%d",
			credential.Pid, credential.Uid, credential.Gid, p.peerPID, p.peerUID, p.peerGID,
		)
	}
	return nil
}

func (p *LoopbackProxy) register(connection *loopbackProxyConnection) bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.stop {
		return false
	}
	p.open[connection] = struct{}{}
	return true
}

func (p *LoopbackProxy) unregister(connection *loopbackProxyConnection) {
	p.mu.Lock()
	delete(p.open, connection)
	p.mu.Unlock()
}

func (p *LoopbackProxy) notifyLocked() {
	close(p.changed)
	p.changed = make(chan struct{})
}

// WaitIdle waits until every accepted connection handler has finished. The
// caller must separately prevent new peers from connecting if it needs this
// condition to remain true after WaitIdle returns.
func (p *LoopbackProxy) WaitIdle(ctx context.Context) error {
	if p == nil {
		return nil
	}
	if ctx == nil {
		return errors.New("loopback proxy idle wait context is nil")
	}
	for {
		p.mu.Lock()
		if p.active == 0 {
			p.mu.Unlock()
			return p.auditFailure()
		}
		changed := p.changed
		p.mu.Unlock()
		select {
		case <-changed:
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

func (p *LoopbackProxy) auditError(err error) {
	if err != nil {
		_ = p.audit(loopbackProxyAuditEvent{Event: "error", Error: err.Error()})
	}
}

func (p *LoopbackProxy) audit(event loopbackProxyAuditEvent) error {
	if p.config.AuditLog == nil {
		return p.auditFailure()
	}
	event.Time = time.Now().UTC()
	event.Target = p.targetAddress
	if stat, ok := p.listenerInfo.Sys().(*syscall.Stat_t); ok {
		event.SocketDevice = uint64(stat.Dev)
		event.SocketInode = stat.Ino
	}
	encoded, err := json.Marshal(event)
	if err != nil {
		return p.setAuditFailure(fmt.Errorf("encode loopback proxy audit event: %w", err))
	}

	p.auditWriteMu.Lock()
	defer p.auditWriteMu.Unlock()
	if err := p.auditFailure(); err != nil {
		return err
	}
	written, err := p.config.AuditLog.Write(append(encoded, '\n'))
	if err == nil && written != len(encoded)+1 {
		err = io.ErrShortWrite
	}
	if err != nil {
		return p.setAuditFailure(fmt.Errorf("loopback proxy audit write: %w", err))
	}
	return nil
}

func (p *LoopbackProxy) setAuditFailure(err error) error {
	if err == nil {
		return p.auditFailure()
	}
	p.auditStateMu.Lock()
	first := p.auditErr == nil
	if first {
		p.auditErr = err
	}
	latched := p.auditErr
	p.auditStateMu.Unlock()
	if first {
		p.failClosed()
	}
	return latched
}

func (p *LoopbackProxy) auditFailure() error {
	p.auditStateMu.Lock()
	defer p.auditStateMu.Unlock()
	return p.auditErr
}

func (p *LoopbackProxy) failClosed() {
	p.mu.Lock()
	p.stop = true
	connections := make([]*loopbackProxyConnection, 0, len(p.open))
	for connection := range p.open {
		connections = append(connections, connection)
	}
	p.mu.Unlock()
	p.cancel()
	_ = p.listener.Close()
	for _, connection := range connections {
		_ = connection.close()
	}
}

// Close stops accepting immediately, permits established copies to drain for
// at most DrainTimeout, then closes them and permits one further DrainTimeout
// for forced shutdown. A timeout means handlers may still be inside the
// caller-owned AuditLog; callers must use Wait before closing that writer. It
// removes SocketPath only if that path still names the Unix socket created by
// this proxy.
func (p *LoopbackProxy) Close() error {
	if p == nil {
		return nil
	}
	p.closeOnce.Do(func() {
		deadline := time.Now().Add(p.config.DrainTimeout)
		p.mu.Lock()
		p.stop = true
		p.mu.Unlock()
		p.cancel()
		listenerErr := p.listener.Close()

		if !waitLoopbackProxyUntil(p.done, deadline) {
			p.closeConnections()
			p.closeErr = errors.Join(p.closeErr, errors.New("loopback proxy connection drain timed out"))
			forcedDeadline := time.Now().Add(p.config.DrainTimeout)
			if !waitLoopbackProxyUntil(p.done, forcedDeadline) {
				p.closeErr = errors.Join(p.closeErr, errors.New("loopback proxy forced shutdown timed out"))
			}
		}
		p.closeErr = errors.Join(
			p.closeErr,
			ignoreClosed(listenerErr),
			removeSameSocket(p.socketPath, p.listenerInfo),
			p.auditFailure(),
		)
	})
	return p.closeErr
}

// Wait reports when the accept loop and every connection handler have
// stopped. Once Wait returns without a context error, AuditLog can no longer
// be used by this proxy and is safe for the caller to close.
func (p *LoopbackProxy) Wait(ctx context.Context) error {
	if p == nil {
		return nil
	}
	if ctx == nil {
		return errors.New("loopback proxy wait context is nil")
	}
	select {
	case <-p.done:
		return p.auditFailure()
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (p *LoopbackProxy) closeConnections() {
	p.mu.Lock()
	connections := make([]*loopbackProxyConnection, 0, len(p.open))
	for connection := range p.open {
		connections = append(connections, connection)
	}
	p.mu.Unlock()
	for _, connection := range connections {
		_ = connection.close()
	}
}

func (c *loopbackProxyConnection) attach(upstream net.Conn) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed {
		_ = upstream.Close()
		return false
	}
	c.upstream = upstream
	return true
}

func (c *loopbackProxyConnection) close() error {
	c.mu.Lock()
	if c.closed {
		c.mu.Unlock()
		return nil
	}
	c.closed = true
	client, upstream := c.client, c.upstream
	c.mu.Unlock()
	var clientErr, upstreamErr error
	if client != nil {
		clientErr = client.Close()
	}
	if upstream != nil {
		upstreamErr = upstream.Close()
	}
	return errors.Join(ignoreClosed(clientErr), ignoreClosed(upstreamErr))
}

func closeLoopbackProxyWrite(connection net.Conn) {
	if closer, ok := connection.(interface{ CloseWrite() error }); ok {
		_ = closer.CloseWrite()
	}
}

func waitLoopbackProxyUntil(done <-chan struct{}, deadline time.Time) bool {
	remaining := time.Until(deadline)
	if remaining <= 0 {
		select {
		case <-done:
			return true
		default:
			return false
		}
	}
	timer := time.NewTimer(remaining)
	defer timer.Stop()
	select {
	case <-done:
		return true
	case <-timer.C:
		return false
	}
}
