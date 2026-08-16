// Command firecracker-guest is the complete PID 1 for the Firecracker demo
// initramfs. Build it with CGO_ENABLED=0. The guest has no IP network: it can
// reach only two host-owned AF_VSOCK ports at CID 2.
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"runtime/debug"
	"strconv"
	"strings"
	"time"

	"golang.org/x/sys/unix"
)

const (
	requestPath       = "/request.json"
	hostCID           = uint32(2)
	gatePort          = uint32(8000)
	operationPort     = uint32(8787)
	maxRequestBytes   = 1 << 20
	maxResponseBytes  = 1 << 20
	maxGateLineBytes  = 4096
	reconnectDelay    = 100 * time.Millisecond
	operationHTTPPath = "/v1/execute"
)

type executeRequest struct {
	CallID string `json:"call_id"`
	Kind   string `json:"kind"`
	Body   []byte `json:"body"`
}

type operationResult struct {
	Status int
	Body   json.RawMessage
}

type resultEvent struct {
	Event  string          `json:"event"`
	Status int             `json:"status"`
	Body   json.RawMessage `json:"body"`
}

type outcomeProjection struct {
	Phase  string `json:"phase"`
	Reused bool   `json:"reused"`
}

type stream interface {
	io.Reader
	io.Writer
	io.Closer
}

type dialStream func(port uint32) (stream, error)

func main() {
	logger := log.New(os.Stdout, "firecracker-guest: ", log.LstdFlags|log.Lmicroseconds)
	if err := runPID1(context.Background(), dialVsock, logger); err != nil {
		logger.Printf("fatal: %v", err)
	}
	unix.Sync()
	if err := unix.Reboot(unix.LINUX_REBOOT_CMD_POWER_OFF); err != nil {
		logger.Printf("poweroff failed: %v", err)
	}
	for {
		_ = unix.Pause()
	}
}

func runPID1(ctx context.Context, dial dialStream, logger *log.Logger) error {
	if os.Getpid() != 1 {
		return fmt.Errorf("firecracker guest must run as PID 1, got %d", os.Getpid())
	}
	if err := requireStaticBuild(); err != nil {
		return err
	}
	if err := mountKernelFilesystems(); err != nil {
		return err
	}
	if err := attachConsole(); err != nil {
		return err
	}
	rawRequest, _, err := readStrictRequest(requestPath)
	if err != nil {
		return fmt.Errorf("read immutable guest request: %w", err)
	}
	generation, err := waitForGo(ctx, dial, logger)
	if err != nil {
		return err
	}
	result, err := executeWithRetry(ctx, dial, rawRequest, logger)
	if err != nil {
		return err
	}
	if err := reportResult(ctx, dial, result, logger); err != nil {
		return err
	}
	if err := validateResult(result); err != nil {
		return err
	}
	if generation == 1 {
		logger.Printf("first Operation completed; waiting for the host to terminate this generation")
		<-ctx.Done()
		return ctx.Err()
	}
	logger.Printf("restored generation completed its Operation; powering off")
	return nil
}

func requireStaticBuild() error {
	info, ok := debug.ReadBuildInfo()
	if !ok {
		return errors.New("guest binary has no Go build information")
	}
	for _, setting := range info.Settings {
		if setting.Key == "CGO_ENABLED" {
			if setting.Value != "0" {
				return fmt.Errorf("guest binary must be built with CGO_ENABLED=0, got %q", setting.Value)
			}
			return nil
		}
	}
	return errors.New("guest binary does not record CGO_ENABLED")
}

