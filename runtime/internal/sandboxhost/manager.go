package sandboxhost

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"

	controlapi "github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
)

const (
	managedSocketPrefix = "sandbox-"
	managedSocketSuffix = ".sock"
	managedDigestBytes  = 16
	unixSocketPathLimit = 108
	endpointDrainTime   = 65 * time.Second
	directoryLockName   = ".safe-change.lock"
)

// Manager is the sole in-process owner of credential-free sandbox endpoints.
// It never attaches bindings reconstructed by History replay. Endpoints are
// created only when ReplaceCommitted is called after a fresh Cutover in this
// Control boot.
type Manager struct {
	mu            sync.Mutex
	control       *control.Control
	serverAPI     *controlapi.Server
	directory     string
	directoryInfo os.FileInfo
	directoryLock *os.File
	endpoints     map[string]*Endpoint
	closed        bool
	closeDone     chan struct{}
	closeErr      error

	prepare func(*control.Control, *controlapi.Server, control.SandboxBinding, string) (*Endpoint, error)
	attach  func([]control.SandboxBinding) error
}

// NewManager validates a private endpoint directory and removes only dead,
// current-user Unix sockets with this manager's hashed filename format. It
// does not inspect durable bindings and cannot re-enable a replayed sandbox.
func NewManager(controller *control.Control, serverAPI *controlapi.Server, directory string) (*Manager, error) {
	if controller == nil || serverAPI == nil {
		return nil, errors.New("sandbox manager requires control and API")
	}
	probePath := filepath.Join(directory, managedSocketName("path-length-probe"))
	directoryInfo, err := validateSocketParent(probePath)
	if err != nil {
		return nil, err
	}
	if len([]byte(probePath)) >= unixSocketPathLimit {
		return nil, fmt.Errorf("sandbox socket directory is too long for Unix sockets: %q", directory)
	}
	directoryLock, err := lockEndpointDirectory(directory)
	if err != nil {
		return nil, err
	}
	releaseOnError := true
	defer func() {
		if releaseOnError {
			_ = unlockEndpointDirectory(directoryLock)
		}
	}()
	entries, err := os.ReadDir(directory)
	if err != nil {
		return nil, fmt.Errorf("read sandbox socket directory: %w", err)
	}
	for _, entry := range entries {
		if !isManagedSocketName(entry.Name()) && !isInternalSocketName(entry.Name()) {
			continue
		}
		path := filepath.Join(directory, entry.Name())
		if err := removeOwnedStaleSocket(path); err != nil {
			return nil, fmt.Errorf("clean managed sandbox socket %q: %w", path, err)
		}
	}
	manager := &Manager{
		control: controller, serverAPI: serverAPI, directory: directory,
		directoryInfo: directoryInfo, directoryLock: directoryLock,
		endpoints: make(map[string]*Endpoint), prepare: prepareUnix,
	}
	manager.attach = controller.AttachSandboxHosts
	releaseOnError = false
	return manager, nil
}

func (m *Manager) validateDirectoryIdentity() error {
	current, err := validateSocketParent(filepath.Join(m.directory, managedSocketName("identity-probe")))
	if err != nil {
		return err
	}
	if m.directoryInfo == nil || !os.SameFile(m.directoryInfo, current) {
		return errors.New("sandbox socket directory identity changed; manager is permanently fail-closed")
	}
	return nil
}

