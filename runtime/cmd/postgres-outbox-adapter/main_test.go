package main

import (
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadPrivateDSN(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "postgres.dsn")
	const dsn = "postgres://adapter:private-value@database/outbox?sslmode=require"
	if err := os.WriteFile(path, []byte(dsn+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	got, err := loadPrivateDSN(path)
	if err != nil {
		t.Fatal(err)
	}
	if got != dsn {
		t.Fatalf("got DSN %q, want exact private file value", got)
	}
}

func TestLoadPrivateDSNRejectsUnsafeFiles(t *testing.T) {
	directory := t.TempDir()
	privatePath := filepath.Join(directory, "private.dsn")
	if err := os.WriteFile(privatePath, []byte("postgres://database/outbox"), 0o600); err != nil {
		t.Fatal(err)
	}

	worldReadablePath := filepath.Join(directory, "readable.dsn")
	if err := os.WriteFile(worldReadablePath, []byte("postgres://database/outbox"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(worldReadablePath, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := loadPrivateDSN(worldReadablePath); err == nil {
		t.Fatal("world-readable DSN file was accepted")
	}

	symlinkPath := filepath.Join(directory, "link.dsn")
	if err := os.Symlink(privatePath, symlinkPath); err != nil {
		t.Fatal(err)
	}
	if _, err := loadPrivateDSN(symlinkPath); err == nil {
		t.Fatal("symlink DSN file was accepted")
	}

	emptyPath := filepath.Join(directory, "empty.dsn")
	if err := os.WriteFile(emptyPath, []byte(" \n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadPrivateDSN(emptyPath); err == nil {
		t.Fatal("empty DSN file was accepted")
	}

	nulPath := filepath.Join(directory, "nul.dsn")
	if err := os.WriteFile(nulPath, []byte("postgres://database/outbox\x00secret"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadPrivateDSN(nulPath); err == nil {
		t.Fatal("DSN file containing NUL was accepted")
	}
}

func TestLoadPrivateDSNDoesNotExposeContentsInValidationErrors(t *testing.T) {
	path := filepath.Join(t.TempDir(), "postgres.dsn")
	const secret = "do-not-print-this-dsn"
	if err := os.WriteFile(path, []byte(secret+"\x00"), 0o600); err != nil {
		t.Fatal(err)
	}
	_, err := loadPrivateDSN(path)
	if err == nil {
		t.Fatal("invalid DSN file was accepted")
	}
	if strings.Contains(err.Error(), secret) {
		t.Fatalf("validation error exposed DSN contents: %v", err)
	}
}

func TestListenerAllowed(t *testing.T) {
	tests := []struct {
		name        string
		addr        *net.TCPAddr
		allowRemote bool
		want        bool
	}{
		{name: "loopback v4", addr: &net.TCPAddr{IP: net.ParseIP("127.0.0.1")}, want: true},
		{name: "loopback v6", addr: &net.TCPAddr{IP: net.ParseIP("::1")}, want: true},
		{name: "unspecified", addr: &net.TCPAddr{IP: net.ParseIP("0.0.0.0")}, want: false},
		{name: "remote", addr: &net.TCPAddr{IP: net.ParseIP("192.0.2.10")}, want: false},
		{name: "remote explicitly allowed", addr: &net.TCPAddr{IP: net.ParseIP("192.0.2.10")}, allowRemote: true, want: true},
		{name: "nil", want: false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := listenerAllowed(test.addr, test.allowRemote); got != test.want {
				t.Fatalf("listenerAllowed() = %v, want %v", got, test.want)
			}
		})
	}
}
