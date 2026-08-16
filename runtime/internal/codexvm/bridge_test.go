package codexvm

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentstream"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentwire"
)

func TestBridgeHoldsToolCallAcrossQuiescentGenerationAdvance(t *testing.T) {
	inputReader, inputWriter := io.Pipe()
	defer inputWriter.Close()
	var output lockedBuffer
	bridge, err := NewBridge("session-bridge", inputReader, &output, log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	bridge.StartInput(ctx)

	guest, err := agentstream.New(agentstream.Guest, "session-bridge", 1, bridgeLimits)
	if err != nil {
		t.Fatal(err)
	}
	hostOne, guestOne := net.Pipe()
	servedOne := make(chan error, 1)
	go func() { servedOne <- bridge.ServeConnection(ctx, hostOne) }()
	readerOne, writerOne := attachTestGuest(t, guestOne, guest, nil)
	if err := bridge.WaitAttached(ctx, 1); err != nil {
		t.Fatal(err)
	}
	// Attach is durable state, not a consumable notification.
	if err := bridge.WaitAttached(ctx, 1); err != nil {
		t.Fatal(err)
	}

	inputLine := []byte(`{"id":1,"method":"initialize","params":{}}`)
	if _, err := inputWriter.Write(append(bytes.Clone(inputLine), '\n')); err != nil {
		t.Fatal(err)
	}
	inputMessage := readWireWithDeadline(t, guestOne, readerOne)
	if inputMessage.Type != agentwire.TypeFrame || inputMessage.Frame == nil {
		t.Fatalf("guest input message = %+v", inputMessage)
	}
	if result, err := guest.Receive(*inputMessage.Frame); err != nil || result != agentstream.Received || !bytes.Equal(inputMessage.Frame.Line, inputLine) {
		t.Fatalf("guest input receive result=%v err=%v line=%q", result, err, inputMessage.Frame.Line)
	}

	normalLine := []byte(`{"id":1,"result":{"ok":true}}`)
	normalFrame, err := guest.Send(normalLine)
	if err != nil {
		t.Fatal(err)
	}
	if err := writerOne.Write(agentwire.Message{Type: agentwire.TypeFrame, Frame: &normalFrame}); err != nil {
		t.Fatal(err)
	}
	waitForContains(t, &output, string(normalLine))
	// An identical transport replay is accepted but never emitted twice.
	if err := writerOne.Write(agentwire.Message{Type: agentwire.TypeFrame, Frame: &normalFrame}); err != nil {
		t.Fatal(err)
	}
	time.Sleep(20 * time.Millisecond)
	if strings.Count(output.String(), string(normalLine)) != 1 {
		t.Fatalf("duplicate output was emitted: %s", output.String())
	}

	toolLine := []byte(`{"id":9,"method":"item/tool/call","params":{"callId":"call-1","threadId":"thread-1","turnId":"turn-1"}}`)
	toolFrame, err := guest.Send(toolLine)
	if err != nil {
		t.Fatal(err)
	}
	if err := writerOne.Write(agentwire.Message{Type: agentwire.TypeFrame, Frame: &toolFrame}); err != nil {
		t.Fatal(err)
	}
	barrierMessage := readWireWithDeadline(t, guestOne, readerOne)
	if barrierMessage.Type != agentwire.TypeBarrier || barrierMessage.Barrier == nil {
		t.Fatalf("barrier message = %+v", barrierMessage)
	}
	guestBarrier := guest.Barrier()
	quiescent, err := guest.Quiescent(guestBarrier, *barrierMessage.Barrier)
	if err != nil || !quiescent {
		t.Fatalf("guest barrier quiescent=%v err=%v", quiescent, err)
	}
	if err := writerOne.Write(agentwire.Message{Type: agentwire.TypeBarrierAck, Barrier: &guestBarrier}); err != nil {
		t.Fatal(err)
	}
	checkpoint, err := bridge.WaitCheckpoint(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(output.String(), string(toolLine)) {
		t.Fatal("tool callback escaped before restore")
	}
	_ = guestOne.Close()
	if err := <-servedOne; !errors.Is(err, ErrDisconnected) {
		t.Fatalf("first connection result = %v", err)
	}
	// More same-generation reconnects than the old notification buffer could
	// hold must not hide the later restored-generation attach.
	for index := 0; index < 6; index++ {
		hostReconnect, guestReconnect := net.Pipe()
		servedReconnect := make(chan error, 1)
		go func() { servedReconnect <- bridge.ServeConnection(ctx, hostReconnect) }()
		_, _ = attachTestGuest(t, guestReconnect, guest, nil)
		_ = guestReconnect.Close()
		if err := <-servedReconnect; !errors.Is(err, ErrDisconnected) {
			t.Fatalf("g1 reconnect %d result = %v", index, err)
		}
	}

	if err := bridge.AdvanceGeneration(3, checkpoint); err != nil {
		t.Fatal(err)
	}
	hostThree, guestThree := net.Pipe()
	servedThree := make(chan error, 1)
	go func() { servedThree <- bridge.ServeConnection(ctx, hostThree) }()
	readerThree, writerThree := attachTestGuest(t, guestThree, guest, &checkpoint)
	if err := bridge.WaitAttached(ctx, 3); err != nil {
		t.Fatal(err)
	}
	if err := bridge.ReleaseToolCall(); err != nil {
		t.Fatal(err)
	}
	waitForContains(t, &output, string(toolLine))
	if strings.Count(output.String(), string(toolLine)) != 1 {
		t.Fatalf("tool callback emission count differs: %s", output.String())
	}
	responseLine := []byte(`{"id":9,"result":{"contentItems":[{"type":"inputText","text":"receipt"}],"success":true}}`)
	if _, err := inputWriter.Write(append(bytes.Clone(responseLine), '\n')); err != nil {
		t.Fatal(err)
	}
	responseMessage := readWireWithDeadline(t, guestThree, readerThree)
	if responseMessage.Type != agentwire.TypeFrame || responseMessage.Frame == nil {
		t.Fatalf("protected callback response message = %+v", responseMessage)
	}
	if result, err := guest.Receive(*responseMessage.Frame); err != nil || result != agentstream.Received || !bytes.Equal(responseMessage.Frame.Line, responseLine) {
		t.Fatalf("protected callback receive result=%v err=%v line=%q", result, err, responseMessage.Frame.Line)
	}
	terminalLine := []byte(`{"method":"turn/completed","params":{"threadId":"thread-1","turn":{"id":"turn-1","status":"completed","error":null}}}`)
	terminalFrame, err := guest.Send(terminalLine)
	if err != nil {
		t.Fatal(err)
	}
	if err := writerThree.Write(agentwire.Message{Type: agentwire.TypeFrame, Frame: &terminalFrame}); err != nil {
		t.Fatal(err)
	}
	waitForContains(t, &output, string(terminalLine))
	if err := inputWriter.Close(); err != nil {
		t.Fatal(err)
	}
	if err := bridge.Wait(ctx); err != nil {
		t.Fatalf("completed bridge wait = %v", err)
	}
	shutdownResult := make(chan error, 1)
	go func() { shutdownResult <- bridge.ShutdownGuest() }()
	shutdown := readWireWithDeadline(t, guestThree, readerThree)
	if shutdown.Type != agentwire.TypeShutdown {
		t.Fatalf("guest shutdown message = %+v", shutdown)
	}
	if err := <-shutdownResult; err != nil {
		t.Fatal(err)
	}
	_ = guestThree.Close()
	if err := <-servedThree; !errors.Is(err, ErrDisconnected) {
		t.Fatalf("restored connection result = %v", err)
	}
}

func TestBridgeRejectsInputEOFBeforeProtectedTurnCompletion(t *testing.T) {
	bridge, err := NewBridge("session-incomplete", strings.NewReader(""), io.Discard, log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	bridge.StartInput(ctx)
	if err := bridge.Wait(ctx); !errors.Is(err, ErrIncompleteSession) {
		t.Fatalf("incomplete bridge wait = %v, want %v", err, ErrIncompleteSession)
	}
}

func TestBridgeRejectsWrongGenerationHello(t *testing.T) {
	bridge, err := NewBridge("session-wrong", strings.NewReader(""), io.Discard, log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	host, guestConnection := net.Pipe()
	done := make(chan error, 1)
	go func() { done <- bridge.ServeConnection(ctx, host) }()
	reader, _ := agentwire.NewReader(guestConnection)
	writer, _ := agentwire.NewWriter(guestConnection)
	if message, err := reader.Read(); err != nil || message.Type != agentwire.TypeRole {
		t.Fatalf("role=%+v err=%v", message, err)
	}
	wrong, _ := agentstream.New(agentstream.Guest, "session-wrong", 2, bridgeLimits)
	hello, _ := wrong.Hello()
	if err := writer.Write(agentwire.Message{Type: agentwire.TypeHello, Hello: &hello}); err != nil {
		t.Fatal(err)
	}
	if err := <-done; !errors.Is(err, agentstream.ErrGeneration) {
		t.Fatalf("wrong generation result = %v", err)
	}
	_ = guestConnection.Close()
}

func TestBridgeResendsBarrierAfterDisconnectBeforeGuestReceivesIt(t *testing.T) {
	testBridgeBarrierReconnect(t, false)
}

func TestBridgeResendsBarrierAfterAcknowledgementIsLost(t *testing.T) {
	testBridgeBarrierReconnect(t, true)
}

func testBridgeBarrierReconnect(t *testing.T, receiveFirstBarrier bool) {
	t.Helper()
	bridge, err := NewBridge("session-barrier-reconnect", strings.NewReader(""), io.Discard, log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	guest, err := agentstream.New(agentstream.Guest, "session-barrier-reconnect", 1, bridgeLimits)
	if err != nil {
		t.Fatal(err)
	}

	hostOne, guestOne := net.Pipe()
	servedOne := make(chan error, 1)
	go func() { servedOne <- bridge.ServeConnection(ctx, hostOne) }()
	readerOne, writerOne := attachTestGuest(t, guestOne, guest, nil)
	toolFrame, err := guest.Send([]byte(`{"id":9,"method":"item/tool/call","params":{"callId":"call-reconnect","threadId":"thread-reconnect","turnId":"turn-reconnect"}}`))
	if err != nil {
		t.Fatal(err)
	}
	if err := writerOne.Write(agentwire.Message{Type: agentwire.TypeFrame, Frame: &toolFrame}); err != nil {
		t.Fatal(err)
	}
	var firstBarrier agentstream.Barrier
	if receiveFirstBarrier {
		message := readWireWithDeadline(t, guestOne, readerOne)
		if message.Type != agentwire.TypeBarrier || message.Barrier == nil {
			t.Fatalf("first barrier message = %+v", message)
		}
		firstBarrier = *message.Barrier
	}
	_ = guestOne.Close()
	if err := <-servedOne; !errors.Is(err, ErrDisconnected) {
		t.Fatalf("first connection result = %v", err)
	}

	hostTwo, guestTwo := net.Pipe()
	servedTwo := make(chan error, 1)
	go func() { servedTwo <- bridge.ServeConnection(ctx, hostTwo) }()
	readerTwo, writerTwo := attachTestGuest(t, guestTwo, guest, nil)
	repeated := readWireWithDeadline(t, guestTwo, readerTwo)
	if repeated.Type != agentwire.TypeBarrier || repeated.Barrier == nil {
		t.Fatalf("repeated barrier message = %+v", repeated)
	}
	if receiveFirstBarrier && *repeated.Barrier != firstBarrier {
		t.Fatalf("repeated barrier = %+v, want %+v", *repeated.Barrier, firstBarrier)
	}
	guestBarrier := guest.Barrier()
	quiescent, err := guest.Quiescent(guestBarrier, *repeated.Barrier)
	if err != nil || !quiescent {
		t.Fatalf("repeated barrier quiescent=%v err=%v", quiescent, err)
	}
	if err := writerTwo.Write(agentwire.Message{Type: agentwire.TypeBarrierAck, Barrier: &guestBarrier}); err != nil {
		t.Fatal(err)
	}
	checkpoint, err := bridge.WaitCheckpoint(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if checkpoint.HostBarrier != *repeated.Barrier || checkpoint.GuestBarrier != guestBarrier {
		t.Fatalf("checkpoint = %+v", checkpoint)
	}
	_ = guestTwo.Close()
	if err := <-servedTwo; !errors.Is(err, ErrDisconnected) {
		t.Fatalf("second connection result = %v", err)
	}
}

func TestWorkspaceBridgeMapsOnlyExactThreadStartCWD(t *testing.T) {
	host := "/tmp/host-workspace"
	guest := "/workspace"
	line := []byte(`{"jsonrpc":"2.0","id":7,"method":"thread/start","params":{"cwd":"/tmp/host-workspace","ephemeral":false}}`)
	mapped, err := mapThreadStartWorkspace(line, host, guest)
	if err != nil {
		t.Fatal(err)
	}
	object, err := decodeRawObject(mapped, "mapped request")
	if err != nil {
		t.Fatal(err)
	}
	params, err := decodeRawObject(object["params"], "mapped params")
	if err != nil {
		t.Fatal(err)
	}
	var cwd string
	if err := json.Unmarshal(params["cwd"], &cwd); err != nil {
		t.Fatal(err)
	}
	if cwd != guest {
		t.Fatalf("mapped cwd = %q, want %q", cwd, guest)
	}

	unchanged := []byte(`{"id":8,"method":"turn/start","params":{"cwd":"/tmp/host-workspace"}}`)
	got, err := mapThreadStartWorkspace(unchanged, host, guest)
	if err != nil || !bytes.Equal(got, unchanged) {
		t.Fatalf("non-thread/start changed to %q, error %v", got, err)
	}
	for _, invalid := range [][]byte{
		[]byte(`{"method":"thread/start","params":{"cwd":"/different"}}`),
		[]byte(`{"method":"thread/start","params":{}}`),
		[]byte(`{"method":"thread/start","method":"turn/start","params":{"cwd":"/tmp/host-workspace"}}`),
	} {
		if _, err := mapThreadStartWorkspace(invalid, host, guest); err == nil {
			t.Fatalf("invalid workspace request accepted: %s", invalid)
		}
	}
}

func TestWorkspaceBridgeSendsMappedRequestToGuest(t *testing.T) {
	inputReader, inputWriter := io.Pipe()
	defer inputWriter.Close()
	var auditMu sync.Mutex
	var auditPhases []string
	var auditDirections []string
	var auditLines [][]byte
	bridge, err := NewAuditedWorkspaceBridge(
		"session-workspace", inputReader, io.Discard, log.New(io.Discard, "", 0),
		"/tmp/host-workspace", "/workspace",
		func(phase, direction string, line []byte) error {
			auditMu.Lock()
			defer auditMu.Unlock()
			auditPhases = append(auditPhases, phase)
			auditDirections = append(auditDirections, direction)
			auditLines = append(auditLines, bytes.Clone(line))
			return nil
		},
	)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	bridge.StartInput(ctx)
	host, guestConnection := net.Pipe()
	served := make(chan error, 1)
	go func() { served <- bridge.ServeConnection(ctx, host) }()
	guest, err := agentstream.New(agentstream.Guest, "session-workspace", 1, bridgeLimits)
	if err != nil {
		t.Fatal(err)
	}
	reader, _ := attachTestGuest(t, guestConnection, guest, nil)
	request := []byte(`{"id":1,"method":"thread/start","params":{"cwd":"/tmp/host-workspace"}}`)
	if _, err := inputWriter.Write(append(request, '\n')); err != nil {
		t.Fatal(err)
	}
	message := readWireWithDeadline(t, guestConnection, reader)
	if message.Frame == nil || !bytes.Contains(message.Frame.Line, []byte(`"cwd":"/workspace"`)) || bytes.Contains(message.Frame.Line, []byte(hostWorkspaceSentinel)) {
		t.Fatalf("mapped guest frame = %+v", message)
	}
	auditMu.Lock()
	if len(auditLines) != 1 || auditPhases[0] != PhaseObserved || auditDirections[0] != DirectionClientToServer || !bytes.Equal(auditLines[0], request) {
		t.Fatalf("client-visible audit phases=%v directions=%v lines=%q", auditPhases, auditDirections, auditLines)
	}
	auditMu.Unlock()
	_ = guestConnection.Close()
	if err := <-served; !errors.Is(err, ErrDisconnected) {
		t.Fatalf("workspace connection result = %v", err)
	}
}

func TestAuditedWorkspaceBridgeCommitsMappedOutput(t *testing.T) {
	var output bytes.Buffer
	var phases, directions []string
	var committed [][]byte
	bridge, err := NewAuditedWorkspaceBridge(
		"session-audited-output", strings.NewReader(""), &output, log.New(io.Discard, "", 0),
		"/tmp/host-workspace", "/workspace",
		func(phase, direction string, line []byte) error {
			phases = append(phases, phase)
			directions = append(directions, direction)
			committed = append(committed, bytes.Clone(line))
			return nil
		},
	)
	if err != nil {
		t.Fatal(err)
	}
	mapped, err := bridge.mapGuestOutput([]byte(`{"id":1,"result":{"cwd":"/workspace"}}`))
	if err != nil {
		t.Fatal(err)
	}
	bridge.mu.Lock()
	ticket := bridge.reserveOutputLocked()
	bridge.mu.Unlock()
	if err := bridge.writeOutput(ticket, mapped); err != nil {
		t.Fatal(err)
	}
	want := []byte(`{"id":1,"result":{"cwd":"/tmp/host-workspace"}}`)
	if !reflect.DeepEqual(phases, []string{PhaseAuthorized, PhaseDelivered}) ||
		!reflect.DeepEqual(directions, []string{DirectionServerToClient, DirectionServerToClient}) ||
		len(committed) != 2 || !bytes.Equal(committed[0], want) || !bytes.Equal(committed[1], want) || output.String() != string(want)+"\n" {
		t.Fatalf("phases=%v directions=%v committed=%q output=%q", phases, directions, committed, output.String())
	}
}

func TestBridgeOutputTicketsPreserveOrderWhileFirstWriteBlocks(t *testing.T) {
	output := &blockingFirstOutput{entered: make(chan struct{}), release: make(chan struct{})}
	bridge, err := NewBridge("session-output-order", strings.NewReader(""), output, log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	bridge.mu.Lock()
	first, second := bridge.reserveOutputLocked(), bridge.reserveOutputLocked()
	bridge.mu.Unlock()
	firstDone := make(chan error, 1)
	secondDone := make(chan error, 1)
	go func() { firstDone <- bridge.writeOutput(first, []byte(`{"id":1}`)) }()
	select {
	case <-output.entered:
	case <-time.After(time.Second):
		t.Fatal("first output did not block")
	}
	go func() { secondDone <- bridge.writeOutput(second, []byte(`{"id":2}`)) }()
	select {
	case err := <-secondDone:
		t.Fatalf("second output completed before first: %v", err)
	case <-time.After(20 * time.Millisecond):
	}
	close(output.release)
	if err := <-firstDone; err != nil {
		t.Fatal(err)
	}
	if err := <-secondDone; err != nil {
		t.Fatal(err)
	}
	if got := output.String(); got != "{\"id\":1}\n{\"id\":2}\n" {
		t.Fatalf("ordered output = %q", got)
	}
}

func TestReadBridgeLinePreservesCRAndRejectsUnterminatedInput(t *testing.T) {
	reader := bufio.NewReaderSize(strings.NewReader("{\"id\":1}\r\n"), 4)
	line, err := readBridgeLine(reader, 64)
	if err != nil {
		t.Fatal(err)
	}
	if string(line) != "{\"id\":1}\r" {
		t.Fatalf("CRLF payload = %q", line)
	}
	if _, err := readBridgeLine(bufio.NewReader(strings.NewReader(`{"id":1}`)), 64); !errors.Is(err, io.ErrUnexpectedEOF) {
		t.Fatalf("unterminated input error = %v, want unexpected EOF", err)
	}
	if _, err := readBridgeLine(bufio.NewReader(strings.NewReader("12345\n")), 4); err == nil || !strings.Contains(err.Error(), "exceeds") {
		t.Fatalf("oversized input error = %v", err)
	}
}

func TestMapGuestWorkspaceRestoresClientVisiblePaths(t *testing.T) {
	line := []byte(`{"id":2,"result":{"cwd":"/workspace","thread":{"cwd":"/workspace/sub"},"runtimeWorkspaceRoots":["/workspace"],"text":"/workspace","arguments":{"cwd":"/workspace/private"}}}`)
	mapped, err := mapGuestWorkspace(line, "/workspace", "/tmp/host-workspace")
	if err != nil {
		t.Fatal(err)
	}
	var output map[string]any
	if err := json.Unmarshal(mapped, &output); err != nil {
		t.Fatal(err)
	}
	result := output["result"].(map[string]any)
	if result["cwd"] != "/tmp/host-workspace" {
		t.Fatalf("result cwd = %v", result["cwd"])
	}
	thread := result["thread"].(map[string]any)
	if thread["cwd"] != "/tmp/host-workspace/sub" {
		t.Fatalf("thread cwd = %v", thread["cwd"])
	}
	roots := result["runtimeWorkspaceRoots"].([]any)
	if len(roots) != 1 || roots[0] != "/tmp/host-workspace" {
		t.Fatalf("runtime roots = %v", roots)
	}
	if result["text"] != "/workspace" {
		t.Fatalf("unrelated text was rewritten: %v", result["text"])
	}
	arguments := result["arguments"].(map[string]any)
	if arguments["cwd"] != "/workspace/private" {
		t.Fatalf("dynamic tool arguments were rewritten: %v", arguments)
	}

	unchanged := []byte(`{"method":"notice","params":{"text":"/workspace"}}`)
	got, err := mapGuestWorkspace(unchanged, "/workspace", "/tmp/host-workspace")
	if err != nil || !bytes.Equal(got, unchanged) {
		t.Fatalf("unrelated output changed to %q, error %v", got, err)
	}
}

const hostWorkspaceSentinel = "/tmp/host-workspace"

func attachTestGuest(t *testing.T, connection net.Conn, transcript *agentstream.Transcript, checkpoint *Checkpoint) (*agentwire.Reader, *agentwire.Writer) {
	t.Helper()
	reader, err := agentwire.NewReader(connection)
	if err != nil {
		t.Fatal(err)
	}
	writer, err := agentwire.NewWriter(connection)
	if err != nil {
		t.Fatal(err)
	}
	message := readWireWithDeadline(t, connection, reader)
	if checkpoint == nil {
		if message.Type != agentwire.TypeRole || message.Generation != 1 {
			t.Fatalf("initial role = %+v", message)
		}
	} else {
		if message.Type != agentwire.TypeAdvance || message.Generation != 3 || message.HostBarrier == nil || message.GuestBarrier == nil {
			t.Fatalf("advance = %+v", message)
		}
		if err := transcript.AdvanceGeneration(3, checkpoint.GuestBarrier, checkpoint.HostBarrier); err != nil {
			t.Fatal(err)
		}
	}
	hello, err := transcript.Hello()
	if err != nil {
		t.Fatal(err)
	}
	if err := writer.Write(agentwire.Message{Type: agentwire.TypeHello, Hello: &hello}); err != nil {
		t.Fatal(err)
	}
	attachMessage := readWireWithDeadline(t, connection, reader)
	if attachMessage.Type != agentwire.TypeAttach || attachMessage.Attach == nil {
		t.Fatalf("attach = %+v", attachMessage)
	}
	if err := transcript.AcceptAttach(hello, *attachMessage.Attach); err != nil {
		t.Fatal(err)
	}
	return reader, writer
}

func readWireWithDeadline(t *testing.T, connection net.Conn, reader *agentwire.Reader) agentwire.Message {
	t.Helper()
	if err := connection.SetReadDeadline(time.Now().Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	message, err := reader.Read()
	_ = connection.SetReadDeadline(time.Time{})
	if err != nil {
		t.Fatal(err)
	}
	return message
}

func waitForContains(t *testing.T, buffer *lockedBuffer, substring string) {
	t.Helper()
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		if strings.Contains(buffer.String(), substring) {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("output %q does not contain %q", buffer.String(), substring)
}

type lockedBuffer struct {
	mu     sync.Mutex
	buffer bytes.Buffer
}

type blockingFirstOutput struct {
	mu      sync.Mutex
	buffer  bytes.Buffer
	entered chan struct{}
	release chan struct{}
	once    sync.Once
}

func (output *blockingFirstOutput) Write(data []byte) (int, error) {
	output.once.Do(func() {
		close(output.entered)
		<-output.release
	})
	output.mu.Lock()
	defer output.mu.Unlock()
	return output.buffer.Write(data)
}

func (output *blockingFirstOutput) String() string {
	output.mu.Lock()
	defer output.mu.Unlock()
	return output.buffer.String()
}

func (buffer *lockedBuffer) Write(data []byte) (int, error) {
	buffer.mu.Lock()
	defer buffer.mu.Unlock()
	return buffer.buffer.Write(data)
}

func (buffer *lockedBuffer) String() string {
	buffer.mu.Lock()
	defer buffer.mu.Unlock()
	return buffer.buffer.String()
}
