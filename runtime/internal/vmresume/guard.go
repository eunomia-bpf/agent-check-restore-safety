// Package vmresume provides the host-owned gate between an accepted edit and
// a virtual-machine resume. The VMM's control channel must be reachable only
// through Guard; an Agent or experiment driver never receives it.
package vmresume

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"syscall"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

var (
	ErrDenied       = errors.New("VM resume denied by edit decision")
	ErrUnauthorized = errors.New("VM resume authorization is invalid")
	ErrConsumed     = errors.New("VM resume authorization was already consumed")
)

// ProcessIdentity distinguishes a concrete VMM process from PID reuse.
type ProcessIdentity struct {
	PID              int    `json:"pid"`
	StartTimeTicks   uint64 `json:"start_time_ticks"`
	ExecutableSHA256 string `json:"executable_sha256"`
	CommandSHA256    string `json:"command_sha256"`
}

// DiskIdentity binds the pre-open verified lane copy to the inode held open
// by the concrete VMM process.
type DiskIdentity struct {
	Path          string `json:"path"`
	Device        uint64 `json:"device"`
	Inode         uint64 `json:"inode"`
	Size          int64  `json:"size"`
	PreopenSHA256 string `json:"preopen_sha256"`
}

// Checkpoint binds both the complete disk/snapshot bytes and the canonical
// machine configuration needed to interpret them.
type Checkpoint struct {
	Path                string `json:"path"`
	SHA256              string `json:"sha256"`
	SnapshotName        string `json:"snapshot_name"`
	MachineConfig       []byte `json:"machine_config"`
	MachineConfigSHA256 string `json:"machine_config_sha256"`
}

// EndpointPublication identifies the concrete host endpoint attached for the
// replacement sandbox. Device and inode prevent path reuse between checks.
type EndpointPublication struct {
	Binding control.SandboxBinding `json:"binding"`
	Path    string                 `json:"path"`
	Device  uint64                 `json:"device"`
	Inode   uint64                 `json:"inode"`
}

// Request contains every fact to which one resume authorization is bound.
// CheckedState is the state against which Certificate was independently
// checked. ActivatedHistory is the head after the durable Rule/binding cutover.
type Request struct {
	CheckedState     *kernel.State       `json:"checked_state"`
	Certificate      kernel.Certificate  `json:"certificate"`
	ActivatedHistory kernel.HistoryPoint `json:"activated_history"`
	Checkpoint       Checkpoint          `json:"checkpoint"`
	Process          ProcessIdentity     `json:"process"`
	Disk             DiskIdentity        `json:"disk"`
	Endpoint         EndpointPublication `json:"endpoint"`
}

// Sources supplies fresh host facts. Continue must be the sole owner of the
// VMM resume primitive (for QEMU, QMP cont).
type Sources struct {
	CurrentState    func() (*kernel.State, error)
	ValidateBinding func(control.SandboxBinding) error
	ProbeEndpoint   func(context.Context, EndpointPublication) error
	Continue        func(context.Context) error
}

// Authorization is opaque outside this package and can be consumed once.
type Authorization struct {
	nonce  [32]byte
	digest [32]byte
}

type pendingAuthorization struct {
	authorization Authorization
	request       Request
}

// Guard serializes authorization and resume so checked host facts cannot be
// replaced between the final validation and the VMM command.
type Guard struct {
	mu      sync.Mutex
	sources Sources
	pending *pendingAuthorization
	used    bool
}

func New(sources Sources) (*Guard, error) {
	if sources.CurrentState == nil || sources.ValidateBinding == nil ||
		sources.ProbeEndpoint == nil || sources.Continue == nil {
		return nil, errors.New("VM resume guard requires all host fact sources")
	}
	return &Guard{sources: sources}, nil
}

