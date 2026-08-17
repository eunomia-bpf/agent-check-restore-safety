// Package effectproxy exposes operator-defined effects to untrusted workload
// code without giving that code a control credential or an arbitrary target.
package effectproxy

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"strings"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const (
	ConfigSchema            = 1
	TransparentConfigSchema = 2
	MaxConfigBytes          = 1 << 20
	MaxRoutes               = 256
	MaxRouteNameBytes       = 128
	MaxContentTypes         = 16
	MaxContentTypeBytes     = 256
)

// Config is the complete authority exposed by one proxy process. Routes are
// selected by name, while their operation kind and network destination remain
// fixed by the operator-owned configuration.
type Config struct {
	Schema int     `json:"schema"`
	Routes []Route `json:"routes"`
}

// Route binds a workload-facing name to one exact Operation contract.
// ContentTypes is an allowlist, not a default: callers must send one of the
// configured values explicitly.
type Route struct {
	Name         string   `json:"name"`
	Path         string   `json:"path,omitempty"`
	Kind         string   `json:"kind"`
	Method       string   `json:"method"`
	URL          string   `json:"url"`
	ContentTypes []string `json:"content_types"`
}

// ParseConfig decodes exactly one bounded JSON object and rejects unknown
// fields. It returns canonical Content-Type values so request forwarding does
// not depend on caller spelling or parameter order.
func ParseConfig(data []byte) (Config, error) {
	if len(data) > MaxConfigBytes {
		return Config{}, fmt.Errorf("effect proxy config exceeds %d bytes", MaxConfigBytes)
	}
	if err := rejectDuplicateJSONNames(data); err != nil {
		return Config{}, fmt.Errorf("decode effect proxy config: %w", err)
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var config Config
	if err := decoder.Decode(&config); err != nil {
		return Config{}, fmt.Errorf("decode effect proxy config: %w", err)
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return Config{}, errors.New("effect proxy config contains multiple JSON values")
		}
		return Config{}, fmt.Errorf("decode effect proxy config trailer: %w", err)
	}
	if err := validateConfig(&config); err != nil {
		return Config{}, err
	}
	return config, nil
}

func rejectDuplicateJSONNames(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var consumeValue func() error
	consumeValue = func() error {
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
				if err := consumeValue(); err != nil {
					return err
				}
			}
			closing, err := decoder.Token()
			if err != nil {
				return err
			}
			if closing != json.Delim('}') {
				return errors.New("object is not closed")
			}
		case '[':
			for decoder.More() {
				if err := consumeValue(); err != nil {
					return err
				}
			}
			closing, err := decoder.Token()
			if err != nil {
				return err
			}
			if closing != json.Delim(']') {
				return errors.New("array is not closed")
			}
		default:
			return errors.New("unexpected closing delimiter")
		}
		return nil
	}
	return consumeValue()
}

