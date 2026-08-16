package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/sandboxhost"
)

func main() {
	var historyPath string
	var listenAddress string
	var anchorPath string
	var adminTokenPath string
	var operationTokenPath string
	var operationDomain string
	var operationKinds string
	var adapterConfigPath string
	var sandboxSocketDirectory string
	var allowNonLoopback bool
	flag.StringVar(&historyPath, "history", "runtime.history", "path for the durable History")
	flag.StringVar(&anchorPath, "head-anchor", "", "host path outside the History restore domain")
	flag.StringVar(&listenAddress, "listen", "127.0.0.1:8787", "HTTP listen address")
	flag.StringVar(&adminTokenPath, "admin-token-file", "", "path to the admin API token")
	flag.StringVar(&operationTokenPath, "operation-token-file", "", "path to the Operation API token")
	flag.StringVar(&operationDomain, "operation-domain", "local-adapter", "domain bound to the Operation API token")
	flag.StringVar(&operationKinds, "operation-kinds", "", "comma-separated operation kinds allowed for the token")
	flag.StringVar(&adapterConfigPath, "adapter-config", "", "strict JSON file containing independently scoped adapter credentials")
	flag.StringVar(&sandboxSocketDirectory, "sandbox-socket-dir", "", "private directory for host-owned sandbox Unix sockets")
	flag.BoolVar(&allowNonLoopback, "allow-nonloopback", false, "allow an explicitly isolated non-loopback listener")
	flag.Parse()
	if anchorPath == "" {
		anchorPath = historyPath + ".head-anchor"
	}
	if adminTokenPath == "" {
		adminTokenPath = historyPath + ".admin-token"
	}
	adminToken, err := loadOrCreateToken(adminTokenPath)
	if err != nil {
		log.Fatal(err)
	}
	adapters, err := loadRuntimeAdapters(
		adapterConfigPath,
		operationTokenPath,
		operationDomain,
		operationKinds,
		historyPath,
		sandboxSocketDirectory,
	)
	if err != nil {
		log.Fatal(err)
	}
	for _, adapter := range adapters {
		if adminToken == adapter.Token {
			log.Fatal("admin and adapter tokens must differ")
		}
	}

	listener, err := net.Listen("tcp", listenAddress)
	if err != nil {
		log.Fatal(err)
	}
	address, ok := listener.Addr().(*net.TCPAddr)
	if !ok {
		listener.Close()
		log.Fatal("control API requires a TCP listener")
	}
	if !listenerAllowed(address, allowNonLoopback) {
		listener.Close()
		log.Fatal("refusing non-loopback control API without -allow-nonloopback; remote TLS is not implemented")
	}

	c, err := control.OpenWithAnchor(historyPath, anchorPath)
	if err != nil {
		listener.Close()
		log.Fatal(err)
	}
	apiServer, err := api.New(c, nil, api.Credentials{
		AdminToken: adminToken,
		Adapters:   adapters,
	})
	if err != nil {
		listener.Close()
		c.Close()
		log.Fatal(err)
	}
	var sandboxManager *sandboxhost.Manager
	if sandboxSocketDirectory != "" {
		if err := ensurePrivateDirectory(sandboxSocketDirectory); err != nil {
			listener.Close()
			c.Close()
			log.Fatal(err)
		}
		sandboxManager, err = sandboxhost.NewManager(c, apiServer, sandboxSocketDirectory)
		if err != nil {
			listener.Close()
			c.Close()
			log.Fatal(err)
		}
		if err := apiServer.SetSandboxEndpointPublisher(sandboxManager); err != nil {
			listener.Close()
			sandboxManager.Close()
			c.Close()
			log.Fatal(err)
		}
	}
	server := &http.Server{
		Handler:           apiServer.Handler(),
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       30 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	shutdownDone := make(chan error, 1)
	go func() {
		<-ctx.Done()
		shutdownDone <- shutdownRuntime(apiServer, server, sandboxManager, c)
	}()
	fmt.Printf("control API listening on http://%s\n", listener.Addr())
	fmt.Printf("admin token: %s\nadapter credentials: %d\n", adminTokenPath, len(adapters))
	if sandboxManager != nil {
		fmt.Printf("sandbox endpoints: %s\n", sandboxSocketDirectory)
	}
	serveErr := server.Serve(listener)
	if ctx.Err() == nil {
		stop()
	}
	shutdownErr := <-shutdownDone
	if serveErr != nil && !errors.Is(serveErr, http.ErrServerClosed) {
		log.Fatal(errors.Join(serveErr, shutdownErr))
	}
	if shutdownErr != nil {
		log.Fatal(shutdownErr)
	}
}

func shutdownRuntime(
	apiServer *api.Server,
	server *http.Server,
	sandboxManager *sandboxhost.Manager,
	controller *control.Control,
) error {
	apiServer.QuiesceCutovers()
	shutdownContext, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	serverShutdownErr := server.Shutdown(shutdownContext)
	cancel()
	if serverShutdownErr != nil {
		serverShutdownErr = errors.Join(serverShutdownErr, server.Close())
	}
	var sandboxErr error
	if sandboxManager != nil {
		sandboxErr = sandboxManager.Close()
	}
	controlErr := controller.Close()
	return errors.Join(serverShutdownErr, sandboxErr, controlErr)
}

func ensurePrivateDirectory(path string) error {
	if path == "" || !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return errors.New("sandbox socket directory must be absolute and canonical")
	}
	if err := os.Mkdir(path, 0o700); err != nil && !errors.Is(err, os.ErrExist) {
		return fmt.Errorf("create sandbox socket directory: %w", err)
	}
	return nil
}

