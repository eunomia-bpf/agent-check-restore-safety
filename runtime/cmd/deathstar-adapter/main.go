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

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/deathstar"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
	"go.mongodb.org/mongo-driver/v2/mongo/readpref"
)

func main() {
	var mode, listenAddress, frontendURL, auditPath, terminalFenceDirectory string
	var mongoURI, mongoDatabase, mongoCollection string
	var dropFirst, abortBeforeUpstream bool
	var postCommitDelay, preUpstreamAbortDelay time.Duration
	flag.StringVar(&mode, "mode", "", "adapter mode: effect or observer")
	flag.StringVar(&listenAddress, "listen", "127.0.0.1:8090", "HTTP listen address")
	flag.StringVar(&frontendURL, "frontend", "http://127.0.0.1:5000", "DeathStarBench frontend base URL")
	flag.StringVar(&auditPath, "audit", "deathstar-adapter.audit.jsonl", "effect delivery audit path")
	flag.BoolVar(&dropFirst, "drop-first-response", false, "drop the first response after upstream commits")
	flag.BoolVar(&abortBeforeUpstream, "abort-before-upstream", false, "durably fence the Operation before any application delivery and close without a response")
	flag.DurationVar(&preUpstreamAbortDelay, "pre-upstream-abort-delay", 0, "delay connection loss after the durable pre-upstream fence")
	flag.StringVar(&terminalFenceDirectory, "terminal-fence-directory", "", "private directory shared by the effect fault gate and observer")
	flag.DurationVar(&postCommitDelay, "post-commit-delay", 0, "delay each successful response after its upstream commit")
	flag.StringVar(&mongoURI, "mongo-uri", "mongodb://127.0.0.1:27017", "reservation MongoDB URI")
	flag.StringVar(&mongoDatabase, "mongo-database", "reservation-db", "reservation MongoDB database")
	flag.StringVar(&mongoCollection, "mongo-collection", "reservation", "reservation MongoDB collection")
	flag.Parse()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	var handler http.Handler
	var closeService func() error
	switch mode {
	case "effect":
		service, err := deathstar.OpenEffect(deathstar.EffectConfig{
			FrontendURL: frontendURL, AuditPath: auditPath, DropFirstResponse: dropFirst,
			AbortBeforeUpstream: abortBeforeUpstream, TerminalFenceDirectory: terminalFenceDirectory,
			PreUpstreamAbortDelay: preUpstreamAbortDelay,
			PostCommitDelay:       postCommitDelay,
		})
		if err != nil {
			log.Fatal(err)
		}
		handler = service.Handler()
		closeService = service.Close
	case "observer":
		connectCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
		client, err := mongo.Connect(options.Client().ApplyURI(mongoURI))
		if err == nil {
			err = client.Ping(connectCtx, readpref.Primary())
		}
		cancel()
		if err != nil {
			log.Fatal(err)
		}
		store, err := deathstar.NewMongoStore(client, mongoDatabase, mongoCollection)
		if err != nil {
			log.Fatal(err)
		}
		service, err := deathstar.NewObserverWithTerminalFences(store, terminalFenceDirectory)
		if err != nil {
			log.Fatal(err)
		}
		handler = service.Handler()
		closeService = func() error {
			shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			return client.Disconnect(shutdown)
		}
	default:
		log.Fatal("-mode must be effect or observer")
	}
	defer closeService()

	server := &http.Server{
		Addr: listenAddress, Handler: handler,
		ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 30 * time.Second,
	}
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	log.Printf("DeathStarBench %s adapter listening on http://%s", mode, listenAddress)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}