// Authorize validates the pre-cutover Certificate and all current post-cutover
// facts, then returns an opaque authorization bound to their exact bytes.
func (g *Guard) Authorize(ctx context.Context, request Request) (Authorization, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	// Every new authorization attempt revokes any older pending authority,
	// including when the new decision is denied or a host fact fails validation.
	g.pending = nil
	g.used = false
	decision := decisionRequest{
		CheckedState: request.CheckedState, Certificate: request.Certificate,
		ActivatedHistory: request.ActivatedHistory,
	}
	if err := validateCheckedDecision(decision); err != nil {
		return Authorization{}, err
	}
	if request.Certificate.Decision != kernel.Activate {
		return Authorization{}, fmt.Errorf("%w: Certificate decision is %q", ErrDenied, request.Certificate.Decision)
	}
	if err := g.validateCurrent(ctx, request); err != nil {
		return Authorization{}, err
	}
	encoded, err := canonicalRequest(request)
	if err != nil {
		return Authorization{}, err
	}
	var authorization Authorization
	if _, err := rand.Read(authorization.nonce[:]); err != nil {
		return Authorization{}, err
	}
	digest := sha256.New()
	_, _ = digest.Write(encoded)
	_, _ = digest.Write(authorization.nonce[:])
	copy(authorization.digest[:], digest.Sum(nil))
	g.pending = &pendingAuthorization{authorization: authorization, request: cloneRequest(request)}
	g.used = false
	return authorization, nil
}

// Resume revalidates every dynamic fact and consumes the authorization before
// invoking Continue. A failed Continue is not retried with the same authority.
func (g *Guard) Resume(ctx context.Context, authorization Authorization) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.used {
		return ErrConsumed
	}
	if g.pending == nil || authorization != g.pending.authorization {
		return ErrUnauthorized
	}
	request := g.pending.request
	g.pending = nil
	g.used = true
	if err := g.validateCurrent(ctx, request); err != nil {
		return fmt.Errorf("revalidate VM resume facts: %w", err)
	}
	if err := g.sources.Continue(ctx); err != nil {
		return fmt.Errorf("VMM resume command failed after authorization was consumed: %w", err)
	}
	return nil
}

func (g *Guard) validateCurrent(ctx context.Context, request Request) error {
	state, err := g.sources.CurrentState()
	if err != nil {
		return fmt.Errorf("read current State: %w", err)
	}
	decision := decisionRequest{
		CheckedState: request.CheckedState, Certificate: request.Certificate,
		ActivatedHistory: request.ActivatedHistory,
	}
	if err := validateActivatedState(state, decision); err != nil {
		return err
	}
	if err := VerifyCheckpoint(request.Checkpoint); err != nil {
		return err
	}
	actualProcess, err := CaptureProcessIdentity(request.Process.PID)
	if err != nil {
		return fmt.Errorf("capture current VMM identity: %w", err)
	}
	if actualProcess != request.Process {
		return errors.New("VMM process identity changed")
	}
	actualDisk, err := CaptureDiskIdentity(request.Disk.Path, request.Disk.PreopenSHA256)
	if err != nil {
		return fmt.Errorf("capture current VMM disk identity: %w", err)
	}
	if actualDisk != request.Disk {
		return errors.New("VMM disk identity changed")
	}
	if err := VerifyProcessDisk(request.Process.PID, request.Disk); err != nil {
		return fmt.Errorf("verify VMM open disk: %w", err)
	}
	if err := g.sources.ValidateBinding(request.Endpoint.Binding); err != nil {
		return fmt.Errorf("validate sandbox binding: %w", err)
	}
	actualEndpoint, err := CaptureEndpoint(request.Endpoint.Path, request.Endpoint.Binding)
	if err != nil {
		return fmt.Errorf("capture current endpoint: %w", err)
	}
	if !reflect.DeepEqual(actualEndpoint, request.Endpoint) {
		return errors.New("sandbox endpoint identity changed")
	}
	if err := g.sources.ProbeEndpoint(ctx, request.Endpoint); err != nil {
		return fmt.Errorf("probe sandbox endpoint: %w", err)
	}
	return nil
}

type decisionRequest struct {
	CheckedState     *kernel.State
	Certificate      kernel.Certificate
	ActivatedHistory kernel.HistoryPoint
}

