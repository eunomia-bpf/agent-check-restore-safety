//go:build linux

package agentguest

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"sync"
	"syscall"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentstream"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentwire"
)

const (
	maxSessionLineBytes = uint64(16 << 20)
	maxSessionLines     = uint64(65536)
	maxSessionBytes     = uint64(64 << 20)
	initialDialBackoff  = 10 * time.Millisecond
	maximumDialBackoff  = 100 * time.Millisecond
)

func sessionTranscriptLimits() agentstream.Limits {
	return agentstream.Limits{
		MaxLineBytes: maxSessionLineBytes,
		MaxLines:     maxSessionLines,
		MaxBytes:     maxSessionBytes,
	}
}

// RunSession carries the unmodified Codex App Server JSONL streams over a
// reconnectable host stream. Transcript state belongs to the VM and therefore
// survives a whole-VM snapshot; transport connections do not.
func RunSession(
	ctx context.Context,
	config Config,
	codexStdin io.Writer,
	codexStdout io.Reader,
	dial func(uint32) (Stream, error),
	logger *log.Logger,
) error {
	if ctx == nil {
		return errors.New("agent guest session context is nil")
	}
	if err := config.Validate(); err != nil {
		return err
	}
	if codexStdin == nil || codexStdout == nil || dial == nil || logger == nil {
		return errors.New("agent guest session requires Codex stdio, a dialer, and a logger")
	}
	transcript, err := agentstream.New(agentstream.Guest, config.SessionID, 1, sessionTranscriptLimits())
	if err != nil {
		return fmt.Errorf("create agent guest transcript: %w", err)
	}

	runContext, cancel := context.WithCancel(ctx)
	session := &guestSession{
		parentContext: ctx,
		ctx:           runContext,
		cancel:        cancel,
		config:        config,
		codexStdin:    codexStdin,
		codexStdout:   codexStdout,
		dial:          dial,
		logger:        logger,
		transcript:    transcript,
		generation:    1,
		changed:       make(chan struct{}),
	}
	defer cancel()
	defer session.closeActive()

	go session.readCodexStdout()
	go func() {
		<-runContext.Done()
		session.closeActive()
	}()

	return session.run()
}

type guestSession struct {
	parentContext context.Context
	ctx           context.Context
	cancel        context.CancelFunc
	config        Config
	codexStdin    io.Writer
	codexStdout   io.Reader
	dial          func(uint32) (Stream, error)
	logger        *log.Logger
	transcript    *agentstream.Transcript

	mu               sync.Mutex
	changed          chan struct{}
	generation       uint64
	handshaking      bool
	frozen           bool
	haveBarrier      bool
	guestBarrier     agentstream.Barrier
	hostBarrier      agentstream.Barrier
	ready            bool
	connection       *sessionConnection
	connectionWriter *agentwire.Writer
	pendingHello     agentstream.Hello
	lastAdvance      *sessionAdvance

	activeMu sync.Mutex
	active   *sessionConnection

	fatalOnce sync.Once
	fatalMu   sync.Mutex
	fatalErr  error
}

type sessionAdvance struct {
	generation   uint64
	guestBarrier agentstream.Barrier
	hostBarrier  agentstream.Barrier
}

type sessionConnection struct {
	Stream
	closeOnce sync.Once
	closeErr  error
}

func (connection *sessionConnection) Close() error {
	connection.closeOnce.Do(func() {
		connection.closeErr = connection.Stream.Close()
	})
	return connection.closeErr
}

type reconnectError struct {
	err error
}

func (failure reconnectError) Error() string { return failure.err.Error() }
func (failure reconnectError) Unwrap() error { return failure.err }

func (session *guestSession) run() error {
	backoff := initialDialBackoff
	for {
		if err := session.terminationError(); err != nil {
			return err
		}
		stream, err := session.dialOnce()
		if err != nil {
			if stream != nil {
				_ = stream.Close()
			}
			if err := session.terminationError(); err != nil {
				return err
			}
			session.logger.Printf("agent stream dial failed: %v", err)
			if err := session.waitBackoff(backoff); err != nil {
				return err
			}
			backoff = nextBackoff(backoff)
			continue
		}
		if stream == nil {
			return errors.New("agent stream dialer returned a nil stream")
		}
		connection := &sessionConnection{Stream: stream}
		if err := session.installActive(connection); err != nil {
			_ = connection.Close()
			return err
		}

		err = session.runConnection(connection)
		session.removeActive(connection)
		_ = connection.Close()
		session.releaseConnection(connection)
		if termination := session.terminationError(); termination != nil {
			return termination
		}
		var reconnect reconnectError
		if !errors.As(err, &reconnect) {
			return err
		}
		session.logger.Printf("agent stream disconnected: %v", reconnect.err)
		if err := session.waitBackoff(backoff); err != nil {
			return err
		}
		backoff = nextBackoff(backoff)
	}
}

