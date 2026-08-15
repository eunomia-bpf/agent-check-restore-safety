// Command postgres-outbox-adapter exposes the provider-adapter protocol over
// a fixed PostgreSQL outbox table.
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

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/postgresoutbox"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/provideradapter"
)

const maxDSNFileBytes = 64 << 10

func main() {
	var dsnPath, listenAddress, effectPath, queryPath string
	var allowNonLoopback bool
	flag.StringVar(&dsnPath, "dsn-file", "", "path to a private file containing the PostgreSQL DSN")
	flag.StringVar(&listenAddress, "listen", "127.0.0.1:8090", "HTTP listen address")
	flag.BoolVar(&allowNonLoopback, "allow-nonloopback", false, "allow an explicitly isolated non-loopback listener")
	flag.StringVar(&effectPath, "effect-path", "/v1/outbox/effects", "immutable effect endpoint path")
	flag.StringVar(&queryPath, "query-path", "/v1/outbox/observations", "immutable observation endpoint path")
	flag.Parse()

	if dsnPath == "" {
		log.Fatal("-dsn-file is required")
	}
	dsn, err := loadPrivateDSN(dsnPath)
	if err != nil {
		log.Fatal(err)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	openCtx, cancelOpen := context.WithTimeout(ctx, 15*time.Second)
	driver, err := postgresoutbox.Open(openCtx, dsn)
	cancelOpen()
	// Discard the only command-local copy before constructing log messages.
	dsn = ""
	if err != nil {
		log.Fatalf("could not open PostgreSQL outbox: %v", err)
	}
	defer driver.Close()

	handler, err := provideradapter.NewHandler(provideradapter.Config{
		EffectPath: effectPath,
		QueryPath:  queryPath,
	}, driver)
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
		log.Fatal("PostgreSQL outbox adapter requires a TCP listener")
	}
	if !listenerAllowed(address, allowNonLoopback) {
		_ = listener.Close()
		log.Fatal("refusing non-loopback PostgreSQL outbox adapter without -allow-nonloopback; remote TLS is not implemented")
	}

	server := &http.Server{
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      35 * time.Second,
		IdleTimeout:       30 * time.Second,
		MaxHeaderBytes:    64 << 10,
	}
	go func() {
		<-ctx.Done()
		shutdownCtx, cancelShutdown := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancelShutdown()
		_ = server.Shutdown(shutdownCtx)
	}()
	log.Printf(
		"PostgreSQL outbox adapter listening on http://%s (effect %s, observation %s)",
		listener.Addr(), effectPath, queryPath,
	)
	if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

func loadPrivateDSN(path string) (string, error) {
	pathInfo, err := os.Lstat(path)
	if err != nil {
		return "", err
	}
	if !pathInfo.Mode().IsRegular() || pathInfo.Mode().Perm()&0o077 != 0 {
		return "", fmt.Errorf("DSN file %q must be a private regular file, not a symlink", path)
	}
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	openedInfo, err := file.Stat()
	if err != nil {
		return "", err
	}
	if !os.SameFile(pathInfo, openedInfo) {
		return "", fmt.Errorf("DSN file %q changed while it was opened", path)
	}
	contents, err := io.ReadAll(io.LimitReader(file, maxDSNFileBytes+1))
	if err != nil {
		return "", fmt.Errorf("read DSN file: %w", err)
	}
	if len(contents) > maxDSNFileBytes {
		return "", fmt.Errorf("DSN file %q exceeds %d bytes", path, maxDSNFileBytes)
	}
	dsn := strings.TrimSpace(string(contents))
	if dsn == "" || strings.ContainsRune(dsn, '\x00') {
		return "", fmt.Errorf("DSN file %q is empty or invalid", path)
	}
	return dsn, nil
}

func listenerAllowed(address *net.TCPAddr, allowNonLoopback bool) bool {
	return address != nil && (allowNonLoopback || address.IP.IsLoopback())
}