func validateCheckedDecision(request decisionRequest) error {
	if request.CheckedState == nil {
		return errors.New("lifecycle request has no checked State")
	}
	if request.Certificate.History != request.CheckedState.History {
		return errors.New("Certificate is not bound to the supplied checked State")
	}
	if err := kernel.VerifyCertificate(request.CheckedState, request.Certificate); err != nil {
		return fmt.Errorf("verify checked Certificate: %w", err)
	}
	return nil
}

func validateActivatedState(state *kernel.State, request decisionRequest) error {
	if request.Certificate.Decision != kernel.Activate || request.Certificate.Rule == nil {
		return errors.New("activate Certificate has no Rule")
	}
	if state == nil || state.Requirement == nil || state.Rule == nil {
		return errors.New("current State has no active Rule")
	}
	if state.History != request.ActivatedHistory {
		return errors.New("current History head differs from the authorized cutover")
	}
	if !reflect.DeepEqual(state.Rule, request.Certificate.Rule) ||
		!reflect.DeepEqual(*state.Requirement, request.Certificate.Requirement) {
		return errors.New("current Rule differs from the checked Certificate")
	}
	requirementHash, err := kernel.RequirementHash(*state.Requirement)
	if err != nil {
		return err
	}
	if requirementHash != state.Rule.RequirementHash {
		return errors.New("current Requirement hash differs from the active Rule")
	}
	return nil
}

func canonicalRequest(request Request) ([]byte, error) {
	return json.Marshal(request)
}

func cloneRequest(request Request) Request {
	encoded, err := json.Marshal(request)
	if err != nil {
		panic(err)
	}
	var clone Request
	if err := json.Unmarshal(encoded, &clone); err != nil {
		panic(err)
	}
	return clone
}

func VerifyCheckpoint(checkpoint Checkpoint) error {
	if checkpoint.Path == "" || !filepath.IsAbs(checkpoint.Path) || filepath.Clean(checkpoint.Path) != checkpoint.Path {
		return errors.New("checkpoint path must be absolute and canonical")
	}
	if checkpoint.SnapshotName == "" || strings.ContainsAny(checkpoint.SnapshotName, " \t\r\n") {
		return errors.New("checkpoint snapshot name is invalid")
	}
	if !validDigest(checkpoint.SHA256) || !validDigest(checkpoint.MachineConfigSHA256) {
		return errors.New("checkpoint hashes must be lowercase SHA-256")
	}
	var configuration any
	if err := json.Unmarshal(checkpoint.MachineConfig, &configuration); err != nil {
		return fmt.Errorf("decode machine configuration: %w", err)
	}
	canonical, err := json.Marshal(configuration)
	if err != nil {
		return err
	}
	if !bytes.Equal(canonical, checkpoint.MachineConfig) {
		return errors.New("machine configuration is not canonical JSON")
	}
	machineHash := sha256.Sum256(checkpoint.MachineConfig)
	if hex.EncodeToString(machineHash[:]) != checkpoint.MachineConfigSHA256 {
		return errors.New("machine configuration hash differs")
	}
	actual, err := hashFile(checkpoint.Path)
	if err != nil {
		return fmt.Errorf("hash checkpoint: %w", err)
	}
	if actual != checkpoint.SHA256 {
		return errors.New("checkpoint bytes differ from the sealed hash")
	}
	return nil
}

