// Package agentguest contains the small Linux guest supervisor used to run an
// unmodified agent runtime inside a Firecracker microVM.
package agentguest

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
)

const (
	ConfigSchema       = 2
	DefaultStreamPort  = uint32(7000)
	DefaultExportPort  = uint32(7001)
	DefaultMCPPort     = uint32(7002)
	MaxConfigBytes     = 1 << 20
	MaxArguments       = 256
	MaxArgumentBytes   = 64 << 10
	MaxTotalArgBytes   = 1 << 20
	SessionIDHexBytes  = 16
	InitExecutable     = "/init"
	CodexChildMode     = "--safe-change-codex-child-v1"
	CodexExecutable    = "/opt/codex/bin/codex"
	PayloadMount       = "/opt/codex"
	WorkspaceDirectory = "/workspace"
	CodexHomeDirectory = "/home/codex/.codex"
	RepositoryDrive    = "/dev/vdb"
	MaxRepositoryBytes = uint64(2 << 30)
)

// Config is the complete immutable input embedded in the guest initramfs.
// The executable path is intentionally not configurable: the host may choose
// a payload image and arguments, but cannot turn PID 1 into a general command
// launcher.
type Config struct {
	Schema             int      `json:"schema"`
	SessionID          string   `json:"session_id"`
	CodexSHA256        string   `json:"codex_sha256"`
	Arguments          []string `json:"arguments"`
	StreamPort         uint32   `json:"stream_port"`
	ModelPort          uint32   `json:"model_port"`
	PayloadDrive       string   `json:"payload_drive"`
	RepositoryDrive    string   `json:"repository_drive"`
	RepositorySize     uint64   `json:"repository_size"`
	RepositorySHA256   string   `json:"repository_sha256"`
	RepositoryTreeRoot string   `json:"repository_tree_root"`
}

// DecodeConfig reads one strict, bounded object. Unknown and duplicate fields
// are rejected so a host and guest can never interpret the same bytes as two
// different launch configurations.
func DecodeConfig(reader io.Reader) (Config, error) {
	if reader == nil {
		return Config{}, errors.New("agent guest config reader is nil")
	}
	data, err := io.ReadAll(io.LimitReader(reader, MaxConfigBytes+1))
	if err != nil {
		return Config{}, fmt.Errorf("read agent guest config: %w", err)
	}
	if len(data) == 0 || len(data) > MaxConfigBytes {
		return Config{}, fmt.Errorf("agent guest config must contain 1 byte to %d bytes", MaxConfigBytes)
	}

	decoder := json.NewDecoder(bytes.NewReader(data))
	first, err := decoder.Token()
	if err != nil {
		return Config{}, fmt.Errorf("decode agent guest config: %w", err)
	}
	if delimiter, ok := first.(json.Delim); !ok || delimiter != '{' {
		return Config{}, errors.New("agent guest config must be one JSON object")
	}
	seen := make(map[string]bool, 11)
	var config Config
	for decoder.More() {
		token, err := decoder.Token()
		if err != nil {
			return Config{}, fmt.Errorf("decode agent guest config field: %w", err)
		}
		name, ok := token.(string)
		if !ok {
			return Config{}, errors.New("agent guest config has a non-string field name")
		}
		if seen[name] {
			return Config{}, fmt.Errorf("agent guest config repeats field %q", name)
		}
		seen[name] = true
		switch name {
		case "schema":
			err = decoder.Decode(&config.Schema)
		case "session_id":
			err = decoder.Decode(&config.SessionID)
		case "codex_sha256":
			err = decoder.Decode(&config.CodexSHA256)
		case "arguments":
			err = decoder.Decode(&config.Arguments)
		case "stream_port":
			err = decoder.Decode(&config.StreamPort)
		case "model_port":
			err = decoder.Decode(&config.ModelPort)
		case "payload_drive":
			err = decoder.Decode(&config.PayloadDrive)
		case "repository_drive":
			err = decoder.Decode(&config.RepositoryDrive)
		case "repository_size":
			err = decoder.Decode(&config.RepositorySize)
		case "repository_sha256":
			err = decoder.Decode(&config.RepositorySHA256)
		case "repository_tree_root":
			err = decoder.Decode(&config.RepositoryTreeRoot)
		default:
			return Config{}, fmt.Errorf("agent guest config contains forbidden field %q", name)
		}
		if err != nil {
			return Config{}, fmt.Errorf("decode agent guest config field %q: %w", name, err)
		}
	}
	last, err := decoder.Token()
	if err != nil {
		return Config{}, fmt.Errorf("close agent guest config object: %w", err)
	}
	if delimiter, ok := last.(json.Delim); !ok || delimiter != '}' {
		return Config{}, errors.New("agent guest config object is not closed")
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return Config{}, fmt.Errorf("agent guest config has trailing value %v", token)
		}
		return Config{}, fmt.Errorf("agent guest config has trailing data: %w", err)
	}
	if len(seen) != 11 {
		return Config{}, errors.New("agent guest config must contain exactly the fixed schema, session, Codex, ports, payload, and repository fields")
	}
	if err := config.Validate(); err != nil {
		return Config{}, err
	}
	return config, nil
}

