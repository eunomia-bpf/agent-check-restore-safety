package agentguest

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
)

const (
	ClaudeConfigSchema      = 1
	ClaudeHTTPConfigSchema  = 2
	ClaudePayloadMount      = "/opt/claude"
	ClaudeExecutable        = ClaudePayloadMount + "/bin/claude"
	ClaudeRelayExecutable   = ClaudePayloadMount + "/bin/mcp-operation-relay"
	ClaudeLoader            = ClaudePayloadMount + "/lib64/ld-linux-x86-64.so.2"
	ClaudeLibraryPath       = ClaudePayloadMount + "/lib/x86_64-linux-gnu"
	ClaudeBusyBoxExecutable = ClaudePayloadMount + "/bin/busybox"
	ClaudeBashExecutable    = ClaudePayloadMount + "/bin/bash"
	ClaudeHomeDirectory     = "/home/claude/.claude"
	ClaudeMCPConfigPath     = "/run/claude-mcp.json"
	ClaudeChildMode         = "--safe-change-claude-child-v1"
	ClaudePrompt            = "Commit effect-A and then effect-B with the continuity MCP tool. Finish with DONE."
	ClaudeHTTPPrompt        = "Use the Bash tool once to submit the fixed reservation to the local HTTP endpoint. Finish with DONE."
	ClaudeHTTPProfile       = "http"
	DefaultClaudeHTTPPort   = uint32(7003)
)

// ClaudeConfig is the complete immutable input for one clean Claude cell.
// Executable paths, the prompt, tools, and model are fixed by the guest; the
// host selects only content hashes, an execution identity, and a relay port.
type ClaudeConfig struct {
	Schema        int    `json:"schema"`
	SessionID     string `json:"session_id"`
	ClaudeSHA256  string `json:"claude_sha256"`
	RelaySHA256   string `json:"relay_sha256"`
	ModelPort     uint32 `json:"model_port"`
	PayloadDrive  string `json:"payload_drive"`
	Profile       string `json:"profile,omitempty"`
	EgressPort    uint32 `json:"egress_port,omitempty"`
	BusyBoxSHA256 string `json:"busybox_sha256,omitempty"`
	BashSHA256    string `json:"bash_sha256,omitempty"`
}

