// Package headanchor stores a History head outside the state that can be
// restored. Callers must place the file outside every restore domain whose
// History it protects.
package headanchor

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
	"syscall"
)

const (
	formatVersion = 1
	maxFileSize   = 4096
	privateMode   = 0o600
)

var (
	zeroHash = hex.EncodeToString(make([]byte, sha256.Size))

	// ErrLocked means another writer holds the anchor lock.
	ErrLocked = errors.New("History head anchor is already open")
	// ErrClosed means the anchor has been closed.
	ErrClosed = errors.New("History head anchor is closed")
	// ErrExists means Create was asked to replace an existing anchor.
	ErrExists = errors.New("History head anchor already exists")
	// ErrCorrupt means the anchor file failed strict decoding or validation.
	ErrCorrupt = errors.New("History head anchor is corrupt")
	// ErrPrivate means the anchor file is not private to its owner.
	ErrPrivate = errors.New("History head anchor is not private")
	// ErrInvalidHead means a Head is not a valid History head.
	ErrInvalidHead = errors.New("invalid History head")
	// ErrRollback means Advance was asked to move to an older sequence.
	ErrRollback = errors.New("History head rollback refused")
	// ErrConflict means the same sequence was presented with a different hash,
	// or a later sequence reused the current hash.
	ErrConflict = errors.New("History head conflicts with current anchor")
	// ErrNeedsReopen means replacement may have reached the directory but its
	// directory sync failed. Close and Open are required before another Advance.
	ErrNeedsReopen = errors.New("History head anchor must be closed and reopened")
)

// Head is the sequence and hash of a durable History event. The empty History
// is sequence zero with a Hash of 64 zeroes.
type Head struct {
	Sequence uint64 `json:"sequence"`
	Hash     string `json:"hash"`
}

type diskRecord struct {
	Version  int    `json:"version"`
	Sequence uint64 `json:"sequence"`
	Hash     string `json:"hash"`
	Checksum string `json:"checksum"`
}

// Anchor is a single-writer durable History head anchor.
type Anchor struct {
	mu      sync.RWMutex
	path    string
	lock    *os.File
	current Head
	closed  bool
	failed  error
}

// Create creates a private anchor at path. It refuses to replace any existing
// file and keeps the writer lock until Close.
func Create(path string, initial Head) (*Anchor, error) {
	if err := validatePath(path); err != nil {
		return nil, err
	}
	if err := validateHead(initial); err != nil {
		return nil, err
	}

	lock, err := acquireLock(path)
	if err != nil {
		return nil, fmt.Errorf("create History head anchor %q: %w", path, err)
	}
	cleanup := func() {
		_ = unlock(lock)
		_ = lock.Close()
	}

	if _, err := os.Lstat(path); err == nil {
		cleanup()
		return nil, fmt.Errorf("create History head anchor %q: %w", path, ErrExists)
	} else if !errors.Is(err, os.ErrNotExist) {
		cleanup()
		return nil, fmt.Errorf("inspect History head anchor %q: %w", path, err)
	}

	_, err = writeRecordAtomic(path, initial)
	if err != nil {
		cleanup()
		return nil, fmt.Errorf("create History head anchor %q: %w", path, err)
	}
	return &Anchor{path: path, lock: lock, current: initial}, nil
}

// Open strictly validates an existing private anchor and keeps its writer lock
// until Close.
func Open(path string) (*Anchor, error) {
	if err := validatePath(path); err != nil {
		return nil, err
	}
	lock, err := acquireLock(path)
	if err != nil {
		return nil, fmt.Errorf("open History head anchor %q: %w", path, err)
	}
	cleanup := func() {
		_ = unlock(lock)
		_ = lock.Close()
	}

	current, err := readRecord(path)
	if err != nil {
		cleanup()
		return nil, fmt.Errorf("open History head anchor %q: %w", path, err)
	}
	return &Anchor{path: path, lock: lock, current: current}, nil
}

// Current returns the durable anchored Head.
func (anchor *Anchor) Current() (Head, error) {
	anchor.mu.RLock()
	defer anchor.mu.RUnlock()
	if err := anchor.stateErrorLocked(); err != nil {
		return Head{}, err
	}
	return anchor.current, nil
}

