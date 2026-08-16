package agentstream

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

var testLimits = Limits{
	MaxLineBytes: 1024,
	MaxLines:     64,
	MaxBytes:     64 * 1024,
}

func TestNewAndDigestValidation(t *testing.T) {
	t.Parallel()

	invalid := []struct {
		name       string
		role       Role
		sessionID  string
		generation uint64
		limits     Limits
	}{
		{name: "zero role", sessionID: "session", generation: 1, limits: testLimits},
		{name: "unknown role", role: Role(3), sessionID: "session", generation: 1, limits: testLimits},
		{name: "empty session", role: Host, generation: 1, limits: testLimits},
		{name: "space in session", role: Host, sessionID: "not safe", generation: 1, limits: testLimits},
		{name: "non ASCII session", role: Host, sessionID: "session-一", generation: 1, limits: testLimits},
		{name: "long session", role: Host, sessionID: strings.Repeat("a", maxSessionIDBytes+1), generation: 1, limits: testLimits},
		{name: "zero generation", role: Host, sessionID: "session", limits: testLimits},
		{name: "zero line limit", role: Host, sessionID: "session", generation: 1, limits: Limits{MaxLines: 1, MaxBytes: 1}},
		{name: "zero count limit", role: Host, sessionID: "session", generation: 1, limits: Limits{MaxLineBytes: 1, MaxBytes: 1}},
		{name: "zero byte limit", role: Host, sessionID: "session", generation: 1, limits: Limits{MaxLineBytes: 1, MaxLines: 1}},
	}
	for _, test := range invalid {
		test := test
		t.Run(test.name, func(t *testing.T) {
			t.Parallel()
			if _, err := New(test.role, test.sessionID, test.generation, test.limits); !errors.Is(err, ErrConfig) {
				t.Fatalf("New() error = %v, want ErrConfig", err)
			}
		})
	}

	transcript := mustNew(t, Host, "session-1:restore_2.test", 7, testLimits)
	empty := Position{Hash: Digest(sha256.Sum256(nil))}
	if got, want := transcript.State(), (State{HostToGuest: empty, GuestToHost: empty}); got != want {
		t.Fatalf("empty state = %+v, want %+v", got, want)
	}

	digest := Digest(sha256.Sum256([]byte("test")))
	encoded, err := digest.MarshalText()
	if err != nil {
		t.Fatalf("MarshalText(): %v", err)
	}
	if got, want := string(encoded), hex.EncodeToString(digest[:]); got != want {
		t.Fatalf("encoded digest = %q, want %q", got, want)
	}
	var decoded Digest
	if err := decoded.UnmarshalText(encoded); err != nil {
		t.Fatalf("UnmarshalText(): %v", err)
	}
	if decoded != digest {
		t.Fatalf("decoded digest = %s, want %s", decoded, digest)
	}
	for _, malformed := range [][]byte{
		[]byte(strings.ToUpper(string(encoded))),
		encoded[:len(encoded)-1],
		[]byte(strings.Repeat("z", sha256.Size*2)),
	} {
		if err := decoded.UnmarshalText(malformed); !errors.Is(err, ErrHash) {
			t.Errorf("UnmarshalText(%q) error = %v, want ErrHash", malformed, err)
		}
	}
	var nilDigest *Digest
	if err := nilDigest.UnmarshalText(encoded); !errors.Is(err, ErrHash) {
		t.Errorf("nil Digest.UnmarshalText() error = %v, want ErrHash", err)
	}
}

