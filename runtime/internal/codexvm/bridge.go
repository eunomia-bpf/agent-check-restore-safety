package codexvm

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"path/filepath"
	"strings"
	"sync"
	"syscall"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentstream"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentwire"
)

var ErrDisconnected = errors.New("Codex VM stream disconnected")
var ErrIncompleteSession = errors.New("Codex client input ended before the protected turn completed")

const (
	DirectionClientToServer = "client_to_server"
	DirectionServerToClient = "server_to_client"
	PhaseObserved           = "observed"
	PhaseAuthorized         = "authorized"
	PhaseDelivered          = "delivered"
)

// IOAudit synchronously commits one client-visible App Server JSON object.
// Returning an error fails the run closed.
type IOAudit func(phase, direction string, line []byte) error

var bridgeLimits = agentstream.Limits{
	MaxLineBytes: 16 << 20,
	MaxLines:     65536,
	MaxBytes:     64 << 20,
}

// Checkpoint is the transport proof required to move a snapshotted guest to a
// new VM generation.
type Checkpoint struct {
	HostBarrier  agentstream.Barrier
	GuestBarrier agentstream.Barrier
}

type activeConnection struct {
	generation uint64
	writer     *agentwire.Writer
	closer     io.Closer
}

type protectedCall struct {
	requestID string
	threadID  string
	turnID    string
	callID    string
}

// Bridge preserves the ordinary Codex JSONL process contract while retaining
// enough transcript state to reconnect the guest after a whole-VM restore.
type Bridge struct {
	transcript     *agentstream.Transcript
	input          io.Reader
	output         io.Writer
	logger         *log.Logger
	hostWorkspace  string
	guestWorkspace string
	audit          IOAudit

	mu                 sync.Mutex
	condition          *sync.Cond
	generation         uint64
	active             *activeConnection
	frozen             bool
	checkpoint         *Checkpoint
	advance            *Checkpoint
	pending            []byte
	barrier            *agentstream.Barrier
	releasing          bool
	released           bool
	closed             bool
	failure            error
	protected          *protectedCall
	responseAccepted   bool
	terminalPending    bool
	terminalDelivered  bool
	inputEOF           bool
	attachedGeneration uint64
	attachedChanged    chan struct{}

	quiescent     chan Checkpoint
	inputDone     chan struct{}
	failed        chan struct{}
	completed     chan struct{}
	failOnce      sync.Once
	completeOnce  sync.Once
	outputMu      sync.Mutex
	outputCond    *sync.Cond
	outputIssued  uint64
	outputNext    uint64
	outputFailure error
}

func NewBridge(sessionID string, input io.Reader, output io.Writer, logger *log.Logger) (*Bridge, error) {
	return newBridge(sessionID, input, output, logger, "", "", nil)
}

// NewWorkspaceBridge maps the caller's exact empty host workspace to the
// fixed in-guest workspace in thread/start requests. No other App Server
// request or response is rewritten.
func NewWorkspaceBridge(sessionID string, input io.Reader, output io.Writer, logger *log.Logger, hostWorkspace, guestWorkspace string) (*Bridge, error) {
	if !filepath.IsAbs(hostWorkspace) || filepath.Clean(hostWorkspace) != hostWorkspace ||
		!filepath.IsAbs(guestWorkspace) || filepath.Clean(guestWorkspace) != guestWorkspace {
		return nil, errors.New("Codex VM workspace mapping requires absolute canonical paths")
	}
	return newBridge(sessionID, input, output, logger, hostWorkspace, guestWorkspace, nil)
}

// NewAuditedWorkspaceBridge is NewWorkspaceBridge with a mandatory durable
// client-visible I/O commitment used to bind runtime and adapter evidence.
func NewAuditedWorkspaceBridge(sessionID string, input io.Reader, output io.Writer, logger *log.Logger, hostWorkspace, guestWorkspace string, audit IOAudit) (*Bridge, error) {
	if audit == nil {
		return nil, errors.New("Codex VM audited workspace bridge requires an I/O audit")
	}
	if !filepath.IsAbs(hostWorkspace) || filepath.Clean(hostWorkspace) != hostWorkspace ||
		!filepath.IsAbs(guestWorkspace) || filepath.Clean(guestWorkspace) != guestWorkspace {
		return nil, errors.New("Codex VM workspace mapping requires absolute canonical paths")
	}
	return newBridge(sessionID, input, output, logger, hostWorkspace, guestWorkspace, audit)
}

