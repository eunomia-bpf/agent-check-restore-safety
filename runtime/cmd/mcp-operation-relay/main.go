// Command mcp-operation-relay is the untrusted sandbox-side MCP stdio process.
// It forwards bytes to the trusted host and owns no durable or provider state.
package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/mcpoperation"
)

func main() {
	var socketPath string
	flag.StringVar(&socketPath, "socket", "", "private Unix socket of the trusted MCP host")
	flag.Parse()
	if socketPath == "" {
		log.Fatal("-socket is required")
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := mcpoperation.RelayUnix(ctx, socketPath, os.Stdin, os.Stdout); err != nil {
		log.Fatal(err)
	}
}