// Advance durably moves the anchor to a later Head. Repeating the exact current
// Head is idempotent. Older sequences and conflicting hashes are refused.
func (anchor *Anchor) Advance(next Head) error {
	anchor.mu.Lock()
	defer anchor.mu.Unlock()
	if err := anchor.stateErrorLocked(); err != nil {
		return err
	}
	if err := validateHead(next); err != nil {
		return err
	}

	if next == anchor.current {
		return nil
	}
	if next.Sequence < anchor.current.Sequence {
		return fmt.Errorf("%w: current sequence %d, requested %d", ErrRollback, anchor.current.Sequence, next.Sequence)
	}
	if next.Sequence == anchor.current.Sequence {
		return fmt.Errorf("%w: sequence %d has a different hash", ErrConflict, next.Sequence)
	}
	if next.Hash == anchor.current.Hash {
		return fmt.Errorf("%w: later sequence %d reuses the current hash", ErrConflict, next.Sequence)
	}

	replaced, err := writeRecordAtomic(anchor.path, next)
	if err != nil {
		if replaced {
			anchor.failed = err
			return errors.Join(ErrNeedsReopen, err)
		}
		return err
	}
	anchor.current = next
	return nil
}

// Close releases the single-writer lock. It is safe to call more than once.
func (anchor *Anchor) Close() error {
	anchor.mu.Lock()
	defer anchor.mu.Unlock()
	if anchor.closed {
		return nil
	}
	anchor.closed = true
	return errors.Join(unlock(anchor.lock), anchor.lock.Close())
}

func (anchor *Anchor) stateErrorLocked() error {
	if anchor.closed {
		return ErrClosed
	}
	if anchor.failed != nil {
		return fmt.Errorf("%w: prior replacement was not durably confirmed: %v", ErrNeedsReopen, anchor.failed)
	}
	return nil
}

func validatePath(path string) error {
	if path == "" {
		return errors.New("History head anchor path is empty")
	}
	return nil
}

func validateHead(head Head) error {
	if !validHash(head.Hash) {
		return fmt.Errorf("%w: hash must be 64 lowercase hexadecimal characters", ErrInvalidHead)
	}
	if head.Sequence == 0 && head.Hash != zeroHash {
		return fmt.Errorf("%w: empty History must use the zero hash", ErrInvalidHead)
	}
	if head.Sequence != 0 && head.Hash == zeroHash {
		return fmt.Errorf("%w: non-empty History cannot use the zero hash", ErrInvalidHead)
	}
	return nil
}

func readRecord(path string) (Head, error) {
	file, err := openReadOnlyNoFollow(path)
	if err != nil {
		return Head{}, err
	}
	defer file.Close()

	info, err := file.Stat()
	if err != nil {
		return Head{}, err
	}
	if !info.Mode().IsRegular() {
		return Head{}, fmt.Errorf("%w: anchor is not a regular file", ErrCorrupt)
	}
	if info.Mode().Perm() != privateMode {
		return Head{}, fmt.Errorf("%w: mode is %#o, want %#o", ErrPrivate, info.Mode().Perm(), privateMode)
	}
	if info.Size() <= 0 || info.Size() > maxFileSize {
		return Head{}, fmt.Errorf("%w: invalid file size %d", ErrCorrupt, info.Size())
	}

	contents, err := io.ReadAll(io.LimitReader(file, maxFileSize+1))
	if err != nil {
		return Head{}, err
	}
	if len(contents) > maxFileSize {
		return Head{}, fmt.Errorf("%w: file exceeds %d bytes", ErrCorrupt, maxFileSize)
	}

	decoder := json.NewDecoder(bytes.NewReader(contents))
	decoder.DisallowUnknownFields()
	var record diskRecord
	if err := decoder.Decode(&record); err != nil {
		return Head{}, fmt.Errorf("%w: decode JSON: %v", ErrCorrupt, err)
	}
	if err := requireJSONEnd(decoder); err != nil {
		return Head{}, fmt.Errorf("%w: %v", ErrCorrupt, err)
	}
	if record.Version != formatVersion {
		return Head{}, fmt.Errorf("%w: unsupported version %d", ErrCorrupt, record.Version)
	}
	head := Head{Sequence: record.Sequence, Hash: record.Hash}
	if err := validateHead(head); err != nil {
		return Head{}, fmt.Errorf("%w: %v", ErrCorrupt, err)
	}
	if !validHash(record.Checksum) || record.Checksum != checksum(head) {
		return Head{}, fmt.Errorf("%w: checksum does not match", ErrCorrupt)
	}
	canonical, err := encodeRecord(head)
	if err != nil {
		return Head{}, fmt.Errorf("%w: re-encode record: %v", ErrCorrupt, err)
	}
	if !bytes.Equal(contents, canonical) {
		return Head{}, fmt.Errorf("%w: JSON is not in the required form", ErrCorrupt)
	}
	return head, nil
}