func lockEndpointDirectory(directory string) (*os.File, error) {
	path := filepath.Join(directory, directoryLockName)
	descriptor, err := syscall.Open(
		path, syscall.O_RDWR|syscall.O_CREAT|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, 0o600,
	)
	if err != nil {
		return nil, fmt.Errorf("open sandbox directory lock: %w", err)
	}
	file := os.NewFile(uintptr(descriptor), path)
	if file == nil {
		_ = syscall.Close(descriptor)
		return nil, errors.New("wrap sandbox directory lock")
	}
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm() != 0o600 {
		_ = file.Close()
		return nil, errors.New("sandbox directory lock must be a private regular file")
	}
	if err := requireCurrentOwner(info, "sandbox directory lock"); err != nil {
		_ = file.Close()
		return nil, err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Nlink != 1 {
		_ = file.Close()
		return nil, errors.New("sandbox directory lock must have exactly one link")
	}
	pathInfo, err := os.Lstat(path)
	if err != nil || pathInfo.Mode()&os.ModeSymlink != 0 || !os.SameFile(info, pathInfo) {
		_ = file.Close()
		return nil, errors.New("sandbox directory lock path changed while opening")
	}
	if err := syscall.Flock(descriptor, syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		_ = file.Close()
		return nil, fmt.Errorf("another sandbox endpoint manager owns %q: %w", directory, err)
	}
	return file, nil
}

func unlockEndpointDirectory(file *os.File) error {
	if file == nil {
		return nil
	}
	return errors.Join(syscall.Flock(int(file.Fd()), syscall.LOCK_UN), file.Close())
}

func isInternalSocketName(name string) bool {
	if len(name) != 3+16 || (!strings.HasPrefix(name, ".p-") && !strings.HasPrefix(name, ".r-")) {
		return false
	}
	decoded, err := hex.DecodeString(name[3:])
	return err == nil && len(decoded) == 8
}

// PathForSandbox returns the stable host socket path for a sandbox identity.
// A 128-bit SHA-256-derived name prevents slashes, dot components, long names,
// and control bytes in a SandboxID from changing the configured directory,
// while leaving enough room under the Unix sockaddr path limit.
func (m *Manager) PathForSandbox(sandboxID string) string {
	return filepath.Join(m.directory, managedSocketName(sandboxID))
}

func managedSocketName(sandboxID string) string {
	digest := sha256.Sum256([]byte(sandboxID))
	return managedSocketPrefix + hex.EncodeToString(digest[:managedDigestBytes]) + managedSocketSuffix
}

func isManagedSocketName(name string) bool {
	if !strings.HasPrefix(name, managedSocketPrefix) || !strings.HasSuffix(name, managedSocketSuffix) {
		return false
	}
	digest := strings.TrimSuffix(strings.TrimPrefix(name, managedSocketPrefix), managedSocketSuffix)
	if len(digest) != managedDigestBytes*2 {
		return false
	}
	decoded, err := hex.DecodeString(digest)
	return err == nil && len(decoded) == managedDigestBytes
}

// ReplaceCommitted publishes endpoints for the complete binding set already
// committed in Control. Old endpoints become logically stale at Cutover; this
// method physically drains them, prepares every replacement socket, atomically
// attaches the complete set, and only then starts serving. Any error leaves
// the committed set unattached.
func (m *Manager) ReplaceCommitted(bindings []control.SandboxBinding) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.closed {
		return errors.New("sandbox endpoint manager is closed")
	}
	if err := m.validateDirectoryIdentity(); err != nil {
		return err
	}
	desired := m.control.SandboxBindings()
	if !bindingSetsEqual(bindings, desired) {
		return errors.New("endpoint publication does not match the committed sandbox set")
	}
	old := m.endpoints
	m.endpoints = make(map[string]*Endpoint)
	if err := closeEndpointSet(old); err != nil {
		return fmt.Errorf("drain stale sandbox endpoints: %w", err)
	}

	prepared := make(map[string]*Endpoint, len(desired))
	for _, binding := range desired {
		path := m.PathForSandbox(binding.SandboxID)
		endpoint, err := m.prepare(m.control, m.serverAPI, binding, path)
		if err != nil {
			abortErr := abortEndpointSet(prepared)
			return errors.Join(fmt.Errorf("prepare sandbox %q endpoint: %w", binding.SandboxID, err), abortErr)
		}
		prepared[binding.SandboxID] = endpoint
	}
	if err := m.attach(desired); err != nil {
		abortErr := abortEndpointSet(prepared)
		return errors.Join(fmt.Errorf("attach complete sandbox endpoint set: %w", err), abortErr)
	}
	for _, binding := range desired {
		prepared[binding.SandboxID].attached = true
	}
	m.endpoints = prepared
	for _, binding := range desired {
		prepared[binding.SandboxID].start()
	}
	return nil
}

// Close stops accepting sandbox calls, drains bounded responses, detaches all
// live bindings, and removes their socket inodes. It does not close Control.
func (m *Manager) Close() error {
	m.mu.Lock()
	if m.closeDone != nil {
		done := m.closeDone
		m.mu.Unlock()
		<-done
		m.mu.Lock()
		err := m.closeErr
		m.mu.Unlock()
		return err
	}
	m.closed = true
	m.closeDone = make(chan struct{})
	done := m.closeDone
	endpoints := m.endpoints
	m.endpoints = make(map[string]*Endpoint)
	directoryLock := m.directoryLock
	m.directoryLock = nil
	m.mu.Unlock()
	err := errors.Join(closeEndpointSet(endpoints), unlockEndpointDirectory(directoryLock))
	m.mu.Lock()
	m.closeErr = err
	close(done)
	m.mu.Unlock()
	return err
}

func closeEndpointSet(endpoints map[string]*Endpoint) error {
	if len(endpoints) == 0 {
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), endpointDrainTime)
	defer cancel()
	type result struct {
		id  string
		err error
	}
	results := make(chan result, len(endpoints))
	for id, endpoint := range endpoints {
		go func(id string, endpoint *Endpoint) {
			results <- result{id: id, err: endpoint.Close(ctx)}
		}(id, endpoint)
	}
	collected := make([]result, 0, len(endpoints))
	for range endpoints {
		collected = append(collected, <-results)
	}
	sort.Slice(collected, func(left, right int) bool { return collected[left].id < collected[right].id })
	var joined error
	for _, item := range collected {
		if item.err != nil {
			joined = errors.Join(joined, fmt.Errorf("sandbox %q: %w", item.id, item.err))
		}
	}
	return joined
}

func abortEndpointSet(endpoints map[string]*Endpoint) error {
	ids := make([]string, 0, len(endpoints))
	for id := range endpoints {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	var joined error
	for _, id := range ids {
		if err := endpoints[id].abort(); err != nil {
			joined = errors.Join(joined, fmt.Errorf("abort sandbox %q: %w", id, err))
		}
	}
	return joined
}

func bindingSetsEqual(left, right []control.SandboxBinding) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index].SandboxID != right[index].SandboxID ||
			left[index].Generation != right[index].Generation ||
			left[index].HostInstanceID != right[index].HostInstanceID ||
			left[index].Domain != right[index].Domain ||
			!stringsEqual(left[index].AllowedKinds, right[index].AllowedKinds) {
			return false
		}
	}
	return true
}

func stringsEqual(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}