func TestSendHashesExactJSONLAndCopiesInput(t *testing.T) {
	t.Parallel()

	host := mustNew(t, Host, "send", 2, testLimits)
	firstLine := []byte(`{"id":1,"method":"tools/call"}`)
	firstOriginal := bytes.Clone(firstLine)
	first := mustSend(t, host, firstLine)
	firstLine[2] = 'X'

	empty := Position{Hash: Digest(sha256.Sum256(nil))}
	firstBytes := append(bytes.Clone(firstOriginal), '\n')
	wantFirst := Position{
		Offset: 1,
		Bytes:  uint64(len(firstBytes)),
		Hash:   Digest(sha256.Sum256(firstBytes)),
	}
	if first.Before != empty || first.After != wantFirst {
		t.Fatalf("first frame positions = %+v -> %+v, want %+v -> %+v", first.Before, first.After, empty, wantFirst)
	}
	if first.Direction != HostToGuest || first.SessionID != "send" || first.Generation != 2 {
		t.Fatalf("first frame identity = %+v", first)
	}
	if !bytes.Equal(first.Line, firstOriginal) {
		t.Fatalf("first frame line = %q, want %q", first.Line, firstOriginal)
	}

	// Returned frames must not alias retained transcript data.
	first.Line[2] = 'Y'
	secondLine := []byte(`{"id":2,"result":{"ok":true}}`)
	second := mustSend(t, host, secondLine)
	prefix := append(bytes.Clone(firstBytes), secondLine...)
	prefix = append(prefix, '\n')
	wantSecond := Position{
		Offset: 2,
		Bytes:  uint64(len(prefix)),
		Hash:   Digest(sha256.Sum256(prefix)),
	}
	if second.Before != wantFirst || second.After != wantSecond {
		t.Fatalf("second frame positions = %+v -> %+v, want %+v -> %+v", second.Before, second.After, wantFirst, wantSecond)
	}
	if got := host.State().HostToGuest; got != wantSecond {
		t.Fatalf("HostToGuest end = %+v, want %+v", got, wantSecond)
	}
	resent, err := host.Resend(empty)
	if err != nil {
		t.Fatalf("Resend(empty): %v", err)
	}
	if len(resent) != 2 || !bytes.Equal(resent[0].Line, firstOriginal) || !bytes.Equal(resent[1].Line, secondLine) {
		t.Fatalf("resent lines = %q, %q", resent[0].Line, resent[1].Line)
	}
}

func TestStrictJSONLObjectLines(t *testing.T) {
	t.Parallel()

	invalid := [][]byte{
		nil,
		{},
		[]byte("null"),
		[]byte("[]"),
		[]byte("1"),
		[]byte(`{"a":1`),
		[]byte(`{"a":1}x`),
		[]byte(`{"a":1} {"b":2}`),
		[]byte("{\"a\":1}\n"),
		[]byte("{\"a\":1}\r"),
		[]byte(`{"a":1,"a":2}`),
		[]byte(`{"outer":{"a":1,"a":2}}`),
		[]byte(`{"array":[{"a":1,"a":2}]}`),
		[]byte(`{"a":NaN}`),
		{'{', '"', 'x', '"', ':', '"', 0xff, '"', '}'},
	}
	for index, line := range invalid {
		transcript := mustNew(t, Host, "json", 1, testLimits)
		before := transcript.State()
		if _, err := transcript.Send(line); !errors.Is(err, ErrInvalidLine) {
			t.Errorf("case %d Send(%q) error = %v, want ErrInvalidLine", index, line, err)
		}
		if got := transcript.State(); got != before {
			t.Errorf("case %d mutated state: got %+v, want %+v", index, got, before)
		}
	}

	valid := [][]byte{
		[]byte(`{}`),
		[]byte(` { "id" : 1 } `),
		[]byte(`{"nested":{"a":[1,true,null,{"b":"c"}]}}`),
		[]byte(`{"large":123456789012345678901234567890}`),
	}
	for index, line := range valid {
		transcript := mustNew(t, Host, "json", 1, testLimits)
		if _, err := transcript.Send(line); err != nil {
			t.Errorf("valid case %d Send(%q): %v", index, line, err)
		}
	}

	tooSmall := mustNew(t, Host, "json", 1, Limits{MaxLineBytes: 2, MaxLines: 2, MaxBytes: 10})
	if _, err := tooSmall.Send([]byte(`{"x":1}`)); !errors.Is(err, ErrLineTooLarge) {
		t.Fatalf("oversized Send error = %v, want ErrLineTooLarge", err)
	}
}