func (session *guestSession) dialOnce() (Stream, error) {
	type dialResult struct {
		stream Stream
		err    error
	}
	result := make(chan dialResult)
	go func() {
		stream, err := session.dial(session.config.StreamPort)
		select {
		case result <- dialResult{stream: stream, err: err}:
		case <-session.ctx.Done():
			if stream != nil {
				_ = stream.Close()
			}
		}
	}()
	select {
	case <-session.ctx.Done():
		return nil, session.terminationError()
	case outcome := <-result:
		return outcome.stream, outcome.err
	}
}

func (session *guestSession) runConnection(connection *sessionConnection) error {
	reader, err := agentwire.NewReader(sessionTransportReader{reader: connection})
	if err != nil {
		return fmt.Errorf("create agent stream reader: %w", err)
	}
	writer, err := agentwire.NewWriter(connection)
	if err != nil {
		return fmt.Errorf("create agent stream writer: %w", err)
	}

	first, err := session.readWire(reader, "read connection role")
	if err != nil {
		return err
	}
	if err := session.beginHandshake(connection, writer, first); err != nil {
		return err
	}
	attachMessage, err := session.readWire(reader, "read host attach")
	if err != nil {
		return err
	}
	if attachMessage.Type != agentwire.TypeAttach || attachMessage.Attach == nil {
		return fmt.Errorf("agent stream protocol: expected attach, got %q", attachMessage.Type)
	}
	if err := session.finishHandshake(connection, writer, *attachMessage.Attach); err != nil {
		return err
	}

	for {
		message, err := session.readWire(reader, "read established message")
		if err != nil {
			return err
		}
		switch message.Type {
		case agentwire.TypeFrame:
			if err := session.receiveHostFrame(connection, *message.Frame); err != nil {
				return err
			}
		case agentwire.TypeBarrier:
			if err := session.receiveBarrier(connection, writer, *message.Barrier); err != nil {
				return err
			}
		default:
			return fmt.Errorf("agent stream protocol: unexpected established message %q", message.Type)
		}
	}
}

func (session *guestSession) beginHandshake(connection *sessionConnection, writer *agentwire.Writer, first agentwire.Message) error {
	session.mu.Lock()
	defer session.mu.Unlock()
	if err := session.terminationError(); err != nil {
		return err
	}
	session.handshaking = true
	session.ready = false
	session.connection = connection
	session.connectionWriter = nil
	session.notifyLocked()

	switch first.Type {
	case agentwire.TypeRole:
		if first.Generation != session.generation {
			return fmt.Errorf("agent stream protocol: role generation %d, require %d", first.Generation, session.generation)
		}
	case agentwire.TypeAdvance:
		if session.lastAdvance != nil && first.Generation == session.generation {
			if first.Generation != session.lastAdvance.generation ||
				*first.GuestBarrier != session.lastAdvance.guestBarrier ||
				*first.HostBarrier != session.lastAdvance.hostBarrier {
				return errors.New("agent stream protocol: repeated advance differs from the accepted proof")
			}
			break
		}
		if !session.frozen || !session.haveBarrier {
			return errors.New("agent stream protocol: advance without a successful frozen barrier")
		}
		if *first.GuestBarrier != session.guestBarrier || *first.HostBarrier != session.hostBarrier {
			return errors.New("agent stream protocol: advance barriers differ from the frozen barrier")
		}
		if err := session.transcript.AdvanceGeneration(first.Generation, session.guestBarrier, session.hostBarrier); err != nil {
			return fmt.Errorf("agent stream protocol: advance generation: %w", err)
		}
		session.generation = first.Generation
		session.lastAdvance = &sessionAdvance{
			generation: first.Generation, guestBarrier: session.guestBarrier, hostBarrier: session.hostBarrier,
		}
		session.frozen = false
		session.haveBarrier = false
		session.guestBarrier = agentstream.Barrier{}
		session.hostBarrier = agentstream.Barrier{}
		session.notifyLocked()
	default:
		return fmt.Errorf("agent stream protocol: connection must begin with role or advance, got %q", first.Type)
	}

	hello, err := session.transcript.Hello()
	if err != nil {
		return fmt.Errorf("create guest hello: %w", err)
	}
	if err := writer.Write(agentwire.Message{Type: agentwire.TypeHello, Hello: &hello}); err != nil {
		return session.classifyWrite("write guest hello", err)
	}
	session.pendingHello = hello
	return nil
}

