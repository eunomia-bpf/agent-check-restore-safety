package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
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
)

func main() {
	var historyPath string
	var listenAddress string
	var anchorPath string
	var adminTokenPath string
	var operationTokenPath string
	var operationDomain string
	var operationKinds string
	var allowNonLoopback bool
	flag.StringVar(&historyPath, "history", "runtime.history", "path for the durable History")
	flag.StringVar(&anchorPath, "head-anchor", "", "host path outside the History restore domain")
	flag.StringVar(&listenAddress, "listen", "127.0.0.1:8787", "HTTP listen address")
	flag.StringVar(&adminTokenPath, "admin-token-file", "", "path to the admin API token")
	flag.StringVar(&operationTokenPath, "operation-token-file", "", "path to the Operation API token")
	flag.StringVar(&operationDomain, "operation-domain", "local-adapter", "domain bound to the Operation API token")
	flag.StringVar(&operationKinds, "operation-kinds", "", "comma-separated operation kinds allowed for the token")
	flag.BoolVar(&allowNonLoopback, "allow-nonloopback", false, "allow an explicitly isolated non-loopback listener")
	flag.Parse()
	if anchorPath == "" {
		anchorPath = historyPath + ".head-anchor"
	}
	allowedKinds, err := parseKinds(operationKinds)
	if err != nil {
		log.Fatal(err)
	}
	if adminTokenPath == "" {
		adminTokenPath = historyPath + ".admin-token"
	}
	if operationTokenPath == "" {
		operationTokenPath = historyPath + ".operation-token"
	}
	adminToken, err := loadOrCreateToken(adminTokenPath)
	if err != nil {
		log.Fatal(err)
	}
	operationToken, err := loadOrCreateToken(operationTokenPath)
	if err != nil {
		log.Fatal(err)
	}
	if adminToken == operationToken {
		log.Fatal("admin and Operation tokens must differ")
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
	defer c.Close()
	apiServer, err := api.New(c, nil, api.Credentials{
		AdminToken: adminToken,
		Adapters: []api.AdapterCredential{{
			Token: operationToken, Domain: operationDomain, Kinds: allowedKinds,
		}},
	})
	if err != nil {
		listener.Close()
		log.Fatal(err)
	}
	server := &http.Server{
		Handler:           apiServer.Handler(),
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       30 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	fmt.Printf("control API listening on http://%s\n", listener.Addr())
	fmt.Printf("admin token: %s\nOperation token: %s\n", adminTokenPath, operationTokenPath)
	if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
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
