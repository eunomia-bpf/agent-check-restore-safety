package main

import (
	"context"
	"errors"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/payment"
)

func main() {
	var listenAddress string
	var statePath string
	var dropFirst bool
	flag.StringVar(&listenAddress, "listen", "127.0.0.1:8081", "HTTP listen address")
	flag.StringVar(&statePath, "state", "payment.history", "independent durable payment state")
	flag.BoolVar(&dropFirst, "drop-first-response", false, "commit the first new payment and drop its response")
	flag.Parse()

	service, err := payment.Open(statePath, dropFirst)
	if err != nil {
		log.Fatal(err)
	}
	defer service.Close()
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
	log.Printf("payment service listening on http://%s", listenAddress)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}
