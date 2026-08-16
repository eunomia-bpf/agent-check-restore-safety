//go:build linux

package mcpoperation

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"golang.org/x/sys/unix"
)

const unixSocketPathBytes = 108

// UnixHost owns the trusted MCP endpoint outside the Agent restore domain.
// It accepts one same-UID relay at a time and keeps the Server and Journal
// alive across relay and Agent process replacement.
type UnixHost struct {
	mu         sync.Mutex
	listener   *net.UnixListener
	path       string
	parentInfo os.FileInfo
	closed     bool
}

func ListenUnixHost(path string) (*UnixHost, error) {
	parentInfo, err := validateHostSocketPath(path, false)
	if err != nil {
		return nil, err
	}
	if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
		if err == nil {
			return nil, errors.New("trusted MCP socket path already exists")
		}
		return nil, err
	}
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		return nil, fmt.Errorf("listen on trusted MCP socket: %w", err)
	}
	listener.SetUnlinkOnClose(true)
	fail := func(cause error) (*UnixHost, error) {
		_ = listener.Close()
		return nil, cause
	}
	if err := os.Chmod(path, 0o600); err != nil {
		return fail(err)
	}
	info, err := os.Lstat(path)
	if err != nil || info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0o600 || !ownedByCurrentUser(info) {
		return fail(errors.New("trusted MCP endpoint is not a private current-user Unix socket"))
	}
	return &UnixHost{listener: listener, path: path, parentInfo: parentInfo}, nil
}

func validateHostSocketPath(path string, requireSocket bool) (os.FileInfo, error) {
	if path == "" || !filepath.IsAbs(path) || filepath.Clean(path) != path || len([]byte(path)) >= unixSocketPathBytes || strings.ContainsAny(path, "\x00\r\n") {
		return nil, errors.New("trusted MCP socket path must be absolute, canonical, and fit a Unix address")
	}
	parent := filepath.Dir(path)
	parentInfo, err := os.Lstat(parent)
	if err != nil {
		return nil, fmt.Errorf("inspect trusted MCP socket parent: %w", err)
	}
	resolvedParent, err := filepath.EvalSymlinks(parent)
	if err != nil || resolvedParent != parent || !parentInfo.IsDir() || parentInfo.Mode()&os.ModeSymlink != 0 || parentInfo.Mode().Perm() != 0o700 || !ownedByCurrentUser(parentInfo) {
		return nil, errors.New("trusted MCP socket parent must be a current-user direct directory with mode 0700")
	}
	if requireSocket {
		info, err := os.Lstat(path)
		if err != nil || info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0o600 || !ownedByCurrentUser(info) {
			return nil, errors.New("trusted MCP endpoint is not a private current-user Unix socket")
		}
	}
	return parentInfo, nil
}

func (host *UnixHost) Path() string {
	if host == nil {
		return ""
	}
	return host.path
}

func (host *UnixHost) Close() error {
	if host == nil {
		return nil
	}
	host.mu.Lock()
	defer host.mu.Unlock()
	if host.closed {
		return nil
	}
	host.closed = true
	return host.listener.Close()
}

func (host *UnixHost) validateParent() error {
	current, err := os.Lstat(filepath.Dir(host.path))
	if err != nil || host.parentInfo == nil || !os.SameFile(host.parentInfo, current) {
		return errors.New("trusted MCP socket parent identity changed")
	}
	return nil
}

func peerCredentials(connection *net.UnixConn) (*unix.Ucred, error) {
	raw, err := connection.SyscallConn()
	if err != nil {
		return nil, err
	}
	var credential *unix.Ucred
	var socketErr error
	if err := raw.Control(func(fd uintptr) {
		credential, socketErr = unix.GetsockoptUcred(int(fd), unix.SOL_SOCKET, unix.SO_PEERCRED)
	}); err != nil {
		return nil, err
	}
	if socketErr != nil || credential == nil {
		return nil, errors.Join(errors.New("read MCP relay peer credentials"), socketErr)
	}
	return credential, nil
}

// Serve accepts replacement relays until cancellation. MCP framing and all
// durable call state remain in Server; disconnects are transport failures and
// never erase or recreate the Journal.
func (host *UnixHost) Serve(ctx context.Context, server *Server, diagnostics io.Writer) error {
	if host == nil || host.listener == nil || server == nil || ctx == nil || diagnostics == nil {
		return errors.New("trusted MCP host requires context, listener, server, and diagnostics")
	}
	go func() {
		<-ctx.Done()
		_ = host.Close()
	}()
	for {
		if err := host.validateParent(); err != nil {
			return err
		}
		connection, err := host.listener.AcceptUnix()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("accept MCP relay: %w", err)
		}
		credential, credentialErr := peerCredentials(connection)
		if credentialErr != nil || credential == nil || int(credential.Uid) != os.Geteuid() {
			_, _ = fmt.Fprintf(diagnostics, "rejected MCP relay peer: %v\n", credentialErr)
			_ = connection.Close()
			continue
		}
		_, _ = fmt.Fprintf(diagnostics, "{\"event\":\"relay_accept\",\"pid\":%d,\"uid\":%d}\n", credential.Pid, credential.Uid)
		connectionDone := make(chan struct{})
		go func() {
			select {
			case <-ctx.Done():
				_ = connection.Close()
			case <-connectionDone:
			}
		}()
		serveErr := server.Serve(ctx, connection, connection, diagnostics)
		close(connectionDone)
		_ = connection.Close()
		_, _ = fmt.Fprintf(diagnostics, "{\"event\":\"relay_disconnect\",\"pid\":%d,\"uid\":%d}\n", credential.Pid, credential.Uid)
		if ctx.Err() != nil {
			return nil
		}
		if serveErr != nil && !errors.Is(serveErr, ErrTransport) {
			return serveErr
		}
	}
}

// RelayUnix connects untrusted MCP stdio to the host-owned endpoint. The
// relay carries no journal, tool configuration, sandbox identity, provider
// route, or credential and does not interpret MCP messages.
func RelayUnix(ctx context.Context, path string, input io.Reader, output io.Writer) error {
	if ctx == nil || input == nil || output == nil {
		return errors.New("MCP relay requires context and both stdio streams")
	}
	if _, err := validateHostSocketPath(path, true); err != nil {
		return err
	}
	connection, err := net.DialUnix("unix", nil, &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		return fmt.Errorf("connect trusted MCP host: %w", err)
	}
	defer connection.Close()
	inputDone := make(chan error, 1)
	go func() {
		_, copyErr := io.Copy(connection, input)
		closeErr := connection.CloseWrite()
		inputDone <- errors.Join(copyErr, closeErr)
	}()
	outputDone := make(chan error, 1)
	go func() {
		_, copyErr := io.Copy(output, connection)
		outputDone <- copyErr
	}()
	select {
	case inputErr := <-inputDone:
		if inputErr != nil {
			_ = connection.Close()
			return inputErr
		}
		select {
		case outputErr := <-outputDone:
			return outputErr
		case <-ctx.Done():
			_ = connection.Close()
			return nil
		}
	case outputErr := <-outputDone:
		_ = connection.Close()
		return outputErr
	case <-ctx.Done():
		_ = connection.Close()
		return nil
	}
}
