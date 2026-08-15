package main

import (
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/effectproxy"
)

func TestLoadPrivateTokenRequiresPrivateRegularFile(t *testing.T) {
	directory := t.TempDir()
	validPath := filepath.Join(directory, "adapter-token")
	validToken := strings.Repeat("a", 64)
	if err := os.WriteFile(validPath, []byte(validToken+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if got, err := loadPrivateToken(validPath); err != nil || got != validToken {
		t.Fatalf("valid token got=%q err=%v", got, err)
	}

	tests := map[string]func() string{
		"public-file": func() string {
			path := filepath.Join(directory, "public")
			if err := os.WriteFile(path, []byte(validToken), 0o644); err != nil {
				t.Fatal(err)
			}
			if err := os.Chmod(path, 0o644); err != nil {
				t.Fatal(err)
			}
			return path
		},
		"directory": func() string { return directory },
		"symlink": func() string {
			path := filepath.Join(directory, "token-link")
			if err := os.Symlink(validPath, path); err != nil {
				t.Fatal(err)
			}
			return path
		},
		"short": func() string {
			path := filepath.Join(directory, "short")
			if err := os.WriteFile(path, []byte("too-short"), 0o600); err != nil {
				t.Fatal(err)
			}
			return path
		},
		"whitespace": func() string {
			path := filepath.Join(directory, "whitespace")
			if err := os.WriteFile(path, []byte(strings.Repeat("x", 32)+" token"), 0o600); err != nil {
				t.Fatal(err)
			}
			return path
		},
		"oversized": func() string {
			path := filepath.Join(directory, "oversized")
			if err := os.WriteFile(path, []byte(strings.Repeat("x", maxTokenFileBytes+1)), 0o600); err != nil {
				t.Fatal(err)
			}
			return path
		},
	}
	for name, makePath := range tests {
		t.Run(name, func(t *testing.T) {
			if token, err := loadPrivateToken(makePath()); err == nil {
				t.Fatalf("invalid token file accepted: %q", token)
			}
		})
	}
}

func TestLoadConfigIsBoundedAndStrict(t *testing.T) {
	directory := t.TempDir()
	validPath := filepath.Join(directory, "routes.json")
	valid := `{"schema":1,"routes":[{"name":"charge","kind":"payment","method":"POST","url":"http://provider/v1/charge","content_types":["application/json"]}]}`
	if err := os.WriteFile(validPath, []byte(valid), 0o600); err != nil {
		t.Fatal(err)
	}
	if config, err := loadConfig(validPath); err != nil || len(config.Routes) != 1 {
		t.Fatalf("config=%+v err=%v", config, err)
	}
	oversizedPath := filepath.Join(directory, "oversized.json")
	if err := os.WriteFile(oversizedPath, []byte(strings.Repeat(" ", effectproxy.MaxConfigBytes+1)), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadConfig(oversizedPath); err == nil {
		t.Fatal("oversized config accepted")
	}
	unknownPath := filepath.Join(directory, "unknown.json")
	if err := os.WriteFile(unknownPath, []byte(strings.Replace(valid, `"schema":1`, `"schema":1,"unknown":true`, 1)), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadConfig(unknownPath); err == nil {
		t.Fatal("unknown config field accepted")
	}
}

func TestListenerAllowed(t *testing.T) {
	tests := []struct {
		address *net.TCPAddr
		allow   bool
		want    bool
	}{
		{&net.TCPAddr{IP: net.ParseIP("127.0.0.1"), Port: 8788}, false, true},
		{&net.TCPAddr{IP: net.ParseIP("::1"), Port: 8788}, false, true},
		{&net.TCPAddr{IP: net.ParseIP("0.0.0.0"), Port: 8788}, false, false},
		{&net.TCPAddr{IP: net.ParseIP("192.0.2.1"), Port: 8788}, false, false},
		{&net.TCPAddr{IP: net.ParseIP("192.0.2.1"), Port: 8788}, true, true},
		{nil, true, false},
	}
	for _, test := range tests {
		if got := listenerAllowed(test.address, test.allow); got != test.want {
			t.Fatalf("listenerAllowed(%v,%t)=%t want %t", test.address, test.allow, got, test.want)
		}
	}
}

func TestControlHTTPClientIsDirectAndBounded(t *testing.T) {
	client := controlHTTPClient(17)
	if client.Timeout != 17 {
		t.Fatalf("client timeout = %s", client.Timeout)
	}
	transport, ok := client.Transport.(*http.Transport)
	if !ok {
		t.Fatalf("transport type = %T", client.Transport)
	}
	if transport.Proxy != nil || transport.DialContext == nil || transport.ResponseHeaderTimeout != 17 {
		t.Fatalf("transport is not direct and bounded: %+v", transport)
	}
}