func DecodeClaudeConfig(reader io.Reader) (ClaudeConfig, error) {
	if reader == nil {
		return ClaudeConfig{}, errors.New("Claude guest config reader is nil")
	}
	data, err := io.ReadAll(io.LimitReader(reader, MaxConfigBytes+1))
	if err != nil {
		return ClaudeConfig{}, fmt.Errorf("read Claude guest config: %w", err)
	}
	if len(data) == 0 || len(data) > MaxConfigBytes {
		return ClaudeConfig{}, errors.New("Claude guest config is empty or oversized")
	}
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	first, err := decoder.Token()
	if err != nil {
		return ClaudeConfig{}, fmt.Errorf("decode Claude guest config: %w", err)
	}
	if delimiter, ok := first.(json.Delim); !ok || delimiter != '{' {
		return ClaudeConfig{}, errors.New("Claude guest config must be one JSON object")
	}
	seen := make(map[string]bool, 10)
	var config ClaudeConfig
	for decoder.More() {
		token, err := decoder.Token()
		if err != nil {
			return ClaudeConfig{}, fmt.Errorf("decode Claude guest config field: %w", err)
		}
		name, ok := token.(string)
		if !ok {
			return ClaudeConfig{}, errors.New("Claude guest config has a non-string field name")
		}
		if seen[name] {
			return ClaudeConfig{}, fmt.Errorf("Claude guest config repeats field %q", name)
		}
		seen[name] = true
		switch name {
		case "schema":
			err = decoder.Decode(&config.Schema)
		case "session_id":
			err = decoder.Decode(&config.SessionID)
		case "claude_sha256":
			err = decoder.Decode(&config.ClaudeSHA256)
		case "relay_sha256":
			err = decoder.Decode(&config.RelaySHA256)
		case "model_port":
			err = decoder.Decode(&config.ModelPort)
		case "payload_drive":
			err = decoder.Decode(&config.PayloadDrive)
		case "profile":
			err = decoder.Decode(&config.Profile)
		case "egress_port":
			err = decoder.Decode(&config.EgressPort)
		case "busybox_sha256":
			err = decoder.Decode(&config.BusyBoxSHA256)
		case "bash_sha256":
			err = decoder.Decode(&config.BashSHA256)
		default:
			return ClaudeConfig{}, fmt.Errorf("Claude guest config contains forbidden field %q", name)
		}
		if err != nil {
			return ClaudeConfig{}, fmt.Errorf("decode Claude guest config field %q: %w", name, err)
		}
	}
	last, err := decoder.Token()
	if err != nil {
		return ClaudeConfig{}, fmt.Errorf("close Claude guest config object: %w", err)
	}
	if delimiter, ok := last.(json.Delim); !ok || delimiter != '}' {
		return ClaudeConfig{}, errors.New("Claude guest config object is not closed")
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return ClaudeConfig{}, fmt.Errorf("Claude guest config has trailing value %v", token)
		}
		return ClaudeConfig{}, fmt.Errorf("Claude guest config has trailing data: %w", err)
	}
	expectedFields := 6
	if config.Schema == ClaudeHTTPConfigSchema {
		expectedFields = 10
	}
	if len(seen) != expectedFields {
		return ClaudeConfig{}, errors.New("Claude guest config must contain exactly the fields required by its schema")
	}
	if err := config.Validate(); err != nil {
		return ClaudeConfig{}, err
	}
	return config, nil
}
func (config ClaudeConfig) Validate() error {
	if config.Schema != ClaudeConfigSchema && config.Schema != ClaudeHTTPConfigSchema {
		return fmt.Errorf("unsupported Claude guest config schema %d", config.Schema)
	}
	if len(config.SessionID) != SessionIDHexBytes*2 || strings.ToLower(config.SessionID) != config.SessionID {
		return errors.New("Claude guest session_id must be 16 bytes of lowercase hex")
	}
	if _, err := hex.DecodeString(config.SessionID); err != nil {
		return errors.New("Claude guest session_id must be 16 bytes of lowercase hex")
	}
	if err := validateLowerHexDigest(config.ClaudeSHA256, "claude_sha256"); err != nil {
		return err
	}
	if err := validateLowerHexDigest(config.RelaySHA256, "relay_sha256"); err != nil {
		return err
	}
	if config.ModelPort == 0 || config.ModelPort > 65535 || config.ModelPort == DefaultMCPPort {
		return errors.New("Claude guest model_port must be a non-reserved port in 1..65535")
	}
	if config.PayloadDrive != "/dev/vda" {
		return errors.New("Claude guest payload_drive must be exactly /dev/vda")
	}
	if config.Schema == ClaudeConfigSchema {
		if config.Profile != "" || config.EgressPort != 0 || config.BusyBoxSHA256 != "" || config.BashSHA256 != "" {
			return errors.New("Claude MCP config cannot contain HTTP profile fields")
		}
	} else {
		if config.Profile != ClaudeHTTPProfile {
			return errors.New("Claude HTTP config profile must be exactly http")
		}
		if config.EgressPort == 0 || config.EgressPort > 65535 || config.EgressPort == config.ModelPort || config.EgressPort == DefaultMCPPort {
			return errors.New("Claude HTTP egress_port must be a distinct non-reserved port")
		}
		if err := validateLowerHexDigest(config.BusyBoxSHA256, "busybox_sha256"); err != nil {
			return err
		}
		if err := validateLowerHexDigest(config.BashSHA256, "bash_sha256"); err != nil {
			return err
		}
	}
	return nil
}

func (config ClaudeConfig) Arguments() []string {
	session := config.SessionID
	uuid := session[0:8] + "-" + session[8:12] + "-" + session[12:16] + "-" + session[16:20] + "-" + session[20:32]
	prompt := ClaudePrompt
	allowedTools := "mcp__continuity__commit_effect"
	maxTurns := "4"
	if config.Schema == ClaudeHTTPConfigSchema {
		prompt = ClaudeHTTPPrompt
		allowedTools = "Bash"
		maxTurns = "3"
	}
	return []string{
		"--bare", "--print", prompt,
		"--output-format", "stream-json", "--verbose",
		"--no-session-persistence", "--strict-mcp-config", "--mcp-config", ClaudeMCPConfigPath,
		"--allowedTools", allowedTools,
		"--permission-mode", "dontAsk", "--model", "claude-fixture-1",
		"--max-turns", maxTurns, "--no-chrome", "--disable-slash-commands",
		"--prompt-suggestions", "false", "--session-id", uuid,
	}
}