// Validate checks the security-relevant launch constraints independent of the
// JSON representation.
func (config Config) Validate() error {
	if config.Schema != ConfigSchema {
		return fmt.Errorf("agent guest config schema is %d, require %d", config.Schema, ConfigSchema)
	}
	if len(config.SessionID) != SessionIDHexBytes*2 || strings.ToLower(config.SessionID) != config.SessionID {
		return errors.New("agent guest session_id must be 16 bytes of lowercase hex")
	}
	if _, err := hex.DecodeString(config.SessionID); err != nil {
		return errors.New("agent guest session_id must be 16 bytes of lowercase hex")
	}
	if len(config.CodexSHA256) != 64 || strings.ToLower(config.CodexSHA256) != config.CodexSHA256 {
		return errors.New("agent guest codex_sha256 must be one lowercase SHA-256 digest")
	}
	if _, err := hex.DecodeString(config.CodexSHA256); err != nil {
		return errors.New("agent guest codex_sha256 must be one lowercase SHA-256 digest")
	}
	if config.StreamPort == 0 || config.StreamPort > 65535 {
		return errors.New("agent guest stream_port must be in 1..65535")
	}
	if config.ModelPort == 0 || config.ModelPort > 65535 || config.ModelPort == config.StreamPort || config.ModelPort == DefaultExportPort || config.ModelPort == DefaultMCPPort {
		return errors.New("agent guest model_port must be a distinct non-reserved port in 1..65535")
	}
	if config.PayloadDrive != "/dev/vda" {
		return errors.New("agent guest payload_drive must be exactly /dev/vda")
	}
	if config.RepositoryDrive != RepositoryDrive {
		return errors.New("agent guest repository_drive must be exactly /dev/vdb")
	}
	if config.RepositorySize == 0 || config.RepositorySize > MaxRepositoryBytes || config.RepositorySize%512 != 0 {
		return fmt.Errorf("agent guest repository_size must be a positive 512-byte multiple no larger than %d", MaxRepositoryBytes)
	}
	if err := validateLowerHexDigest(config.RepositorySHA256, "repository_sha256"); err != nil {
		return err
	}
	if err := validateLowerHexDigest(config.RepositoryTreeRoot, "repository_tree_root"); err != nil {
		return err
	}
	return ValidateCodexArguments(config.Arguments)
}

func validateLowerHexDigest(value, label string) error {
	if len(value) != 64 || strings.ToLower(value) != value {
		return fmt.Errorf("agent guest %s must be one lowercase SHA-256 digest", label)
	}
	if _, err := hex.DecodeString(value); err != nil {
		return fmt.Errorf("agent guest %s must be one lowercase SHA-256 digest", label)
	}
	return nil
}

// ValidateCodexArguments constrains both PID 1 and its internal child mode to
// the fixed App Server entrypoint. Keeping one validator prevents the child
// exec boundary from accidentally accepting more authority than the config.
func ValidateCodexArguments(arguments []string) error {
	if len(arguments) < 2 || len(arguments) > MaxArguments || arguments[0] != "app-server" || arguments[1] != "--stdio" {
		return fmt.Errorf("agent guest arguments must begin with app-server --stdio and contain at most %d entries", MaxArguments)
	}
	total := 0
	for index, argument := range arguments {
		if argument == "" || len(argument) > MaxArgumentBytes || strings.IndexByte(argument, 0) >= 0 || containsControl(argument) {
			return fmt.Errorf("agent guest argument %d is empty, too large, or contains a control character", index)
		}
		total += len(argument)
		if total > MaxTotalArgBytes {
			return fmt.Errorf("agent guest arguments exceed %d bytes", MaxTotalArgBytes)
		}
	}
	return nil
}

func containsControl(value string) bool {
	for _, character := range value {
		if character < 0x20 || character == 0x7f {
			return true
		}
	}
	return false
}
