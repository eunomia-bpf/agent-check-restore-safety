//go:build linux

package agentguest

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentstream"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentwire"
)

const sessionTestTimeout = 2 * time.Second

func TestRunSessionFirstAttachAndBidirectionalLines(t *testing.T) {
	input := newObservedWriter()
	running := startTestSession(t, input)
	defer running.stop(t)

	host := newHostTranscript(t, 1)
	endpoint := running.nextEndpoint(t)
	defer endpoint.close()
	endpoint.attach(t, host, agentwire.Message{Type: agentwire.TypeRole, Generation: 1})

	hostLine := []byte(`{"id":1,"method":"initialize"}`)
	hostFrame := mustHostSend(t, host, hostLine)
	endpoint.write(t, agentwire.Message{Type: agentwire.TypeFrame, Frame: &hostFrame})
	input.waitFor(t, append(bytes.Clone(hostLine), '\n'))

	guestLine := []byte(`{"id":1,"result":{"ready":true}}`)
	writeDone := running.writeCodex(guestLine)
	message := endpoint.read(t)
	if message.Type != agentwire.TypeFrame || message.Frame == nil {
		t.Fatalf("Codex output produced %+v, want frame", message)
	}
	if !bytes.Equal(message.Frame.Line, guestLine) || message.Frame.Direction != agentstream.GuestToHost || message.Frame.Generation != 1 {
		t.Fatalf("guest frame = %+v, want line %q in generation 1", message.Frame, guestLine)
	}
	mustHostReceive(t, host, *message.Frame, agentstream.Received)
	if err := <-writeDone; err != nil {
		t.Fatalf("write Codex stdout: %v", err)
	}
}

func TestRunSessionDisconnectReplaysSuffixWithoutDuplicateCodexInput(t *testing.T) {
	input := newObservedWriter()
	running := startTestSession(t, input)
	defer running.stop(t)

	host := newHostTranscript(t, 1)
	first := running.nextEndpoint(t)
	first.attach(t, host, agentwire.Message{Type: agentwire.TypeRole, Generation: 1})

	hostLine := []byte(`{"id":7,"method":"tools/call"}`)
	hostFrame := mustHostSend(t, host, hostLine)
	first.write(t, agentwire.Message{Type: agentwire.TypeFrame, Frame: &hostFrame})
	wantInput := append(bytes.Clone(hostLine), '\n')
	input.waitFor(t, wantInput)

	// The first connection carries the Guest frame, but the Host deliberately
	// drops the connection before recording it. The Guest transcript must retain
	// the line and resend it from the Host's exact known position.
	guestLine := []byte(`{"id":7,"result":"done"}`)
	writeDone := running.writeCodex(guestLine)
	lost := first.read(t)
	if lost.Type != agentwire.TypeFrame || lost.Frame == nil || !bytes.Equal(lost.Frame.Line, guestLine) {
		t.Fatalf("lost message = %+v, want guest frame %q", lost, guestLine)
	}
	if err := <-writeDone; err != nil {
		t.Fatalf("write Codex stdout: %v", err)
	}
	first.close()
	offlineHostLine := []byte(`{"id":8,"method":"after-disconnect"}`)
	mustHostSend(t, host, offlineHostLine)

	second := running.nextEndpoint(t)
	defer second.close()
	resends := second.attach(t, host, agentwire.Message{Type: agentwire.TypeRole, Generation: 1})
	if len(resends) != 1 || !bytes.Equal(resends[0].Line, guestLine) {
		t.Fatalf("replayed guest suffix = %+v, want exactly %q", resends, guestLine)
	}
	wantInput = append(wantInput, offlineHostLine...)
	wantInput = append(wantInput, '\n')
	input.waitFor(t, wantInput)

	// A Host retry of an already delivered frame is accepted as a transcript
	// duplicate but must never be written to Codex a second time.
	second.write(t, agentwire.Message{Type: agentwire.TypeFrame, Frame: &hostFrame})
	barrier := host.Barrier()
	second.write(t, agentwire.Message{Type: agentwire.TypeBarrier, Barrier: &barrier})
	if message := second.read(t); message.Type != agentwire.TypeBarrierAck {
		t.Fatalf("post-duplicate barrier response = %+v, want barrier_ack", message)
	}
	if got := input.bytes(); !bytes.Equal(got, wantInput) {
		t.Fatalf("Codex input after duplicate = %q, want exactly %q", got, wantInput)
	}
}

