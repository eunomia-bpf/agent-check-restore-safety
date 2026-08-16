//go:build linux

package agentguest

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repobundle"
	"golang.org/x/sys/unix"
)

func TestVerifyCodexExecutableIsPathAndHashBound(t *testing.T) {
	if err := VerifyCodexExecutable("/tmp/codex", strings.Repeat("0", 64)); err == nil {
		t.Fatal("arbitrary executable path accepted")
	}
	// The fixed absolute path is intentionally impossible to replace in this
	// rootless test. Malformed expected hashes must still fail before trust.
	if err := VerifyCodexExecutable(CodexExecutable, "bad"); err == nil {
		t.Fatal("malformed Codex digest accepted")
	}
}

func TestDecodeRepositoryBindsImageAndTree(t *testing.T) {
	bundle, err := repobundle.FromEntries([]repobundle.Entry{{
		Path: "README.md", Type: repobundle.EntryFile, Mode: 0o644, Data: []byte("hello\n"),
	}}, repobundle.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	var encoded bytes.Buffer
	if err := repobundle.Encode(&encoded, bundle, repobundle.DefaultLimits()); err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(encoded.Bytes())
	got, err := DecodeRepository(bytes.NewReader(encoded.Bytes()), uint64(encoded.Len()), hex.EncodeToString(digest[:]), bundle.TreeRoot.String())
	if err != nil {
		t.Fatal(err)
	}
	if got.TreeRoot != bundle.TreeRoot {
		t.Fatalf("decoded tree root = %s, want %s", got.TreeRoot, bundle.TreeRoot)
	}
	if _, err := DecodeRepository(bytes.NewReader(encoded.Bytes()), uint64(encoded.Len()), strings.Repeat("0", 64), bundle.TreeRoot.String()); err == nil {
		t.Fatal("wrong repository image digest accepted")
	}
	if _, err := DecodeRepository(bytes.NewReader(encoded.Bytes()), uint64(encoded.Len()), hex.EncodeToString(digest[:]), strings.Repeat("0", 64)); err == nil {
		t.Fatal("wrong repository tree root accepted")
	}
}

func TestCodexCommandUsesFixedInitChildAndDropsAllGroups(t *testing.T) {
	config := validConfig()
	command, err := codexCommand(config, io.Discard)
	if err != nil {
		t.Fatal(err)
	}
	wantArguments := append([]string{InitExecutable, CodexChildMode}, config.Arguments...)
	if command.Path != InitExecutable || strings.Join(command.Args, "\x00") != strings.Join(wantArguments, "\x00") {
		t.Fatalf("Codex command path=%q args=%q, want %q", command.Path, command.Args, wantArguments)
	}
	if command.Dir != WorkspaceDirectory || strings.Join(command.Env, "\x00") != strings.Join(fixedCodexEnvironment(), "\x00") {
		t.Fatalf("Codex command dir=%q environment=%q", command.Dir, command.Env)
	}
	attributes := command.SysProcAttr
	if attributes == nil || attributes.Credential == nil {
		t.Fatal("Codex command lacks numeric credentials")
	}
	credential := attributes.Credential
	if credential.Uid != agentUID || credential.Gid != agentGID || credential.NoSetGroups || credential.Groups == nil || len(credential.Groups) != 0 {
		t.Fatalf("Codex credential = %+v, want uid/gid 1000 and an explicit empty supplementary group set", credential)
	}
	if attributes.Pdeathsig != syscall.SIGKILL {
		t.Fatalf("Codex parent-death signal = %v, want SIGKILL", attributes.Pdeathsig)
	}
	if _, err := codexCommand(config, nil); err == nil {
		t.Fatal("nil Codex stderr accepted")
	}
}

func TestProxyModelConnectionCopiesBothDirections(t *testing.T) {
	guestClient, guestProxy := net.Pipe()
	hostProxy, hostServer := net.Pipe()
	dialed := make(chan uint32, 1)
	done := make(chan struct{})
	go func() {
		proxyModelConnection(guestProxy, 4567, func(port uint32) (Stream, error) {
			dialed <- port
			return hostProxy, nil
		}, log.New(io.Discard, "", 0))
		close(done)
	}()

	request := []byte("POST /v1/responses HTTP/1.1\r\n\r\n")
	go func() { _, _ = guestClient.Write(request) }()
	gotRequest := make([]byte, len(request))
	if _, err := io.ReadFull(hostServer, gotRequest); err != nil {
		t.Fatal(err)
	}
	if string(gotRequest) != string(request) {
		t.Fatalf("host received %q", gotRequest)
	}
	response := []byte("HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
	go func() { _, _ = hostServer.Write(response) }()
	gotResponse := make([]byte, len(response))
	if _, err := io.ReadFull(guestClient, gotResponse); err != nil {
		t.Fatal(err)
	}
	if string(gotResponse) != string(response) {
		t.Fatalf("guest received %q", gotResponse)
	}
	if port := <-dialed; port != 4567 {
		t.Fatalf("dialed port %d", port)
	}
	_ = guestClient.Close()
	_ = hostServer.Close()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("proxy did not stop after both peers closed")
	}
}

func TestProxyModelConnectionStopsOnDialFailure(t *testing.T) {
	client, proxy := net.Pipe()
	done := make(chan struct{})
	go func() {
		proxyModelConnection(proxy, 1234, func(uint32) (Stream, error) {
			return nil, errors.New("no host relay")
		}, log.New(io.Discard, "", 0))
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("proxy retained guest connection after dial failure")
	}
	_ = client.Close()
}

func TestStartModelProxyBindsBeforeReturning(t *testing.T) {
	reserved, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := uint32(reserved.Addr().(*net.TCPAddr).Port)
	if err := reserved.Close(); err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	result, err := StartModelProxy(done, port, func(uint32) (Stream, error) {
		return nil, errors.New("probe has no host relay")
	}, log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	probe, err := net.DialTimeout("tcp4", net.JoinHostPort("127.0.0.1", fmt.Sprint(port)), time.Second)
	if err != nil {
		t.Fatalf("listener was not ready when StartModelProxy returned: %v", err)
	}
	_ = probe.Close()
	close(done)
	select {
	case err := <-result:
		if err != nil {
			t.Fatalf("model proxy shutdown: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("model proxy did not report shutdown")
	}
}

func TestStartModelProxyReportsBindFailureSynchronously(t *testing.T) {
	occupied, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer occupied.Close()
	port := uint32(occupied.Addr().(*net.TCPAddr).Port)
	done := make(chan struct{})
	defer close(done)
	result, err := StartModelProxy(done, port, func(uint32) (Stream, error) {
		return nil, errors.New("must not dial")
	}, log.New(io.Discard, "", 0))
	if err == nil || result != nil {
		t.Fatalf("StartModelProxy result=%v error=%v, want synchronous bind failure", result, err)
	}
}

func TestModelProxyCancellationClosesIdleGuestAndHostPairs(t *testing.T) {
	reserved, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := uint32(reserved.Addr().(*net.TCPAddr).Port)
	if err := reserved.Close(); err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	hosts := make(chan net.Conn, 1)
	result, err := StartModelProxy(done, port, func(uint32) (Stream, error) {
		proxy, host := net.Pipe()
		hosts <- host
		return proxy, nil
	}, log.New(io.Discard, "", 0))
	if err != nil {
		t.Fatal(err)
	}
	guest, err := net.DialTimeout("tcp4", net.JoinHostPort("127.0.0.1", fmt.Sprint(port)), time.Second)
	if err != nil {
		t.Fatal(err)
	}
	host := <-hosts
	close(done)
	select {
	case err := <-result:
		if err != nil {
			t.Fatalf("model proxy shutdown: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("model proxy retained idle connection handlers after cancellation")
	}
	for name, connection := range map[string]net.Conn{"guest": guest, "host": host} {
		_ = connection.SetReadDeadline(time.Now().Add(time.Second))
		if _, err := connection.Read(make([]byte, 1)); err == nil {
			t.Fatalf("%s side remained open after model proxy cancellation", name)
		}
		_ = connection.Close()
	}
}

func TestVsockStreamCloseWritePreservesReadHalf(t *testing.T) {
	descriptors, err := unix.Socketpair(unix.AF_UNIX, unix.SOCK_STREAM|unix.SOCK_CLOEXEC|unix.SOCK_NONBLOCK, 0)
	if err != nil {
		t.Fatal(err)
	}
	stream, err := newVsockStream(descriptors[0])
	if err != nil {
		_ = unix.Close(descriptors[1])
		t.Fatal(err)
	}
	defer stream.Close()
	peer := os.NewFile(uintptr(descriptors[1]), "vsock-test-peer")
	if peer == nil {
		t.Fatal("wrap peer descriptor")
	}
	defer peer.Close()
	if _, err := stream.Write([]byte("request")); err != nil {
		t.Fatal(err)
	}
	request := make([]byte, len("request"))
	if _, err := io.ReadFull(peer, request); err != nil || string(request) != "request" {
		t.Fatalf("peer request=%q error=%v", request, err)
	}
	if err := stream.CloseWrite(); err != nil {
		t.Fatal(err)
	}
	if _, err := peer.Read(make([]byte, 1)); !errors.Is(err, io.EOF) {
		t.Fatalf("peer read after CloseWrite = %v, want EOF", err)
	}
	if _, err := peer.Write([]byte("response")); err != nil {
		t.Fatal(err)
	}
	response := make([]byte, len("response"))
	if _, err := io.ReadFull(stream, response); err != nil || string(response) != "response" {
		t.Fatalf("stream response=%q error=%v", response, err)
	}
}

func TestVsockStreamConcurrentCloseCannotTouchReusedDescriptor(t *testing.T) {
	descriptors, err := unix.Socketpair(unix.AF_UNIX, unix.SOCK_STREAM|unix.SOCK_CLOEXEC|unix.SOCK_NONBLOCK, 0)
	if err != nil {
		t.Fatal(err)
	}
	originalDescriptor := descriptors[0]
	stream, err := newVsockStream(originalDescriptor)
	if err != nil {
		_ = unix.Close(descriptors[1])
		t.Fatal(err)
	}
	peer := os.NewFile(uintptr(descriptors[1]), "vsock-race-peer")
	if peer == nil {
		t.Fatal("wrap race peer")
	}

	start := make(chan struct{})
	var concurrent sync.WaitGroup
	for index := 0; index < 64; index++ {
		concurrent.Add(1)
		go func(operation int) {
			defer concurrent.Done()
			<-start
			switch operation % 4 {
			case 0:
				_, _ = stream.Read(make([]byte, 1))
			case 1:
				_, _ = stream.Write([]byte("x"))
			case 2:
				_ = stream.CloseWrite()
			case 3:
				_ = stream.Close()
			}
		}(index)
	}
	close(start)
	_ = peer.Close()
	_ = stream.Close()
	concurrent.Wait()

	var opened []*os.File
	var reused *os.File
	for len(opened) < 128 {
		file, err := os.Open("/dev/null")
		if err != nil {
			t.Fatal(err)
		}
		opened = append(opened, file)
		if int(file.Fd()) == originalDescriptor {
			reused = file
			break
		}
	}
	defer func() {
		for _, file := range opened {
			_ = file.Close()
		}
	}()
	if reused == nil {
		t.Fatalf("descriptor %d was not reused", originalDescriptor)
	}
	for index := 0; index < 64; index++ {
		concurrent.Add(1)
		go func(operation int) {
			defer concurrent.Done()
			switch operation % 4 {
			case 0:
				_, _ = stream.Read(make([]byte, 1))
			case 1:
				_, _ = stream.Write([]byte("x"))
			case 2:
				_ = stream.CloseWrite()
			case 3:
				_ = stream.Close()
			}
		}(index)
	}
	concurrent.Wait()
	if _, err := unix.FcntlInt(reused.Fd(), unix.F_GETFD, 0); err != nil {
		t.Fatalf("old stream operation touched reused descriptor %d: %v", originalDescriptor, err)
	}
}

// This small helper test documents that evidence builders must hash the exact
// native executable bytes rather than the vendor directory name.
func TestCodexDigestUsesFileBytes(t *testing.T) {
	path := filepath.Join(t.TempDir(), "codex")
	contents := []byte("native-codex-fixture")
	if err := os.WriteFile(path, contents, 0o700); err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(contents)
	if hex.EncodeToString(digest[:]) == strings.Repeat("0", 64) {
		t.Fatal("impossible digest collision in fixture")
	}
}
