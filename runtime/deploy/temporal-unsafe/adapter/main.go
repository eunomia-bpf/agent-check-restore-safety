// Command temporal-provider-adapter presents the exact HTTP shape expected by
// the frozen Temporal worker while keeping all effect authority in the durable
// control runtime. It is deliberately not a general reverse or forward proxy.
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

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/apiclient"
)

const maxTokenFileBytes = 4096

func main() {
	var configPath, controlURL, tokenPath, listenAddress string
	var allowNonLoopback bool
	var executionTimeout time.Duration
	flag.StringVar(&configPath, "config", "", "path to the strict provider-route JSON config")
	flag.StringVar(&controlURL, "control-url", "http://127.0.0.1:8787", "fixed durable control API URL")
	flag.StringVar(&tokenPath, "adapter-token-file", "", "path to the private adapter Bearer token")
	flag.StringVar(&listenAddress, "listen", "127.0.0.1:8790", "Temporal-facing TCP listen address")
	flag.BoolVar(&allowNonLoopback, "allow-nonloopback", false, "allow an explicitly isolated non-loopback listener")
	flag.DurationVar(&executionTimeout, "execute-timeout", 30*time.Second, "deadline for one control-mediated provider Operation")
	flag.Parse()

	if configPath == "" {
		log.Fatal("-config is required")
	}
	if tokenPath == "" {
		log.Fatal("-adapter-token-file is required")
	}
	if executionTimeout <= 0 || executionTimeout > 10*time.Minute {
		log.Fatal("-execute-timeout must be positive and at most 10m")
	}
	config, err := loadConfig(configPath)
	if err != nil {
		log.Fatal(err)
	}
	token, err := loadPrivateToken(tokenPath)
	if err != nil {
		log.Fatal(err)
	}
	client, err := apiclient.New(controlURL, token, controlHTTPClient(executionTimeout))
	if err != nil {
		log.Fatal(err)
	}
	adapter, err := NewAdapter(client, config, executionTimeout)
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
		log.Fatal("provider adapter requires a TCP listener")
	}
	if !listenerAllowed(address, allowNonLoopback) {
		_ = listener.Close()
		log.Fatal("refusing non-loopback listener without -allow-nonloopback; remote TLS is not implemented")
	}

	server := &http.Server{
		Handler: adapter.Handler(), ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout: 10 * time.Second, WriteTimeout: executionTimeout + 5*time.Second,
		IdleTimeout: 30 * time.Second, MaxHeaderBytes: 16 << 10,
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	log.Printf("Temporal provider adapter listening on http://%s with %d immutable bindings", listener.Addr(), len(config.Routes))
	if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

func loadConfig(path string) (Config, error) {
	data, err := loadRegularFile(path, maxConfigBytes, "adapter config", false)
	if err != nil {
		return Config{}, err
	}
	return ParseConfig(data)
}

func loadPrivateToken(path string) (string, error) {
	data, err := loadRegularFile(path, maxTokenFileBytes, "adapter token", true)
	if err != nil {
		return "", err
	}
	token := strings.TrimSpace(string(data))
	if len(token) < 32 || strings.IndexFunc(token, func(character rune) bool {
		return unicode.IsSpace(character) || unicode.IsControl(character)
	}) >= 0 {
		return "", fmt.Errorf("adapter token file %q must contain one token of at least 32 bytes", path)
	}
	return token, nil
}

func loadRegularFile(path string, maxBytes int64, label string, private bool) ([]byte, error) {
	pathInfo, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !pathInfo.Mode().IsRegular() {
		return nil, fmt.Errorf("%s %q must be a regular file, not a symlink", label, path)
	}
	if private && pathInfo.Mode().Perm()&0o077 != 0 {
		return nil, fmt.Errorf("%s %q must not be accessible by group or other", label, path)
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	openedInfo, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if !os.SameFile(pathInfo, openedInfo) {
		return nil, fmt.Errorf("%s %q changed while it was opened", label, path)
	}
	data, err := io.ReadAll(io.LimitReader(file, maxBytes+1))
	if err != nil {
		return nil, fmt.Errorf("read %s: %w", label, err)
	}
	if int64(len(data)) > maxBytes {
		return nil, fmt.Errorf("%s %q exceeds %d bytes", label, path, maxBytes)
	}
	return data, nil
}

func listenerAllowed(address *net.TCPAddr, allowNonLoopback bool) bool {
	return address != nil && (allowNonLoopback || address.IP.IsLoopback())
}

func controlHTTPClient(timeout time.Duration) *http.Client {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	// Never expose the private adapter token to HTTP_PROXY/HTTPS_PROXY selected
	// from the process environment.
	transport.Proxy = nil
	transport.DialContext = (&net.Dialer{Timeout: 5 * time.Second, KeepAlive: 30 * time.Second}).DialContext
	transport.TLSHandshakeTimeout = 5 * time.Second
	transport.ResponseHeaderTimeout = timeout
	transport.MaxIdleConns = 8
	transport.MaxIdleConnsPerHost = 8
	return &http.Client{Transport: transport, Timeout: timeout}
}
