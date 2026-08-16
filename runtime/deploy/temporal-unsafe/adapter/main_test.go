package main

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/apiclient"
)

func TestControlClientIgnoresAmbientProxyAndUsesTimeouts(t *testing.T) {
	timeout := 17 * time.Second
	client := controlHTTPClient(timeout)
	if client.Timeout != timeout {
		t.Fatalf("client timeout = %s", client.Timeout)
	}
	transport, ok := client.Transport.(*http.Transport)
	if !ok {
		t.Fatalf("transport = %T", client.Transport)
	}
	if transport.Proxy != nil || transport.ResponseHeaderTimeout != timeout || transport.DialContext == nil {
		t.Fatalf("transport is not hardened: %+v", transport)
	}
}

func TestBoundControlClientNeverFollowsRedirects(t *testing.T) {
	var destinationCalls atomic.Int32
	destination := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		destinationCalls.Add(1)
		writer.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(writer).Encode(map[string]any{})
	}))
	defer destination.Close()
	redirect := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		writer.Header().Set("Location", destination.URL+"/v1/execute")
		writer.WriteHeader(http.StatusTemporaryRedirect)
		_, _ = writer.Write([]byte(`{"outcome":{},"error":"redirect denied"}`))
	}))
	defer redirect.Close()
	client, err := apiclient.New(
		redirect.URL,
		"adapter-token-00000000000000000000000000",
		controlHTTPClient(time.Second),
	)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := client.Execute(context.Background(), api.ExecuteRequest{
		CallID: "order-1", Kind: "charge-v1", Method: http.MethodPost,
		URL: "http://payment/v1/charge",
	}); err == nil {
		t.Fatal("redirect response was accepted")
	}
	if destinationCalls.Load() != 0 {
		t.Fatalf("redirect destination calls = %d", destinationCalls.Load())
	}
}

func TestListenerRequiresLoopbackOrExplicitIsolation(t *testing.T) {
	loopback := &net.TCPAddr{IP: net.ParseIP("127.0.0.1"), Port: 8790}
	remote := &net.TCPAddr{IP: net.ParseIP("192.0.2.10"), Port: 8790}
	if !listenerAllowed(loopback, false) || listenerAllowed(remote, false) || !listenerAllowed(remote, true) || listenerAllowed(nil, true) {
		t.Fatal("listener policy mismatch")
	}
}

func TestPrivateTokenFileMustBeStablePrivateAndBounded(t *testing.T) {
	directory := t.TempDir()
	valid := filepath.Join(directory, "token")
	if err := os.WriteFile(valid, []byte("token-00000000000000000000000000000000\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if token, err := loadPrivateToken(valid); err != nil || token != "token-00000000000000000000000000000000" {
		t.Fatalf("token=%q error=%v", token, err)
	}
	public := filepath.Join(directory, "public")
	if err := os.WriteFile(public, []byte("token-00000000000000000000000000000000"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(public, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := loadPrivateToken(public); err == nil {
		t.Fatal("public token accepted")
	}
	symlink := filepath.Join(directory, "link")
	if err := os.Symlink(valid, symlink); err != nil {
		t.Fatal(err)
	}
	if _, err := loadPrivateToken(symlink); err == nil {
		t.Fatal("token symlink accepted")
	}
	oversized := filepath.Join(directory, "oversized")
	data := make([]byte, maxTokenFileBytes+1)
	for index := range data {
		data[index] = 'x'
	}
	if err := os.WriteFile(oversized, data, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadPrivateToken(oversized); err == nil {
		t.Fatal("oversized token accepted")
	}
}