func TestAggregateLineAndByteLimits(t *testing.T) {
	t.Parallel()

	lineLimited := Limits{MaxLineBytes: 32, MaxLines: 2, MaxBytes: 100}
	host, guest := mustPair(t, "line-limit", 1, lineLimited)
	hostFrame := mustSend(t, host, []byte(`{"h":1}`))
	mustReceive(t, guest, hostFrame, Received)
	guestFrame := mustSend(t, guest, []byte(`{"g":1}`))
	mustReceive(t, host, guestFrame, Received)
	if _, err := host.Send([]byte(`{"h":2}`)); !errors.Is(err, ErrLimit) {
		t.Fatalf("third host line error = %v, want ErrLimit", err)
	}
	if _, err := guest.Send([]byte(`{"g":2}`)); !errors.Is(err, ErrLimit) {
		t.Fatalf("third guest line error = %v, want ErrLimit", err)
	}

	line := []byte(`{}`)
	lineBytes := uint64(len(line) + 1)
	byteLimited := Limits{MaxLineBytes: 32, MaxLines: 10, MaxBytes: lineBytes * 2}
	host, guest = mustPair(t, "byte-limit", 1, byteLimited)
	mustReceive(t, guest, mustSend(t, host, line), Received)
	mustReceive(t, host, mustSend(t, guest, line), Received)
	if _, err := host.Send(line); !errors.Is(err, ErrLimit) {
		t.Fatalf("host byte overflow error = %v, want ErrLimit", err)
	}
	if _, err := guest.Send(line); !errors.Is(err, ErrLimit) {
		t.Fatalf("guest byte overflow error = %v, want ErrLimit", err)
	}
}

func TestReceiveNextDuplicateAndFailClosedMutations(t *testing.T) {
	t.Parallel()

	source := mustNew(t, Host, "receive", 4, testLimits)
	frame := mustSend(t, source, []byte(`{"id":1,"method":"initialize"}`))

	mutations := []struct {
		name   string
		mutate func(*Frame)
		want   error
	}{
		{name: "session", mutate: func(frame *Frame) { frame.SessionID = "other" }, want: ErrSession},
		{name: "generation", mutate: func(frame *Frame) { frame.Generation++ }, want: ErrGeneration},
		{name: "direction", mutate: func(frame *Frame) { frame.Direction = GuestToHost }, want: ErrDirection},
		{name: "before offset gap", mutate: func(frame *Frame) { frame.Before.Offset++ }, want: ErrOffset},
		{name: "before bytes", mutate: func(frame *Frame) { frame.Before.Bytes = 3 }, want: ErrOffset},
		{name: "before hash", mutate: func(frame *Frame) { frame.Before.Hash[0] ^= 1 }, want: ErrHash},
		{name: "after offset", mutate: func(frame *Frame) { frame.After.Offset++ }, want: ErrOffset},
		{name: "after bytes", mutate: func(frame *Frame) { frame.After.Bytes++ }, want: ErrOffset},
		{name: "after hash", mutate: func(frame *Frame) { frame.After.Hash[0] ^= 1 }, want: ErrHash},
		{name: "different valid line", mutate: func(frame *Frame) { frame.Line[6] = '2' }, want: ErrHash},
		{name: "newline", mutate: func(frame *Frame) { frame.Line = append(frame.Line, '\n') }, want: ErrInvalidLine},
	}
	for _, mutation := range mutations {
		mutation := mutation
		t.Run(mutation.name, func(t *testing.T) {
			t.Parallel()
			guest := mustNew(t, Guest, "receive", 4, testLimits)
			mutated := cloneFrame(frame)
			mutation.mutate(&mutated)
			before := guest.State()
			if _, err := guest.Receive(mutated); !errors.Is(err, mutation.want) {
				t.Fatalf("Receive() error = %v, want %v", err, mutation.want)
			}
			if got := guest.State(); got != before {
				t.Fatalf("failed Receive mutated state: got %+v, want %+v", got, before)
			}
		})
	}

	guest := mustNew(t, Guest, "receive", 4, testLimits)
	mustReceive(t, guest, frame, Received)
	accepted := guest.State()
	mustReceive(t, guest, frame, Duplicate)
	if got := guest.State(); got != accepted {
		t.Fatalf("duplicate changed state: got %+v, want %+v", got, accepted)
	}
	conflict := cloneFrame(frame)
	conflict.Line[6] = '2'
	if _, err := guest.Receive(conflict); !errors.Is(err, ErrConflict) {
		t.Fatalf("conflicting duplicate error = %v, want ErrConflict", err)
	}
	if got := guest.State(); got != accepted {
		t.Fatalf("conflict changed state: got %+v, want %+v", got, accepted)
	}

	next := mustSend(t, source, []byte(`{"id":2,"method":"initialized"}`))
	gapGuest := mustNew(t, Guest, "receive", 4, testLimits)
	if _, err := gapGuest.Receive(next); !errors.Is(err, ErrOffset) {
		t.Fatalf("gap Receive error = %v, want ErrOffset", err)
	}
	if got := gapGuest.State(); got != (mustNew(t, Guest, "receive", 4, testLimits).State()) {
		t.Fatalf("gap Receive changed state: %+v", got)
	}
}

