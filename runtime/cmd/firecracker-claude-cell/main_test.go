//go:build linux

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/firecracker"
)

func TestParseTargetPort(t *testing.T) {
	tests := map[string]uint32{
		"127.0.0.1:1":     1,
		"127.0.0.1:65535": 65535,
		"127.0.0.1":       0,
		"127.0.0.1:":      0,
		"127.0.0.1:0":     0,
		"127.0.0.1:65536": 0,
		"127.0.0.1:port":  0,
	}
	for target, want := range tests {
		if got := parseTargetPort(target); got != want {
			t.Errorf("parseTargetPort(%q)=%d, want %d", target, got, want)
		}
	}
}

func TestValidateGuestResultStrictSuccess(t *testing.T) {
	stream := `{"type":"result","result":"DONE"}` + "\n"
	digest := sha256.Sum256([]byte(stream))
	body, err := json.Marshal(map[string]any{
		"result": "DONE", "stream": stream, "stream_bytes": len(stream),
		"stream_sha256": hex.EncodeToString(digest[:]),
	})
	if err != nil {
		t.Fatal(err)
	}
	result := firecracker.Result{Event: "RESULT", Status: 200, Body: body}
	if err := validateGuestResult(result); err != nil {
		t.Fatal(err)
	}

	invalid := []string{
		strings.Replace(string(body), `"result":"DONE"`, `"result":"DONE","result":"DONE"`, 1),
		strings.Replace(string(body), `"result":"DONE"`, `"result":"DONE","extra":true`, 1),
		strings.Replace(string(body), `"result":"DONE",`, "", 1),
	}
	for _, raw := range invalid {
		result.Body = json.RawMessage(raw)
		if err := validateGuestResult(result); err == nil {
			t.Fatalf("accepted ambiguous guest body: %s", raw)
		}
	}
}

func TestRandomHexLengthAndValidation(t *testing.T) {
	value, err := randomHex(16)
	if err != nil {
		t.Fatal(err)
	}
	if len(value) != 32 || strings.ToLower(value) != value {
		t.Fatalf("randomHex(16)=%q", value)
	}
	if _, err := randomHex(0); err == nil {
		t.Fatal("randomHex accepted a non-positive size")
	}
}