func TestRunSessionBarrierAdvanceReleasesHeldStdoutInNewGeneration(t *testing.T) {
	input := newObservedWriter()
	running := startTestSession(t, input)
	defer running.stop(t)

	host := newHostTranscript(t, 1)
	first := running.nextEndpoint(t)
	first.attach(t, host, agentwire.Message{Type: agentwire.TypeRole, Generation: 1})
	hostBarrier := host.Barrier()
	first.write(t, agentwire.Message{Type: agentwire.TypeBarrier, Barrier: &hostBarrier})
	ackMessage := first.read(t)
	if ackMessage.Type != agentwire.TypeBarrierAck || ackMessage.Barrier == nil {
		t.Fatalf("barrier response = %+v, want barrier_ack", ackMessage)
	}
	guestBarrier := *ackMessage.Barrier
	quiescent, err := host.Quiescent(hostBarrier, guestBarrier)
	if err != nil || !quiescent {
		t.Fatalf("acknowledged barrier is not quiescent: %t, %v", quiescent, err)
	}

	heldLine := []byte(`{"id":9,"result":"after-snapshot"}`)
	writeDone := running.writeCodex(heldLine)
	if err := <-writeDone; err != nil {
		t.Fatalf("write held Codex stdout: %v", err)
	}
	first.expectNoMessage(t, 40*time.Millisecond)
	first.close()

	// A same-generation reconnect can repeat the already acknowledged barrier,
	// but it must not thaw the held Codex output.
	replay := running.nextEndpoint(t)
	replay.attach(t, host, agentwire.Message{Type: agentwire.TypeRole, Generation: 1})
	replay.write(t, agentwire.Message{Type: agentwire.TypeBarrier, Barrier: &hostBarrier})
	replayedAck := replay.read(t)
	if replayedAck.Type != agentwire.TypeBarrierAck || replayedAck.Barrier == nil || *replayedAck.Barrier != guestBarrier {
		t.Fatalf("replayed barrier response = %+v, want original barrier_ack", replayedAck)
	}
	replay.close()

	if err := host.AdvanceGeneration(3, hostBarrier, guestBarrier); err != nil {
		t.Fatalf("host AdvanceGeneration(3): %v", err)
	}
	second := running.nextEndpoint(t)
	advance := agentwire.Message{
		Type:         agentwire.TypeAdvance,
		Generation:   3,
		HostBarrier:  &hostBarrier,
		GuestBarrier: &guestBarrier,
	}
	second.attach(t, host, advance)
	message := second.read(t)
	if message.Type != agentwire.TypeFrame || message.Frame == nil {
		t.Fatalf("held stdout produced %+v, want frame", message)
	}
	if message.Frame.Generation != 3 || !bytes.Equal(message.Frame.Line, heldLine) {
		t.Fatalf("held frame = %+v, want generation 3 line %q", message.Frame, heldLine)
	}
	mustHostReceive(t, host, *message.Frame, agentstream.Received)
	second.close()

	// The restored transport may disconnect after consuming Advance. Repeating
	// the identical proof is idempotent, so a transient attach failure cannot
	// strand the restored VM in generation 3.
	third := running.nextEndpoint(t)
	defer third.close()
	third.attach(t, host, advance)
	afterReconnect := mustHostSend(t, host, []byte(`{"id":10,"method":"initialized"}`))
	third.write(t, agentwire.Message{Type: agentwire.TypeFrame, Frame: &afterReconnect})
	input.waitFor(t, append([]byte(`{"id":10,"method":"initialized"}`), '\n'))
}