func TestResendReturnsOnlyMissingSuffix(t *testing.T) {
	t.Parallel()

	host, guest := mustPair(t, "resend", 1, testLimits)
	frames := []Frame{
		mustSend(t, host, []byte(`{"n":1}`)),
		mustSend(t, host, []byte(`{"n":2}`)),
		mustSend(t, host, []byte(`{"n":3}`)),
	}
	mustReceive(t, guest, frames[0], Received)
	guestPrefix := guest.State().HostToGuest
	missing, err := host.Resend(guestPrefix)
	if err != nil {
		t.Fatalf("Resend(guest prefix): %v", err)
	}
	if len(missing) != 2 || missing[0].Before.Offset != 1 || missing[1].Before.Offset != 2 {
		t.Fatalf("missing suffix = %+v", missing)
	}
	missing[0].Line[2] = 'X'
	missingAgain, err := host.Resend(guestPrefix)
	if err != nil {
		t.Fatalf("second Resend(guest prefix): %v", err)
	}
	if !bytes.Equal(missingAgain[0].Line, frames[1].Line) {
		t.Fatalf("caller mutation changed retained frame: got %q, want %q", missingAgain[0].Line, frames[1].Line)
	}
	for _, resent := range missingAgain {
		mustReceive(t, guest, resent, Received)
	}
	if guest.State().HostToGuest != host.State().HostToGuest {
		t.Fatalf("HostToGuest did not converge: host %+v guest %+v", host.State(), guest.State())
	}
	emptySuffix, err := host.Resend(guest.State().HostToGuest)
	if err != nil || len(emptySuffix) != 0 {
		t.Fatalf("Resend(end) = %+v, %v, want empty", emptySuffix, err)
	}

	badHash := guestPrefix
	badHash.Hash[0] ^= 1
	if _, err := host.Resend(badHash); !errors.Is(err, ErrHash) {
		t.Fatalf("Resend(bad hash) error = %v, want ErrHash", err)
	}
	ahead := host.State().HostToGuest
	ahead.Offset++
	ahead.Bytes += 3
	if _, err := host.Resend(ahead); !errors.Is(err, ErrOffset) {
		t.Fatalf("Resend(ahead) error = %v, want ErrOffset", err)
	}

	guestFrame := mustSend(t, guest, []byte(`{"result":1}`))
	guestMissing, err := guest.Resend(host.State().GuestToHost)
	if err != nil || len(guestMissing) != 1 {
		t.Fatalf("guest Resend() = %+v, %v", guestMissing, err)
	}
	if guestMissing[0].Direction != GuestToHost || !bytes.Equal(guestMissing[0].Line, guestFrame.Line) {
		t.Fatalf("guest resend frame = %+v, want %+v", guestMissing[0], guestFrame)
	}
	mustReceive(t, host, guestMissing[0], Received)
}

