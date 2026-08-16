package agentguest

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func validConfig() Config {
	return Config{
		Schema: ConfigSchema, SessionID: strings.Repeat("1", 32), CodexSHA256: strings.Repeat("a", 64),
		Arguments:  []string{"app-server", "--stdio", "-c", `model="gpt-5.6-sol"`},
		StreamPort: DefaultStreamPort, ModelPort: 45678, PayloadDrive: "/dev/vda",
		RepositoryDrive: RepositoryDrive, RepositorySize: 512,
		RepositorySHA256: strings.Repeat("b", 64), RepositoryTreeRoot: strings.Repeat("c", 64),
	}
}

func TestDecodeConfigStrictRoundTrip(t *testing.T) {
	want := validConfig()
	encoded, err := json.Marshal(want)
	if err != nil {
		t.Fatal(err)
	}
	got, err := DecodeConfig(bytes.NewReader(encoded))
	if err != nil {
		t.Fatal(err)
	}
	if got.Schema != want.Schema || got.SessionID != want.SessionID || got.CodexSHA256 != want.CodexSHA256 || got.StreamPort != want.StreamPort || got.ModelPort != want.ModelPort || got.PayloadDrive != want.PayloadDrive || got.RepositoryDrive != want.RepositoryDrive || got.RepositorySize != want.RepositorySize || got.RepositorySHA256 != want.RepositorySHA256 || got.RepositoryTreeRoot != want.RepositoryTreeRoot || strings.Join(got.Arguments, "\x00") != strings.Join(want.Arguments, "\x00") {
		t.Fatalf("decoded config = %+v, want %+v", got, want)
	}
}

func TestDecodeConfigRejectsMissingUnknownDuplicateAndTrailing(t *testing.T) {
	valid, _ := json.Marshal(validConfig())
	tests := []struct {
		name string
		data string
	}{
		{name: "not object", data: `[]`},
		{name: "missing", data: `{"schema":1}`},
		{name: "unknown", data: strings.TrimSuffix(string(valid), "}") + `,"command":"sh"}`},
		{name: "duplicate", data: strings.Replace(string(valid), `"schema":2`, `"schema":2,"schema":2`, 1)},
		{name: "trailing", data: string(valid) + ` {}`},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if _, err := DecodeConfig(strings.NewReader(test.data)); err == nil {
				t.Fatalf("accepted %s", test.data)
			}
		})
	}
}

func TestConfigValidationRejectsAuthorityExpansion(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*Config)
	}{
		{name: "schema", mutate: func(c *Config) { c.Schema = 1 }},
		{name: "session uppercase", mutate: func(c *Config) { c.SessionID = strings.Repeat("A", 32) }},
		{name: "session malformed", mutate: func(c *Config) { c.SessionID = strings.Repeat("z", 32) }},
		{name: "digest uppercase", mutate: func(c *Config) { c.CodexSHA256 = strings.Repeat("A", 64) }},
		{name: "digest malformed", mutate: func(c *Config) { c.CodexSHA256 = strings.Repeat("z", 64) }},
		{name: "zero stream", mutate: func(c *Config) { c.StreamPort = 0 }},
		{name: "same ports", mutate: func(c *Config) { c.ModelPort = c.StreamPort }},
		{name: "other drive", mutate: func(c *Config) { c.PayloadDrive = "/dev/vdb" }},
		{name: "repository drive", mutate: func(c *Config) { c.RepositoryDrive = "/dev/vdc" }},
		{name: "repository size", mutate: func(c *Config) { c.RepositorySize = 511 }},
		{name: "repository digest", mutate: func(c *Config) { c.RepositorySHA256 = "bad" }},
		{name: "arbitrary command", mutate: func(c *Config) { c.Arguments = []string{"sh", "-c", "id"} }},
		{name: "control argument", mutate: func(c *Config) { c.Arguments = append(c.Arguments, "x\n") }},
		{name: "empty argument", mutate: func(c *Config) { c.Arguments = append(c.Arguments, "") }},
		{name: "too many arguments", mutate: func(c *Config) {
			c.Arguments = []string{"app-server", "--stdio"}
			for len(c.Arguments) <= MaxArguments {
				c.Arguments = append(c.Arguments, "x")
			}
		}},
		{name: "argument too large", mutate: func(c *Config) { c.Arguments = append(c.Arguments, strings.Repeat("x", MaxArgumentBytes+1)) }},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			config := validConfig()
			test.mutate(&config)
			if err := config.Validate(); err == nil {
				t.Fatalf("accepted config %+v", config)
			}
		})
	}
}

func TestDecodeConfigIsBoundedAndNilSafe(t *testing.T) {
	if _, err := DecodeConfig(nil); err == nil {
		t.Fatal("nil reader accepted")
	}
	if _, err := DecodeConfig(bytes.NewReader(bytes.Repeat([]byte{' '}, MaxConfigBytes+1))); err == nil {
		t.Fatal("oversized config accepted")
	}
}
