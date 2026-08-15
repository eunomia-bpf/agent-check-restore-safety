package main

import (
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"testing"
)

func TestListenerPolicy(t *testing.T) {
	loopback := &net.TCPAddr{IP: net.ParseIP("127.0.0.1"), Port: 8787}
	remote := &net.TCPAddr{IP: net.ParseIP("172.20.0.2"), Port: 8787}
	if !listenerAllowed(loopback, false) {
		t.Fatal("loopback listener was rejected")
	}
	if listenerAllowed(remote, false) {
		t.Fatal("non-loopback listener was accepted without the explicit flag")
	}
	if !listenerAllowed(remote, true) {
		t.Fatal("explicitly allowed isolated listener was rejected")
	}
}

func TestLoadOrCreateTokenIsPrivateAndStable(t *testing.T) {
	path := filepath.Join(t.TempDir(), "control.token")
	first, err := loadOrCreateToken(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(first) != 64 {
		t.Fatalf("token length = %d", len(first))
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("token mode = %o", info.Mode().Perm())
	}
	second, err := loadOrCreateToken(path)
	if err != nil {
		t.Fatal(err)
	}
	if first != second {
		t.Fatal("token changed after reopen")
	}
}

func TestLoadOrCreateTokenRejectsSharedFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "shared.token")
	if err := os.WriteFile(path, []byte("01234567890123456789012345678901\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := loadOrCreateToken(path); err == nil {
		t.Fatal("shared token file was accepted")
	}
}

func TestLoadAdaptersUsesIndependentDomainsAndPrivateTokens(t *testing.T) {
	directory := t.TempDir()
	configuration := adapterConfig{Schema: 1, Adapters: []adapterConfigEntry{
		{Domain: "orders", TokenFile: filepath.Join(directory, "orders.token"), Kinds: []string{"charge-v1", "charge-v2"}},
		{Domain: "full-linux-vm", TokenFile: filepath.Join(directory, "vm.token"), Kinds: []string{"vm-audit"}},
	}}
	data, err := json.Marshal(configuration)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, "adapters.json")
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	credentials, err := loadAdapters(path, "", "local-adapter", "", filepath.Join(directory, "runtime.history"))
	if err != nil {
		t.Fatal(err)
	}
	if len(credentials) != 2 || credentials[0].Domain != "orders" || credentials[1].Domain != "full-linux-vm" {
		t.Fatalf("credentials = %+v", credentials)
	}
	if credentials[0].Token == credentials[1].Token {
		t.Fatal("independent adapters received the same token")
	}
	for _, entry := range configuration.Adapters {
		info, err := os.Stat(entry.TokenFile)
		if err != nil {
			t.Fatal(err)
		}
		if info.Mode().Perm() != 0o600 {
			t.Fatalf("token %s mode = %o", entry.TokenFile, info.Mode().Perm())
		}
	}
}

func TestLoadAdaptersRejectsAmbiguousOrAliasedConfiguration(t *testing.T) {
	directory := t.TempDir()
	token := filepath.Join(directory, "shared.token")
	configuration := `{"schema":1,"adapters":[` +
		`{"domain":"orders","token_file":` + quoted(token) + `,"kinds":["charge"]},` +
		`{"domain":"orders","token_file":` + quoted(filepath.Join(directory, "other.token")) + `,"kinds":["audit"]}]}`
	path := filepath.Join(directory, "duplicate.json")
	if err := os.WriteFile(path, []byte(configuration), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadAdapters(path, "", "local-adapter", "", filepath.Join(directory, "runtime.history")); err == nil {
		t.Fatal("duplicate adapter domain was accepted")
	}
	if _, err := loadAdapters(path, token, "local-adapter", "", filepath.Join(directory, "runtime.history")); err == nil {
		t.Fatal("adapter config combined with a legacy token was accepted")
	}
}

func TestLoadAdaptersRejectsUnknownFields(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "unknown.json")
	data := `{"schema":1,"adapters":[{"domain":"orders","token_file":"/tmp/token",` +
		`"kinds":["charge"],"authority":"admin"}]}`
	if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadAdapters(path, "", "local-adapter", "", filepath.Join(directory, "runtime.history")); err == nil {
		t.Fatal("unknown adapter config field was accepted")
	}
}

func quoted(value string) string {
	encoded, _ := json.Marshal(value)
	return string(encoded)
}