const maxAdapterConfigBytes = 1 << 20

func loadRuntimeAdapters(
	configPath, legacyTokenPath, legacyDomain, legacyKinds, historyPath, sandboxSocketDirectory string,
) ([]api.AdapterCredential, error) {
	if sandboxSocketDirectory != "" && configPath == "" && legacyTokenPath == "" && legacyKinds == "" {
		return nil, nil
	}
	return loadAdapters(configPath, legacyTokenPath, legacyDomain, legacyKinds, historyPath)
}

type adapterConfig struct {
	Schema   int                  `json:"schema"`
	Adapters []adapterConfigEntry `json:"adapters"`
}

type adapterConfigEntry struct {
	Domain    string   `json:"domain"`
	TokenFile string   `json:"token_file"`
	Kinds     []string `json:"kinds"`
}

func loadAdapters(configPath, legacyTokenPath, legacyDomain, legacyKinds, historyPath string) ([]api.AdapterCredential, error) {
	if configPath == "" {
		allowedKinds, err := parseKinds(legacyKinds)
		if err != nil {
			return nil, err
		}
		if legacyTokenPath == "" {
			legacyTokenPath = historyPath + ".operation-token"
		}
		token, err := loadOrCreateToken(legacyTokenPath)
		if err != nil {
			return nil, err
		}
		return []api.AdapterCredential{{
			Token: token, Domain: legacyDomain, Kinds: allowedKinds,
		}}, nil
	}
	if legacyTokenPath != "" || legacyDomain != "local-adapter" || legacyKinds != "" {
		return nil, errors.New("-adapter-config cannot be combined with legacy Operation credential flags")
	}
	data, err := os.ReadFile(configPath)
	if err != nil {
		return nil, err
	}
	if len(data) > maxAdapterConfigBytes {
		return nil, fmt.Errorf("adapter config exceeds %d bytes", maxAdapterConfigBytes)
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var configuration adapterConfig
	if err := decoder.Decode(&configuration); err != nil {
		return nil, fmt.Errorf("decode adapter config: %w", err)
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return nil, errors.New("adapter config contains multiple JSON values")
		}
		return nil, fmt.Errorf("decode adapter config trailer: %w", err)
	}
	if configuration.Schema != 1 {
		return nil, fmt.Errorf("unsupported adapter config schema %d", configuration.Schema)
	}
	if len(configuration.Adapters) == 0 || len(configuration.Adapters) > 32 {
		return nil, errors.New("adapter config must contain between 1 and 32 adapters")
	}
	credentials := make([]api.AdapterCredential, 0, len(configuration.Adapters))
	seenDomains := make(map[string]bool)
	seenTokenFiles := make(map[string]bool)
	seenTokens := make(map[string]bool)
	for index, entry := range configuration.Adapters {
		if entry.Domain == "" || seenDomains[entry.Domain] {
			return nil, fmt.Errorf("adapter %d has an empty or duplicate domain", index)
		}
		seenDomains[entry.Domain] = true
		if entry.TokenFile == "" || seenTokenFiles[entry.TokenFile] {
			return nil, fmt.Errorf("adapter %d has an empty or duplicate token file", index)
		}
		seenTokenFiles[entry.TokenFile] = true
		if len(entry.Kinds) == 0 {
			return nil, fmt.Errorf("adapter %d has no allowed kind", index)
		}
		seenKinds := make(map[string]bool)
		for _, kind := range entry.Kinds {
			if kind == "" || seenKinds[kind] {
				return nil, fmt.Errorf("adapter %d has an empty or duplicate kind", index)
			}
			seenKinds[kind] = true
		}
		token, err := loadOrCreateToken(entry.TokenFile)
		if err != nil {
			return nil, fmt.Errorf("load adapter %q token: %w", entry.Domain, err)
		}
		if seenTokens[token] {
			return nil, fmt.Errorf("adapter %q reuses another adapter token", entry.Domain)
		}
		seenTokens[token] = true
		credentials = append(credentials, api.AdapterCredential{
			Token: token, Domain: entry.Domain, Kinds: append([]string(nil), entry.Kinds...),
		})
	}
	return credentials, nil
}