func CaptureProcessIdentity(pid int) (ProcessIdentity, error) {
	if pid <= 0 {
		return ProcessIdentity{}, errors.New("process PID must be positive")
	}
	stat, err := os.ReadFile(filepath.Join("/proc", strconv.Itoa(pid), "stat"))
	if err != nil {
		return ProcessIdentity{}, err
	}
	closeParen := bytes.LastIndexByte(stat, ')')
	if closeParen < 0 || closeParen+2 >= len(stat) {
		return ProcessIdentity{}, errors.New("process stat is malformed")
	}
	fields := strings.Fields(string(stat[closeParen+2:]))
	// After removing pid and comm, field index 19 is Linux /proc stat field 22.
	if len(fields) <= 19 {
		return ProcessIdentity{}, errors.New("process stat omits start time")
	}
	start, err := strconv.ParseUint(fields[19], 10, 64)
	if err != nil {
		return ProcessIdentity{}, err
	}
	executable := filepath.Join("/proc", strconv.Itoa(pid), "exe")
	hash, err := hashFile(executable)
	if err != nil {
		return ProcessIdentity{}, err
	}
	command, err := os.ReadFile(filepath.Join("/proc", strconv.Itoa(pid), "cmdline"))
	if err != nil {
		return ProcessIdentity{}, err
	}
	if len(command) == 0 {
		return ProcessIdentity{}, errors.New("process command line is empty")
	}
	commandHash := sha256.Sum256(command)
	return ProcessIdentity{
		PID: pid, StartTimeTicks: start, ExecutableSHA256: hash,
		CommandSHA256: hex.EncodeToString(commandHash[:]),
	}, nil
}

// CaptureDiskIdentity records the exact private lane inode whose bytes were
// hashed before QEMU opened it.
func CaptureDiskIdentity(path, preopenSHA256 string) (DiskIdentity, error) {
	if path == "" || !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return DiskIdentity{}, errors.New("VMM disk path must be absolute and canonical")
	}
	if !validDigest(preopenSHA256) {
		return DiskIdentity{}, errors.New("VMM disk pre-open hash must be lowercase SHA-256")
	}
	info, err := os.Lstat(path)
	if err != nil {
		return DiskIdentity{}, err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0o077 != 0 {
		return DiskIdentity{}, errors.New("VMM disk must be a private regular file")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(stat.Uid) != os.Geteuid() || stat.Nlink != 1 {
		return DiskIdentity{}, errors.New("VMM disk must be current-user owned with one link")
	}
	return DiskIdentity{
		Path: path, Device: uint64(stat.Dev), Inode: stat.Ino,
		Size: info.Size(), PreopenSHA256: preopenSHA256,
	}, nil
}

// VerifyProcessDisk proves that the identified VMM still holds the exact lane
// inode open. It does not trust a path string from argv or retained evidence.
func VerifyProcessDisk(pid int, disk DiskIdentity) error {
	if pid <= 0 {
		return errors.New("process PID must be positive")
	}
	current, err := CaptureDiskIdentity(disk.Path, disk.PreopenSHA256)
	if err != nil {
		return err
	}
	if current != disk {
		return errors.New("VMM disk path no longer names the captured inode")
	}
	entries, err := os.ReadDir(filepath.Join("/proc", strconv.Itoa(pid), "fd"))
	if err != nil {
		return err
	}
	for _, entry := range entries {
		file, openErr := os.Open(filepath.Join("/proc", strconv.Itoa(pid), "fd", entry.Name()))
		if openErr != nil {
			continue
		}
		info, statErr := file.Stat()
		closeErr := file.Close()
		if statErr != nil || closeErr != nil {
			continue
		}
		stat, ok := info.Sys().(*syscall.Stat_t)
		if ok && uint64(stat.Dev) == disk.Device && stat.Ino == disk.Inode {
			return nil
		}
	}
	return errors.New("VMM process does not hold the captured disk inode open")
}

func CaptureEndpoint(path string, binding control.SandboxBinding) (EndpointPublication, error) {
	if path == "" || !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return EndpointPublication{}, errors.New("endpoint path must be absolute and canonical")
	}
	info, err := os.Lstat(path)
	if err != nil {
		return EndpointPublication{}, err
	}
	if info.Mode()&os.ModeSocket == 0 || info.Mode().Perm()&0o077 != 0 {
		return EndpointPublication{}, errors.New("endpoint must be a private Unix socket")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return EndpointPublication{}, errors.New("endpoint lacks Unix identity")
	}
	return EndpointPublication{Binding: binding, Path: path, Device: uint64(stat.Dev), Inode: stat.Ino}, nil
}

func hashFile(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	digest := sha256.New()
	if _, err := io.Copy(digest, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(digest.Sum(nil)), nil
}

func validDigest(value string) bool {
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size && hex.EncodeToString(decoded) == value
}
