// Command effect-proxy gives workload code a small set of named effects. It
// holds the adapter credential and exact provider targets on the workload's
// behalf; it is deliberately not a forward proxy.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
	"unicode"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/apiclient"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/effectproxy"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/mcpoperation"
)

const maxTokenFileBytes = 4096

func main() {
	var configPath, controlURL, tokenPath, sandboxSocket, listenAddress string
	var allowNonLoopback bool
	var executeTimeout time.Duration
	flag.StringVar(&configPath, "config", "", "path to the strict effect-route JSON config")
	flag.StringVar(&controlURL, "control-url", "http://127.0.0.1:8787", "fixed durable control API URL")
	flag.StringVar(&tokenPath, "adapter-token-file", "", "path to the private adapter Bearer token")
	flag.StringVar(&sandboxSocket, "sandbox-socket", "", "generation-bound credential-free sandbox Operation socket")
	flag.StringVar(&listenAddress, "listen", "127.0.0.1:8788", "workload-facing HTTP listen address")
	flag.BoolVar(&allowNonLoopback, "allow-nonloopback", false, "allow an explicitly isolated non-loopback listener")
	flag.DurationVar(&executeTimeout, "execute-timeout", 30*time.Second, "deadline for one control-mediated effect")
	flag.Parse()

	if configPath == "" {
		log.Fatal("-config is required")
	}
	if (tokenPath == "") == (sandboxSocket == "") {
		log.Fatal("exactly one -adapter-token-file or -sandbox-socket is required")
	}
	if executeTimeout <= 0 || executeTimeout > 10*time.Minute {
		log.Fatal("-execute-timeout must be positive and at most 10m")
	}
	configuration, err := loadConfig(configPath)
	if err != nil {
		log.Fatal(err)
	}
	var executor effectproxy.Executor
	if sandboxSocket != "" {
		sandbox, err := mcpoperation.NewSandboxExecutor(sandboxSocket, mcpoperation.SandboxExecutorOptions{
			RecoveryAttempts: mcpoperation.DefaultRecoveryAttempts,
			RequestTimeout:   executeTimeout,
		})
		if err != nil {
			log.Fatal(err)
		}
		defer sandbox.Close()
		executor = sandboxEffectExecutor{sandbox}
	} else {
		token, err := loadPrivateToken(tokenPath)
		if err != nil {
			log.Fatal(err)
		}
		client, err := apiclient.New(controlURL, token, controlHTTPClient(executeTimeout))
		if err != nil {
			log.Fatal(err)
		}
		executor = client
	}
	proxy, err := effectproxy.New(executor, configuration, effectproxy.Options{ExecutionTimeout: executeTimeout})
	if err != nil {
		log.Fatal(err)
	}
	listener, err := net.Listen("tcp", listenAddress)
	if err != nil {
		log.Fatal(err)
	}
	address, ok := listener.Addr().(*net.TCPAddr)
	if !ok {
		_ = listener.Close()
		log.Fatal("effect proxy requires a TCP listener")
	}
	if !listenerAllowed(address, allowNonLoopback) {
		_ = listener.Close()
		log.Fatal("refusing non-loopback effect proxy without -allow-nonloopback; remote TLS is not implemented")
	}

	server := &http.Server{
		Handler: proxy.Handler(), ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout: 15 * time.Second, WriteTimeout: executeTimeout + 5*time.Second,
		IdleTimeout: 30 * time.Second, MaxHeaderBytes: 64 << 10,
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	log.Printf("effect proxy listening on http://%s with %d fixed routes", listener.Addr(), len(configuration.Routes))
	if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

type sandboxEffectExecutor struct{ sandbox *mcpoperation.SandboxExecutor }

func (executor sandboxEffectExecutor) Execute(ctx context.Context, request api.ExecuteRequest) (gateway.Outcome, error) {
	if executor.sandbox == nil {
		return gateway.Outcome{}, errors.New("sandbox effect executor is unavailable")
	}
	return executor.sandbox.Execute(ctx, request.CallID, request.Kind, request.Body)
}

func loadConfig(path string) (effectproxy.Config, error) {
	file, err := os.Open(path)
	if err != nil {
		return effectproxy.Config{}, err
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, effectproxy.MaxConfigBytes+1))
	if err != nil {
		return effectproxy.Config{}, fmt.Errorf("read effect proxy config: %w", err)
	}
	return effectproxy.ParseConfig(data)
}

func loadPrivateToken(path string) (string, error) {
	pathInfo, err := os.Lstat(path)
	if err != nil {
		return "", err
	}
	if !pathInfo.Mode().IsRegular() || pathInfo.Mode().Perm()&0o077 != 0 {
		return "", fmt.Errorf("adapter token file %q must be a private regular file, not a symlink", path)
	}
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return "", err
	}
	if !os.SameFile(pathInfo, info) {
		return "", fmt.Errorf("adapter token file %q changed while it was opened", path)
	}
	data, err := io.ReadAll(io.LimitReader(file, maxTokenFileBytes+1))
	if err != nil {
		return "", fmt.Errorf("read adapter token file: %w", err)
	}
	if len(data) > maxTokenFileBytes {
		return "", fmt.Errorf("adapter token file %q exceeds %d bytes", path, maxTokenFileBytes)
	}
	token := strings.TrimSpace(string(data))
	if len(token) < 32 || strings.IndexFunc(token, unicode.IsSpace) >= 0 || strings.ContainsAny(token, "\x00\r\n") {
		return "", fmt.Errorf("adapter token file %q must contain one token of at least 32 bytes", path)
	}
	return token, nil
}

func listenerAllowed(address *net.TCPAddr, allowNonLoopback bool) bool {
	return address != nil && (allowNonLoopback || address.IP.IsLoopback())
}

func controlHTTPClient(timeout time.Duration) *http.Client {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	// The adapter credential is scoped to the fixed control API. Do not send it
	// through an ambient HTTP_PROXY selected by the process environment.
	transport.Proxy = nil
	transport.DialContext = (&net.Dialer{Timeout: 5 * time.Second, KeepAlive: 30 * time.Second}).DialContext
	transport.TLSHandshakeTimeout = 5 * time.Second
	transport.ResponseHeaderTimeout = timeout
	return &http.Client{Transport: transport, Timeout: timeout}
}
