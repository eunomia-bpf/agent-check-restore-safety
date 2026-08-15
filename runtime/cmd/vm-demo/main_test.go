package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestEnsureImageDownloadsAndVerifiesOnce(t *testing.T) {
	contents := []byte("small deterministic image fixture")
	digest := sha256.Sum256(contents)
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		requests++
		_, _ = writer.Write(contents)
	}))
	defer server.Close()
	path := filepath.Join(t.TempDir(), "image.qcow2")
	ctx := context.Background()
	expected := hex.EncodeToString(digest[:])
	if err := ensureImage(ctx, path, server.URL, expected); err != nil {
		t.Fatal(err)
	}
	if err := ensureImage(ctx, path, server.URL, expected); err != nil {
		t.Fatal(err)
	}
	if requests != 1 {
		t.Fatalf("download requests=%d", requests)
	}
}

func TestEnsureImageRejectsWrongDigest(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		_, _ = writer.Write([]byte("wrong"))
	}))
	defer server.Close()
	path := filepath.Join(t.TempDir(), "image.qcow2")
	err := ensureImage(context.Background(), path, server.URL, strings.Repeat("0", 64))
	if err == nil {
		t.Fatal("wrong image digest was accepted")
	}
	if _, statErr := os.Stat(path); !os.IsNotExist(statErr) {
		t.Fatalf("failed download remained at final path: %v", statErr)
	}
}

func TestWaitForText(t *testing.T) {
	path := filepath.Join(t.TempDir(), "serial.log")
	go func() {
		time.Sleep(20 * time.Millisecond)
		_ = os.WriteFile(path, []byte("boot\nREADY\n"), 0o600)
	}()
	if err := waitForText(context.Background(), path, "READY", time.Second); err != nil {
		t.Fatal(err)
	}
}

func TestMarkerField(t *testing.T) {
	serial := "boot\r\nSAFE_CHANGE_VM_READY kernel=6.8.0-90-generic\r\n"
	if got := markerField(serial, "SAFE_CHANGE_VM_READY kernel="); got != "6.8.0-90-generic" {
		t.Fatalf("kernel marker=%q", got)
	}
}
