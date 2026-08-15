package main

import (
	"os"
	"path/filepath"
	"testing"
)

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
