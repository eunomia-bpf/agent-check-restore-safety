// Command mcp-operation-server exposes sandbox-bound durable Operations over
// the standard MCP stdio transport. It carries no provider route or credential.
package main

import (
	"context"
	"flag"
	"log"
	"os"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/mcpoperation"
)

func main() {
	var configPath string
	var sandboxSocket string
	var executionID string
	var journalPath string
	var executeTimeout time.Duration
	flag.StringVar(&configPath, "config", "", "strict operator-owned MCP tool configuration")
	flag.StringVar(&sandboxSocket, "sandbox-socket", "", "credential-free active sandbox Unix socket")
	flag.StringVar(&executionID, "execution-id", "", "stable identity supplied by the continuity supervisor")
	flag.StringVar(&journalPath, "journal", "", "host-durable private MCP call journal outside the sandbox restore domain")
	flag.DurationVar(&executeTimeout, "execute-timeout", mcpoperation.DefaultExecuteTimeout, "deadline for one protected tool call")
	flag.Parse()
	if configPath == "" || sandboxSocket == "" || executionID == "" || journalPath == "" {
		log.Fatal("-config, -sandbox-socket, -execution-id, and -journal are required")
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
	if err := server.Serve(context.Background(), os.Stdin, os.Stdout, os.Stderr); err != nil {
		log.Fatal(err)
	}
}
