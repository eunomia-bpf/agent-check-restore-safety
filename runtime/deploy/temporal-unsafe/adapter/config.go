package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const (
	configSchema   = 1
	maxConfigBytes = 64 << 10
	maxRoutes      = 16

	closureAbsent = "absent"
	closureExact  = "exact"

	callIDOrder         = "order_id"
	callIDCompleteOrder = "complete_order_id"
)

var allowedEffectPaths = map[string]bool{
	"/v1/charge":   true,
	"/v2/charge":   true,
	"/v1/complete": true,
}

type Config struct {
	Schema int     `json:"schema"`
	Routes []Route `json:"routes"`
}

// Route is the complete authority for one provider-shaped request class. Two
// versions may share a Path only when their closure expectations differ.
type Route struct {
	Path           string             `json:"path"`
	ClosureVersion ClosureExpectation `json:"closure_version"`
	Kind           string             `json:"kind"`
	Target         string             `json:"target"`
	CallIDMode     string             `json:"call_id_mode"`
}

type ClosureExpectation struct {
	Mode  string `json:"mode"`
	Value string `json:"value,omitempty"`
}

func ParseConfig(data []byte) (Config, error) {
	if len(data) > maxConfigBytes {
		return Config{}, fmt.Errorf("adapter config exceeds %d bytes", maxConfigBytes)
	}
	if err := rejectDuplicateJSONNames(data); err != nil {
		return Config{}, fmt.Errorf("decode adapter config: %w", err)
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var config Config
	if err := decoder.Decode(&config); err != nil {
		return Config{}, fmt.Errorf("decode adapter config: %w", err)
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return Config{}, errors.New("adapter config contains multiple JSON values")
		}
		return Config{}, fmt.Errorf("decode adapter config end: %w", err)
	}
	if err := validateConfig(config); err != nil {
		return Config{}, err
	}
	return config, nil
}

func validateConfig(config Config) error {
	if config.Schema != configSchema {
		return fmt.Errorf("unsupported adapter config schema %d", config.Schema)
	}
	if len(config.Routes) == 0 || len(config.Routes) > maxRoutes {
		return fmt.Errorf("adapter config must contain between 1 and %d routes", maxRoutes)
	}
	seenBindings := make(map[string]bool, len(config.Routes))
	for index, route := range config.Routes {
		if !allowedEffectPaths[route.Path] {
			return fmt.Errorf("route %d has unsupported provider path %q", index, route.Path)
		}
		if !safeConfigText(route.Kind, kernel.MaxNameBytes) {
			return fmt.Errorf("route %d has invalid operation kind", index)
		}
		if err := validateTarget(route.Target, route.Path); err != nil {
			return fmt.Errorf("route %d target: %w", index, err)
		}
		switch route.ClosureVersion.Mode {
		case closureAbsent:
			if route.ClosureVersion.Value != "" {
				return fmt.Errorf("route %d absent closure expectation carries a value", index)
			}
		case closureExact:
			if !safeConfigText(route.ClosureVersion.Value, kernel.MaxNameBytes) {
				return fmt.Errorf("route %d has invalid exact closure version", index)
			}
		default:
			return fmt.Errorf("route %d has unsupported closure expectation %q", index, route.ClosureVersion.Mode)
		}
		switch route.Path {
		case "/v1/charge", "/v2/charge":
			if route.CallIDMode != callIDOrder {
				return fmt.Errorf("route %d charge path must use %q call identity", index, callIDOrder)
			}
		case "/v1/complete":
			if route.CallIDMode != callIDCompleteOrder {
				return fmt.Errorf("route %d completion path must use %q call identity", index, callIDCompleteOrder)
			}
		}
		binding := route.Path + "\x00" + route.ClosureVersion.Mode + "\x00" + route.ClosureVersion.Value
		if seenBindings[binding] {
			return fmt.Errorf("route %d duplicates an existing path and closure expectation", index)
		}
		seenBindings[binding] = true
	}
	return nil
}

func validateTarget(value, path string) error {
	if value == "" || len(value) > kernel.MaxNameBytes {
		return fmt.Errorf("absolute HTTP URL must contain between 1 and %d bytes", kernel.MaxNameBytes)
	}
	target, err := url.Parse(value)
	if err != nil || !target.IsAbs() || (target.Scheme != "http" && target.Scheme != "https") || target.Host == "" {
		return errors.New("URL must be absolute and use http or https")
	}
	if target.Opaque != "" || target.User != nil || target.RawQuery != "" || target.ForceQuery || target.Fragment != "" {
		return errors.New("URL must not contain opaque data, credentials, a query, or a fragment")
	}
	if target.Path != path || target.RawPath != "" {
		return fmt.Errorf("URL path must be exactly %q", path)
	}
	return nil
}

func safeConfigText(value string, maxBytes int) bool {
	if value == "" || len(value) > maxBytes || !utf8.ValidString(value) || strings.TrimSpace(value) != value {
		return false
	}
	for _, character := range value {
		if unicode.IsControl(character) {
			return false
		}
	}
	return true
}