func TestHelloAttachReconcilesEitherSideAhead(t *testing.T) {
	t.Parallel()

	t.Run("host ahead in HostToGuest", func(t *testing.T) {
		host, guest := mustPair(t, "attach-h", 1, testLimits)
		first := mustSend(t, host, []byte(`{"h":1}`))
		mustReceive(t, guest, first, Received)
		mustSend(t, host, []byte(`{"h":2}`))

		hello, err := guest.Hello()
		if err != nil {
			t.Fatalf("Hello(): %v", err)
		}
		attach, err := host.Attach(hello)
		if err != nil {
			t.Fatalf("Attach(): %v", err)
		}
		if err := guest.AcceptAttach(hello, attach); err != nil {
			t.Fatalf("AcceptAttach(): %v", err)
		}
		missing, err := host.Resend(hello.State.HostToGuest)
		if err != nil || len(missing) != 1 {
			t.Fatalf("Resend() = %+v, %v, want one frame", missing, err)
		}
		mustReceive(t, guest, missing[0], Received)
	})

	t.Run("guest ahead in GuestToHost", func(t *testing.T) {
		host, guest := mustPair(t, "attach-g", 1, testLimits)
		guestFrame := mustSend(t, guest, []byte(`{"g":1}`))

		hello, err := guest.Hello()
		if err != nil {
			t.Fatalf("Hello(): %v", err)
		}
		attach, err := host.Attach(hello)
		if err != nil {
			t.Fatalf("Attach(): %v", err)
		}
		if err := guest.AcceptAttach(hello, attach); err != nil {
			t.Fatalf("AcceptAttach(): %v", err)
		}
		missing, err := guest.Resend(attach.State.GuestToHost)
		if err != nil || len(missing) != 1 {
			t.Fatalf("guest Resend() = %+v, %v, want one frame", missing, err)
		}
		if !bytes.Equal(missing[0].Line, guestFrame.Line) {
			t.Fatalf("resent line = %q, want %q", missing[0].Line, guestFrame.Line)
		}
		mustReceive(t, host, missing[0], Received)
	})

	t.Run("synchronized", func(t *testing.T) {
		host, guest := mustPair(t, "attach-sync", 1, testLimits)
		mustReceive(t, guest, mustSend(t, host, []byte(`{"h":1}`)), Received)
		mustReceive(t, host, mustSend(t, guest, []byte(`{"g":1}`)), Received)
		hello, err := guest.Hello()
		if err != nil {
			t.Fatalf("Hello(): %v", err)
		}
		attach, err := host.Attach(hello)
		if err != nil {
			t.Fatalf("Attach(): %v", err)
		}
		if err := guest.AcceptAttach(hello, attach); err != nil {
			t.Fatalf("AcceptAttach(): %v", err)
		}
		if attach.State != hello.State {
			t.Fatalf("synchronized states differ: hello %+v attach %+v", hello.State, attach.State)
		}
	})
}

func TestHelloAttachRejectsIdentityPrefixAndStalenessMutations(t *testing.T) {
	t.Parallel()

	host, guest := mustPair(t, "attach-bad", 5, testLimits)
	hostFrame := mustSend(t, host, []byte(`{"h":1}`))
	mustReceive(t, guest, hostFrame, Received)
	hello, err := guest.Hello()
	if err != nil {
		t.Fatalf("Hello(): %v", err)
	}

	if _, err := host.Hello(); !errors.Is(err, ErrRole) {
		t.Fatalf("Host.Hello() error = %v, want ErrRole", err)
	}
	if _, err := guest.Attach(hello); !errors.Is(err, ErrRole) {
		t.Fatalf("Guest.Attach() error = %v, want ErrRole", err)
	}
	if err := host.AcceptAttach(hello, Attach{}); !errors.Is(err, ErrRole) {
		t.Fatalf("Host.AcceptAttach() error = %v, want ErrRole", err)
	}

	badHellos := []struct {
		name   string
		mutate func(*Hello)
		want   error
	}{
		{name: "session", mutate: func(hello *Hello) { hello.SessionID = "other" }, want: ErrSession},
		{name: "generation", mutate: func(hello *Hello) { hello.Generation++ }, want: ErrGeneration},
		{name: "claims unsent host line", mutate: func(hello *Hello) {
			hello.State.HostToGuest.Offset++
			hello.State.HostToGuest.Bytes += 3
		}, want: ErrOffset},
		{name: "host prefix hash", mutate: func(hello *Hello) { hello.State.HostToGuest.Hash[0] ^= 1 }, want: ErrHash},
		{name: "empty guest hash", mutate: func(hello *Hello) { hello.State.GuestToHost.Hash[0] ^= 1 }, want: ErrHash},
		{name: "offset beyond bound", mutate: func(hello *Hello) {
			hello.State.GuestToHost.Offset = testLimits.MaxLines + 1
			hello.State.GuestToHost.Bytes = (testLimits.MaxLines + 1) * 3
		}, want: ErrLimit},
		{name: "bytes beyond bound", mutate: func(hello *Hello) { hello.State.GuestToHost.Bytes = testLimits.MaxBytes + 1 }, want: ErrLimit},
	}
	for _, mutation := range badHellos {
		mutation := mutation
		t.Run(mutation.name, func(t *testing.T) {
			bad := hello
			mutation.mutate(&bad)
			if _, err := host.Attach(bad); !errors.Is(err, mutation.want) {
				t.Fatalf("Attach() error = %v, want %v", err, mutation.want)
			}
		})
	}

	attach, err := host.Attach(hello)
	if err != nil {
		t.Fatalf("Attach(): %v", err)
	}
	badAttaches := []struct {
		name   string
		mutate func(*Attach)
		want   error
	}{
		{name: "session", mutate: func(attach *Attach) { attach.SessionID = "other" }, want: ErrSession},
		{name: "generation", mutate: func(attach *Attach) { attach.Generation++ }, want: ErrGeneration},
		{name: "forgets host line", mutate: func(attach *Attach) {
			attach.State.HostToGuest = Position{Hash: Digest(sha256.Sum256(nil))}
		}, want: ErrOffset},
		{name: "host prefix hash", mutate: func(attach *Attach) { attach.State.HostToGuest.Hash[0] ^= 1 }, want: ErrHash},
		{name: "empty guest hash", mutate: func(attach *Attach) { attach.State.GuestToHost.Hash[0] ^= 1 }, want: ErrHash},
		{name: "host claims guest output", mutate: func(attach *Attach) {
			line := []byte("{}\n")
			attach.State.GuestToHost = Position{Offset: 1, Bytes: uint64(len(line)), Hash: Digest(sha256.Sum256(line))}
		}, want: ErrOffset},
	}
	for _, mutation := range badAttaches {
		mutation := mutation
		t.Run(mutation.name, func(t *testing.T) {
			bad := attach
			mutation.mutate(&bad)
			if err := guest.AcceptAttach(hello, bad); !errors.Is(err, mutation.want) {
				t.Fatalf("AcceptAttach() error = %v, want %v", err, mutation.want)
			}
		})
	}

	staleGuest := mustNew(t, Guest, "attach-bad", 5, testLimits)
	mustReceive(t, staleGuest, hostFrame, Received)
	staleHello, err := staleGuest.Hello()
	if err != nil {
		t.Fatalf("stale Hello(): %v", err)
	}
	staleAttach, err := host.Attach(staleHello)
	if err != nil {
		t.Fatalf("stale Attach(): %v", err)
	}
	mustSend(t, staleGuest, []byte(`{"moved":true}`))
	if err := staleGuest.AcceptAttach(staleHello, staleAttach); !errors.Is(err, ErrStaleHello) {
		t.Fatalf("AcceptAttach(stale hello) error = %v, want ErrStaleHello", err)
	}
}