func (session *guestSession) finishHandshake(connection *sessionConnection, writer *agentwire.Writer, attach agentstream.Attach) error {
	session.mu.Lock()
	defer session.mu.Unlock()
	if err := session.terminationError(); err != nil {
		return err
	}
	if !session.handshaking || session.connection != connection {
		return errors.New("agent stream protocol: attach does not belong to the active handshake")
	}
	hello := session.pendingHello
	if hello.SessionID == "" {
		return errors.New("agent stream protocol: active handshake has no recorded hello")
	}
	if session.frozen {
		if !session.haveBarrier || hello.State != session.guestBarrier.State || attach.State != session.hostBarrier.State {
			return errors.New("agent stream protocol: frozen reconnect differs from the acknowledged barrier")
		}
	}
	if err := session.transcript.AcceptAttach(hello, attach); err != nil {
		return fmt.Errorf("agent stream protocol: reject host attach: %w", err)
	}
	missing, err := session.transcript.Resend(attach.State.GuestToHost)
	if err != nil {
		return fmt.Errorf("agent stream protocol: compute guest resend suffix: %w", err)
	}
	for index := range missing {
		frame := missing[index]
		if err := writer.Write(agentwire.Message{Type: agentwire.TypeFrame, Frame: &frame}); err != nil {
			return session.classifyWrite("write guest resend suffix", err)
		}
	}
	session.connection = connection
	session.connectionWriter = writer
	session.ready = true
	session.handshaking = false
	session.pendingHello = agentstream.Hello{}
	session.notifyLocked()
	return nil
}

func (session *guestSession) receiveHostFrame(connection *sessionConnection, frame agentstream.Frame) error {
	session.mu.Lock()
	defer session.mu.Unlock()
	if err := session.terminationError(); err != nil {
		return err
	}
	if !session.ready || session.connection != connection {
		return errors.New("agent stream protocol: frame arrived outside the active connection")
	}
	if session.frozen {
		return errors.New("agent stream protocol: frame arrived while transcript is frozen")
	}
	result, err := session.transcript.Receive(frame)
	if err != nil {
		return fmt.Errorf("agent stream protocol: reject host frame: %w", err)
	}
	if result == agentstream.Duplicate {
		return nil
	}
	line := make([]byte, len(frame.Line)+1)
	copy(line, frame.Line)
	line[len(line)-1] = '\n'
	if err := writeSessionAll(session.codexStdin, line); err != nil {
		return fmt.Errorf("write Codex stdin: %w", err)
	}
	return nil
}

func (session *guestSession) receiveBarrier(connection *sessionConnection, writer *agentwire.Writer, hostBarrier agentstream.Barrier) error {
	session.mu.Lock()
	defer session.mu.Unlock()
	if err := session.terminationError(); err != nil {
		return err
	}
	if !session.ready || session.connection != connection {
		return errors.New("agent stream protocol: barrier arrived outside the active connection")
	}

	if session.frozen {
		if !session.haveBarrier || hostBarrier != session.hostBarrier {
			return errors.New("agent stream protocol: frozen barrier differs from the acknowledged barrier")
		}
		quiescent, err := session.transcript.Quiescent(session.guestBarrier, hostBarrier)
		if err != nil {
			return fmt.Errorf("agent stream protocol: revalidate frozen barrier: %w", err)
		}
		if !quiescent {
			return errors.New("agent stream protocol: acknowledged barrier is no longer quiescent")
		}
		ack := session.guestBarrier
		if err := writer.Write(agentwire.Message{Type: agentwire.TypeBarrierAck, Barrier: &ack}); err != nil {
			return session.classifyWrite("repeat guest barrier acknowledgement", err)
		}
		return nil
	}

	session.frozen = true
	session.notifyLocked()
	guestBarrier := session.transcript.Barrier()
	quiescent, err := session.transcript.Quiescent(guestBarrier, hostBarrier)
	if err != nil {
		return fmt.Errorf("agent stream protocol: validate host barrier: %w", err)
	}
	if !quiescent {
		return errors.New("agent stream protocol: host barrier is not quiescent")
	}
	session.haveBarrier = true
	session.guestBarrier = guestBarrier
	session.hostBarrier = hostBarrier
	ack := guestBarrier
	if err := writer.Write(agentwire.Message{Type: agentwire.TypeBarrierAck, Barrier: &ack}); err != nil {
		return session.classifyWrite("write guest barrier acknowledgement", err)
	}
	return nil
}