func validateConfig(config *Config) error {
	if config == nil {
		return errors.New("nil effect proxy config")
	}
	if config.Schema != ConfigSchema && config.Schema != TransparentConfigSchema {
		return fmt.Errorf("unsupported effect proxy config schema %d", config.Schema)
	}
	if len(config.Routes) == 0 || len(config.Routes) > MaxRoutes {
		return fmt.Errorf("effect proxy config must contain between 1 and %d routes", MaxRoutes)
	}
	seenNames := make(map[string]bool, len(config.Routes))
	seenPaths := make(map[string]bool, len(config.Routes))
	for index := range config.Routes {
		route := &config.Routes[index]
		if !validRouteName(route.Name) || seenNames[route.Name] {
			return fmt.Errorf("route %d has an invalid or duplicate name", index)
		}
		seenNames[route.Name] = true
		if config.Schema == ConfigSchema {
			if route.Path != "" {
				return fmt.Errorf("route %q cannot set path in schema %d", route.Name, ConfigSchema)
			}
		} else {
			if !validPublicPath(route.Path) || seenPaths[route.Path] {
				return fmt.Errorf("route %q has an invalid or duplicate public path", route.Name)
			}
			seenPaths[route.Path] = true
		}
		if route.Kind == "" || len(route.Kind) > kernel.MaxNameBytes {
			return fmt.Errorf("route %q has an invalid operation kind", route.Name)
		}
		if !validMethod(route.Method) {
			return fmt.Errorf("route %q has an invalid HTTP method", route.Name)
		}
		if err := validateTarget(route.URL); err != nil {
			return fmt.Errorf("route %q target: %w", route.Name, err)
		}
		if len(route.ContentTypes) == 0 || len(route.ContentTypes) > MaxContentTypes {
			return fmt.Errorf("route %q must allow between 1 and %d Content-Types", route.Name, MaxContentTypes)
		}
		seenContentTypes := make(map[string]bool, len(route.ContentTypes))
		for contentIndex, value := range route.ContentTypes {
			canonical, err := canonicalContentType(value)
			if err != nil {
				return fmt.Errorf("route %q Content-Type %d: %w", route.Name, contentIndex, err)
			}
			if seenContentTypes[canonical] {
				return fmt.Errorf("route %q has duplicate Content-Type %q", route.Name, canonical)
			}
			seenContentTypes[canonical] = true
			route.ContentTypes[contentIndex] = canonical
		}
	}
	return nil
}

func validPublicPath(value string) bool {
	if value == "" || value == "/" || value == "/healthz" || len(value) > kernel.MaxNameBytes ||
		value[0] != '/' || strings.ContainsAny(value, "?#\\\r\n\x00") || strings.Contains(value, "//") {
		return false
	}
	for _, segment := range strings.Split(strings.TrimPrefix(value, "/"), "/") {
		if segment == "" || segment == "." || segment == ".." {
			return false
		}
	}
	return true
}

func validRouteName(value string) bool {
	if value == "" || len(value) > MaxRouteNameBytes {
		return false
	}
	for index, character := range []byte(value) {
		if (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') || (index > 0 && strings.ContainsRune("._-", rune(character))) {
			continue
		}
		return false
	}
	return true
}

func validMethod(value string) bool {
	if value == "" || len(value) > 32 || value != strings.ToUpper(value) {
		return false
	}
	if value == http.MethodConnect || value == http.MethodTrace {
		return false
	}
	for _, character := range value {
		if (character >= 'A' && character <= 'Z') || (character >= '0' && character <= '9') ||
			strings.ContainsRune("!#$%&'*+-.^_`|~", character) {
			continue
		}
		return false
	}
	return true
}

func validateTarget(value string) error {
	if value == "" || len(value) > kernel.MaxNameBytes {
		return fmt.Errorf("absolute HTTP URL must contain between 1 and %d bytes", kernel.MaxNameBytes)
	}
	target, err := url.Parse(value)
	if err != nil {
		return errors.New("invalid absolute HTTP URL")
	}
	if !target.IsAbs() || (target.Scheme != "http" && target.Scheme != "https") || target.Host == "" {
		return errors.New("URL must be absolute and use http or https")
	}
	if target.Opaque != "" || target.User != nil || target.Fragment != "" {
		return errors.New("URL must not contain opaque data, user information, or a fragment")
	}
	return nil
}

func canonicalContentType(value string) (string, error) {
	if value == "" || len(value) > MaxContentTypeBytes || strings.TrimSpace(value) != value || strings.ContainsAny(value, "\r\n\x00") {
		return "", fmt.Errorf("value must contain between 1 and %d safe bytes", MaxContentTypeBytes)
	}
	mediaType, parameters, err := mime.ParseMediaType(value)
	if err != nil || mediaType == "" || !strings.Contains(mediaType, "/") {
		return "", errors.New("value is not a valid media type")
	}
	mediaType = strings.ToLower(mediaType)
	canonical := mime.FormatMediaType(mediaType, parameters)
	if canonical == "" || len(canonical) > MaxContentTypeBytes {
		return "", errors.New("value has unsupported parameters")
	}
	return canonical, nil
}