func TestBarrierQuiescenceAndGenerationTransition(t *testing.T) {
	t.Parallel()

	host, guest := mustPair(t, "barrier", 1, testLimits)
	hostFrame := mustSend(t, host, []byte(`{"h":1}`))
	mustReceive(t, guest, hostFrame, Received)
	guestFrame := mustSend(t, guest, []byte(`{"g":1}`))
	mustReceive(t, host, guestFrame, Received)

	hostBarrier := host.Barrier()
	guestBarrier := guest.Barrier()
	assertQuiescent(t, host, hostBarrier, guestBarrier, true)
	assertQuiescent(t, guest, guestBarrier, hostBarrier, true)

	behind := guestBarrier
	behind.State.HostToGuest = hostFrame.Before
	assertQuiescent(t, host, hostBarrier, behind, false)
	badHash := guestBarrier
	badHash.State.HostToGuest.Hash[0] ^= 1
	if _, err := host.Quiescent(hostBarrier, badHash); !errors.Is(err, ErrHash) {
		t.Fatalf("Quiescent(bad hash) error = %v, want ErrHash", err)
	}
	wrongSession := guestBarrier
	wrongSession.SessionID = "other"
	if _, err := host.Quiescent(hostBarrier, wrongSession); !errors.Is(err, ErrSession) {
		t.Fatalf("Quiescent(wrong session) error = %v, want ErrSession", err)
	}
	wrongGeneration := guestBarrier
	wrongGeneration.Generation++
	if _, err := host.Quiescent(hostBarrier, wrongGeneration); !errors.Is(err, ErrGeneration) {
		t.Fatalf("Quiescent(wrong generation) error = %v, want ErrGeneration", err)
	}

	if err := host.AdvanceGeneration(3, hostBarrier, guestBarrier); err != nil {
		t.Fatalf("host AdvanceGeneration(): %v", err)
	}
	if err := guest.AdvanceGeneration(3, guestBarrier, hostBarrier); err != nil {
		t.Fatalf("guest AdvanceGeneration(): %v", err)
	}
	if _, err := guest.Receive(hostFrame); !errors.Is(err, ErrGeneration) {
		t.Fatalf("old-generation Receive error = %v, want ErrGeneration", err)
	}
	newHello, err := guest.Hello()
	if err != nil {
		t.Fatalf("new-generation Hello(): %v", err)
	}
	if newHello.Generation != 3 {
		t.Fatalf("new Hello generation = %d, want 3", newHello.Generation)
	}
	newAttach, err := host.Attach(newHello)
	if err != nil {
		t.Fatalf("new-generation Attach(): %v", err)
	}
	if err := guest.AcceptAttach(newHello, newAttach); err != nil {
		t.Fatalf("new-generation AcceptAttach(): %v", err)
	}
	if err := host.AdvanceGeneration(3, host.Barrier(), guest.Barrier()); !errors.Is(err, ErrGeneration) {
		t.Fatalf("non-increasing AdvanceGeneration error = %v, want ErrGeneration", err)
	}
}

