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
	var loopbackPort uint
	flag.StringVar(&socketPath, "socket", "", "private Unix socket of the trusted MCP host")
	flag.UintVar(&loopbackPort, "loopback-port", 0, "guest PID 1 loopback proxy port for the trusted host")
	flag.Parse()
	if (socketPath == "") == (loopbackPort == 0) || loopbackPort > 65535 {
		log.Fatal("exactly one of -socket or -loopback-port is required")
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	var err error
	if socketPath != "" {
		err = mcpoperation.RelayUnix(ctx, socketPath, os.Stdin, os.Stdout)
	} else {
		err = mcpoperation.RelayLoopbackTCP(ctx, uint32(loopbackPort), os.Stdin, os.Stdout)
	}
	if err != nil {
		log.Fatal(err)
	}
}
