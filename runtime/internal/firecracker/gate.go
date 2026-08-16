package firecracker

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"strings"
	"sync"
	"time"

	"golang.org/x/sys/unix"
)

const (
	gatePort         = uint32(8000)
	maxGateLineBytes = 2 << 20
	gateWriteTimeout = time.Second
)

var ErrGateClosed = errors.New("Firecracker gate is closed")

// GateConfig describes the restore gate for one Firecracker guest. BasePath
// forms the fixed Firecracker vsock UDS name BasePath_8000. Generation is the
// role sent to the guest in GO: the unique base path and FirecrackerPID bind
// that role to the actual guest generation.
type GateConfig struct {
	Generation     uint64
	BasePath       string
	FirecrackerPID int
	// VerifyProcess must prove that FirecrackerPID still names the exact VMM
	// generation this gate was armed for (for example, by checking a pidfd-bound
	// Process identity). Numeric SO_PEERCRED alone is insufficient after PID
	// reuse.
	VerifyProcess func() error
	AuditLog      io.Writer
	DrainTimeout  time.Duration
}

// Result is the immutable first RESULT event accepted by a Gate.
type Result struct {
	Event  string          `json:"event"`
	Status int             `json:"status"`
	Body   json.RawMessage `json:"body"`
}

// GateResult is retained as a descriptive alias for callers.
type GateResult = Result

// Gate waits for a guest READY event, releases it only after Allow, and then
// accepts one strict RESULT event. It is deliberately a small protocol rather
// than a general guest-to-host transport.
type Gate struct {
	config       GateConfig
	socketPath   string
	listener     *net.UnixListener
	listenerInfo os.FileInfo

	mu          sync.Mutex
	connections map[*net.UnixConn]struct{}
	current     *gateReady
	allowed     bool
	goSent      bool
	closed      bool
	ready       bool
	result      Result
	hasResult   bool

	readyDone  chan struct{}
	resultDone chan struct{}
	closeDone  chan struct{}
	serveDone  chan struct{}
	handlers   sync.WaitGroup
	readyOnce  sync.Once
	resultOnce sync.Once
	closeOnce  sync.Once
	closeErr   error
	logMu      sync.Mutex
	auditErr   error
	auditDone  chan struct{}
	auditOnce  sync.Once
}

type gateReady struct {
	connection *net.UnixConn
	release    chan struct{}
	once       sync.Once
}

type gateAuditEvent struct {
	Event      string    `json:"event"`
	Time       time.Time `json:"time"`
	Generation uint64    `json:"generation,omitempty"`
	Port       uint32    `json:"port"`
	PID        int       `json:"pid,omitempty"`
	Bytes      int       `json:"bytes,omitempty"`
	Status     int       `json:"status,omitempty"`
	Error      string    `json:"error,omitempty"`
}

// ArmGate starts a gate at BasePath_8000. Its UDS parent must already be a
// current-user-owned, real 0700 directory. A guest connection is accepted
// only when Linux SO_PEERCRED identifies the configured Firecracker process.
func ArmGate(config GateConfig) (*Gate, error) {
	if config.Generation == 0 {
		return nil, errors.New("Firecracker gate requires a positive generation")
	}
	if config.FirecrackerPID <= 0 {
		return nil, errors.New("Firecracker gate requires a positive Firecracker PID")
	}
	if config.VerifyProcess == nil {
		return nil, errors.New("Firecracker gate requires a process identity verifier")
	}
	if err := config.VerifyProcess(); err != nil {
		return nil, fmt.Errorf("verify Firecracker process before arming gate: %w", err)
	}
	if config.DrainTimeout < 0 {
		return nil, errors.New("Firecracker gate drain timeout cannot be negative")
	}
	if config.DrainTimeout == 0 {
		config.DrainTimeout = defaultDrainTimeout
	}
	path, parentInfo, err := relaySocketPath(config.BasePath, gatePort)
	if err != nil {
		return nil, err
	}
	if err := removeStaleRelaySocket(path); err != nil {
		return nil, err
	}
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		return nil, fmt.Errorf("listen Firecracker gate: %w", err)
	}
	listener.SetUnlinkOnClose(false)
	info, err := privateCreatedSocket(path, nil)
	if err != nil {
		_ = listener.Close()
		return nil, err
	}
	if currentParent, err := validatePrivateParent(path); err != nil || !os.SameFile(parentInfo, currentParent) {
		_ = listener.Close()
		_ = removeSameSocket(path, info)
		return nil, errors.New("Firecracker gate parent changed while binding")
	}
	gate := &Gate{
		config: config, socketPath: path, listener: listener, listenerInfo: info,
		connections: make(map[*net.UnixConn]struct{}), readyDone: make(chan struct{}),
		resultDone: make(chan struct{}), closeDone: make(chan struct{}), serveDone: make(chan struct{}),
		auditDone: make(chan struct{}),
	}
	go gate.serve()
	return gate, nil
}

