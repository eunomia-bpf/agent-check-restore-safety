//go:build linux

// Command firecracker-claude-guest is PID 1 for one clean, networkless Claude
// Code cell. It exposes only fixed loopback model and declared-operation
// endpoints, which leave the microVM through generation-bound AF_VSOCK relays.
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentguest"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentwire"
	"golang.org/x/sys/unix"
)

const (
	configPath       = "/config.json"
	gatePort         = uint32(8000)
	maxGateLineBytes = 4096
	maxClaudeOutput  = 1 << 20
	shutdownTimeout  = 3 * time.Second
)

type claudeOutcome struct {
	Result       string `json:"result"`
	Stream       string `json:"stream"`
	StreamBytes  int    `json:"stream_bytes"`
	StreamSHA256 string `json:"stream_sha256"`
}

func main() {
	logger := log.New(os.Stdout, "firecracker-claude-guest: ", log.LstdFlags|log.Lmicroseconds)
	if len(os.Args) > 1 {
		err := runChild(os.Args)
		logger.Printf("fatal Claude child launch: %v", err)
		if os.Getpid() != 1 {
			os.Exit(127)
		}
		powerOff(logger)
		return
	}
	if err := runPID1(context.Background(), logger); err != nil {
		logger.Printf("fatal: %v", err)
	}
	powerOff(logger)
}

func runChild(arguments []string) error {
	if len(arguments) < 7 || arguments[0] != agentguest.InitExecutable || arguments[1] != agentguest.ClaudeChildMode {
		return errors.New("Claude guest received a forbidden internal mode")
	}
	schema, err := strconv.Atoi(arguments[2])
	if err != nil || (schema != agentguest.ClaudeConfigSchema && schema != agentguest.ClaudeHTTPConfigSchema) {
		return errors.New("Claude guest child schema is invalid")
	}
	port, err := strconv.ParseUint(arguments[3], 10, 32)
	if err != nil || port == 0 || port > 65535 {
		return errors.New("Claude guest child model port is invalid")
	}
	sessionID := arguments[4]
	if len(sessionID) != agentguest.SessionIDHexBytes*2 {
		return errors.New("Claude guest child session is invalid")
	}
	egressPort, err := strconv.ParseUint(arguments[5], 10, 32)
	if err != nil || egressPort > 65535 || (schema == agentguest.ClaudeHTTPConfigSchema && egressPort == 0) || (schema == agentguest.ClaudeConfigSchema && egressPort != 0) {
		return errors.New("Claude guest child egress port is invalid")
	}
	return agentguest.ExecClaudeChild(arguments[6:], schema, uint32(port), sessionID, uint32(egressPort))
}

func runPID1(ctx context.Context, logger *log.Logger) (returnErr error) {
	config, err := readConfig(configPath)
	if err != nil {
		return err
	}
	if err := agentguest.PrepareClaudeLinuxPID1(config); err != nil {
		return fmt.Errorf("prepare Claude cell: %w", err)
	}
	generation, err := waitForGo(ctx, logger)
	if err != nil {
		return err
	}
	logger.Printf("released generation %d", generation)

	runContext, cancel := context.WithCancel(ctx)
	defer cancel()
	ports := []uint32{config.ModelPort, agentguest.DefaultMCPPort}
	if config.Schema == agentguest.ClaudeHTTPConfigSchema {
		ports = []uint32{config.ModelPort, config.EgressPort}
	}
	proxyResults := make([]<-chan error, 0, len(ports))
	for _, port := range ports {
		result, err := agentguest.StartModelProxy(runContext.Done(), port, agentguest.DialHostVsock, logger)
		if err != nil {
			return fmt.Errorf("start Claude loopback proxy %d: %w", port, err)
		}
		proxyResults = append(proxyResults, result)
	}

	domain, err := agentguest.NewExecutionDomain()
	if err != nil {
		return err
	}
	defer func() { returnErr = errors.Join(returnErr, domain.Close()) }()
	cgroupFD, err := domain.FD()
	if err != nil {
		return err
	}
	command, stdout, err := agentguest.StartClaude(config, logger.Writer(), cgroupFD)
	if err != nil {
		return err
	}
	var stream bytes.Buffer
	copyDone := make(chan error, 1)
	go func() {
		written, copyErr := io.Copy(io.MultiWriter(&stream, os.Stdout), io.LimitReader(stdout, maxClaudeOutput+1))
		if copyErr == nil && written > maxClaudeOutput {
			copyErr = errors.New("Claude stream exceeded the guest evidence limit")
		}
		copyDone <- copyErr
	}()
	waitErr := command.Wait()
	copyErr := <-copyDone
	copyErr = normalizeClaudeCopyError(waitErr, copyErr)
	_ = stdout.Close()
	if killErr := domain.FreezeAndKill(shutdownTimeout); killErr != nil {
		return errors.Join(waitErr, copyErr, killErr)
	}
	cancel()
	for _, result := range proxyResults {
		select {
		case proxyErr := <-result:
			if proxyErr != nil {
				return errors.Join(waitErr, copyErr, proxyErr)
			}
		case <-time.After(shutdownTimeout):
			return errors.New("Claude loopback proxy did not stop")
		}
	}
	if waitErr != nil || copyErr != nil {
		return errors.Join(fmt.Errorf("Claude exited: %w", waitErr), copyErr)
	}
	outcome, err := validateClaudeStream(stream.Bytes())
	if err != nil {
		return err
	}
	if err := reportResult(ctx, outcome); err != nil {
		return err
	}
	logger.Printf("reported authenticated result for generation %d", generation)
	return nil
}