func writeRecordAtomic(path string, head Head) (bool, error) {
	contents, err := encodeRecord(head)
	if err != nil {
		return false, err
	}
	directory := filepath.Dir(path)
	temporary, err := os.CreateTemp(directory, "."+filepath.Base(path)+".tmp-")
	if err != nil {
		return false, fmt.Errorf("create temporary anchor: %w", err)
	}
	temporaryPath := temporary.Name()
	closed := false
	defer func() {
		if !closed {
			_ = temporary.Close()
		}
		_ = os.Remove(temporaryPath)
	}()

	if err := temporary.Chmod(privateMode); err != nil {
		return false, fmt.Errorf("set private anchor mode: %w", err)
	}
	if err := writeAll(temporary, contents); err != nil {
		return false, fmt.Errorf("write temporary anchor: %w", err)
	}
	if err := temporary.Sync(); err != nil {
		return false, fmt.Errorf("sync temporary anchor: %w", err)
	}
	if err := temporary.Close(); err != nil {
		closed = true
		return false, fmt.Errorf("close temporary anchor: %w", err)
	}
	closed = true

	if err := os.Rename(temporaryPath, path); err != nil {
		return false, fmt.Errorf("replace anchor: %w", err)
	}
	if err := syncDirectory(directory); err != nil {
		return true, fmt.Errorf("sync anchor directory: %w", err)
	}
	return true, nil
}

func encodeRecord(head Head) ([]byte, error) {
	record := diskRecord{
		Version:  formatVersion,
		Sequence: head.Sequence,
		Hash:     head.Hash,
		Checksum: checksum(head),
	}
	contents, err := json.Marshal(record)
	if err != nil {
		return nil, err
	}
	return append(contents, '\n'), nil
}

func checksum(head Head) string {
	digest := sha256.New()
	_, _ = digest.Write([]byte("history-head-anchor-v1\x00"))
	var sequence [8]byte
	binary.BigEndian.PutUint64(sequence[:], head.Sequence)
	_, _ = digest.Write(sequence[:])
	_, _ = digest.Write([]byte(head.Hash))
	return hex.EncodeToString(digest.Sum(nil))
}

func validHash(hash string) bool {
	if len(hash) != sha256.Size*2 {
		return false
	}
	decoded, err := hex.DecodeString(hash)
	return err == nil && hex.EncodeToString(decoded) == hash
}

func requireJSONEnd(decoder *json.Decoder) error {
	var extra any
	err := decoder.Decode(&extra)
	if errors.Is(err, io.EOF) {
		return nil
	}
	if err == nil {
		return errors.New("multiple JSON values")
	}
	return err
}

func acquireLock(anchorPath string) (*os.File, error) {
	lockPath := anchorPath + ".lock"
	_, statErr := os.Lstat(lockPath)
	created := errors.Is(statErr, os.ErrNotExist)
	if statErr != nil && !created {
		return nil, statErr
	}

	descriptor, err := syscall.Open(lockPath, syscall.O_RDWR|syscall.O_CREAT|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, privateMode)
	if err != nil {
		return nil, err
	}
	file := os.NewFile(uintptr(descriptor), lockPath)
	if file == nil {
		_ = syscall.Close(descriptor)
		return nil, errors.New("create lock file handle")
	}

	if err := lock(file); err != nil {
		_ = file.Close()
		return nil, err
	}
	cleanup := func() {
		_ = unlock(file)
		_ = file.Close()
	}
	info, err := file.Stat()
	if err != nil {
		cleanup()
		return nil, err
	}
	if !info.Mode().IsRegular() {
		cleanup()
		return nil, errors.New("anchor lock is not a regular file")
	}
	if err := file.Chmod(privateMode); err != nil {
		cleanup()
		return nil, err
	}
	if err := file.Sync(); err != nil {
		cleanup()
		return nil, err
	}
	if created {
		if err := syncDirectory(filepath.Dir(lockPath)); err != nil {
			cleanup()
			return nil, err
		}
	}
	return file, nil
}

func openReadOnlyNoFollow(path string) (*os.File, error) {
	descriptor, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return nil, err
	}
	file := os.NewFile(uintptr(descriptor), path)
	if file == nil {
		_ = syscall.Close(descriptor)
		return nil, errors.New("open anchor file handle")
	}
	return file, nil
}

func lock(file *os.File) error {
	for {
		err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
		if errors.Is(err, syscall.EINTR) {
			continue
		}
		if errors.Is(err, syscall.EWOULDBLOCK) || errors.Is(err, syscall.EAGAIN) {
			return ErrLocked
		}
		return err
	}
}

func unlock(file *os.File) error {
	for {
		err := syscall.Flock(int(file.Fd()), syscall.LOCK_UN)
		if errors.Is(err, syscall.EINTR) {
			continue
		}
		return err
	}
}

func syncDirectory(path string) error {
	directory, err := os.Open(path)
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}

func writeAll(writer io.Writer, data []byte) error {
	for len(data) != 0 {
		written, err := writer.Write(data)
		if err != nil {
			return err
		}
		if written == 0 {
			return io.ErrShortWrite
		}
		data = data[written:]
	}
	return nil
}