// NewGate is an alias for ArmGate.
func NewGate(config GateConfig) (*Gate, error) { return ArmGate(config) }

// SocketPath is the UDS path to configure as the Firecracker backend for
// guest vsock port 8000.
func (g *Gate) SocketPath() string { return g.socketPath }

// Address is an alias for SocketPath.
func (g *Gate) Address() string { return g.socketPath }

// Allow releases the current READY connection, or causes the next valid READY
// connection to receive GO. It is idempotent.
func (g *Gate) Allow() error {
	if err := g.auditFailure(); err != nil {
		return err
	}
	if err := g.verifyProcess(); err != nil {
		g.auditError(err)
		return err
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.closed {
		return ErrGateClosed
	}
	g.allowed = true
	if g.current != nil {
		g.current.signal()
	}
	g.audit(gateAuditEvent{Event: "allow"})
	return g.auditFailure()
}

// WaitReady waits until a peer-authenticated guest sends exactly READY\n.
// It is latched: calls after READY return immediately.
func (g *Gate) WaitReady(ctx context.Context) error {
	if err := g.auditFailure(); err != nil {
		return err
	}
	select {
	case <-g.readyDone:
		if err := g.auditFailure(); err != nil {
			return err
		}
		return nil
	case <-g.closeDone:
		select {
		case <-g.readyDone:
			return nil
		default:
			return ErrGateClosed
		}
	case <-ctx.Done():
		return ctx.Err()
	case <-g.auditDone:
		return g.auditFailure()
	}
}

// WaitResult waits for the first peer-authenticated, strict RESULT JSON line.
// Its returned Body is copied so callers cannot mutate the gate's record.
func (g *Gate) WaitResult(ctx context.Context) (Result, error) {
	if err := g.auditFailure(); err != nil {
		return Result{}, err
	}
	select {
	case <-g.resultDone:
		if err := g.auditFailure(); err != nil {
			return Result{}, err
		}
		g.mu.Lock()
		result := cloneGateResult(g.result)
		g.mu.Unlock()
		return result, nil
	case <-g.closeDone:
		select {
		case <-g.resultDone:
			g.mu.Lock()
			result := cloneGateResult(g.result)
			g.mu.Unlock()
			return result, nil
		default:
			return Result{}, ErrGateClosed
		}
	case <-ctx.Done():
		return Result{}, ctx.Err()
	case <-g.auditDone:
		return Result{}, g.auditFailure()
	}
}

func (g *Gate) serve() {
	defer close(g.serveDone)
	for {
		connection, err := g.listener.AcceptUnix()
		if err != nil {
			if !errors.Is(err, net.ErrClosed) {
				g.auditError(err)
			}
			return
		}
		if !g.addConnection(connection) {
			_ = connection.Close()
			continue
		}
		g.handlers.Add(1)
		go func() {
			defer g.handlers.Done()
			defer g.dropConnection(connection)
			g.handle(connection)
		}()
	}
}

func (g *Gate) addConnection(connection *net.UnixConn) bool {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.closed {
		return false
	}
	g.connections[connection] = struct{}{}
	return true
}

func (g *Gate) dropConnection(connection *net.UnixConn) {
	g.mu.Lock()
	delete(g.connections, connection)
	if g.current != nil && g.current.connection == connection {
		g.current = nil
	}
	g.mu.Unlock()
	_ = connection.Close()
}

func (g *Gate) handle(connection *net.UnixConn) {
	if err := g.auditFailure(); err != nil {
		return
	}
	if err := g.verifyProcess(); err != nil {
		g.auditError(err)
		return
	}
	if err := g.verifyPeer(connection); err != nil {
		g.auditError(err)
		return
	}
	g.audit(gateAuditEvent{Event: "accept", PID: g.config.FirecrackerPID})
	if err := g.auditFailure(); err != nil {
		return
	}
	reader := bufio.NewReader(connection)
	line, err := readGateLine(reader, maxGateLineBytes)
	if err != nil {
		g.auditError(fmt.Errorf("read gate event: %w", err))
		return
	}
	if line == "READY\n" {
		g.handleReady(connection)
		return
	}
	result, err := parseResult(line)
	if err != nil {
		g.auditError(err)
		return
	}
	if err := ensureEOF(reader, connection); err != nil {
		g.auditError(err)
		return
	}
	if err := g.verifyProcess(); err != nil {
		g.auditError(err)
		return
	}
	g.recordResult(result)
}

func (g *Gate) handleReady(connection *net.UnixConn) {
	pending := &gateReady{connection: connection, release: make(chan struct{})}
	g.mu.Lock()
	if g.closed {
		g.mu.Unlock()
		return
	}
	if g.current != nil {
		g.current.signal()
	}
	g.current = pending
	if !g.ready {
		g.ready = true
		g.readyOnce.Do(func() { close(g.readyDone) })
	}
	if g.allowed {
		pending.signal()
	}
	g.mu.Unlock()
	g.audit(gateAuditEvent{Event: "ready"})
	if g.auditFailure() != nil {
		return
	}

	select {
	case <-pending.release:
	case <-g.closeDone:
		return
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.closed || !g.allowed || g.current != pending {
		return
	}
	if err := g.verifyProcess(); err != nil {
		g.auditError(err)
		return
	}
	_ = connection.SetWriteDeadline(time.Now().Add(gateWriteTimeout))
	message := []byte(fmt.Sprintf("GO %d\n", g.config.Generation))
	err := writeGateAll(connection, message)
	_ = connection.SetWriteDeadline(time.Time{})
	if err != nil {
		g.auditError(fmt.Errorf("write gate GO: %w", err))
		return
	}
	g.goSent = true
	g.current = nil
	g.audit(gateAuditEvent{Event: "go", Bytes: len(message)})
}

func (g *Gate) recordResult(result Result) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.closed {
		return
	}
	if !g.goSent {
		g.auditError(errors.New("reject Firecracker gate RESULT before GO"))
		return
	}
	if g.hasResult {
		g.auditError(errors.New("reject duplicate Firecracker gate RESULT"))
		return
	}
	g.result = cloneGateResult(result)
	g.hasResult = true
	g.resultOnce.Do(func() { close(g.resultDone) })
	g.audit(gateAuditEvent{Event: "result", Status: result.Status, Bytes: len(result.Body)})
}

func (g *Gate) verifyPeer(connection *net.UnixConn) error {
	var credential *unix.Ucred
	raw, err := connection.SyscallConn()
	if err != nil {
		return fmt.Errorf("access gate Unix socket: %w", err)
	}
	if err := raw.Control(func(fd uintptr) {
		credential, err = unix.GetsockoptUcred(int(fd), unix.SOL_SOCKET, unix.SO_PEERCRED)
	}); err != nil {
		return fmt.Errorf("read gate Unix peer credentials: %w", err)
	}
	if err != nil || credential == nil {
		return fmt.Errorf("read gate Unix peer credentials: %w", err)
	}
	if int(credential.Pid) != g.config.FirecrackerPID {
		return fmt.Errorf("reject gate peer pid %d, want Firecracker pid %d", credential.Pid, g.config.FirecrackerPID)
	}
	return nil
}

func (g *Gate) verifyProcess() error {
	if g == nil || g.config.VerifyProcess == nil {
		return errors.New("Firecracker gate has no process identity verifier")
	}
	if err := g.config.VerifyProcess(); err != nil {
		return fmt.Errorf("Firecracker gate process identity changed: %w", err)
	}
	return nil
}

func (g *Gate) auditError(err error) {
	if err != nil {
		g.audit(gateAuditEvent{Event: "error", Error: err.Error()})
	}
}

func (g *Gate) audit(event gateAuditEvent) {
	if g.config.AuditLog == nil {
		return
	}
	event.Time = time.Now().UTC()
	event.Generation = g.config.Generation
	event.Port = gatePort
	data, err := json.Marshal(event)
	if err != nil {
		return
	}
	g.logMu.Lock()
	written, err := g.config.AuditLog.Write(append(data, '\n'))
	if err == nil && written != len(data)+1 {
		err = io.ErrShortWrite
	}
	if err != nil && g.auditErr == nil {
		g.auditErr = fmt.Errorf("Firecracker gate audit write: %w", err)
		g.auditOnce.Do(func() { close(g.auditDone) })
	}
	g.logMu.Unlock()
}

func (g *Gate) auditFailure() error {
	g.logMu.Lock()
	defer g.logMu.Unlock()
	return g.auditErr
}

// Close stops accepting, closes the current and partial protocol streams, and
// waits only DrainTimeout for handlers. It removes the UDS only if it still
// names the inode created by this Gate.
func (g *Gate) Close() error {
	g.closeOnce.Do(func() {
		g.mu.Lock()
		g.closed = true
		if g.current != nil {
			g.current.signal()
		}
		connections := make([]*net.UnixConn, 0, len(g.connections))
		for connection := range g.connections {
			connections = append(connections, connection)
		}
		close(g.closeDone)
		g.mu.Unlock()
		listenerErr := g.listener.Close()
		for _, connection := range connections {
			_ = connection.Close()
		}
		<-g.serveDone
		done := make(chan struct{})
		go func() { g.handlers.Wait(); close(done) }()
		select {
		case <-done:
		case <-time.After(g.config.DrainTimeout):
			g.closeErr = errors.Join(g.closeErr, errors.New("Firecracker gate drain timed out"))
		}
		g.closeErr = errors.Join(g.closeErr, ignoreClosed(listenerErr), removeSameSocket(g.socketPath, g.listenerInfo), g.auditFailure())
	})
	return g.closeErr
}

func (r *gateReady) signal() { r.once.Do(func() { close(r.release) }) }

func readGateLine(reader *bufio.Reader, limit int) (string, error) {
	if limit <= 0 {
		return "", errors.New("gate line limit must be positive")
	}
	capacity := 128
	if limit < capacity {
		capacity = limit
	}
	line := make([]byte, 0, capacity)
	for len(line) < limit {
		byteValue, err := reader.ReadByte()
		if err != nil {
			return "", err
		}
		line = append(line, byteValue)
		if byteValue == '\n' {
			return string(line), nil
		}
	}
	return "", errors.New("gate line exceeds limit")
}

func ensureEOF(reader *bufio.Reader, connection *net.UnixConn) error {
	_ = connection.SetReadDeadline(time.Now().Add(gateWriteTimeout))
	defer connection.SetReadDeadline(time.Time{})
	var byteValue [1]byte
	n, err := reader.Read(byteValue[:])
	if n != 0 {
		return errors.New("gate RESULT has trailing data")
	}
	if errors.Is(err, io.EOF) {
		return nil
	}
	if err == nil {
		return errors.New("gate RESULT reader made no progress")
	}
	return fmt.Errorf("wait for end of gate RESULT: %w", err)
}

func parseResult(line string) (Result, error) {
	if !strings.HasSuffix(line, "\n") {
		return Result{}, errors.New("gate RESULT must end in newline")
	}
	decoder := json.NewDecoder(strings.NewReader(strings.TrimSuffix(line, "\n")))
	token, err := decoder.Token()
	if err != nil {
		return Result{}, fmt.Errorf("decode gate RESULT: %w", err)
	}
	if delimiter, ok := token.(json.Delim); !ok || delimiter != '{' {
		return Result{}, errors.New("gate RESULT must be a JSON object")
	}
	var result Result
	seen := make(map[string]bool, 3)
	for decoder.More() {
		token, err := decoder.Token()
		if err != nil {
			return Result{}, fmt.Errorf("decode gate RESULT key: %w", err)
		}
		key, ok := token.(string)
		if !ok || seen[key] || (key != "event" && key != "status" && key != "body") {
			return Result{}, errors.New("gate RESULT must contain exactly event, status, and body")
		}
		seen[key] = true
		switch key {
		case "event":
			err = decoder.Decode(&result.Event)
		case "status":
			err = decoder.Decode(&result.Status)
		case "body":
			err = decoder.Decode(&result.Body)
		}
		if err != nil {
			return Result{}, fmt.Errorf("decode gate RESULT %s: %w", key, err)
		}
	}
	token, err = decoder.Token()
	if err != nil {
		return Result{}, fmt.Errorf("close gate RESULT object: %w", err)
	}
	if delimiter, ok := token.(json.Delim); !ok || delimiter != '}' || len(seen) != 3 {
		return Result{}, errors.New("gate RESULT must contain exactly event, status, and body")
	}
	if _, err := decoder.Token(); !errors.Is(err, io.EOF) {
		return Result{}, errors.New("gate RESULT has trailing JSON")
	}
	if result.Event != "RESULT" || result.Status < 100 || result.Status > 599 || len(result.Body) == 0 || !json.Valid(result.Body) {
		return Result{}, errors.New("gate RESULT must contain event RESULT, an HTTP status, and a JSON body")
	}
	return result, nil
}

func cloneGateResult(result Result) Result {
	result.Body = append(json.RawMessage(nil), result.Body...)
	return result
}

func writeGateAll(writer io.Writer, data []byte) error {
	for len(data) > 0 {
		n, err := writer.Write(data)
		if err != nil {
			return err
		}
		if n <= 0 || n > len(data) {
			return io.ErrShortWrite
		}
		data = data[n:]
	}
	return nil
}