func listenerAllowed(address *net.TCPAddr, allowNonLoopback bool) bool {
	return allowNonLoopback || address.IP.IsLoopback()
}

func parseKinds(value string) ([]string, error) {
	seen := make(map[string]bool)
	var kinds []string
	for _, part := range strings.Split(value, ",") {
		kind := strings.TrimSpace(part)
		if kind == "" {
			continue
		}
		if seen[kind] {
			return nil, fmt.Errorf("duplicate operation kind %q", kind)
		}
		seen[kind] = true
		kinds = append(kinds, kind)
	}
	if len(kinds) == 0 {
		return nil, errors.New("-operation-kinds must name at least one allowed kind")
	}
	return kinds, nil
}

func loadOrCreateToken(path string) (string, error) {
	contents, err := os.ReadFile(path)
	if err == nil {
		info, statErr := os.Stat(path)
		if statErr != nil {
			return "", statErr
		}
		if !info.Mode().IsRegular() || info.Mode().Perm()&0o077 != 0 {
			return "", fmt.Errorf("token file %q must be a private regular file", path)
		}
		token := strings.TrimSpace(string(contents))
		if len(token) < 32 {
			return "", fmt.Errorf("token file %q is too short", path)
		}
		return token, nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return "", err
	}
	random := make([]byte, 32)
	if _, err := rand.Read(random); err != nil {
		return "", err
	}
	token := hex.EncodeToString(random)
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return "", err
	}
	if _, err := file.WriteString(token + "\n"); err != nil {
		_ = file.Close()
		return "", err
	}
	if err := file.Sync(); err != nil {
		_ = file.Close()
		return "", err
	}
	if err := file.Close(); err != nil {
		return "", err
	}
	directory, err := os.Open(filepath.Dir(path))
	if err != nil {
		return "", err
	}
	syncErr := directory.Sync()
	closeErr := directory.Close()
	if syncErr != nil {
		return "", syncErr
	}
	if closeErr != nil {
		return "", closeErr
	}
	return token, nil
}
