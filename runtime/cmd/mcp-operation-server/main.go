// Command mcp-operation-server exposes sandbox-bound durable Operations over
// the standard MCP stdio transport. It carries no provider route or credential.
package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"syscall"
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
	config, err := loadConfig(configPath)
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

func loadConfig(path string) (mcpoperation.Config, error) {
	pathInfo, err := os.Lstat(path)
	if err != nil {
		return mcpoperation.Config{}, err
	}
	if !pathInfo.Mode().IsRegular() || pathInfo.Mode().Perm()&0o022 != 0 {
		return mcpoperation.Config{}, fmt.Errorf("MCP Operation config %q must be a direct regular file not writable by group or others", path)
	}
	stat, ok := pathInfo.Sys().(*syscall.Stat_t)
	if !ok || int(stat.Uid) != os.Geteuid() {
		return mcpoperation.Config{}, fmt.Errorf("MCP Operation config %q must be owned by the current user", path)
	}
	file, err := os.Open(path)
	if err != nil {
		return mcpoperation.Config{}, err
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !os.SameFile(pathInfo, opened) {
		return mcpoperation.Config{}, fmt.Errorf("MCP Operation config %q changed while it was opened", path)
	}
	data, err := io.ReadAll(io.LimitReader(file, mcpoperation.MaxConfigBytes+1))
	if err != nil {
		return mcpoperation.Config{}, fmt.Errorf("read MCP Operation config: %w", err)
	}
	return mcpoperation.ParseConfig(data)
}
