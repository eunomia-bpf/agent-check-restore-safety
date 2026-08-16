// Package sandboxhost owns the host side of sandbox-only HTTP channels.
package sandboxhost

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"sync"
	"time"

	controlapi "github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
)

const (
	readHeaderTimeout = 5 * time.Second
	writeTimeout      = 60 * time.Second
	idleTimeout       = 5 * time.Second
)

// Endpoint is one loopback listener bound to one concrete sandbox generation.
// Its handler captures the binding; requests cannot select or forge it. A VM
// supervisor must close the endpoint before publishing a replacement binding.
type Endpoint struct {
	control  *control.Control
	binding  control.SandboxBinding
	listener net.Listener
	server   *http.Server
	done     chan error

	closeOnce sync.Once
	closeErr  error
}

// Listen creates and attaches a sandbox-only endpoint. The listener is limited
// to host loopback so a VM monitor or a namespace-local proxy can be the only
// route into it. The finite WriteTimeout bounds how long response delivery can
// delay a Rule-and-sandbox cutover.
func Listen(
	controller *control.Control,
	serverAPI *controlapi.Server,
	binding control.SandboxBinding,
	address string,
) (*Endpoint, error) {
	if controller == nil || serverAPI == nil {
		return nil, errors.New("sandbox endpoint requires control and API")
	}
	listener, err := net.Listen("tcp", address)
	if err != nil {
		return nil, err
	}
	tcpAddress, ok := listener.Addr().(*net.TCPAddr)
	if !ok || !tcpAddress.IP.IsLoopback() {
		_ = listener.Close()
		return nil, errors.New("sandbox endpoint must listen on host loopback")
	}
	handler, err := serverAPI.HandlerForSandbox(binding)
	if err != nil {
		_ = listener.Close()
		return nil, err
	}
	endpoint := &Endpoint{
		control:  controller,
		binding:  cloneBinding(binding),
		listener: listener,
		done:     make(chan error, 1),
	}
	endpoint.server = &http.Server{
		Handler:           handler,
		ReadHeaderTimeout: readHeaderTimeout,
		WriteTimeout:      writeTimeout,
		IdleTimeout:       idleTimeout,
	}
	go func() {
		err := endpoint.server.Serve(listener)
		if errors.Is(err, http.ErrServerClosed) {
			err = nil
		}
		endpoint.done <- err
		close(endpoint.done)
	}()
	return endpoint, nil
}

// Address returns the concrete loopback address suitable for a VM-owned
// forward. It is host configuration, never guest-supplied identity.
func (e *Endpoint) Address() string {
	return e.listener.Addr().String()
}

// Binding returns an independent copy of the captured sandbox identity.
func (e *Endpoint) Binding() control.SandboxBinding {
	return cloneBinding(e.binding)
}

// Close drains the bounded HTTP server and then detaches exactly this sandbox
// generation. It is idempotent. A stale endpoint cannot detach a newer one.
func (e *Endpoint) Close(ctx context.Context) error {
	if e == nil {
		return nil
	}
	e.closeOnce.Do(func() {
		shutdownErr := e.server.Shutdown(ctx)
		if shutdownErr != nil {
			_ = e.server.Close()
		}
		serveErr := <-e.done
		detachErr := e.control.DetachSandboxHost(e.binding)
		e.closeErr = errors.Join(shutdownErr, serveErr, detachErr)
	})
	return e.closeErr
}

// Port returns the concrete TCP port used by a VM monitor forward.
func (e *Endpoint) Port() (int, error) {
	address, ok := e.listener.Addr().(*net.TCPAddr)
	if !ok || address.Port == 0 {
		return 0, fmt.Errorf("sandbox endpoint has invalid TCP address %q", e.listener.Addr())
	}
	return address.Port, nil
}

func cloneBinding(binding control.SandboxBinding) control.SandboxBinding {
	binding.AllowedKinds = append([]string(nil), binding.AllowedKinds...)
	return binding
}
