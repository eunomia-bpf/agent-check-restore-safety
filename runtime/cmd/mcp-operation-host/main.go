// Command mcp-operation-host keeps protected MCP state outside the Agent
// sandbox and serves replacement stdio relays over one private Unix socket.
package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/mcpoperation"
)

func main() {
	var configPath string
	var sandboxSocket string
	var listenSocket string
	var executionID string
	var journalPath string
	var executeTimeout time.Duration
	flag.StringVar(&configPath, "config", "", "strict operator-owned MCP tool configuration")
	flag.StringVar(&sandboxSocket, "sandbox-socket", "", "credential-free active sandbox Operation socket")
	flag.StringVar(&listenSocket, "listen-socket", "", "private Unix socket exposed only to the Agent relay")
	flag.StringVar(&executionID, "execution-id", "", "stable identity supplied by the continuity supervisor")
	flag.StringVar(&journalPath, "journal", "", "host-durable MCP call journal outside the Agent restore domain")
	flag.DurationVar(&executeTimeout, "execute-timeout", mcpoperation.DefaultExecuteTimeout, "deadline for one protected tool call")
	flag.Parse()
	if configPath == "" || sandboxSocket == "" || listenSocket == "" || executionID == "" || journalPath == "" {
		log.Fatal("-config, -sandbox-socket, -listen-socket, -execution-id, and -journal are required")
	}
	config, err := mcpoperation.LoadConfigFile(configPath)
	if err != nil {
		log.Fatal(err)
	}
	executor, err := mcpoperation.NewSandboxExecutor(sandboxSocket, mcpoperation.SandboxExecutorOptions{
		RecoveryAttempts: mcpoperation.DefaultRecoveryAttempts,
		RequestTimeout:   executeTimeout,
	})
	if err != nil {
		log.Fatal(err)
	}
	defer executor.Close()
	journal, err := mcpoperation.OpenJournal(journalPath, executionID)
	if err != nil {
		log.Fatal(err)
	}
	defer journal.Close()
	server, err := mcpoperation.NewServer(executor, config, mcpoperation.ServerOptions{
		ExecutionID: executionID, ExecuteTimeout: executeTimeout, Journal: journal,
	})
	if err != nil {
		log.Fatal(err)
	}
	host, err := mcpoperation.ListenUnixHost(listenSocket)
	if err != nil {
		log.Fatal(err)
	}
	defer host.Close()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := host.Serve(ctx, server, os.Stderr); err != nil {
		log.Fatal(err)
	}
}
