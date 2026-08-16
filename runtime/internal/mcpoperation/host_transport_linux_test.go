//go:build linux

package mcpoperation

import (
	"bufio"
	"bytes"
	"context"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestUnixHostAcceptsConcurrentThreadRelays(t *testing.T) {
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	journal, err := OpenJournal(filepath.Join(directory, "calls.jsonl"), "concurrent-relays")
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	server, err := NewServer(&fakeExecutor{}, testServerConfig(t), ServerOptions{
		ExecutionID: "concurrent-relays", Journal: journal,
	})
	if err != nil {
		t.Fatal(err)
	}
	host, err := ListenUnixHost(filepath.Join(directory, "host.sock"))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- host.Serve(ctx, server, &bytes.Buffer{}) }()

	first, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: host.Path(), Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	initialize := `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25"}}` + "\n"
	if _, err := first.Write([]byte(initialize)); err != nil {
		t.Fatal(err)
	}
	if response, err := bufio.NewReader(first).ReadString('\n'); err != nil || !strings.Contains(response, `"serverInfo"`) {
		t.Fatalf("first relay initialize response=%q error=%v", response, err)
	}

	var secondOutput bytes.Buffer
	secondContext, secondCancel := context.WithTimeout(context.Background(), 2*time.Second)
	secondErr := RelayUnix(secondContext, host.Path(), strings.NewReader(
		`{"jsonrpc":"2.0","id":2,"method":"ping"}`+"\n",
	), &secondOutput)
	secondCancel()
	if secondErr != nil || !strings.Contains(secondOutput.String(), `"result"`) {
		t.Fatalf("concurrent second relay output=%q error=%v", secondOutput.String(), secondErr)
	}
	_ = first.Close()
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("concurrent trusted MCP host did not stop")
	}
}

func relayRequests(t *testing.T, path string, requests ...string) []string {
	t.Helper()
	var output bytes.Buffer
	input := strings.NewReader(strings.Join(requests, "\n") + "\n")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := RelayUnix(ctx, path, input, &output); err != nil {
		t.Fatal(err)
	}
	text := strings.TrimSpace(output.String())
	if text == "" {
		return nil
	}
	return strings.Split(text, "\n")
}

func TestUnixHostKeepsJournalAcrossReplacementRelays(t *testing.T) {
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	journal, err := OpenJournal(filepath.Join(directory, "calls.jsonl"), "host-relay")
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	executor := &fakeExecutor{}
	server, err := NewServer(executor, testServerConfig(t), ServerOptions{
		ExecutionID: "host-relay", Journal: journal,
	})
	if err != nil {
		t.Fatal(err)
	}
	host, err := ListenUnixHost(filepath.Join(directory, "host.sock"))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- host.Serve(ctx, server, &bytes.Buffer{}) }()

	first := relayRequests(t, host.Path(),
		`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"A-17"},"_meta":{"progressToken":"first"}}}`,
	)
	second := relayRequests(t, host.Path(),
		`{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"A-17"},"_meta":{"progressToken":"replacement"}}}`,
		`{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"B-18"}}}`,
	)
	if len(first) != 1 || len(second) != 2 || first[0] != second[0] || len(executor.calls) != 2 {
		t.Fatalf("first=%v second=%v executions=%+v", first, second, executor.calls)
	}
	if executor.calls[0].callID != "mcp-call-v1:10:host-relay:1" || executor.calls[1].callID != "mcp-call-v1:10:host-relay:2" {
		t.Fatalf("host call identities = %+v", executor.calls)
	}
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("trusted MCP host did not stop")
	}
	if _, err := os.Lstat(host.Path()); !os.IsNotExist(err) {
		t.Fatalf("trusted MCP socket survived close: %v", err)
	}
}

func TestUnixHostRejectsUnsafePaths(t *testing.T) {
	if _, err := ListenUnixHost("relative.sock"); err == nil {
		t.Fatal("relative trusted MCP socket was accepted")
	}
	directory := t.TempDir()
	path := filepath.Join(directory, "host.sock")
	if err := os.Chmod(directory, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := ListenUnixHost(path); err == nil {
		t.Fatal("non-private trusted MCP socket parent was accepted")
	}
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("occupied"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := ListenUnixHost(path); err == nil {
		t.Fatal("occupied trusted MCP socket path was replaced")
	}
}

func TestLoopbackRelayCarriesMCPWithoutVsockAuthority(t *testing.T) {
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	journal, err := OpenJournal(filepath.Join(t.TempDir(), "loopback.jsonl"), "guest-loopback")
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	server, err := NewServer(&fakeExecutor{}, testServerConfig(t), ServerOptions{
		ExecutionID: "guest-loopback", Journal: journal,
	})
	if err != nil {
		t.Fatal(err)
	}
	serverDone := make(chan error, 1)
	go func() {
		connection, acceptErr := listener.Accept()
		if acceptErr != nil {
			serverDone <- acceptErr
			return
		}
		defer connection.Close()
		serverDone <- server.Serve(context.Background(), connection, connection, &bytes.Buffer{})
	}()
	request := `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"charge_payment","arguments":{"effect_id":"guest-A"}}}` + "\n"
	var output bytes.Buffer
	port := uint32(listener.Addr().(*net.TCPAddr).Port)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := RelayLoopbackTCP(ctx, port, strings.NewReader(request), &output); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output.String(), `"phase":"succeeded"`) {
		t.Fatalf("loopback MCP response = %s", output.String())
	}
	if err := <-serverDone; err != nil {
		t.Fatal(err)
	}
	if err := RelayLoopbackTCP(ctx, 0, strings.NewReader(request), &output); err == nil {
		t.Fatal("zero guest MCP loopback port was accepted")
	}
}
