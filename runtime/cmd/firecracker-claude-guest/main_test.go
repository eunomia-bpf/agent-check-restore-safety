//go:build linux

package main

import (
	"strings"
	"testing"
)

func TestValidateClaudeStreamStrictResult(t *testing.T) {
	stream := []byte("{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"DONE\"}\n")
	outcome, err := validateClaudeStream(stream)
	if err != nil {
		t.Fatal(err)
	}
	if outcome.Result != "DONE" || outcome.Stream != string(stream) || outcome.StreamBytes != len(stream) || len(outcome.StreamSHA256) != 64 {
		t.Fatalf("outcome=%+v", outcome)
	}
}

func TestValidateClaudeStreamRejectsAmbiguity(t *testing.T) {
	invalid := []string{
		"{\"type\":\"result\",\"type\":\"assistant\",\"subtype\":\"success\",\"result\":\"DONE\"}\n",
		"{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"DONE\"}\n" +
			"{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"DONE\"}\n",
		"{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"not-DONE\"}\n",
		strings.Repeat("x", maxClaudeOutput+1),
	}
	for _, stream := range invalid {
		if _, err := validateClaudeStream([]byte(stream)); err == nil {
			t.Fatalf("accepted invalid Claude stream prefix %.80q", stream)
		}
	}
}
