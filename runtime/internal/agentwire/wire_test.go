package agentwire

import (
	"bytes"
	"errors"
	"io"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentstream"
)

func TestMessageRoundTripAndCanonicalDigestText(t *testing.T) {
	transcript, err := agentstream.New(agentstream.Guest, "session-1", 1, agentstream.Limits{MaxLineBytes: 1024, MaxLines: 10, MaxBytes: 4096})
	if err != nil {
		t.Fatal(err)
	}
	hello, err := transcript.Hello()
	if err != nil {
		t.Fatal(err)
	}
	var buffer bytes.Buffer
	writer, _ := NewWriter(&buffer)
	if err := writer.Write(Message{Type: TypeHello, Hello: &hello}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(buffer.String(), `"hash":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"`) {
		t.Fatalf("digest is not canonical text: %s", buffer.String())
	}
	reader, _ := NewReader(&buffer)
	got, err := reader.Read()
	if err != nil {
		t.Fatal(err)
	}
	if got.Type != TypeHello || got.Hello == nil || *got.Hello != hello {
		t.Fatalf("round trip = %+v", got)
	}
}

func TestReaderRejectsUnknownDuplicateTrailingAndOversize(t *testing.T) {
	tests := []string{
		`{"type":"role","generation":1,"unknown":true}` + "\n",
		`{"type":"role","type":"role","generation":1}` + "\n",
		`{"type":"role","generation":1,"generation":1}` + "\n",
		`{"type":"role","generation":1} {}` + "\n",
		`[]` + "\n",
		"\n",
	}
	for _, input := range tests {
		reader, _ := NewReader(strings.NewReader(input))
		if _, err := reader.Read(); err == nil {
			t.Fatalf("accepted %q", input)
		}
	}
	reader, _ := NewReader(strings.NewReader(strings.Repeat("x", MaxMessageBytes+1) + "\n"))
	if _, err := reader.Read(); err == nil {
		t.Fatal("accepted oversized wire line")
	}
}

func TestTaggedUnionRejectsMissingAndMixedFields(t *testing.T) {
	barrier := agentstream.Barrier{}
	tests := []Message{
		{Type: TypeRole},
		{Type: TypeRole, Generation: 1, Barrier: &barrier},
		{Type: TypeAdvance, Generation: 3, HostBarrier: &barrier},
		{Type: TypeHello},
		{Type: TypeBarrierAck, Generation: 1, Barrier: &barrier},
		{Type: "future"},
	}
	for _, message := range tests {
		if err := message.Validate(); err == nil {
			t.Fatalf("accepted %+v", message)
		}
	}
}

type shortWriter struct{}

func (shortWriter) Write(data []byte) (int, error) {
	if len(data) == 0 {
		return 0, nil
	}
	return len(data) - 1, nil
}

func TestNilAndShortIOFail(t *testing.T) {
	if _, err := NewReader(nil); err == nil {
		t.Fatal("nil reader accepted")
	}
	if _, err := NewWriter(nil); err == nil {
		t.Fatal("nil writer accepted")
	}
	writer, _ := NewWriter(shortWriter{})
	if err := writer.Write(Message{Type: TypeRole, Generation: 1}); !errors.Is(err, io.ErrShortWrite) {
		t.Fatalf("short write = %v", err)
	}
}

func TestCanonicalJSONObjectSortsAndRejectsAmbiguity(t *testing.T) {
	canonical, err := CanonicalJSONObject([]byte(` {"z":2,"a":{"y":1,"x":[3]}} `))
	if err != nil {
		t.Fatal(err)
	}
	if string(canonical) != `{"a":{"x":[3],"y":1},"z":2}` {
		t.Fatalf("canonical object = %s", canonical)
	}
	for _, invalid := range [][]byte{
		[]byte(`{"a":{"x":1,"x":2}}`),
		[]byte(`[]`),
		[]byte(`{"a":1} {}`),
	} {
		if _, err := CanonicalJSONObject(invalid); err == nil {
			t.Fatalf("accepted ambiguous object %s", invalid)
		}
	}
}