func TestBarrierRejectsStaleAndNonQuiescentTransition(t *testing.T) {
	t.Parallel()

	host, guest := mustPair(t, "not-quiescent", 1, testLimits)
	hostBarrier := host.Barrier()
	guestBarrier := guest.Barrier()
	mustSend(t, host, []byte(`{"pending":true}`))
	if _, err := host.Quiescent(hostBarrier, guestBarrier); !errors.Is(err, ErrStaleBarrier) {
		t.Fatalf("Quiescent(stale ours) error = %v, want ErrStaleBarrier", err)
	}
	if err := host.AdvanceGeneration(2, hostBarrier, guestBarrier); !errors.Is(err, ErrStaleBarrier) {
		t.Fatalf("AdvanceGeneration(stale ours) error = %v, want ErrStaleBarrier", err)
	}

	currentHost := host.Barrier()
	currentGuest := guest.Barrier()
	assertQuiescent(t, host, currentHost, currentGuest, false)
	if err := host.AdvanceGeneration(2, currentHost, currentGuest); !errors.Is(err, ErrNotQuiescent) {
		t.Fatalf("AdvanceGeneration(non-quiescent) error = %v, want ErrNotQuiescent", err)
	}
}

func TestAttachRejectsHostAheadGuestToHostAfterRestore(t *testing.T) {
	t.Parallel()

	host, originalGuest := mustPair(t, "restore", 1, testLimits)
	hostLine := []byte(`{"id":1,"method":"tool"}`)
	hostFrame := mustSend(t, host, hostLine)
	mustReceive(t, originalGuest, hostFrame, Received)
	firstResultLine := []byte(`{"id":1,"result":"started"}`)
	firstResult := mustSend(t, originalGuest, firstResultLine)
	mustReceive(t, host, firstResult, Received)

	// This is the durable snapshot point. The Host then retains one additional
	// GuestToHost result that the restored Guest no longer remembers.
	secondResultLine := []byte(`{"id":1,"result":"complete"}`)
	secondResult := mustSend(t, originalGuest, secondResultLine)
	mustReceive(t, host, secondResult, Received)

	restoredGuest := restoreGuestAtFirstResult(t, hostFrame, firstResultLine)
	hello, err := restoredGuest.Hello()
	if err != nil {
		t.Fatalf("restored Hello(): %v", err)
	}
	before := host.State()
	if _, err := host.Attach(hello); !errors.Is(err, ErrOffset) {
		t.Fatalf("Attach(restored Guest missing GuestToHost suffix) error = %v, want ErrOffset", err)
	}
	if got := host.State(); got != before {
		t.Fatalf("rejected attach mutated Host: got %+v, want %+v", got, before)
	}
}