func newBridge(sessionID string, input io.Reader, output io.Writer, logger *log.Logger, hostWorkspace, guestWorkspace string, audit IOAudit) (*Bridge, error) {
	if input == nil || output == nil || logger == nil {
		return nil, errors.New("Codex VM bridge requires input, output, and logger")
	}
	transcript, err := agentstream.New(agentstream.Host, sessionID, 1, bridgeLimits)
	if err != nil {
		return nil, err
	}
	bridge := &Bridge{
		transcript: transcript, input: input, output: output, logger: logger,
		hostWorkspace: hostWorkspace, guestWorkspace: guestWorkspace, audit: audit,
		generation: 1, quiescent: make(chan Checkpoint, 1), attachedChanged: make(chan struct{}),
		inputDone: make(chan struct{}), failed: make(chan struct{}), completed: make(chan struct{}),
	}
	bridge.condition = sync.NewCond(&bridge.mu)
	bridge.outputCond = sync.NewCond(&bridge.outputMu)
	return bridge, nil
}

// StartInput begins the one host-to-guest JSONL producer. It returns
// immediately; failures are reported through Failure and the supplied
// context closes the current transport.
func (bridge *Bridge) StartInput(ctx context.Context) {
	go bridge.scanInput(ctx)
	go func() {
		<-ctx.Done()
		bridge.mu.Lock()
		bridge.closed = true
		if bridge.active != nil {
			_ = bridge.active.closer.Close()
		}
		bridge.condition.Broadcast()
		bridge.mu.Unlock()
	}()
}

func (bridge *Bridge) scanInput(ctx context.Context) {
	defer close(bridge.inputDone)
	reader := bufio.NewReaderSize(bridge.input, 64<<10)
	for {
		line, readErr := readBridgeLine(reader, bridgeLimits.MaxLineBytes)
		if readErr != nil {
			if errors.Is(readErr, io.EOF) {
				if ctx.Err() == nil {
					bridge.handleInputEOF()
				}
				return
			}
			bridge.fail(fmt.Errorf("read host Codex JSONL input: %w", readErr))
			return
		}
		if bridge.audit != nil {
			if err := bridge.audit(PhaseObserved, DirectionClientToServer, line); err != nil {
				bridge.fail(fmt.Errorf("commit client-to-server Codex I/O: %w", err))
				return
			}
		}
		if bridge.hostWorkspace != "" {
			var err error
			line, err = mapThreadStartWorkspace(line, bridge.hostWorkspace, bridge.guestWorkspace)
			if err != nil {
				bridge.fail(fmt.Errorf("map Codex workspace into guest: %w", err))
				return
			}
		}
		bridge.mu.Lock()
		for bridge.frozen && !bridge.closed && bridge.failure == nil {
			bridge.condition.Wait()
		}
		if bridge.closed || bridge.failure != nil {
			bridge.mu.Unlock()
			return
		}
		frame, sendErr := bridge.transcript.Send(line)
		responseAccepted := false
		if sendErr == nil && bridge.protected != nil && !bridge.responseAccepted {
			responseAccepted, sendErr = matchesProtectedResponse(line, bridge.protected)
		}
		if sendErr == nil && bridge.active != nil {
			if writeErr := bridge.active.writer.Write(agentwire.Message{Type: agentwire.TypeFrame, Frame: &frame}); writeErr != nil {
				_ = bridge.active.closer.Close()
				bridge.active = nil
			}
		}
		if sendErr == nil && responseAccepted {
			bridge.responseAccepted = true
		}
		bridge.mu.Unlock()
		if sendErr != nil {
			bridge.fail(fmt.Errorf("record Codex input for guest: %w", sendErr))
			return
		}
	}
}

