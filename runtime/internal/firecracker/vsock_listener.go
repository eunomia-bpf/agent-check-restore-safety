package firecracker

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"sync"
	"time"
)

// VsockListenerConfig binds one guest port to one exact Firecracker process.
// It is the general stream counterpart to the fixed restore Gate.
type VsockListenerConfig struct {
	BasePath       string
	Port           uint32
	FirecrackerPID int
	VerifyProcess  func() error
}

// VsockListener accepts host-side connections originating from one
// Firecracker vsock backend. Accepted streams are still protocol-untrusted;
// callers must apply their own bounded framing.
type VsockListener struct {
	config       VsockListenerConfig
	path         string
	listener     *net.UnixListener
	listenerInfo os.FileInfo
	mu           sync.Mutex
	closed       bool
	closeErr     error
}

func ArmVsockListener(config VsockListenerConfig) (*VsockListener, error) {
	if config.Port == 0 {
		return nil, errors.New("Firecracker vsock listener requires a non-zero port")
	}
	if config.FirecrackerPID <= 0 || config.VerifyProcess == nil {
		return nil, errors.New("Firecracker vsock listener requires an exact process identity")
	}
	if err := config.VerifyProcess(); err != nil {
		return nil, fmt.Errorf("verify Firecracker before arming vsock listener: %w", err)
	}
	path, parentInfo, err := relaySocketPath(config.BasePath, config.Port)
	if err != nil {
		return nil, err
	}
	if err := removeStaleRelaySocket(path); err != nil {
		return nil, err
	}
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		return nil, fmt.Errorf("listen on Firecracker vsock stream: %w", err)
	}
	listener.SetUnlinkOnClose(false)
	info, err := privateCreatedSocket(path, nil)
	if err != nil {
		_ = listener.Close()
		return nil, err
	}
	currentParent, err := validatePrivateParent(path)
	if err != nil || !os.SameFile(parentInfo, currentParent) {
		_ = listener.Close()
		_ = removeSameSocket(path, info)
		return nil, errors.New("Firecracker vsock listener parent changed while binding")
	}
	return &VsockListener{config: config, path: path, listener: listener, listenerInfo: info}, nil
}

func (listener *VsockListener) SocketPath() string {
	if listener == nil {
		return ""
	}
	return listener.path
}

// Accept waits for one peer-authenticated Firecracker connection.
func (listener *VsockListener) Accept(ctx context.Context) (*net.UnixConn, error) {
	if listener == nil || listener.listener == nil {
		return nil, errors.New("Firecracker vsock listener is nil")
	}
	if ctx == nil {
		return nil, errors.New("Firecracker vsock listener context is nil")
	}
	for {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		if err := listener.config.VerifyProcess(); err != nil {
			return nil, fmt.Errorf("verify Firecracker before vsock accept: %w", err)
		}
		if err := listener.listener.SetDeadline(time.Now().Add(100 * time.Millisecond)); err != nil {
			return nil, err
		}
		connection, err := listener.listener.AcceptUnix()
		if timeout, ok := err.(net.Error); ok && timeout.Timeout() {
			continue
		}
		if err != nil {
			listener.mu.Lock()
			closed := listener.closed
			listener.mu.Unlock()
			if closed {
				return nil, net.ErrClosed
			}
			return nil, fmt.Errorf("accept Firecracker vsock stream: %w", err)
		}
		if err := listener.verifyConnection(connection); err != nil {
			_ = connection.Close()
			return nil, err
		}
		return connection, nil
	}
}

func (listener *VsockListener) verifyConnection(connection *net.UnixConn) error {
	if err := listener.config.VerifyProcess(); err != nil {
		return fmt.Errorf("verify Firecracker for vsock peer: %w", err)
	}
	pid, err := unixPeerPID(connection)
	if err != nil {
		return fmt.Errorf("read Firecracker vsock peer: %w", err)
	}
	if pid != listener.config.FirecrackerPID {
		return fmt.Errorf("Firecracker vsock peer PID is %d, require %d", pid, listener.config.FirecrackerPID)
	}
	info, err := validatePrivateSocket(listener.path, "Firecracker vsock listener")
	if err != nil || !os.SameFile(listener.listenerInfo, info) {
		return errors.New("Firecracker vsock listener socket identity changed")
	}
	return listener.config.VerifyProcess()
}

func (listener *VsockListener) Close() error {
	if listener == nil {
		return nil
	}
	listener.mu.Lock()
	defer listener.mu.Unlock()
	if listener.closed {
		return listener.closeErr
	}
	listener.closed = true
	listener.closeErr = errors.Join(listener.listener.Close(), removeSameSocket(listener.path, listener.listenerInfo))
	return listener.closeErr
}