func mountKernelFilesystems() error {
	mounts := []struct {
		source string
		target string
		kind   string
		flags  uintptr
		data   string
	}{
		{"devtmpfs", "/dev", "devtmpfs", unix.MS_NOSUID, "mode=0755"},
		{"proc", "/proc", "proc", unix.MS_NOSUID | unix.MS_NODEV | unix.MS_NOEXEC, ""},
		{"sysfs", "/sys", "sysfs", unix.MS_NOSUID | unix.MS_NODEV | unix.MS_NOEXEC, ""},
	}
	for _, mount := range mounts {
		if err := os.MkdirAll(mount.target, 0o755); err != nil {
			return fmt.Errorf("create mount point %s: %w", mount.target, err)
		}
		if err := unix.Mount(mount.source, mount.target, mount.kind, mount.flags, mount.data); err != nil && !errors.Is(err, unix.EBUSY) {
			return fmt.Errorf("mount %s on %s: %w", mount.kind, mount.target, err)
		}
	}
	return nil
}

// attachConsole is deliberately done after mounting devtmpfs. PID 1 must not
// rely on whatever descriptors the kernel happened to inherit across exec;
// duplicating the guest console onto all standard descriptors keeps protocol
// failures and kernel-facing diagnostics visible in retained serial evidence.
func attachConsole() error {
	console, err := unix.Open("/dev/console", unix.O_RDWR|unix.O_CLOEXEC|unix.O_NOCTTY, 0)
	if errors.Is(err, unix.ENOENT) || errors.Is(err, unix.ENXIO) {
		console, err = unix.Open("/dev/ttyS0", unix.O_RDWR|unix.O_CLOEXEC|unix.O_NOCTTY, 0)
	}
	if err != nil {
		return fmt.Errorf("open guest console: %w", err)
	}
	if console <= unix.Stderr {
		duplicate, duplicateErr := unix.FcntlInt(uintptr(console), unix.F_DUPFD_CLOEXEC, unix.Stderr+1)
		if duplicateErr != nil {
			_ = unix.Close(console)
			return fmt.Errorf("duplicate guest console above standard descriptors: %w", duplicateErr)
		}
		_ = unix.Close(console)
		console = duplicate
	}
	defer unix.Close(console)
	for _, descriptor := range []int{unix.Stdin, unix.Stdout, unix.Stderr} {
		if console == descriptor {
			continue
		}
		if err := unix.Dup3(console, descriptor, 0); err != nil {
			return fmt.Errorf("attach guest console to fd %d: %w", descriptor, err)
		}
	}
	return nil
}

func readStrictRequest(path string) ([]byte, executeRequest, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, executeRequest{}, err
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, maxRequestBytes+1))
	if err != nil {
		return nil, executeRequest{}, err
	}
	if len(data) == 0 || len(data) > maxRequestBytes {
		return nil, executeRequest{}, errors.New("request.json must contain 1 byte to 1 MiB")
	}
	request, err := decodeStrictRequest(data)
	if err != nil {
		return nil, executeRequest{}, err
	}
	return data, request, nil
}

func decodeStrictRequest(data []byte) (executeRequest, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	first, err := decoder.Token()
	if err != nil {
		return executeRequest{}, err
	}
	if delimiter, ok := first.(json.Delim); !ok || delimiter != '{' {
		return executeRequest{}, errors.New("request.json must be one JSON object")
	}
	seen := make(map[string]bool, 3)
	var request executeRequest
	for decoder.More() {
		token, err := decoder.Token()
		if err != nil {
			return executeRequest{}, err
		}
		name, ok := token.(string)
		if !ok {
			return executeRequest{}, errors.New("request.json has a non-string field name")
		}
		if seen[name] {
			return executeRequest{}, fmt.Errorf("request.json repeats field %q", name)
		}
		seen[name] = true
		switch name {
		case "call_id":
			err = decoder.Decode(&request.CallID)
		case "kind":
			err = decoder.Decode(&request.Kind)
		case "body":
			err = decoder.Decode(&request.Body)
		default:
			return executeRequest{}, fmt.Errorf("request.json contains forbidden field %q", name)
		}
		if err != nil {
			return executeRequest{}, fmt.Errorf("decode request field %q: %w", name, err)
		}
	}
	last, err := decoder.Token()
	if err != nil {
		return executeRequest{}, err
	}
	if delimiter, ok := last.(json.Delim); !ok || delimiter != '}' {
		return executeRequest{}, errors.New("request.json object is not closed")
	}
	if len(seen) != 3 || !seen["call_id"] || !seen["kind"] || !seen["body"] {
		return executeRequest{}, errors.New("request.json must contain exactly call_id, kind, and body")
	}
	if strings.TrimSpace(request.CallID) == "" || strings.TrimSpace(request.Kind) == "" {
		return executeRequest{}, errors.New("request.json has an empty call_id or kind")
	}
	if request.Body == nil {
		return executeRequest{}, errors.New("request.json body must be a base64 JSON string")
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return executeRequest{}, fmt.Errorf("request.json has trailing value %v", token)
		}
		return executeRequest{}, fmt.Errorf("request.json has trailing data: %w", err)
	}
	return request, nil
}

