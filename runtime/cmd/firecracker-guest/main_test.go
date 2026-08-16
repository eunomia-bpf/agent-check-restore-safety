package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"testing"
	"time"
)

func TestDecodeStrictRequestAcceptsOnlyThreeFields(t *testing.T) {
	raw := []byte(`{"call_id":"call-1","kind":"audit","body":"e30="}`)
	request, err := decodeStrictRequest(raw)
	if err != nil {
		t.Fatal(err)
	}
	if request.CallID != "call-1" || request.Kind != "audit" || string(request.Body) != "{}" {
		t.Fatalf("decoded request = %+v body=%q", request, request.Body)
	}

	invalid := []string{
		`{"call_id":"call-1","kind":"audit"}`,
		`{"call_id":"call-1","kind":"audit","body":"e30=","target":"host"}`,
		`{"call_id":"first","call_id":"second","kind":"audit","body":"e30="}`,
		`{"call_id":"call-1","kind":"audit","body":"e30="} {}`,
		`[{"call_id":"call-1","kind":"audit","body":"e30="}]`,
	}
	for _, candidate := range invalid {
		if _, err := decodeStrictRequest([]byte(candidate)); err == nil {
			t.Errorf("accepted invalid request %s", candidate)
		}
	}
}

func TestExecuteOnceSendsOriginalThreeFieldJSON(t *testing.T) {
	raw := []byte(" {\n\"kind\":\"audit\",\"body\":\"e30=\",\"call_id\":\"call-1\"\n}\n")
	responseBody := []byte(`{"phase":"succeeded","reused":false}`)
	response := fmt.Sprintf(
		"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s",
		len(responseBody), responseBody,
	)
	connection := &scriptedStream{reader: strings.NewReader(response)}
	result, err := executeOnce(connection, raw)
	if err != nil {
		t.Fatal(err)
	}
	if result.Status != http.StatusOK || !bytes.Equal(result.Body, responseBody) {
		t.Fatalf("result = %+v", result)
	}

	request, err := http.ReadRequest(bufio.NewReader(bytes.NewReader(connection.written.Bytes())))
	if err != nil {
		t.Fatal(err)
	}
	body, err := io.ReadAll(request.Body)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(body, raw) {
		t.Fatalf("HTTP body changed:\n got %q\nwant %q", body, raw)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(body, &fields); err != nil {
		t.Fatal(err)
	}
	if len(fields) != 3 || fields["call_id"] == nil || fields["kind"] == nil || fields["body"] == nil {
		t.Fatalf("HTTP body fields = %v", fields)
	}
}

func TestWaitForGoReconnectsAfterRestoreDisconnect(t *testing.T) {
	first := &scriptedStream{reader: bytes.NewReader(nil)}
	second := &scriptedStream{reader: strings.NewReader("GO 3\n")}
	connections := []*scriptedStream{first, second}
	var calls int
	dial := func(port uint32) (stream, error) {
		if port != gatePort {
			t.Fatalf("dialed port %d", port)
		}
		connection := connections[calls]
		calls++
		return connection, nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	generation, err := waitForGo(ctx, dial, log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	if generation != 3 || calls != 2 || first.written.String() != "READY\n" || second.written.String() != "READY\n" {
		t.Fatalf("generation=%d gate attempts=%d first=%q second=%q", generation, calls, first.written.String(), second.written.String())
	}
}

func TestParseGenerationRoleRejectsAmbiguousGateMessages(t *testing.T) {
	for _, test := range []struct {
		line string
		want uint64
	}{
		{line: "GO 1\n", want: 1},
		{line: "GO 3\n", want: 3},
		{line: "GO\n"},
		{line: "GO 0\n"},
		{line: "GO 2\n"},
		{line: "GO 3"},
		{line: "GO 03\n"},
		{line: "GO 3 extra\n"},
	} {
		got, err := parseGenerationRole(test.line)
		if test.want == 0 && err == nil {
			t.Errorf("parseGenerationRole(%q)=%d, want rejection", test.line, got)
		}
		if test.want != 0 && (err != nil || got != test.want) {
			t.Errorf("parseGenerationRole(%q)=%d, %v; want %d", test.line, got, err, test.want)
		}
	}
}

func TestResultValidationDoesNotChooseGenerationLifecycle(t *testing.T) {
	for _, reused := range []bool{false, true} {
		result := operationResult{Status: http.StatusOK, Body: json.RawMessage(fmt.Sprintf(`{"phase":"succeeded","reused":%v}`, reused))}
		if err := validateResult(result); err != nil {
			t.Fatalf("validateResult(reused=%v): %v", reused, err)
		}
	}
}

func TestReportResultUsesGateJSONLine(t *testing.T) {
	connection := &scriptedStream{reader: bytes.NewReader(nil)}
	dial := func(port uint32) (stream, error) {
		if port != gatePort {
			t.Fatalf("dialed port %d", port)
		}
		return connection, nil
	}
	result := operationResult{Status: http.StatusOK, Body: json.RawMessage(`{"phase":"succeeded","reused":true}`)}
	if err := reportResult(context.Background(), dial, result, log.New(io.Discard, "", 0)); err != nil {
		t.Fatal(err)
	}
	var event resultEvent
	if err := json.Unmarshal(bytes.TrimSpace(connection.written.Bytes()), &event); err != nil {
		t.Fatal(err)
	}
	if event.Event != "RESULT" || event.Status != http.StatusOK || !bytes.Equal(event.Body, result.Body) {
		t.Fatalf("reported event = %+v", event)
	}
}

type scriptedStream struct {
	reader  io.Reader
	written bytes.Buffer
	closed  bool
}

func (connection *scriptedStream) Read(data []byte) (int, error) {
	if connection.reader == nil {
		return 0, io.EOF
	}
	return connection.reader.Read(data)
}

func (connection *scriptedStream) Write(data []byte) (int, error) {
	return connection.written.Write(data)
}

func (connection *scriptedStream) Close() error {
	connection.closed = true
	return nil
}
