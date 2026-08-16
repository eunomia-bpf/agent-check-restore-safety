// Package mcpoperation exposes History-backed Operations as strict MCP tools.
// Tool descriptions and business arguments are operator-defined, while the
// active sandbox binding supplies provider routes and authority.
package mcpoperation

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const (
	ConfigSchema       = 1
	MaxConfigBytes     = 1 << 20
	MaxTools           = 256
	MaxToolNameBytes   = 128
	MaxDescription     = 4096
	MaxArguments       = 128
	MaxArgumentName    = 128
	MaxStringBytes     = int(kernel.MaxOperationRequestBodyBytes)
	MaxEnumValues      = 256
	MaxExecutionIDSize = 128
)

type Config struct {
	Schema int    `json:"schema"`
	Tools  []Tool `json:"tools"`
}

type Tool struct {
	Name        string     `json:"name"`
	Description string     `json:"description"`
	Kind        string     `json:"kind"`
	Arguments   []Argument `json:"arguments"`
}

type Argument struct {
	Name        string   `json:"name"`
	Description string   `json:"description,omitempty"`
	Type        string   `json:"type"`
	Required    bool     `json:"required"`
	MaxLength   int      `json:"max_length,omitempty"`
	Enum        []string `json:"enum,omitempty"`
}

// ParseConfig decodes one strict, bounded configuration. The intentionally
// small argument type system is also enforced at execution time; inputSchema
// is not treated as advisory client-side validation.
func ParseConfig(data []byte) (Config, error) {
	if len(data) == 0 || len(data) > MaxConfigBytes {
		return Config{}, fmt.Errorf("MCP Operation config must contain between 1 and %d bytes", MaxConfigBytes)
	}
	if err := rejectDuplicateJSONNames(data); err != nil {
		return Config{}, fmt.Errorf("decode MCP Operation config: %w", err)
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var config Config
	if err := decoder.Decode(&config); err != nil {
		return Config{}, fmt.Errorf("decode MCP Operation config: %w", err)
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return Config{}, errors.New("MCP Operation config contains multiple JSON values")
		}
		return Config{}, fmt.Errorf("decode MCP Operation config trailer: %w", err)
	}
	if err := validateConfig(config); err != nil {
		return Config{}, err
	}
	return cloneConfig(config), nil
}

func validateConfig(config Config) error {
	if config.Schema != ConfigSchema {
		return fmt.Errorf("unsupported MCP Operation config schema %d", config.Schema)
	}
	if len(config.Tools) == 0 || len(config.Tools) > MaxTools {
		return fmt.Errorf("MCP Operation config must contain between 1 and %d tools", MaxTools)
	}
	toolNames := make(map[string]bool, len(config.Tools))
	for toolIndex, tool := range config.Tools {
		if !validName(tool.Name, MaxToolNameBytes) || toolNames[tool.Name] {
			return fmt.Errorf("tool %d has an invalid or duplicate name", toolIndex)
		}
		toolNames[tool.Name] = true
		if !validDescription(tool.Description) {
			return fmt.Errorf("tool %q has an invalid description", tool.Name)
		}
		if !validName(tool.Kind, kernel.MaxNameBytes) {
			return fmt.Errorf("tool %q has an invalid Operation kind", tool.Name)
		}
		if len(tool.Arguments) > MaxArguments {
			return fmt.Errorf("tool %q has more than %d arguments", tool.Name, MaxArguments)
		}
		argumentNames := make(map[string]bool, len(tool.Arguments))
		for argumentIndex, argument := range tool.Arguments {
			if !validName(argument.Name, MaxArgumentName) || argumentNames[argument.Name] {
				return fmt.Errorf("tool %q argument %d has an invalid or duplicate name", tool.Name, argumentIndex)
			}
			argumentNames[argument.Name] = true
			if argument.Description != "" && !validDescription(argument.Description) {
				return fmt.Errorf("tool %q argument %q has an invalid description", tool.Name, argument.Name)
			}
			switch argument.Type {
			case "string":
				if argument.MaxLength <= 0 || argument.MaxLength > MaxStringBytes {
					return fmt.Errorf("tool %q string argument %q requires max_length between 1 and %d", tool.Name, argument.Name, MaxStringBytes)
				}
			case "integer", "number", "boolean":
				if argument.MaxLength != 0 || len(argument.Enum) != 0 {
					return fmt.Errorf("tool %q argument %q uses string-only constraints", tool.Name, argument.Name)
				}
			default:
				return fmt.Errorf("tool %q argument %q has unsupported type %q", tool.Name, argument.Name, argument.Type)
			}
			if len(argument.Enum) > MaxEnumValues {
				return fmt.Errorf("tool %q argument %q has more than %d enum values", tool.Name, argument.Name, MaxEnumValues)
			}
			seenEnum := make(map[string]bool, len(argument.Enum))
			for _, value := range argument.Enum {
				if value == "" || len(value) > argument.MaxLength || !safeText(value, false) || seenEnum[value] {
					return fmt.Errorf("tool %q argument %q has an invalid or duplicate enum value", tool.Name, argument.Name)
				}
				seenEnum[value] = true
			}
		}
	}
	return nil
}

func validName(value string, maximum int) bool {
	if value == "" || len(value) > maximum || !utf8.ValidString(value) {
		return false
	}
	for index, character := range []byte(value) {
		if character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z' ||
			character >= '0' && character <= '9' || index > 0 && strings.ContainsRune("._-", rune(character)) {
			continue
		}
		return false
	}
	return true
}

func validDescription(value string) bool {
	return value != "" && len(value) <= MaxDescription && safeText(value, true)
}

func safeText(value string, allowNewline bool) bool {
	if !utf8.ValidString(value) {
		return false
	}
	for _, character := range value {
		if unicode.IsControl(character) && !(allowNewline && (character == '\n' || character == '\t')) {
			return false
		}
	}
	return true
}

func cloneConfig(config Config) Config {
	cloned := Config{Schema: config.Schema, Tools: make([]Tool, len(config.Tools))}
	for index, tool := range config.Tools {
		cloned.Tools[index] = tool
		cloned.Tools[index].Arguments = make([]Argument, len(tool.Arguments))
		for argumentIndex, argument := range tool.Arguments {
			cloned.Tools[index].Arguments[argumentIndex] = argument
			cloned.Tools[index].Arguments[argumentIndex].Enum = append([]string(nil), argument.Enum...)
		}
	}
	return cloned
}

func rejectDuplicateJSONNames(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var consume func() error
	consume = func() error {
		token, err := decoder.Token()
		if err != nil {
			return err
		}
		delimiter, ok := token.(json.Delim)
		if !ok {
			return nil
		}
		switch delimiter {
		case '{':
			seen := make(map[string]bool)
			for decoder.More() {
				nameToken, err := decoder.Token()
				if err != nil {
					return err
				}
				name, ok := nameToken.(string)
				if !ok {
					return errors.New("object member name is not a string")
				}
				if seen[name] {
					return fmt.Errorf("duplicate JSON field %q", name)
				}
				seen[name] = true
				if err := consume(); err != nil {
					return err
				}
			}
			_, err = decoder.Token()
			return err
		case '[':
			for decoder.More() {
				if err := consume(); err != nil {
					return err
				}
			}
			_, err = decoder.Token()
			return err
		default:
			return errors.New("unexpected closing JSON delimiter")
		}
	}
	return consume()
}