func waitForGo(ctx context.Context, dial dialStream, logger *log.Logger) (uint64, error) {
	for {
		if err := ctx.Err(); err != nil {
			return 0, err
		}
		connection, err := dial(gatePort)
		if err != nil {
			if err := waitRetry(ctx); err != nil {
				return 0, err
			}
			continue
		}
		if err := writeAll(connection, []byte("READY\n")); err != nil {
			_ = connection.Close()
			if err := waitRetry(ctx); err != nil {
				return 0, err
			}
			continue
		}
		logger.Printf("READY")
		line, err := readLine(connection, maxGateLineBytes)
		_ = connection.Close()
		if err != nil {
			// Firecracker resets open vsock connections across restore. Reconnect
			// and publish READY again instead of treating EOF as completion.
			if err := waitRetry(ctx); err != nil {
				return 0, err
			}
			continue
		}
		generation, err := parseGenerationRole(line)
		if err != nil {
			return 0, err
		}
		logger.Printf("GO %d", generation)
		return generation, nil
	}
}

func parseGenerationRole(line string) (uint64, error) {
	if !strings.HasPrefix(line, "GO ") || !strings.HasSuffix(line, "\n") {
		return 0, fmt.Errorf("gate returned %q instead of GO <generation>", line)
	}
	generationText := strings.TrimSuffix(strings.TrimPrefix(line, "GO "), "\n")
	generation, err := strconv.ParseUint(generationText, 10, 64)
	if err != nil || strconv.FormatUint(generation, 10) != generationText || (generation != 1 && generation != 3) {
		return 0, fmt.Errorf("gate returned unsupported generation %q", generationText)
	}
	return generation, nil
}

func executeWithRetry(ctx context.Context, dial dialStream, rawRequest []byte, logger *log.Logger) (operationResult, error) {
	for {
		if err := ctx.Err(); err != nil {
			return operationResult{}, err
		}
		connection, err := dial(operationPort)
		if err != nil {
			if err := waitRetry(ctx); err != nil {
				return operationResult{}, err
			}
			continue
		}
		result, err := executeOnce(connection, rawRequest)
		_ = connection.Close()
		if err != nil {
			// A response can be lost after the host committed the external
			// Operation. Retrying the exact request is therefore mandatory.
			if err := waitRetry(ctx); err != nil {
				return operationResult{}, err
			}
			continue
		}
		if retryableStatus(result.Status) {
			logger.Printf("Operation temporarily unavailable with HTTP %d; retrying", result.Status)
			if err := waitRetry(ctx); err != nil {
				return operationResult{}, err
			}
			continue
		}
		return result, nil
	}
}