func TestRunSessionRejectsWrongGenerationBarrierAndFrozenFrame(t *testing.T) {
	t.Run("wrong role generation", func(t *testing.T) {
		running := startTestSession(t, newObservedWriter())
		defer running.closeCodex()
		endpoint := running.nextEndpoint(t)
		defer endpoint.close()
		endpoint.write(t, agentwire.Message{Type: agentwire.TypeRole, Generation: 2})
		err := running.wait(t)
		if err == nil || !strings.Contains(err.Error(), "role generation 2") {
			t.Fatalf("RunSession error = %v, want wrong generation rejection", err)
		}
	})

	t.Run("wrong frame generation", func(t *testing.T) {
		running := startTestSession(t, newObservedWriter())
		defer running.closeCodex()
		host := newHostTranscript(t, 1)
		endpoint := running.nextEndpoint(t)
		defer endpoint.close()
		endpoint.attach(t, host, agentwire.Message{Type: agentwire.TypeRole, Generation: 1})
		rogue := newHostTranscript(t, 2)
		frame := mustHostSend(t, rogue, []byte(`{"wrong":2}`))
		endpoint.write(t, agentwire.Message{Type: agentwire.TypeFrame, Frame: &frame})
		err := running.wait(t)
		if !errors.Is(err, agentstream.ErrGeneration) {
			t.Fatalf("RunSession error = %v, want ErrGeneration", err)
		}
	})

	t.Run("wrong barrier", func(t *testing.T) {
		running := startTestSession(t, newObservedWriter())
		defer running.closeCodex()
		host := newHostTranscript(t, 1)
		endpoint := running.nextEndpoint(t)
		defer endpoint.close()
		endpoint.attach(t, host, agentwire.Message{Type: agentwire.TypeRole, Generation: 1})
		barrier := host.Barrier()
		barrier.State.HostToGuest.Hash[0] ^= 1
		endpoint.write(t, agentwire.Message{Type: agentwire.TypeBarrier, Barrier: &barrier})
		err := running.wait(t)
		if !errors.Is(err, agentstream.ErrHash) {
			t.Fatalf("RunSession error = %v, want ErrHash", err)
		}
	})

	t.Run("frame while frozen", func(t *testing.T) {
		input := newObservedWriter()
		running := startTestSession(t, input)
		defer running.closeCodex()
		host := newHostTranscript(t, 1)
		endpoint := running.nextEndpoint(t)
		defer endpoint.close()
		endpoint.attach(t, host, agentwire.Message{Type: agentwire.TypeRole, Generation: 1})
		barrier := host.Barrier()
		endpoint.write(t, agentwire.Message{Type: agentwire.TypeBarrier, Barrier: &barrier})
		if message := endpoint.read(t); message.Type != agentwire.TypeBarrierAck {
			t.Fatalf("barrier response = %+v, want barrier_ack", message)
		}
		frame := mustHostSend(t, host, []byte(`{"forbidden":true}`))
		endpoint.write(t, agentwire.Message{Type: agentwire.TypeFrame, Frame: &frame})
		err := running.wait(t)
		if err == nil || !strings.Contains(err.Error(), "while transcript is frozen") {
			t.Fatalf("RunSession error = %v, want frozen-frame rejection", err)
		}
		if got := input.bytes(); len(got) != 0 {
			t.Fatalf("frozen frame reached Codex stdin: %q", got)
		}
	})

	t.Run("advance without barrier", func(t *testing.T) {
		running := startTestSession(t, newObservedWriter())
		defer running.closeCodex()
		endpoint := running.nextEndpoint(t)
		defer endpoint.close()
		barrier := agentstream.Barrier{}
		endpoint.write(t, agentwire.Message{
			Type: agentwire.TypeAdvance, Generation: 3,
			HostBarrier: &barrier, GuestBarrier: &barrier,
		})
		err := running.wait(t)
		if err == nil || !strings.Contains(err.Error(), "advance without") {
			t.Fatalf("RunSession error = %v, want advance rejection", err)
		}
	})
}

func TestRunSessionContextCancellationClosesConnectionAndWakesFreeze(t *testing.T) {
	running := startTestSession(t, newObservedWriter())
	host := newHostTranscript(t, 1)
	endpoint := running.nextEndpoint(t)
	defer endpoint.close()
	endpoint.attach(t, host, agentwire.Message{Type: agentwire.TypeRole, Generation: 1})
	barrier := host.Barrier()
	endpoint.write(t, agentwire.Message{Type: agentwire.TypeBarrier, Barrier: &barrier})
	if message := endpoint.read(t); message.Type != agentwire.TypeBarrierAck {
		t.Fatalf("barrier response = %+v, want barrier_ack", message)
	}

	held := running.writeCodex([]byte(`{"held":true}`))
	if err := <-held; err != nil {
		t.Fatalf("write held output: %v", err)
	}
	running.cancel()
	err := running.wait(t)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("RunSession error = %v, want context.Canceled", err)
	}
	running.closeCodex()

	buffer := make([]byte, 1)
	_ = endpoint.connection.SetReadDeadline(time.Now().Add(sessionTestTimeout))
	if _, err := endpoint.connection.Read(buffer); err == nil {
		t.Fatal("host connection remained open after context cancellation")
	}
}