func normalizeClaudeCopyError(waitErr, copyErr error) error {
	if waitErr == nil && errors.Is(copyErr, os.ErrClosed) {
		return nil
	}
	return copyErr
}

func readConfig(path string) (agentguest.ClaudeConfig, error) {
	descriptor, err := unix.Open(path, unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return agentguest.ClaudeConfig{}, err
	}
	file := os.NewFile(uintptr(descriptor), path)
	if file == nil {
		_ = unix.Close(descriptor)
		return agentguest.ClaudeConfig{}, errors.New("wrap immutable Claude config")
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm() != 0o400 || info.Size() <= 0 || info.Size() > agentguest.MaxConfigBytes {
		return agentguest.ClaudeConfig{}, errors.New("Claude config must be one bounded root-only regular file")
	}
	return agentguest.DecodeClaudeConfig(file)
}

func waitForGo(ctx context.Context, logger *log.Logger) (uint64, error) {
	for {
		if err := ctx.Err(); err != nil {
			return 0, err
		}
		connection, err := agentguest.DialHostVsock(gatePort)
		if err != nil {
			time.Sleep(50 * time.Millisecond)
			continue
		}
		if _, err := connection.Write([]byte("READY\n")); err != nil {
			_ = connection.Close()
			continue
		}
		logger.Printf("READY")
		line, err := readLine(connection)
		_ = connection.Close()
		if err != nil {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) != 2 || fields[0] != "GO" {
			return 0, errors.New("Claude gate returned a malformed GO line")
		}
		generation, err := strconv.ParseUint(fields[1], 10, 64)
		if err != nil || generation == 0 {
			return 0, errors.New("Claude gate returned an invalid generation")
		}
		return generation, nil
	}
}

func readLine(reader io.Reader) (string, error) {
	buffered := bufio.NewReader(io.LimitReader(reader, maxGateLineBytes+1))
	line, err := buffered.ReadString('\n')
	if err != nil || len(line) > maxGateLineBytes {
		return "", errors.New("Claude gate line is missing or oversized")
	}
	return strings.TrimSuffix(line, "\n"), nil
}

func validateClaudeStream(data []byte) (claudeOutcome, error) {
	if len(data) == 0 || len(data) > maxClaudeOutput {
		return claudeOutcome{}, errors.New("Claude stream is empty or oversized")
	}
	result := ""
	scanner := bufio.NewScanner(bytes.NewReader(data))
	scanner.Buffer(make([]byte, 4096), maxClaudeOutput)
	for scanner.Scan() {
		canonical, err := agentwire.CanonicalJSONObject(scanner.Bytes())
		if err != nil {
			return claudeOutcome{}, fmt.Errorf("Claude stream contains ambiguous JSON: %w", err)
		}
		var record map[string]any
		if err := json.Unmarshal(canonical, &record); err != nil {
			return claudeOutcome{}, fmt.Errorf("Claude stream contains non-JSON: %w", err)
		}
		if record["type"] == "result" {
			value, ok := record["result"].(string)
			if !ok || record["subtype"] != "success" || result != "" {
				return claudeOutcome{}, errors.New("Claude stream has a malformed or repeated result")
			}
			result = value
		}
	}
	if err := scanner.Err(); err != nil {
		return claudeOutcome{}, err
	}
	if result != "DONE" {
		return claudeOutcome{}, fmt.Errorf("Claude result is %q, require DONE", result)
	}
	digest := sha256.Sum256(data)
	return claudeOutcome{Result: result, Stream: string(data), StreamBytes: len(data), StreamSHA256: hex.EncodeToString(digest[:])}, nil
}

func reportResult(ctx context.Context, outcome claudeOutcome) error {
	body, err := json.Marshal(outcome)
	if err != nil {
		return err
	}
	event := struct {
		Event  string          `json:"event"`
		Status int             `json:"status"`
		Body   json.RawMessage `json:"body"`
	}{Event: "RESULT", Status: 200, Body: body}
	line, err := json.Marshal(event)
	if err != nil {
		return err
	}
	line = append(line, '\n')
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		connection, err := agentguest.DialHostVsock(gatePort)
		if err == nil {
			writeErr := writeAll(connection, line)
			if writeErr == nil {
				closer, ok := connection.(interface{ CloseWrite() error })
				if !ok {
					writeErr = errors.New("Claude gate transport cannot half-close its result")
				} else {
					writeErr = closer.CloseWrite()
				}
			}
			if writeErr == nil {
				var acknowledgement [1]byte
				count, readErr := connection.Read(acknowledgement[:])
				if count != 0 || !errors.Is(readErr, io.EOF) {
					writeErr = errors.New("Claude gate did not close after accepting its result")
				}
			}
			closeErr := connection.Close()
			if writeErr == nil && closeErr == nil {
				return nil
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
}

func writeAll(writer io.Writer, data []byte) error {
	for len(data) > 0 {
		written, err := writer.Write(data)
		if err != nil {
			return err
		}
		if written <= 0 || written > len(data) {
			return io.ErrShortWrite
		}
		data = data[written:]
	}
	return nil
}

func powerOff(logger *log.Logger) {
	unix.Sync()
	if err := unix.Reboot(unix.LINUX_REBOOT_CMD_POWER_OFF); err != nil {
		logger.Printf("poweroff failed: %v", err)
	}
	for {
		_ = unix.Pause()
	}
}
