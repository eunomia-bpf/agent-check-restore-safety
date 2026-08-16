package mcpoperation

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
)

const (
	DefaultRecoveryAttempts = 2
	maxSandboxResponseBytes = 4 << 20
)

type SandboxExecutorOptions struct {
	RecoveryAttempts int
	RequestTimeout   time.Duration
}

// SandboxExecutor reaches one host-owned, generation-bound Unix endpoint. It
// carries neither a bearer credential nor a provider URL. A bounded retry uses
// the exact same call identity and bytes, allowing History to reuse or query
// the first attempt without converting uncertainty into a new Operation.
type SandboxExecutor struct {
	socketPath       string
	parentInfo       os.FileInfo
	client           *http.Client
	recoveryAttempts int
}

type sandboxExecuteRequest struct {
	CallID string `json:"call_id"`
	Kind   string `json:"kind"`
	Body   []byte `json:"body,omitempty"`
}

func NewSandboxExecutor(socketPath string, options SandboxExecutorOptions) (*SandboxExecutor, error) {
	if socketPath == "" || !filepath.IsAbs(socketPath) || filepath.Clean(socketPath) != socketPath || len([]byte(socketPath)) >= 108 || strings.ContainsAny(socketPath, "\x00\r\n") {
		return nil, errors.New("sandbox socket path must be absolute, canonical, and fit a Unix address")
	}
	parent := filepath.Dir(socketPath)
	parentInfo, err := os.Lstat(parent)
	if err != nil {
		return nil, fmt.Errorf("inspect sandbox socket parent: %w", err)
	}
	resolvedParent, err := filepath.EvalSymlinks(parent)
	if err != nil || resolvedParent != parent || !parentInfo.IsDir() || parentInfo.Mode()&os.ModeSymlink != 0 || parentInfo.Mode().Perm() != 0o700 {
		return nil, errors.New("sandbox socket parent must be a direct private directory with mode 0700")
	}
	parentStat, ok := parentInfo.Sys().(*syscall.Stat_t)
	if !ok || int(parentStat.Uid) != os.Geteuid() {
		return nil, errors.New("sandbox socket parent must be owned by the current user")
	}
	attempts := options.RecoveryAttempts
	if attempts == 0 {
		attempts = DefaultRecoveryAttempts
	}
	if attempts < 1 || attempts > 4 {
		return nil, errors.New("sandbox recovery attempts must be between 1 and 4")
	}
	timeout := options.RequestTimeout
	if timeout == 0 {
		timeout = DefaultExecuteTimeout
	}
	if timeout <= 0 || timeout > 10*time.Minute {
		return nil, errors.New("sandbox request timeout must be positive and at most 10m")
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	transport.DisableKeepAlives = true
	transport.DialContext = func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{Timeout: 5 * time.Second}).DialContext(ctx, "unix", socketPath)
	}
	return &SandboxExecutor{
		socketPath: socketPath, parentInfo: parentInfo,
		client: &http.Client{Transport: transport, Timeout: timeout}, recoveryAttempts: attempts,
	}, nil
}

func (executor *SandboxExecutor) Execute(
	ctx context.Context,
	callID string,
	kind string,
	body []byte,
) (gateway.Outcome, error) {
	if executor == nil || executor.client == nil {
		return gateway.Outcome{}, errors.New("sandbox executor is unavailable")
	}
	requestBody, err := json.Marshal(sandboxExecuteRequest{CallID: callID, Kind: kind, Body: body})
	if err != nil {
		return gateway.Outcome{}, fmt.Errorf("encode sandbox Operation: %w", err)
	}
	var last gateway.Outcome
	var lastErr error
	for attempt := 0; attempt < executor.recoveryAttempts; attempt++ {
		if err := executor.validateSocket(); err != nil {
			return last, err
		}
		outcome, executeErr, retryable := executor.executeOnce(ctx, requestBody)
		if executeErr == nil {
			return outcome, nil
		}
		last, lastErr = outcome, executeErr
		if !retryable || ctx.Err() != nil {
			break
		}
	}
	return last, lastErr
}

func (executor *SandboxExecutor) validateSocket() error {
	currentParent, err := os.Lstat(filepath.Dir(executor.socketPath))
	if err != nil || !os.SameFile(executor.parentInfo, currentParent) {
		return errors.New("sandbox socket parent identity changed")
	}
	info, err := os.Lstat(executor.socketPath)
	if err != nil {
		return fmt.Errorf("inspect sandbox socket: %w", err)
	}
	if info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0o600 {
		return errors.New("sandbox endpoint is not a private Unix socket")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(stat.Uid) != os.Geteuid() {
		return errors.New("sandbox endpoint must be owned by the current user")
	}
	return nil
}

func (executor *SandboxExecutor) executeOnce(ctx context.Context, body []byte) (gateway.Outcome, error, bool) {
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, "http://safe-change.invalid/v1/execute", bytes.NewReader(body))
	if err != nil {
		return gateway.Outcome{}, err, false
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := executor.client.Do(request)
	if err != nil {
		return gateway.Outcome{}, fmt.Errorf("send sandbox Operation: %w", err), true
	}
	defer response.Body.Close()
	mediaType, _, mediaErr := mime.ParseMediaType(response.Header.Get("Content-Type"))
	encoded, readErr := io.ReadAll(io.LimitReader(response.Body, maxSandboxResponseBytes+1))
	if readErr != nil {
		return gateway.Outcome{}, fmt.Errorf("read sandbox Operation response: %w", readErr), true
	}
	if len(encoded) > maxSandboxResponseBytes {
		return gateway.Outcome{}, errors.New("sandbox Operation response exceeds the size limit"), true
	}
	if mediaErr != nil || mediaType != "application/json" {
		return gateway.Outcome{}, errors.New("sandbox Operation response is not JSON"), true
	}
	if response.StatusCode == http.StatusOK {
		var outcome gateway.Outcome
		if err := decodeStrictJSON(encoded, &outcome); err != nil {
			return gateway.Outcome{}, fmt.Errorf("decode sandbox Operation outcome: %w", err), true
		}
		return outcome, nil, false
	}
	var envelope api.OperationError
	if err := decodeStrictJSON(encoded, &envelope); err != nil {
		return gateway.Outcome{}, fmt.Errorf("decode sandbox Operation error: %w", err), true
	}
	switch envelope.Code {
	case api.OperationErrorOutcomeUnknown:
		return envelope.Outcome, fmt.Errorf("%w: %s", gateway.ErrOutcomeUnknown, envelope.Error), true
	case api.OperationErrorRequestConflict:
		return envelope.Outcome, fmt.Errorf("%w: %s", gateway.ErrOperationRequestConflict, envelope.Error), false
	case api.OperationErrorSandboxStale:
		return envelope.Outcome, fmt.Errorf("sandbox binding is stale: %s", envelope.Error), false
	default:
		return envelope.Outcome, fmt.Errorf("sandbox Operation returned HTTP %s: %s", response.Status, envelope.Error), false
	}
}

func decodeStrictJSON(data []byte, target any) error {
	if err := rejectDuplicateJSONNames(data); err != nil {
		return err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("response contains multiple JSON values")
		}
		return err
	}
	return nil
}
