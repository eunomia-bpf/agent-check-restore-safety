// Package firecracker provides the small, deliberately strict subset of the
// Firecracker v1.16.1 API used by the runtime.  It is Linux-only in practice:
// Firecracker exposes its HTTP API on a Unix domain socket.
package firecracker

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path"
	"strings"
	"sync"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

const (
	defaultAPITimeout       = 10 * time.Second
	defaultMaxResponseBytes = 1 << 20
)

// ClientConfig configures a Firecracker API client. Trace, when non-nil,
// receives one JSON object followed by a newline for every attempted call.
// It is intentionally an io.Writer so callers decide where and how evidence
// is retained; the client never silently creates a world-readable trace file.
type ClientConfig struct {
	SocketPath       string
	Timeout          time.Duration
	MaxResponseBytes int64
	Trace            io.Writer
	// ExpectedPeerPID is the exact Firecracker VMM PID expected on the other
	// end of the Unix socket. It is mandatory so a same-uid socket replacement
	// cannot redirect lifecycle calls to a different microVM.
	ExpectedPeerPID int
}

// Client calls one Firecracker API socket.  A Client is safe for concurrent
// use.  It does not follow redirects and does not use proxy environment
// variables, which are both invalid for this local control plane.
type Client struct {
	socketPath      string
	timeout         time.Duration
	maxBody         int64
	socketInfo      os.FileInfo
	expectedPeerPID int
	http            *http.Client
	trace           *jsonlTrace
}

// TraceError means an API action may already have reached Firecracker, but
// its required JSONL evidence could not be durably written. Callers must stop
// rather than retrying the action automatically.
type TraceError struct{ Err error }

func (e *TraceError) Error() string {
	return fmt.Sprintf("Firecracker API trace failed; refusing further calls: %v", e.Err)
}
func (e *TraceError) Unwrap() error { return e.Err }

// HTTPError is returned for an HTTP response whose status is not the exact
// status required by the invoked Firecracker endpoint.
type HTTPError struct {
	Method     string
	Path       string
	StatusCode int
	Status     string
	Body       []byte
}

func (e *HTTPError) Error() string {
	if len(e.Body) == 0 {
		return fmt.Sprintf("Firecracker %s %s returned %s", e.Method, e.Path, e.Status)
	}
	return fmt.Sprintf("Firecracker %s %s returned %s: %s", e.Method, e.Path, e.Status, strings.TrimSpace(string(e.Body)))
}

// ResponseTooLargeError reports a peer response that exceeded the configured
// limit.  No partial response is accepted by higher-level methods.
type ResponseTooLargeError struct{ Limit int64 }

func (e *ResponseTooLargeError) Error() string {
	return fmt.Sprintf("Firecracker response exceeds %d bytes", e.Limit)
}

// NewClient creates a strict client for one Unix API socket.
func NewClient(config ClientConfig) (*Client, error) {
	if config.SocketPath == "" {
		return nil, errors.New("Firecracker API socket path is empty")
	}
	if strings.IndexByte(config.SocketPath, 0) >= 0 {
		return nil, errors.New("Firecracker API socket path contains NUL")
	}
	if config.ExpectedPeerPID <= 0 {
		return nil, errors.New("Firecracker API expected peer PID must be positive")
	}
	socketInfo, err := validateAPISocket(config.SocketPath)
	if err != nil {
		return nil, err
	}
	if config.Timeout <= 0 {
		config.Timeout = defaultAPITimeout
	}
	if config.MaxResponseBytes <= 0 {
		config.MaxResponseBytes = defaultMaxResponseBytes
	}
	dialer := &net.Dialer{Timeout: config.Timeout}
	transport := &http.Transport{
		Proxy: nil,
		DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			if err := requireSameAPISocket(config.SocketPath, socketInfo); err != nil {
				return nil, err
			}
			connection, err := dialer.DialContext(ctx, "unix", config.SocketPath)
			if err != nil {
				return nil, err
			}
			if err := requireSameAPISocket(config.SocketPath, socketInfo); err != nil {
				_ = connection.Close()
				return nil, err
			}
			if err := requirePeerPID(connection, config.ExpectedPeerPID); err != nil {
				_ = connection.Close()
				return nil, err
			}
			return connection, nil
		},
		ForceAttemptHTTP2:     false,
		MaxIdleConns:          1,
		MaxIdleConnsPerHost:   1,
		IdleConnTimeout:       config.Timeout,
		ResponseHeaderTimeout: config.Timeout,
	}
	return &Client{
		socketPath: config.SocketPath, timeout: config.Timeout, maxBody: config.MaxResponseBytes, socketInfo: socketInfo, expectedPeerPID: config.ExpectedPeerPID,
		http:  &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }},
		trace: newJSONLTrace(config.Trace),
	}, nil
}