func TestRunSessionContextCancellationDoesNotWaitForDial(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	stdoutReader, stdoutWriter := io.Pipe()
	defer stdoutReader.Close()
	defer stdoutWriter.Close()
	releaseDial := make(chan struct{})
	dialStarted := make(chan struct{})
	dialReturned := make(chan struct{})
	result := make(chan error, 1)
	go func() {
		result <- RunSession(ctx, validConfig(), newObservedWriter(), stdoutReader, func(uint32) (Stream, error) {
			close(dialStarted)
			defer close(dialReturned)
			<-releaseDial
			return nil, errors.New("dial released")
		}, log.New(io.Discard, "", 0))
	}()
	select {
	case <-dialStarted:
	case <-time.After(sessionTestTimeout):
		t.Fatal("dialer did not start")
	}
	cancel()
	select {
	case err := <-result:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("RunSession error = %v, want context.Canceled", err)
		}
	case <-time.After(sessionTestTimeout):
		t.Fatal("RunSession waited for a non-context-aware dialer")
	}
	close(releaseDial)
	select {
	case <-dialReturned:
	case <-time.After(sessionTestTimeout):
		t.Fatal("released dialer goroutine did not exit")
	}
}

func TestRunSessionStdioAndMalformedWireFailuresAreTerminal(t *testing.T) {
	t.Run("invalid Codex JSONL", func(t *testing.T) {
		running := startTestSession(t, newObservedWriter())
		endpoint := running.nextEndpoint(t)
		defer endpoint.close()
		if _, err := running.stdout.Write([]byte("{}\r\n")); err != nil {
			t.Fatalf("write invalid Codex output: %v", err)
		}
		err := running.wait(t)
		if !errors.Is(err, agentstream.ErrInvalidLine) {
			t.Fatalf("RunSession error = %v, want ErrInvalidLine", err)
		}
		running.closeCodex()
	})

	t.Run("Codex stdin failure", func(t *testing.T) {
		writeFailure := errors.New("stdin failed")
		running := startTestSession(t, errorWriter{err: writeFailure})
		defer running.closeCodex()
		host := newHostTranscript(t, 1)
		endpoint := running.nextEndpoint(t)
		defer endpoint.close()
		endpoint.attach(t, host, agentwire.Message{Type: agentwire.TypeRole, Generation: 1})
		frame := mustHostSend(t, host, []byte(`{"input":true}`))
		endpoint.write(t, agentwire.Message{Type: agentwire.TypeFrame, Frame: &frame})
		err := running.wait(t)
		if !errors.Is(err, writeFailure) {
			t.Fatalf("RunSession error = %v, want stdin failure", err)
		}
	})

	t.Run("malformed complete wire message", func(t *testing.T) {
		running := startTestSession(t, newObservedWriter())
		defer running.closeCodex()
		endpoint := running.nextEndpoint(t)
		defer endpoint.close()
		_ = endpoint.connection.SetWriteDeadline(time.Now().Add(sessionTestTimeout))
		if _, err := endpoint.connection.Write([]byte("{\"type\":\n")); err != nil {
			t.Fatalf("write malformed wire message: %v", err)
		}
		_ = endpoint.connection.SetWriteDeadline(time.Time{})
		err := running.wait(t)
		if err == nil || !strings.Contains(err.Error(), "protocol") {
			t.Fatalf("RunSession error = %v, want terminal protocol error", err)
		}
	})
}

func TestReadCodexLinePreservesStrictFramingAndBounds(t *testing.T) {
	reader := bufio.NewReader(strings.NewReader("{}\n{\"x\":1}\r\n"))
	first, err := readCodexLine(reader, 16)
	if err != nil || string(first) != "{}" {
		t.Fatalf("first line = %q, %v", first, err)
	}
	second, err := readCodexLine(reader, 16)
	if err != nil || string(second) != "{\"x\":1}\r" {
		t.Fatalf("CRLF line = %q, %v; CR must remain visible for rejection", second, err)
	}
	if _, err := readCodexLine(bufio.NewReader(strings.NewReader("{\"x\":1}\n")), 2); err == nil {
		t.Fatal("readCodexLine accepted an oversized line")
	}
	if _, err := readCodexLine(bufio.NewReader(strings.NewReader("{}")), 2); !errors.Is(err, io.ErrUnexpectedEOF) {
		t.Fatalf("unterminated line error = %v, want io.ErrUnexpectedEOF", err)
	}
}

