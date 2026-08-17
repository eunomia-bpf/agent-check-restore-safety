package agentguest

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func validClaudeConfig() ClaudeConfig {
	return ClaudeConfig{
		Schema:       ClaudeConfigSchema,
		SessionID:    strings.Repeat("01", SessionIDHexBytes),
		ClaudeSHA256: strings.Repeat("a", 64),
		RelaySHA256:  strings.Repeat("b", 64),
		ModelPort:    8001,
		PayloadDrive: "/dev/vda",
	}
}

func TestDecodeClaudeConfigStrictRoundTrip(t *testing.T) {
	want := validClaudeConfig()
	encoded, err := json.Marshal(want)
	if err != nil {
		t.Fatal(err)
	}
	got, err := DecodeClaudeConfig(bytes.NewReader(encoded))
	if err != nil {
		t.Fatal(err)
	}
	if got != want {
		t.Fatalf("config=%+v, want %+v", got, want)
	}
}

func TestDecodeClaudeConfigRejectsAmbiguousObjects(t *testing.T) {
	encoded, err := json.Marshal(validClaudeConfig())
	if err != nil {
		t.Fatal(err)
	}
	valid := string(encoded)
	tests := map[string]string{
		"missing":   strings.Replace(valid, `,"payload_drive":"/dev/vda"`, "", 1),
		"unknown":   strings.Replace(valid, `"schema":1`, `"schema":1,"command":"sh"`, 1),
		"duplicate": strings.Replace(valid, `"schema":1`, `"schema":1,"schema":1`, 1),
		"trailing":  valid + `{}`,
		"array":     `[` + valid + `]`,
	}
	for name, input := range tests {
		t.Run(name, func(t *testing.T) {
			if _, err := DecodeClaudeConfig(strings.NewReader(input)); err == nil {
				t.Fatalf("accepted %s config", name)
			}
		})
	}
}

func TestClaudeConfigValidationAndFixedArguments(t *testing.T) {
	config := validClaudeConfig()
	config.ModelPort = DefaultMCPPort
	if err := config.Validate(); err == nil {
		t.Fatal("accepted reserved MCP port as model port")
	}
	arguments := validClaudeConfig().Arguments()
	joined := strings.Join(arguments, "\x00")
	for _, required := range []string{
		"--bare", ClaudePrompt, "--strict-mcp-config", ClaudeMCPConfigPath,
		"--allowedTools", "mcp__continuity__commit_effect", "--permission-mode", "dontAsk",
	} {
		if !strings.Contains(joined, required) {
			t.Fatalf("fixed Claude arguments omit %q: %q", required, arguments)
		}
	}
}

func TestDecodeClaudeConfigIsBoundedAndNilSafe(t *testing.T) {
	if _, err := DecodeClaudeConfig(nil); err == nil {
		t.Fatal("accepted a nil reader")
	}
	if _, err := DecodeClaudeConfig(bytes.NewReader(bytes.Repeat([]byte{' '}, MaxConfigBytes+1))); err == nil {
		t.Fatal("accepted an oversized config")
	}
}