func TestRemoteStateBoundsFailClosed(t *testing.T) {
	t.Parallel()

	limits := Limits{MaxLineBytes: 8, MaxLines: 4, MaxBytes: 24}
	host, guest := mustPair(t, "bounds", 1, limits)
	hello, err := guest.Hello()
	if err != nil {
		t.Fatalf("Hello(): %v", err)
	}
	empty := hello.State.GuestToHost
	tests := []struct {
		name string
		pos  Position
		want error
	}{
		{name: "empty bytes", pos: Position{Bytes: 1, Hash: empty.Hash}, want: ErrOffset},
		{name: "empty hash", pos: Position{}, want: ErrHash},
		{name: "too many lines", pos: Position{Offset: 5, Bytes: 15}, want: ErrLimit},
		{name: "too many bytes", pos: Position{Offset: 1, Bytes: 25}, want: ErrLimit},
		{name: "too few bytes", pos: Position{Offset: 2, Bytes: 5}, want: ErrOffset},
		{name: "over max line average", pos: Position{Offset: 2, Bytes: 19}, want: ErrLimit},
	}
	for _, test := range tests {
		test := test
		t.Run(test.name, func(t *testing.T) {
			bad := hello
			bad.State.GuestToHost = test.pos
			if _, err := host.Attach(bad); !errors.Is(err, test.want) {
				t.Fatalf("Attach() error = %v, want %v", err, test.want)
			}
		})
	}

	combined := hello
	combined.State.HostToGuest = Position{Offset: 3, Bytes: 9, Hash: empty.Hash}
	combined.State.GuestToHost = Position{Offset: 2, Bytes: 6, Hash: empty.Hash}
	if _, err := host.Attach(combined); !errors.Is(err, ErrLimit) {
		t.Fatalf("Attach(aggregate lines) error = %v, want ErrLimit", err)
	}
}

func TestProtocolValuesRoundTripJSON(t *testing.T) {
	t.Parallel()

	host := mustNew(t, Host, "json-wire", 9, testLimits)
	frame := mustSend(t, host, []byte(`{"id":7}`))
	encoded, err := json.Marshal(frame)
	if err != nil {
		t.Fatalf("json.Marshal(Frame): %v", err)
	}
	var decoded Frame
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("json.Unmarshal(Frame): %v", err)
	}
	if !framesEqual(frame, decoded) {
		t.Fatalf("JSON frame round trip differs:\n got %+v\nwant %+v\nwire %s", decoded, frame, encoded)
	}

	uppercase := bytes.Replace(encoded, []byte(frame.After.Hash.String()), []byte(strings.ToUpper(frame.After.Hash.String())), 1)
	if bytes.Equal(uppercase, encoded) {
		t.Fatal("test did not find encoded digest")
	}
	if err := json.Unmarshal(uppercase, &decoded); !errors.Is(err, ErrHash) {
		t.Fatalf("uppercase digest unmarshal error = %v, want ErrHash", err)
	}
}

func restoreGuestAtFirstResult(t *testing.T, hostFrame Frame, firstResultLine []byte) *Transcript {
	t.Helper()
	restored := mustNew(t, Guest, hostFrame.SessionID, hostFrame.Generation, testLimits)
	mustReceive(t, restored, hostFrame, Received)
	mustSend(t, restored, firstResultLine)
	return restored
}

func mustPair(t *testing.T, sessionID string, generation uint64, limits Limits) (*Transcript, *Transcript) {
	t.Helper()
	return mustNew(t, Host, sessionID, generation, limits), mustNew(t, Guest, sessionID, generation, limits)
}

func mustNew(t *testing.T, role Role, sessionID string, generation uint64, limits Limits) *Transcript {
	t.Helper()
	transcript, err := New(role, sessionID, generation, limits)
	if err != nil {
		t.Fatalf("New(%d, %q, %d): %v", role, sessionID, generation, err)
	}
	return transcript
}

func mustSend(t *testing.T, transcript *Transcript, line []byte) Frame {
	t.Helper()
	frame, err := transcript.Send(line)
	if err != nil {
		t.Fatalf("Send(%q): %v", line, err)
	}
	return frame
}

func mustReceive(t *testing.T, transcript *Transcript, frame Frame, want ReceiveResult) {
	t.Helper()
	got, err := transcript.Receive(frame)
	if err != nil {
		t.Fatalf("Receive(%+v): %v", frame, err)
	}
	if got != want {
		t.Fatalf("Receive() = %d, want %d", got, want)
	}
}

func assertQuiescent(t *testing.T, transcript *Transcript, ours, peer Barrier, want bool) {
	t.Helper()
	got, err := transcript.Quiescent(ours, peer)
	if err != nil {
		t.Fatalf("Quiescent(): %v", err)
	}
	if got != want {
		t.Fatalf("Quiescent() = %t, want %t", got, want)
	}
}

func cloneFrame(frame Frame) Frame {
	cloned := frame
	cloned.Line = bytes.Clone(frame.Line)
	return cloned
}

func framesEqual(left, right Frame) bool {
	return left.SessionID == right.SessionID &&
		left.Generation == right.Generation &&
		left.Direction == right.Direction &&
		left.Before == right.Before &&
		left.After == right.After &&
		bytes.Equal(left.Line, right.Line)
}