// New cannot safely construct a client because it has no peer-PID argument.
// Use NewClient with ClientConfig.ExpectedPeerPID.
func New(socketPath string, timeout time.Duration) (*Client, error) {
	return nil, errors.New("Firecracker New requires an explicit ExpectedPeerPID; use NewClient")
}

func validateAPISocket(socketPath string) (os.FileInfo, error) {
	info, err := os.Lstat(socketPath)
	if err != nil {
		return nil, fmt.Errorf("inspect Firecracker API socket: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0o600 {
		return nil, errors.New("Firecracker API socket must be a non-symlink Unix socket with mode 0600")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != uint32(os.Geteuid()) {
		return nil, errors.New("Firecracker API socket must be owned by the current user")
	}
	return info, nil
}

func requireSameAPISocket(socketPath string, expected os.FileInfo) error {
	current, err := validateAPISocket(socketPath)
	if err != nil {
		return err
	}
	if expected == nil || !os.SameFile(expected, current) {
		return errors.New("Firecracker API socket identity changed")
	}
	return nil
}

func requirePeerPID(connection net.Conn, expectedPID int) error {
	unixConnection, ok := connection.(*net.UnixConn)
	if !ok {
		return errors.New("Firecracker API dial did not return a Unix connection")
	}
	raw, err := unixConnection.SyscallConn()
	if err != nil {
		return fmt.Errorf("access Firecracker API Unix connection: %w", err)
	}
	var credential *unix.Ucred
	if err := raw.Control(func(fd uintptr) { credential, err = unix.GetsockoptUcred(int(fd), unix.SOL_SOCKET, unix.SO_PEERCRED) }); err != nil {
		return fmt.Errorf("read Firecracker API peer credentials: %w", err)
	}
	if err != nil || credential == nil {
		return fmt.Errorf("read Firecracker API peer credentials: %w", err)
	}
	if int(credential.Pid) != expectedPID {
		return fmt.Errorf("Firecracker API peer PID is %d, want %d", credential.Pid, expectedPID)
	}
	return nil
}

// MachineConfig is the Firecracker machine-config request body.
type MachineConfig struct {
	VCPUCount       int  `json:"vcpu_count"`
	MemSizeMiB      int  `json:"mem_size_mib"`
	SMT             bool `json:"smt"`
	TrackDirtyPages bool `json:"track_dirty_pages"`
}

// BootSource is the Firecracker boot-source request body.
type BootSource struct {
	KernelImagePath string `json:"kernel_image_path"`
	BootArgs        string `json:"boot_args,omitempty"`
	InitrdPath      string `json:"initrd_path,omitempty"`
}

// VsockDevice is one Firecracker virtio-vsock device.
type VsockDevice struct {
	GuestCID uint32 `json:"guest_cid"`
	UDSPath  string `json:"uds_path"`
}

// Configure applies machine configuration, boot source, then the one vsock
// device.  Firecracker permits configuration only before InstanceStart, so a
// failure leaves later configuration steps unattempted.
func (c *Client) Configure(ctx context.Context, machine MachineConfig, boot BootSource, vsock VsockDevice) error {
	if err := c.ConfigureMachine(ctx, machine); err != nil {
		return err
	}
	if err := c.ConfigureBoot(ctx, boot); err != nil {
		return err
	}
	return c.ConfigureVsock(ctx, vsock)
}

func (c *Client) ConfigureMachine(ctx context.Context, machine MachineConfig) error {
	if machine.VCPUCount <= 0 || machine.MemSizeMiB <= 0 {
		return errors.New("Firecracker machine configuration requires positive vcpu_count and mem_size_mib")
	}
	return c.callNoContent(ctx, http.MethodPut, "/machine-config", machine)
}

func (c *Client) ConfigureBoot(ctx context.Context, boot BootSource) error {
	if boot.KernelImagePath == "" {
		return errors.New("Firecracker kernel image path is empty")
	}
	return c.callNoContent(ctx, http.MethodPut, "/boot-source", boot)
}

func (c *Client) ConfigureVsock(ctx context.Context, vsock VsockDevice) error {
	if err := validateVsock(vsock); err != nil {
		return err
	}
	return c.callNoContent(ctx, http.MethodPut, "/vsock", vsock)
}

// Start starts a configured microVM exactly once.
func (c *Client) Start(ctx context.Context) error {
	return c.callNoContent(ctx, http.MethodPut, "/actions", struct {
		ActionType string `json:"action_type"`
	}{"InstanceStart"})
}

// VMState is the state string returned by GET / and consumed by PATCH /vm.
type VMState string

const (
	StateNotStarted VMState = "Not started"
	StatePaused     VMState = "Paused"
	StateRunning    VMState = "Running"
	StateResumed    VMState = "Resumed"
)

// InstanceInfo is the v1.16.1 response for GET /.
type InstanceInfo struct {
	AppName    string  `json:"app_name"`
	ID         string  `json:"id"`
	State      VMState `json:"state"`
	VMMVersion string  `json:"vmm_version"`
}

// State reads general instance information from GET /.
func (c *Client) State(ctx context.Context) (InstanceInfo, error) {
	var response InstanceInfo
	if err := c.callJSON(ctx, http.MethodGet, "/", nil, http.StatusOK, &response); err != nil {
		return InstanceInfo{}, err
	}
	if response.AppName == "" || response.ID == "" || response.VMMVersion == "" || !isInstanceState(response.State) {
		return InstanceInfo{}, errors.New("Firecracker GET / returned incomplete instance information")
	}
	return response, nil
}

func (c *Client) Pause(ctx context.Context) error  { return c.setState(ctx, StatePaused) }
func (c *Client) Resume(ctx context.Context) error { return c.setState(ctx, StateResumed) }

func (c *Client) setState(ctx context.Context, state VMState) error {
	return c.callNoContent(ctx, http.MethodPatch, "/vm", struct {
		State VMState `json:"state"`
	}{state})
}

// SnapshotCreateConfig identifies the two files created by a full snapshot.
type SnapshotCreateConfig struct {
	SnapshotPath string
	MemFilePath  string
}

// CreateFullSnapshot makes a full snapshot while the caller has the VM
// paused.  This method deliberately does not pause the VM implicitly.
func (c *Client) CreateFullSnapshot(ctx context.Context, snapshotPath, memFilePath string) error {
	if snapshotPath == "" || memFilePath == "" {
		return errors.New("Firecracker full snapshot paths are required")
	}
	return c.callNoContent(ctx, http.MethodPut, "/snapshot/create", struct {
		SnapshotType string `json:"snapshot_type"`
		SnapshotPath string `json:"snapshot_path"`
		MemFilePath  string `json:"mem_file_path"`
	}{"Full", snapshotPath, memFilePath})
}

// MemoryBackend describes the v1.16 snapshot memory backend.  Only File is
// admitted: anonymous/UFFD backends would weaken the restore artifact's file
// identity and are intentionally outside this runtime's contract.
type MemoryBackend struct {
	BackendType string `json:"backend_type"`
	BackendPath string `json:"backend_path"`
}

// LoadSnapshotConfig describes a paused snapshot restore.  Resume is present
// solely so configuration assembled from an untrusted source can be rejected;
// LoadSnapshotPaused never emits resume_vm=true.
type LoadSnapshotConfig struct {
	SnapshotPath  string
	MemoryBackend MemoryBackend
	VsockOverride *VsockOverride
	Resume        bool
}

// VsockOverride is the v1.16.1 restore override. The snapshot already owns
// the device and guest CID, so a restore may change only its backing UDS path.
type VsockOverride struct {
	UDSPath string `json:"uds_path"`
}

// LoadSnapshotPaused loads a snapshot and requires Firecracker to leave it
// paused.  It hard-rejects Resume=true and any memory backend other than File.
func (c *Client) LoadSnapshotPaused(ctx context.Context, config LoadSnapshotConfig) error {
	if config.Resume {
		return errors.New("Firecracker snapshot restore must not resume the VM")
	}
	if config.SnapshotPath == "" {
		return errors.New("Firecracker snapshot path is empty")
	}
	if config.MemoryBackend.BackendType != "File" || config.MemoryBackend.BackendPath == "" {
		return errors.New("Firecracker snapshot memory backend must be File with a path")
	}
	request := struct {
		SnapshotPath  string         `json:"snapshot_path"`
		MemBackend    MemoryBackend  `json:"mem_backend"`
		ResumeVM      bool           `json:"resume_vm"`
		VsockOverride *VsockOverride `json:"vsock_override,omitempty"`
	}{SnapshotPath: config.SnapshotPath, MemBackend: config.MemoryBackend, ResumeVM: false}
	if config.VsockOverride != nil {
		if config.VsockOverride.UDSPath == "" {
			return errors.New("Firecracker vsock override UDS path is empty")
		}
		request.VsockOverride = config.VsockOverride
	}
	return c.callNoContent(ctx, http.MethodPut, "/snapshot/load", request)
}

func validateVsock(v VsockDevice) error {
	if v.GuestCID < 3 || v.UDSPath == "" {
		return errors.New("Firecracker vsock requires guest CID >= 3 and a UDS path")
	}
	return nil
}

func isInstanceState(state VMState) bool {
	return state == StateNotStarted || state == StateRunning || state == StatePaused
}

func (c *Client) callNoContent(ctx context.Context, method, requestPath string, request any) error {
	return c.callJSON(ctx, method, requestPath, request, http.StatusNoContent, nil)
}

func (c *Client) callJSON(ctx context.Context, method, requestPath string, request any, expectedStatus int, response any) error {
	if err := c.TraceError(); err != nil {
		return err
	}
	if !strings.HasPrefix(requestPath, "/") || path.Clean(requestPath) != requestPath {
		return errors.New("invalid Firecracker API path")
	}
	var encoded []byte
	var err error
	if request != nil {
		encoded, err = json.Marshal(request)
		if err != nil {
			return fmt.Errorf("encode Firecracker %s %s request: %w", method, requestPath, err)
		}
	}
	callCtx, cancel := withTimeout(ctx, c.timeout)
	defer cancel()
	httpRequest, err := http.NewRequestWithContext(callCtx, method, "http://firecracker"+requestPath, bytes.NewReader(encoded))
	if err != nil {
		return fmt.Errorf("create Firecracker request: %w", err)
	}
	if request != nil {
		httpRequest.Header.Set("Content-Type", "application/json")
	}
	result, err := c.http.Do(httpRequest)
	if err != nil {
		callErr := fmt.Errorf("send Firecracker %s %s: %w", method, requestPath, err)
		return errors.Join(callErr, c.trace.record(method, requestPath, encoded, 0, nil, callErr))
	}
	body, readErr := io.ReadAll(io.LimitReader(result.Body, c.maxBody+1))
	closeErr := result.Body.Close()
	if readErr != nil {
		err = fmt.Errorf("read Firecracker response: %w", readErr)
	} else if len(body) > int(c.maxBody) {
		err = &ResponseTooLargeError{Limit: c.maxBody}
	} else if closeErr != nil {
		err = fmt.Errorf("close Firecracker response: %w", closeErr)
	}
	if traceErr := c.trace.record(method, requestPath, encoded, result.StatusCode, body, err); traceErr != nil {
		return errors.Join(err, traceErr)
	}
	if err != nil {
		return err
	}
	if result.StatusCode != expectedStatus {
		return &HTTPError{Method: method, Path: requestPath, StatusCode: result.StatusCode, Status: result.Status, Body: append([]byte(nil), body...)}
	}
	if response == nil {
		if len(body) != 0 {
			return fmt.Errorf("Firecracker %s %s returned %d unexpected body bytes", method, requestPath, len(body))
		}
		return nil
	}
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(response); err != nil {
		return fmt.Errorf("decode Firecracker %s %s response: %w", method, requestPath, err)
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return errors.New("Firecracker response contains multiple JSON values")
	}
	return nil
}

// TraceError returns the permanent evidence failure recorded by this client.
// Once non-nil, later calls are rejected before any network activity.
func (c *Client) TraceError() error {
	if c == nil || c.trace == nil {
		return nil
	}
	return c.trace.err()
}

// Close closes idle API connections and returns any retained trace failure.
// It does not close Trace: ownership remains with the caller.
func (c *Client) Close() error {
	if c == nil {
		return nil
	}
	if c.http != nil {
		c.http.CloseIdleConnections()
	}
	return c.TraceError()
}

func withTimeout(ctx context.Context, timeout time.Duration) (context.Context, context.CancelFunc) {
	if deadline, ok := ctx.Deadline(); ok && time.Until(deadline) <= timeout {
		return context.WithCancel(ctx)
	}
	return context.WithTimeout(ctx, timeout)
}

type jsonlTrace struct {
	mu       sync.Mutex
	writer   io.Writer
	sequence uint64
	failure  error
}

func newJSONLTrace(writer io.Writer) *jsonlTrace { return &jsonlTrace{writer: writer} }
func (t *jsonlTrace) record(method, requestPath string, request []byte, status int, response []byte, callErr error) error {
	if t == nil || t.writer == nil {
		return nil
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.failure != nil {
		return &TraceError{Err: t.failure}
	}
	t.sequence++
	record := struct {
		Sequence     uint64          `json:"sequence"`
		TimeNS       int64           `json:"time_ns"`
		Method       string          `json:"method"`
		Path         string          `json:"path"`
		Request      json.RawMessage `json:"request,omitempty"`
		Status       int             `json:"status,omitempty"`
		Response     json.RawMessage `json:"response,omitempty"`
		ResponseText string          `json:"response_text,omitempty"`
		Error        string          `json:"error,omitempty"`
	}{Sequence: t.sequence, TimeNS: time.Now().UnixNano(), Method: method, Path: requestPath, Request: request, Status: status}
	if json.Valid(response) {
		record.Response = response
	} else if len(response) != 0 {
		record.ResponseText = string(response)
	}
	if callErr != nil {
		record.Error = callErr.Error()
	}
	encoded, err := json.Marshal(record)
	if err == nil {
		encoded = append(encoded, '\n')
	}
	if err == nil {
		var written int
		written, err = t.writer.Write(encoded)
		if err == nil && written != len(encoded) {
			err = io.ErrShortWrite
		}
	}
	if err != nil {
		t.failure = err
		return &TraceError{Err: err}
	}
	return nil
}

func (t *jsonlTrace) err() error {
	if t == nil {
		return nil
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.failure == nil {
		return nil
	}
	return &TraceError{Err: t.failure}
}