type testRunningSession struct {
	cancel    context.CancelFunc
	stdout    *io.PipeWriter
	dialer    *testSessionDialer
	result    chan error
	waitOnce  sync.Once
	waitedErr error
}

func startTestSession(t *testing.T, stdin io.Writer) *testRunningSession {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	stdoutReader, stdoutWriter := io.Pipe()
	dialer := &testSessionDialer{hosts: make(chan net.Conn, 16)}
	result := make(chan error, 1)
	go func() {
		result <- RunSession(ctx, validConfig(), stdin, stdoutReader, dialer.dial, log.New(io.Discard, "", 0))
	}()
	return &testRunningSession{cancel: cancel, stdout: stdoutWriter, dialer: dialer, result: result}
}

func (running *testRunningSession) nextEndpoint(t *testing.T) *testHostEndpoint {
	t.Helper()
	select {
	case connection := <-running.dialer.hosts:
		reader, err := agentwire.NewReader(connection)
		if err != nil {
			t.Fatalf("NewReader(host): %v", err)
		}
		writer, err := agentwire.NewWriter(connection)
		if err != nil {
			t.Fatalf("NewWriter(host): %v", err)
		}
		return &testHostEndpoint{connection: connection, reader: reader, writer: writer}
	case err := <-running.result:
		t.Fatalf("RunSession exited before dialing: %v", err)
	case <-time.After(sessionTestTimeout):
		t.Fatal("timed out waiting for guest dial")
	}
	return nil
}

func (running *testRunningSession) writeCodex(line []byte) <-chan error {
	done := make(chan error, 1)
	go func() {
		payload := append(bytes.Clone(line), '\n')
		_, err := running.stdout.Write(payload)
		done <- err
	}()
	return done
}

func (running *testRunningSession) wait(t *testing.T) error {
	t.Helper()
	running.waitOnce.Do(func() {
		select {
		case running.waitedErr = <-running.result:
		case <-time.After(sessionTestTimeout):
			t.Fatal("timed out waiting for RunSession to exit")
		}
	})
	return running.waitedErr
}

func (running *testRunningSession) stop(t *testing.T) {
	t.Helper()
	running.cancel()
	err := running.wait(t)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("RunSession stop error = %v, want context.Canceled", err)
	}
	running.closeCodex()
}

func (running *testRunningSession) closeCodex() {
	running.cancel()
	_ = running.stdout.Close()
}

type testSessionDialer struct {
	hosts chan net.Conn
}

func (dialer *testSessionDialer) dial(port uint32) (Stream, error) {
	if port != DefaultStreamPort {
		return nil, fmt.Errorf("dial port %d", port)
	}
	guest, host := net.Pipe()
	dialer.hosts <- host
	return guest, nil
}

type testHostEndpoint struct {
	connection net.Conn
	reader     *agentwire.Reader
	writer     *agentwire.Writer
	closeOnce  sync.Once
}

func (endpoint *testHostEndpoint) attach(t *testing.T, host *agentstream.Transcript, first agentwire.Message) []agentstream.Frame {
	t.Helper()
	endpoint.write(t, first)
	helloMessage := endpoint.read(t)
	if helloMessage.Type != agentwire.TypeHello || helloMessage.Hello == nil {
		t.Fatalf("handshake response = %+v, want hello", helloMessage)
	}
	hello := *helloMessage.Hello
	attach, err := host.Attach(hello)
	if err != nil {
		t.Fatalf("host Attach(%+v): %v", hello, err)
	}
	endpoint.write(t, agentwire.Message{Type: agentwire.TypeAttach, Attach: &attach})

	missingGuestLines := hello.State.GuestToHost.Offset - attach.State.GuestToHost.Offset
	guestResends := make([]agentstream.Frame, 0, missingGuestLines)
	for index := uint64(0); index < missingGuestLines; index++ {
		message := endpoint.read(t)
		if message.Type != agentwire.TypeFrame || message.Frame == nil {
			t.Fatalf("guest resend %d = %+v, want frame", index, message)
		}
		guestResends = append(guestResends, *message.Frame)
		mustHostReceive(t, host, *message.Frame, agentstream.Received)
	}
	hostResends, err := host.Resend(hello.State.HostToGuest)
	if err != nil {
		t.Fatalf("host Resend(): %v", err)
	}
	for index := range hostResends {
		frame := hostResends[index]
		endpoint.write(t, agentwire.Message{Type: agentwire.TypeFrame, Frame: &frame})
	}
	return guestResends
}

