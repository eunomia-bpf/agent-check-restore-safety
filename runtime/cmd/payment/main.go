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
	var alwaysDropBeforeCommit bool
	var holdBeforeCommit bool
	var holdAfterCommit bool
	var nonIdempotent bool
	var referencePrefix string
	flag.StringVar(&listenAddress, "listen", "127.0.0.1:8081", "HTTP listen address")
	flag.StringVar(&statePath, "state", "payment.history", "independent durable payment state")
	flag.BoolVar(&dropFirst, "drop-first-response", false, "commit the first new payment and drop its response")
	flag.BoolVar(&alwaysDropBeforeCommit, "always-drop-before-commit", false, "drop every new payment request before committing it")
	flag.BoolVar(&holdBeforeCommit, "hold-before-commit", false, "hold every new payment before commit until its connection is canceled")
	flag.BoolVar(&holdAfterCommit, "hold-after-commit", false, "commit the next payment and hold its response until SIGUSR1 or cancellation")
	flag.BoolVar(&nonIdempotent, "non-idempotent", false, "commit repeated deliveries of identical Operation work independently")
	flag.StringVar(&referencePrefix, "reference-prefix", "payment", "label used in durable remote references")
	flag.Parse()

	service, err := payment.OpenWithOptions(statePath, payment.Options{
		DropFirstResponse: dropFirst, AlwaysDropBeforeCommit: alwaysDropBeforeCommit,
		HoldBeforeCommit: holdBeforeCommit, HoldAfterCommit: holdAfterCommit,
		NonIdempotent: nonIdempotent, ReferencePrefix: referencePrefix,
	})
	if err != nil {
		log.Fatal(err)
	}
	defer service.Close()
	releaseSignals := make(chan os.Signal, 1)
	signal.Notify(releaseSignals, syscall.SIGUSR1)
	defer signal.Stop(releaseSignals)
	go func() {
		for range releaseSignals {
			if service.ReleaseHeldAfterCommit() {
				log.Printf("released held post-commit response")
			} else {
				log.Printf("ignored SIGUSR1 without an active post-commit hold")
			}
		}
	}()
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
