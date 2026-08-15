package main

import (
	"context"
	"errors"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/order"
)

func main() {
	var listenAddress string
	var configPath string
	var controlURL string
	var tokenPath string
	flag.StringVar(&listenAddress, "listen", "127.0.0.1:8080", "HTTP listen address")
	flag.StringVar(&configPath, "release", "", "path to the process-wide release configuration")
	flag.StringVar(&controlURL, "control", "http://127.0.0.1:8787", "control service URL")
	flag.StringVar(&tokenPath, "operation-token-file", "", "path to the Operation API token")
	flag.Parse()
	if configPath == "" {
		log.Fatal("-release is required")
	}
	config, err := order.LoadConfig(configPath)
	if err != nil {
		log.Fatal(err)
	}
	service, err := serviceForRelease(config, controlURL, tokenPath)
	if err != nil {
		log.Fatal(err)
	}
	server := &http.Server{
		Addr: listenAddress, Handler: service.Handler(),
		ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 30 * time.Second,
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	log.Printf("order release %s listening on http://%s", config.Version, listenAddress)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

func serviceForRelease(config order.Config, controlURL, tokenPath string) (*order.Service, error) {
	if config.UsesEffectProxy() {
		if tokenPath != "" {
			return nil, errors.New("-operation-token-file must not be set for a proxy release")
		}
		return order.NewProxy(config, nil)
	}
	if tokenPath == "" {
		return nil, errors.New("-operation-token-file is required for a legacy release")
	}
	tokenBytes, err := os.ReadFile(tokenPath)
	if err != nil {
		return nil, err
	}
	return order.New(config, controlURL, strings.TrimSpace(string(tokenBytes)), nil)
}