func (endpoint *testHostEndpoint) write(t *testing.T, message agentwire.Message) {
	t.Helper()
	_ = endpoint.connection.SetWriteDeadline(time.Now().Add(sessionTestTimeout))
	err := endpoint.writer.Write(message)
	_ = endpoint.connection.SetWriteDeadline(time.Time{})
	if err != nil {
		t.Fatalf("host wire Write(%s): %v", message.Type, err)
	}
}

func (endpoint *testHostEndpoint) read(t *testing.T) agentwire.Message {
	t.Helper()
	_ = endpoint.connection.SetReadDeadline(time.Now().Add(sessionTestTimeout))
	message, err := endpoint.reader.Read()
	_ = endpoint.connection.SetReadDeadline(time.Time{})
	if err != nil {
		t.Fatalf("host wire Read(): %v", err)
	}
	return message
}

func (endpoint *testHostEndpoint) expectNoMessage(t *testing.T, duration time.Duration) {
	t.Helper()
	_ = endpoint.connection.SetReadDeadline(time.Now().Add(duration))
	_, err := endpoint.reader.Read()
	_ = endpoint.connection.SetReadDeadline(time.Time{})
	var networkError net.Error
	if !errors.As(err, &networkError) || !networkError.Timeout() {
		t.Fatalf("expected no host message, got error %v", err)
	}
}

func (endpoint *testHostEndpoint) close() {
	endpoint.closeOnce.Do(func() { _ = endpoint.connection.Close() })
}

type observedWriter struct {
	mu     sync.Mutex
	buffer bytes.Buffer
	notify chan struct{}
}

func newObservedWriter() *observedWriter {
	return &observedWriter{notify: make(chan struct{}, 1)}
}

func (writer *observedWriter) Write(data []byte) (int, error) {
	writer.mu.Lock()
	written, err := writer.buffer.Write(data)
	writer.mu.Unlock()
	select {
	case writer.notify <- struct{}{}:
	default:
	}
	return written, err
}

func (writer *observedWriter) bytes() []byte {
	writer.mu.Lock()
	defer writer.mu.Unlock()
	return bytes.Clone(writer.buffer.Bytes())
}

func (writer *observedWriter) waitFor(t *testing.T, want []byte) {
	t.Helper()
	deadline := time.NewTimer(sessionTestTimeout)
	defer deadline.Stop()
	for {
		if got := writer.bytes(); bytes.Equal(got, want) {
			return
		} else if len(got) > len(want) {
			t.Fatalf("observed Codex input %q exceeds wanted %q", got, want)
		}
		select {
		case <-writer.notify:
		case <-deadline.C:
			t.Fatalf("timed out waiting for Codex input %q; got %q", want, writer.bytes())
		}
	}
}

type errorWriter struct {
	err error
}

func (writer errorWriter) Write([]byte) (int, error) { return 0, writer.err }

func newHostTranscript(t *testing.T, generation uint64) *agentstream.Transcript {
	t.Helper()
	transcript, err := agentstream.New(agentstream.Host, validConfig().SessionID, generation, sessionTranscriptLimits())
	if err != nil {
		t.Fatalf("New(host transcript): %v", err)
	}
	return transcript
}

func mustHostSend(t *testing.T, transcript *agentstream.Transcript, line []byte) agentstream.Frame {
	t.Helper()
	frame, err := transcript.Send(line)
	if err != nil {
		t.Fatalf("host Send(%q): %v", line, err)
	}
	return frame
}

func mustHostReceive(t *testing.T, transcript *agentstream.Transcript, frame agentstream.Frame, want agentstream.ReceiveResult) {
	t.Helper()
	got, err := transcript.Receive(frame)
	if err != nil {
		t.Fatalf("host Receive(%+v): %v", frame, err)
	}
	if got != want {
		t.Fatalf("host Receive() = %d, want %d", got, want)
	}
}