func (session *guestSession) readCodexStdout() {
	reader := bufio.NewReaderSize(session.codexStdout, 64<<10)
	for {
		line, err := readCodexLine(reader, maxSessionLineBytes)
		if err != nil {
			if session.ctx.Err() != nil {
				return
			}
			session.fail(fmt.Errorf("read Codex stdout: %w", err))
			return
		}
		if err := session.sendCodexLine(line); err != nil {
			if session.ctx.Err() != nil {
				return
			}
			session.fail(err)
			return
		}
	}
}

func (session *guestSession) sendCodexLine(line []byte) error {
	for {
		session.mu.Lock()
		if err := session.terminationError(); err != nil {
			session.mu.Unlock()
			return err
		}
		if session.handshaking || session.frozen {
			changed := session.changed
			session.mu.Unlock()
			select {
			case <-session.ctx.Done():
				return session.terminationError()
			case <-changed:
				continue
			}
		}

		frame, err := session.transcript.Send(line)
		if err != nil {
			session.mu.Unlock()
			return fmt.Errorf("record Codex stdout: %w", err)
		}
		connection := session.connection
		if !session.ready || connection == nil || session.connectionWriter == nil {
			session.mu.Unlock()
			return nil
		}
		writer := session.connectionWriter
		err = writer.Write(agentwire.Message{Type: agentwire.TypeFrame, Frame: &frame})
		if err == nil {
			session.mu.Unlock()
			return nil
		}
		session.ready = false
		session.connectionWriter = nil
		session.notifyLocked()
		session.mu.Unlock()
		if classified := session.classifyWrite("write Codex stdout frame", err); !isReconnect(classified) {
			return classified
		}
		session.logger.Printf("agent stream output write failed: %v", err)
		session.removeActive(connection)
		_ = connection.Close()
		return nil
	}
}

func (session *guestSession) releaseConnection(connection *sessionConnection) {
	session.mu.Lock()
	defer session.mu.Unlock()
	if session.connection != connection {
		return
	}
	session.ready = false
	session.connection = nil
	session.connectionWriter = nil
	if session.handshaking {
		session.handshaking = false
	}
	session.pendingHello = agentstream.Hello{}
	session.notifyLocked()
}

func (session *guestSession) installActive(connection *sessionConnection) error {
	session.activeMu.Lock()
	defer session.activeMu.Unlock()
	if err := session.terminationError(); err != nil {
		return err
	}
	if session.active != nil {
		return errors.New("agent guest session already has an active connection")
	}
	session.active = connection
	return nil
}

func (session *guestSession) removeActive(connection *sessionConnection) {
	session.activeMu.Lock()
	defer session.activeMu.Unlock()
	if session.active == connection {
		session.active = nil
	}
}

func (session *guestSession) closeActive() {
	session.activeMu.Lock()
	connection := session.active
	session.active = nil
	session.activeMu.Unlock()
	if connection != nil {
		_ = connection.Close()
	}
}

func (session *guestSession) readWire(reader *agentwire.Reader, operation string) (agentwire.Message, error) {
	message, err := reader.Read()
	if err == nil {
		return message, nil
	}
	if termination := session.terminationError(); termination != nil {
		return agentwire.Message{}, termination
	}
	if isTransportError(err) {
		return agentwire.Message{}, reconnectError{err: fmt.Errorf("%s: %w", operation, err)}
	}
	return agentwire.Message{}, fmt.Errorf("agent stream protocol: %s: %w", operation, err)
}