// WaitInput waits until the single host input producer has exited, after which
// it can no longer invoke the I/O audit callback.
func (bridge *Bridge) WaitInput(ctx context.Context) error {
	if ctx == nil {
		return errors.New("Codex VM input wait context is nil")
	}
	select {
	case <-bridge.inputDone:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func readBridgeLine(reader *bufio.Reader, limit uint64) ([]byte, error) {
	if reader == nil || limit == 0 {
		return nil, errors.New("Codex VM input reader and line limit are required")
	}
	var line []byte
	for {
		fragment, err := reader.ReadSlice('\n')
		terminated := err == nil
		payload := fragment
		if terminated {
			payload = fragment[:len(fragment)-1]
		}
		if uint64(len(payload)) > limit || uint64(len(line)) > limit-uint64(len(payload)) {
			return nil, fmt.Errorf("host Codex JSONL line exceeds %d bytes", limit)
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

func mapThreadStartWorkspace(line []byte, hostWorkspace, guestWorkspace string) ([]byte, error) {
	envelope, err := decodeRawObject(line, "App Server request")
	if err != nil {
		return nil, err
	}
	methodRaw, present := envelope["method"]
	if !present {
		return bytes.Clone(line), nil
	}
	var method string
	if err := json.Unmarshal(methodRaw, &method); err != nil {
		return nil, errors.New("App Server request method is not a string")
	}
	if method != "thread/start" {
		return bytes.Clone(line), nil
	}
	paramsRaw, present := envelope["params"]
	if !present {
		return nil, errors.New("thread/start request omits params")
	}
	params, err := decodeRawObject(paramsRaw, "thread/start params")
	if err != nil {
		return nil, err
	}
	cwdRaw, present := params["cwd"]
	if !present {
		return nil, errors.New("thread/start request omits cwd")
	}
	var cwd string
	if err := json.Unmarshal(cwdRaw, &cwd); err != nil {
		return nil, errors.New("thread/start cwd is not a string")
	}
	if cwd != hostWorkspace {
		return nil, fmt.Errorf("thread/start cwd %q differs from fixed host workspace %q", cwd, hostWorkspace)
	}
	mapped, err := json.Marshal(guestWorkspace)
	if err != nil {
		return nil, err
	}
	params["cwd"] = mapped
	mappedParams, err := json.Marshal(params)
	if err != nil {
		return nil, fmt.Errorf("encode mapped thread/start params: %w", err)
	}
	envelope["params"] = mappedParams
	mappedLine, err := json.Marshal(envelope)
	if err != nil {
		return nil, fmt.Errorf("encode mapped thread/start request: %w", err)
	}
	return mappedLine, nil
}

func decodeRawObject(data []byte, label string) (map[string]json.RawMessage, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	first, err := decoder.Token()
	if err != nil {
		return nil, fmt.Errorf("decode %s: %w", label, err)
	}
	if delimiter, ok := first.(json.Delim); !ok || delimiter != '{' {
		return nil, fmt.Errorf("%s is not one JSON object", label)
	}
	result := make(map[string]json.RawMessage)
	for decoder.More() {
		nameToken, err := decoder.Token()
		if err != nil {
			return nil, fmt.Errorf("decode %s field: %w", label, err)
		}
		name, ok := nameToken.(string)
		if !ok {
			return nil, fmt.Errorf("%s has a non-string field name", label)
		}
		if _, duplicate := result[name]; duplicate {
			return nil, fmt.Errorf("%s repeats field %q", label, name)
		}
		var value json.RawMessage
		if err := decoder.Decode(&value); err != nil {
			return nil, fmt.Errorf("decode %s field %q: %w", label, name, err)
		}
		result[name] = value
	}
	last, err := decoder.Token()
	if err != nil {
		return nil, fmt.Errorf("close %s: %w", label, err)
	}
	if delimiter, ok := last.(json.Delim); !ok || delimiter != '}' {
		return nil, fmt.Errorf("%s object is not closed", label)
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return nil, fmt.Errorf("%s has trailing value %v", label, token)
		}
		return nil, fmt.Errorf("%s has trailing data: %w", label, err)
	}
	return result, nil
}

// ServeConnection performs one attach and then receives frames until the
// connection resets or the context ends. The caller authenticates the
// Firecracker peer before passing the stream here.
func (bridge *Bridge) ServeConnection(ctx context.Context, connection io.ReadWriteCloser) error {
	if connection == nil {
		return errors.New("Codex VM bridge connection is nil")
	}
	defer connection.Close()
	stopContextClose := make(chan struct{})
	defer close(stopContextClose)
	go func() {
		select {
		case <-ctx.Done():
			_ = connection.Close()
		case <-stopContextClose:
		}
	}()
	reader, err := agentwire.NewReader(connection)
	if err != nil {
		return err
	}
	writer, err := agentwire.NewWriter(connection)
	if err != nil {
		return err
	}

	bridge.mu.Lock()
	if bridge.closed || bridge.failure != nil {
		bridge.mu.Unlock()
		return errors.New("Codex VM bridge is closed")
	}
	generation := bridge.generation
	if generation == 1 {
		err = writer.Write(agentwire.Message{Type: agentwire.TypeRole, Generation: generation})
	} else if bridge.advance != nil {
		host, guest := bridge.advance.HostBarrier, bridge.advance.GuestBarrier
		err = writer.Write(agentwire.Message{
			Type: agentwire.TypeAdvance, Generation: generation,
			HostBarrier: &host, GuestBarrier: &guest,
		})
	} else {
		err = errors.New("restored Codex VM connection lacks an advance proof")
	}
	if err != nil {
		bridge.mu.Unlock()
		return err
	}
	message, err := reader.Read()
	if err != nil {
		bridge.mu.Unlock()
		return connectionResult(ctx, err)
	}
	if message.Type != agentwire.TypeHello || message.Hello == nil {
		bridge.mu.Unlock()
		return errors.New("Codex VM guest did not begin with Hello")
	}
	attach, err := bridge.transcript.Attach(*message.Hello)
	if err != nil {
		bridge.mu.Unlock()
		return fmt.Errorf("attach Codex VM guest: %w", err)
	}
	if err := writer.Write(agentwire.Message{Type: agentwire.TypeAttach, Attach: &attach}); err != nil {
		bridge.mu.Unlock()
		return connectionResult(ctx, err)
	}
	missing, err := bridge.transcript.Resend(message.Hello.State.HostToGuest)
	if err != nil {
		bridge.mu.Unlock()
		return fmt.Errorf("reconcile Codex VM input: %w", err)
	}
	for index := range missing {
		frame := missing[index]
		if err := writer.Write(agentwire.Message{Type: agentwire.TypeFrame, Frame: &frame}); err != nil {
			bridge.mu.Unlock()
			return connectionResult(ctx, err)
		}
	}
	active := &activeConnection{generation: generation, writer: writer, closer: connection}
	if bridge.active != nil {
		_ = bridge.active.closer.Close()
	}
	bridge.active = active
	if generation > bridge.attachedGeneration {
		bridge.attachedGeneration = generation
		close(bridge.attachedChanged)
		bridge.attachedChanged = make(chan struct{})
	}
	var awaiting *agentstream.Barrier
	if bridge.barrier != nil {
		barrier := *bridge.barrier
		if err := writer.Write(agentwire.Message{Type: agentwire.TypeBarrier, Barrier: &barrier}); err != nil {
			bridge.active = nil
			bridge.mu.Unlock()
			return connectionResult(ctx, err)
		}
		awaiting = &barrier
	}
	bridge.mu.Unlock()

	defer func() {
		bridge.mu.Lock()
		if bridge.active == active {
			bridge.active = nil
		}
		bridge.mu.Unlock()
	}()

	for {
		message, err := reader.Read()
		if err != nil {
			return connectionResult(ctx, err)
		}
		switch message.Type {
		case agentwire.TypeFrame:
			if awaiting != nil {
				return errors.New("Codex VM guest sent a frame after snapshot barrier")
			}
			barrier, err := bridge.receiveFrame(active, *message.Frame)
			if err != nil {
				return err
			}
			if barrier != nil {
				awaiting = barrier
			}
		case agentwire.TypeBarrierAck:
			if awaiting == nil {
				return errors.New("Codex VM guest sent an unsolicited barrier acknowledgement")
			}
			if err := bridge.acceptBarrier(active, *awaiting, *message.Barrier); err != nil {
				return err
			}
			awaiting = nil
		default:
			return fmt.Errorf("Codex VM guest sent unexpected %q after attach", message.Type)
		}
	}
}

func (bridge *Bridge) receiveFrame(active *activeConnection, frame agentstream.Frame) (*agentstream.Barrier, error) {
	bridge.mu.Lock()
	if bridge.active != active || active.generation != bridge.generation {
		bridge.mu.Unlock()
		return nil, errors.New("Codex VM frame arrived on a stale connection")
	}
	if bridge.frozen {
		bridge.mu.Unlock()
		return nil, errors.New("Codex VM guest sent a frame while the bridge was frozen")
	}
	result, err := bridge.transcript.Receive(frame)
	if err != nil {
		bridge.mu.Unlock()
		return nil, fmt.Errorf("receive Codex VM output: %w", err)
	}
	if result == agentstream.Duplicate {
		bridge.mu.Unlock()
		return nil, nil
	}
	toolCall, err := parseProtectedToolCall(frame.Line)
	if err != nil {
		bridge.mu.Unlock()
		return nil, fmt.Errorf("inspect Codex App Server output: %w", err)
	}
	if toolCall != nil {
		if bridge.pending != nil || bridge.released {
			bridge.mu.Unlock()
			return nil, errors.New("Codex VM bridge observed more than one protected tool boundary")
		}
		bridge.pending = bytes.Clone(frame.Line)
		bridge.protected = toolCall
		bridge.frozen = true
		barrier := bridge.transcript.Barrier()
		bridge.barrier = &barrier
		if err := active.writer.Write(agentwire.Message{Type: agentwire.TypeBarrier, Barrier: &barrier}); err != nil {
			bridge.mu.Unlock()
			if isConnectionError(err) {
				return nil, fmt.Errorf("%w: write snapshot barrier: %v", ErrDisconnected, err)
			}
			return nil, fmt.Errorf("write snapshot barrier: %w", err)
		}
		bridge.mu.Unlock()
		return &barrier, nil
	}
	outputLine, err := bridge.mapGuestOutput(frame.Line)
	if err != nil {
		bridge.mu.Unlock()
		return nil, err
	}
	terminal, err := matchesProtectedCompletion(frame.Line, bridge.protected)
	if err != nil {
		bridge.mu.Unlock()
		return nil, err
	}
	if terminal {
		if !bridge.responseAccepted {
			bridge.mu.Unlock()
			return nil, errors.New("Codex VM completed the protected turn before accepting its callback response")
		}
		if bridge.terminalPending || bridge.terminalDelivered {
			bridge.mu.Unlock()
			return nil, errors.New("Codex VM emitted more than one completion for the protected turn")
		}
		bridge.terminalPending = true
	}
	ticket := bridge.reserveOutputLocked()
	bridge.mu.Unlock()
	if err := bridge.writeOutput(ticket, outputLine); err != nil {
		return nil, err
	}
	if terminal {
		bridge.mu.Lock()
		bridge.terminalPending = false
		bridge.terminalDelivered = true
		bridge.completeIfReadyLocked()
		bridge.mu.Unlock()
	}
	return nil, nil
}

func (bridge *Bridge) acceptBarrier(active *activeConnection, host, guest agentstream.Barrier) error {
	bridge.mu.Lock()
	defer bridge.mu.Unlock()
	if bridge.active != active || active.generation != bridge.generation {
		return errors.New("Codex VM barrier acknowledgement arrived on a stale connection")
	}
	if bridge.barrier == nil || *bridge.barrier != host {
		return errors.New("Codex VM barrier acknowledgement differs from the pending barrier")
	}
	quiescent, err := bridge.transcript.Quiescent(host, guest)
	if err != nil {
		return fmt.Errorf("validate Codex VM snapshot barrier: %w", err)
	}
	if !quiescent {
		return errors.New("Codex VM snapshot barrier is not quiescent")
	}
	checkpoint := Checkpoint{HostBarrier: host, GuestBarrier: guest}
	bridge.checkpoint = &checkpoint
	bridge.barrier = nil
	select {
	case bridge.quiescent <- checkpoint:
	default:
		return errors.New("Codex VM produced a duplicate snapshot checkpoint")
	}
	return nil
}

func (bridge *Bridge) WaitCheckpoint(ctx context.Context) (Checkpoint, error) {
	select {
	case checkpoint := <-bridge.quiescent:
		return checkpoint, nil
	case <-bridge.failed:
		return Checkpoint{}, bridge.Failure()
	case <-ctx.Done():
		return Checkpoint{}, ctx.Err()
	}
}

// AdvanceGeneration binds the retained transcript to the restored VMM role.
func (bridge *Bridge) AdvanceGeneration(next uint64, checkpoint Checkpoint) error {
	bridge.mu.Lock()
	defer bridge.mu.Unlock()
	if !bridge.frozen || bridge.pending == nil || bridge.checkpoint == nil || *bridge.checkpoint != checkpoint {
		return errors.New("Codex VM generation advance lacks the current frozen checkpoint")
	}
	if err := bridge.transcript.AdvanceGeneration(next, checkpoint.HostBarrier, checkpoint.GuestBarrier); err != nil {
		return err
	}
	bridge.generation = next
	copy := checkpoint
	bridge.advance = &copy
	return nil
}

func (bridge *Bridge) WaitAttached(ctx context.Context, generation uint64) error {
	if ctx == nil {
		return errors.New("Codex VM attach wait context is nil")
	}
	if generation == 0 {
		return errors.New("Codex VM attach generation must be positive")
	}
	for {
		bridge.mu.Lock()
		if bridge.attachedGeneration >= generation {
			bridge.mu.Unlock()
			return nil
		}
		if bridge.failure != nil {
			err := bridge.failure
			bridge.mu.Unlock()
			return err
		}
		changed := bridge.attachedChanged
		bridge.mu.Unlock()
		select {
		case <-changed:
		case <-bridge.failed:
			return bridge.Failure()
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

// ReleaseToolCall publishes the held callback only after the restored guest is
// attached; this prevents an unmodified client from answering the old VM.
func (bridge *Bridge) ReleaseToolCall() error {
	bridge.mu.Lock()
	if bridge.generation <= 1 || bridge.active == nil || bridge.active.generation != bridge.generation || bridge.pending == nil || !bridge.frozen || bridge.released || bridge.releasing {
		bridge.mu.Unlock()
		return errors.New("Codex VM tool callback cannot be released before restored attach")
	}
	pending := bytes.Clone(bridge.pending)
	outputLine, err := bridge.mapGuestOutput(pending)
	if err != nil {
		bridge.mu.Unlock()
		return err
	}
	bridge.releasing = true
	ticket := bridge.reserveOutputLocked()
	bridge.mu.Unlock()

	if err := bridge.writeOutput(ticket, outputLine); err != nil {
		bridge.mu.Lock()
		bridge.releasing = false
		bridge.mu.Unlock()
		return err
	}

	bridge.mu.Lock()
	defer bridge.mu.Unlock()
	if !bridge.releasing || bridge.pending == nil || !bytes.Equal(bridge.pending, pending) || bridge.released {
		return errors.New("Codex VM tool callback state changed during release")
	}
	bridge.pending = nil
	bridge.released = true
	bridge.releasing = false
	bridge.frozen = false
	bridge.condition.Broadcast()
	return nil
}

func (bridge *Bridge) mapGuestOutput(line []byte) ([]byte, error) {
	if bridge.hostWorkspace == "" {
		return bytes.Clone(line), nil
	}
	return mapGuestWorkspace(line, bridge.guestWorkspace, bridge.hostWorkspace)
}

func mapGuestWorkspace(line []byte, guestWorkspace, hostWorkspace string) ([]byte, error) {
	decoder := json.NewDecoder(bytes.NewReader(line))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return nil, fmt.Errorf("decode guest App Server output for workspace mapping: %w", err)
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return nil, fmt.Errorf("guest App Server output has trailing value %v", token)
		}
		return nil, fmt.Errorf("guest App Server output has trailing data: %w", err)
	}
	if _, ok := value.(map[string]any); !ok {
		return nil, errors.New("guest App Server output is not one JSON object")
	}
	mapped, changed, err := mapGuestWorkspaceEnvelope(value.(map[string]any), guestWorkspace, hostWorkspace)
	if err != nil {
		return nil, err
	}
	if !changed {
		return bytes.Clone(line), nil
	}
	encoded, err := json.Marshal(mapped)
	if err != nil {
		return nil, fmt.Errorf("encode host-mapped App Server output: %w", err)
	}
	return encoded, nil
}

func mapGuestWorkspaceEnvelope(envelope map[string]any, guestWorkspace, hostWorkspace string) (map[string]any, bool, error) {
	changed := false
	if result, ok := envelope["result"].(map[string]any); ok {
		resultChanged, err := mapThreadContainer(result, guestWorkspace, hostWorkspace)
		if err != nil {
			return nil, false, err
		}
		changed = changed || resultChanged
	}
	if params, ok := envelope["params"].(map[string]any); ok {
		if thread, ok := params["thread"].(map[string]any); ok {
			threadChanged, err := mapCWDField(thread, guestWorkspace, hostWorkspace)
			if err != nil {
				return nil, false, err
			}
			changed = changed || threadChanged
		}
	}
	return envelope, changed, nil
}

func mapThreadContainer(container map[string]any, guestWorkspace, hostWorkspace string) (bool, error) {
	changed, err := mapCWDField(container, guestWorkspace, hostWorkspace)
	if err != nil {
		return false, err
	}
	if thread, ok := container["thread"].(map[string]any); ok {
		threadChanged, err := mapCWDField(thread, guestWorkspace, hostWorkspace)
		if err != nil {
			return false, err
		}
		changed = changed || threadChanged
	}
	if roots, present := container["runtimeWorkspaceRoots"]; present {
		array, ok := roots.([]any)
		if !ok {
			return false, errors.New("guest App Server runtimeWorkspaceRoots is not an array")
		}
		for index, root := range array {
			path, ok := root.(string)
			if !ok {
				return false, errors.New("guest App Server runtimeWorkspaceRoots contains a non-string path")
			}
			mapped, pathChanged := mapWorkspacePath(path, guestWorkspace, hostWorkspace)
			if pathChanged {
				array[index] = mapped
				changed = true
			}
		}
	}
	return changed, nil
}

func mapCWDField(object map[string]any, guestWorkspace, hostWorkspace string) (bool, error) {
	value, present := object["cwd"]
	if !present {
		return false, nil
	}
	path, ok := value.(string)
	if !ok {
		return false, errors.New("guest App Server cwd is not a string")
	}
	mapped, changed := mapWorkspacePath(path, guestWorkspace, hostWorkspace)
	if changed {
		object["cwd"] = mapped
	}
	return changed, nil
}

func mapWorkspacePath(value, from, to string) (string, bool) {
	if value == from {
		return to, true
	}
	prefix := from + string(filepath.Separator)
	if strings.HasPrefix(value, prefix) && filepath.Clean(value) == value {
		return filepath.Join(to, strings.TrimPrefix(value, prefix)), true
	}
	return value, false
}

func (bridge *Bridge) reserveOutputLocked() uint64 {
	ticket := bridge.outputIssued
	bridge.outputIssued++
	return ticket
}

func (bridge *Bridge) writeOutput(ticket uint64, line []byte) error {
	bridge.outputMu.Lock()
	defer bridge.outputMu.Unlock()
	if ticket < bridge.outputNext {
		return fmt.Errorf("Codex VM output ticket %d was already completed", ticket)
	}
	for ticket != bridge.outputNext && bridge.outputFailure == nil {
		bridge.outputCond.Wait()
	}
	if bridge.outputFailure != nil {
		return bridge.outputFailure
	}
	finish := func(err error) error {
		if err != nil && bridge.outputFailure == nil {
			bridge.outputFailure = err
		}
		bridge.outputNext++
		bridge.outputCond.Broadcast()
		return err
	}
	if bridge.audit != nil {
		if err := bridge.audit(PhaseAuthorized, DirectionServerToClient, line); err != nil {
			return finish(fmt.Errorf("authorize server-to-client Codex I/O: %w", err))
		}
	}
	if err := writeAll(bridge.output, line); err != nil {
		return finish(fmt.Errorf("write Codex VM JSONL output: %w", err))
	}
	if err := writeAll(bridge.output, []byte{'\n'}); err != nil {
		return finish(fmt.Errorf("terminate Codex VM JSONL output: %w", err))
	}
	if bridge.audit != nil {
		if err := bridge.audit(PhaseDelivered, DirectionServerToClient, line); err != nil {
			return finish(fmt.Errorf("commit delivered server-to-client Codex I/O: %w", err))
		}
	}
	return finish(nil)
}

func (bridge *Bridge) handleInputEOF() {
	bridge.mu.Lock()
	bridge.inputEOF = true
	if bridge.terminalDelivered {
		bridge.completeIfReadyLocked()
		bridge.mu.Unlock()
		return
	}
	if bridge.terminalPending {
		bridge.mu.Unlock()
		return
	}
	bridge.mu.Unlock()
	bridge.fail(ErrIncompleteSession)
}

func (bridge *Bridge) completeIfReadyLocked() {
	if !bridge.inputEOF || !bridge.responseAccepted || !bridge.terminalDelivered || bridge.failure != nil {
		return
	}
	bridge.closed = true
	bridge.condition.Broadcast()
	bridge.completeOnce.Do(func() { close(bridge.completed) })
}

// ShutdownGuest ends the successfully completed stream with an authenticated
// protocol message. The guest uses this boundary to stop its complete process
// domain before exporting the final repository.
func (bridge *Bridge) ShutdownGuest() error {
	bridge.mu.Lock()
	if !bridge.closed || bridge.failure != nil || bridge.active == nil {
		bridge.mu.Unlock()
		return errors.New("Codex VM guest shutdown requires one completed active stream")
	}
	active := bridge.active
	bridge.active = nil
	bridge.mu.Unlock()
	writeErr := active.writer.Write(agentwire.Message{Type: agentwire.TypeShutdown})
	closeErr := active.closer.Close()
	return errors.Join(writeErr, closeErr)
}

func (bridge *Bridge) fail(err error) {
	if err == nil {
		return
	}
	bridge.failOnce.Do(func() {
		bridge.mu.Lock()
		bridge.failure = err
		bridge.closed = true
		if bridge.active != nil {
			_ = bridge.active.closer.Close()
			bridge.active = nil
		}
		bridge.condition.Broadcast()
		bridge.mu.Unlock()
		close(bridge.failed)
	})
}

func (bridge *Bridge) Failure() error {
	bridge.mu.Lock()
	defer bridge.mu.Unlock()
	return bridge.failure
}

func (bridge *Bridge) Wait(ctx context.Context) error {
	if ctx == nil {
		return errors.New("Codex VM wait context is nil")
	}
	select {
	case <-bridge.completed:
		return nil
	case <-bridge.failed:
		return bridge.Failure()
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (bridge *Bridge) Fail(err error) { bridge.fail(err) }

func parseProtectedToolCall(line []byte) (*protectedCall, error) {
	envelope, err := decodeRawObject(line, "App Server output")
	if err != nil {
		return nil, err
	}
	methodRaw, present := envelope["method"]
	if !present {
		return nil, nil
	}
	var method string
	if err := json.Unmarshal(methodRaw, &method); err != nil {
		return nil, errors.New("App Server output method is not a string")
	}
	if method != "item/tool/call" {
		return nil, nil
	}
	requestID, err := canonicalRequestID(envelope["id"])
	if err != nil {
		return nil, fmt.Errorf("protected tool request id: %w", err)
	}
	paramsRaw, present := envelope["params"]
	if !present {
		return nil, errors.New("protected tool request omits params")
	}
	params, err := decodeRawObject(paramsRaw, "protected tool params")
	if err != nil {
		return nil, err
	}
	threadID, err := requiredJSONString(params, "threadId", "protected tool params")
	if err != nil {
		return nil, err
	}
	turnID, err := requiredJSONString(params, "turnId", "protected tool params")
	if err != nil {
		return nil, err
	}
	callID, err := requiredJSONString(params, "callId", "protected tool params")
	if err != nil {
		return nil, err
	}
	return &protectedCall{requestID: requestID, threadID: threadID, turnID: turnID, callID: callID}, nil
}

func matchesProtectedResponse(line []byte, call *protectedCall) (bool, error) {
	if call == nil {
		return false, nil
	}
	envelope, err := decodeRawObject(line, "App Server client request")
	if err != nil {
		return false, err
	}
	idRaw, present := envelope["id"]
	if !present {
		return false, nil
	}
	requestID, err := canonicalRequestID(idRaw)
	if err != nil {
		return false, nil
	}
	if requestID != call.requestID {
		return false, nil
	}
	resultRaw, present := envelope["result"]
	if !present {
		return false, errors.New("protected callback response omits result")
	}
	result, err := decodeRawObject(resultRaw, "protected callback result")
	if err != nil {
		return false, err
	}
	var success bool
	successRaw, present := result["success"]
	if !present || json.Unmarshal(successRaw, &success) != nil {
		return false, errors.New("protected callback result lacks a Boolean success")
	}
	if !success {
		return false, errors.New("protected callback response reports failure")
	}
	return true, nil
}

func matchesProtectedCompletion(line []byte, call *protectedCall) (bool, error) {
	if call == nil {
		return false, nil
	}
	envelope, err := decodeRawObject(line, "App Server output")
	if err != nil {
		return false, err
	}
	methodRaw, present := envelope["method"]
	if !present {
		return false, nil
	}
	var method string
	if err := json.Unmarshal(methodRaw, &method); err != nil {
		return false, errors.New("App Server output method is not a string")
	}
	if method != "turn/completed" {
		return false, nil
	}
	paramsRaw, present := envelope["params"]
	if !present {
		return false, errors.New("turn/completed omits params")
	}
	params, err := decodeRawObject(paramsRaw, "turn/completed params")
	if err != nil {
		return false, err
	}
	threadID, err := requiredJSONString(params, "threadId", "turn/completed params")
	if err != nil {
		return false, err
	}
	turnRaw, present := params["turn"]
	if !present {
		return false, errors.New("turn/completed omits turn")
	}
	turn, err := decodeRawObject(turnRaw, "turn/completed turn")
	if err != nil {
		return false, err
	}
	turnID, err := requiredJSONString(turn, "id", "turn/completed turn")
	if err != nil {
		return false, err
	}
	if threadID != call.threadID || turnID != call.turnID {
		return false, nil
	}
	status, err := requiredJSONString(turn, "status", "turn/completed turn")
	if err != nil {
		return false, err
	}
	if status != "completed" {
		return false, fmt.Errorf("protected turn completed with status %q", status)
	}
	errorRaw, present := turn["error"]
	if !present || !bytes.Equal(bytes.TrimSpace(errorRaw), []byte("null")) {
		return false, errors.New("protected turn/completed reports an error")
	}
	return true, nil
}

func canonicalRequestID(raw json.RawMessage) (string, error) {
	if len(raw) == 0 {
		return "", errors.New("request id is missing")
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return "", err
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return "", fmt.Errorf("request id has trailing value %v", token)
		}
		return "", fmt.Errorf("request id has trailing data: %w", err)
	}
	switch value.(type) {
	case string, json.Number:
	default:
		return "", errors.New("request id is not a string or number")
	}
	canonical, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	return string(canonical), nil
}

func requiredJSONString(object map[string]json.RawMessage, field, label string) (string, error) {
	raw, present := object[field]
	if !present {
		return "", fmt.Errorf("%s omits %s", label, field)
	}
	var value string
	if err := json.Unmarshal(raw, &value); err != nil || value == "" {
		return "", fmt.Errorf("%s %s is not a non-empty string", label, field)
	}
	return value, nil
}

func writeAll(writer io.Writer, data []byte) error {
	for len(data) > 0 {
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

func connectionResult(ctx context.Context, err error) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if errors.Is(err, io.EOF) || isConnectionError(err) {
		return fmt.Errorf("%w: %v", ErrDisconnected, err)
	}
	return err
}

func isConnectionError(err error) bool {
	return errors.Is(err, io.EOF) || errors.Is(err, io.ErrClosedPipe) || errors.Is(err, net.ErrClosed) ||
		errors.Is(err, syscall.EPIPE) || errors.Is(err, syscall.ECONNRESET) || errors.Is(err, syscall.ENOTCONN) ||
		errors.Is(err, context.Canceled)
}
