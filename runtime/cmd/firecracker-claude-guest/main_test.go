//go:build linux

package main

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"
)

func TestNormalizeClaudeCopyError(t *testing.T) {
	closed := fmt.Errorf("copy stdout: %w", os.ErrClosed)
	if err := normalizeClaudeCopyError(nil, closed); err != nil {
		t.Fatalf("successful child retained pipe-close race: %v", err)
	}
	processError := errors.New("child failed")
	if err := normalizeClaudeCopyError(processError, closed); !errors.Is(err, os.ErrClosed) {
		t.Fatalf("failed child lost copy error: %v", err)
	}
}

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