func executeOnce(connection stream, rawRequest []byte) (operationResult, error) {
	request := &http.Request{
		Method:        http.MethodPost,
		URL:           &url.URL{Path: operationHTTPPath},
		Host:          "firecracker-host",
		Header:        make(http.Header),
		Body:          io.NopCloser(bytes.NewReader(rawRequest)),
		ContentLength: int64(len(rawRequest)),
		Close:         true,
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept", "application/json")
	if err := request.Write(connection); err != nil {
		return operationResult{}, err
	}
	response, err := http.ReadResponse(bufio.NewReader(connection), request)
	if err != nil {
		return operationResult{}, err
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, maxResponseBytes+1))
	if err != nil {
		return operationResult{}, err
	}
	if len(body) == 0 || len(body) > maxResponseBytes {
		return operationResult{}, errors.New("host Operation response must contain 1 byte to 1 MiB")
	}
	if !json.Valid(body) {
		return operationResult{}, errors.New("host Operation response is not JSON")
	}
	return operationResult{Status: response.StatusCode, Body: append(json.RawMessage(nil), body...)}, nil
}

func retryableStatus(status int) bool {
	return status == http.StatusConflict || status == http.StatusTooEarly ||
		status == http.StatusTooManyRequests || status >= 500
}

func reportResult(ctx context.Context, dial dialStream, result operationResult, logger *log.Logger) error {
	event, err := json.Marshal(resultEvent{Event: "RESULT", Status: result.Status, Body: result.Body})
	if err != nil {
		return err
	}
	event = append(event, '\n')
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		connection, err := dial(gatePort)
		if err == nil {
			err = writeAll(connection, event)
			_ = connection.Close()
		}
		if err == nil {
			logger.Printf("RESULT %s", bytes.TrimSpace(event))
			return nil
		}
		if err := waitRetry(ctx); err != nil {
			return err
		}
	}
}

func validateResult(result operationResult) error {
	if result.Status < 200 || result.Status >= 300 {
		return fmt.Errorf("Operation failed with HTTP %d", result.Status)
	}
	var outcome outcomeProjection
	if err := json.Unmarshal(result.Body, &outcome); err != nil {
		return fmt.Errorf("decode Operation outcome: %w", err)
	}
	if outcome.Phase != "succeeded" {
		return fmt.Errorf("Operation completed in unexpected phase %q", outcome.Phase)
	}
	return nil
}

func waitRetry(ctx context.Context) error {
	timer := time.NewTimer(reconnectDelay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func readLine(reader io.Reader, limit int) (string, error) {
	if limit <= 0 {
		return "", errors.New("line limit must be positive")
	}
	line := make([]byte, 0, 16)
	one := []byte{0}
	for len(line) < limit {
		n, err := reader.Read(one)
		if n > 0 {
			line = append(line, one[0])
			if one[0] == '\n' {
				return string(line), nil
			}
		}
		if err != nil {
			return "", err
		}
		if n == 0 {
			return "", io.ErrNoProgress
		}
	}
	return "", errors.New("gate line exceeds limit")
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

type vsockStream struct {
	fd int
}

func dialVsock(port uint32) (stream, error) {
	fd, err := unix.Socket(unix.AF_VSOCK, unix.SOCK_STREAM|unix.SOCK_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	if err := unix.Connect(fd, &unix.SockaddrVM{CID: hostCID, Port: port}); err != nil {
		_ = unix.Close(fd)
		return nil, err
	}
	return &vsockStream{fd: fd}, nil
}

func (connection *vsockStream) Read(data []byte) (int, error) {
	for {
		n, err := unix.Read(connection.fd, data)
		if errors.Is(err, unix.EINTR) {
			continue
		}
		if n == 0 && err == nil {
			return 0, io.EOF
		}
		return n, err
	}
}

func (connection *vsockStream) Write(data []byte) (int, error) {
	for {
		n, err := unix.Write(connection.fd, data)
		if errors.Is(err, unix.EINTR) {
			continue
		}
		return n, err
	}
}

func (connection *vsockStream) Close() error {
	if connection.fd < 0 {
		return nil
	}
	err := unix.Close(connection.fd)
	connection.fd = -1
	return err
}