func (session *guestSession) classifyWrite(operation string, err error) error {
	if termination := session.terminationError(); termination != nil {
		return termination
	}
	if errors.Is(err, io.EOF) || isTransportError(err) {
		return reconnectError{err: fmt.Errorf("%s: %w", operation, err)}
	}
	return fmt.Errorf("agent stream protocol: %s: %w", operation, err)
}

func (session *guestSession) waitBackoff(delay time.Duration) error {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-session.ctx.Done():
		return session.terminationError()
	case <-timer.C:
		return nil
	}
}

func (session *guestSession) notifyLocked() {
	close(session.changed)
	session.changed = make(chan struct{})
}

func (session *guestSession) fail(err error) {
	if err == nil {
		return
	}
	session.fatalOnce.Do(func() {
		session.fatalMu.Lock()
		session.fatalErr = err
		session.fatalMu.Unlock()
		session.cancel()
	})
}

func (session *guestSession) terminationError() error {
	session.fatalMu.Lock()
	fatal := session.fatalErr
	session.fatalMu.Unlock()
	if fatal != nil {
		return fatal
	}
	if err := session.parentContext.Err(); err != nil {
		return err
	}
	if err := session.ctx.Err(); err != nil {
		return err
	}
	return nil
}

func readCodexLine(reader *bufio.Reader, limit uint64) ([]byte, error) {
	var line []byte
	for {
		fragment, err := reader.ReadSlice('\n')
		terminated := err == nil
		payload := fragment
		if terminated {
			payload = fragment[:len(fragment)-1]
		}
		if uint64(len(payload)) > limit || uint64(len(line)) > limit-uint64(len(payload)) {
			return nil, fmt.Errorf("Codex stdout line exceeds %d bytes", limit)
		}
		line = append(line, payload...)
		if terminated {
			return line, nil
		}
		if errors.Is(err, bufio.ErrBufferFull) {
			continue
		}
		if errors.Is(err, io.EOF) && len(line) != 0 {
			return nil, io.ErrUnexpectedEOF
		}
		return nil, err
	}
}

func writeSessionAll(writer io.Writer, data []byte) error {
	for len(data) != 0 {
		written, err := writer.Write(data)
		if err != nil {
			return err
		}
		if written <= 0 || written > len(data) {
			return io.ErrShortWrite
		}
		data = data[written:]
	}
	return nil
}

// sessionTransportReader preserves the origin of an error from the socket.
// The JSON decoder also uses io.EOF to report a complete but truncated JSON
// value, which is a terminal protocol error rather than a reconnect signal.
type sessionTransportReader struct {
	reader io.Reader
}

func (reader sessionTransportReader) Read(data []byte) (int, error) {
	count, err := reader.reader.Read(data)
	if err != nil {
		return count, sessionTransportError{err: err}
	}
	return count, nil
}

type sessionTransportError struct {
	err error
}

func (failure sessionTransportError) Error() string { return failure.err.Error() }
func (failure sessionTransportError) Unwrap() error { return failure.err }

func isTransportError(err error) bool {
	if err == nil {
		return false
	}
	var transport sessionTransportError
	if errors.As(err, &transport) {
		return true
	}
	// Decoder EOF is deliberately absent here. Only errors carrying the
	// sessionTransportError marker came from the socket; treating decoder EOF as
	// transport loss would turn malformed protocol into a retry loop.
	if errors.Is(err, io.ErrClosedPipe) || errors.Is(err, io.ErrShortWrite) || errors.Is(err, net.ErrClosed) || errors.Is(err, os.ErrDeadlineExceeded) {
		return true
	}
	for _, target := range []error{syscall.ECONNRESET, syscall.ECONNABORTED, syscall.EPIPE, syscall.ENOTCONN, syscall.ETIMEDOUT} {
		if errors.Is(err, target) {
			return true
		}
	}
	var networkError net.Error
	return errors.As(err, &networkError)
}

func isReconnect(err error) bool {
	var reconnect reconnectError
	return errors.As(err, &reconnect)
}

func nextBackoff(current time.Duration) time.Duration {
	next := current * 2
	if next > maximumDialBackoff {
		return maximumDialBackoff
	}
	return next
}
