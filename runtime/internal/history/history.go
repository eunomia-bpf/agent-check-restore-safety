// Package history provides a durable, append-only History for executed
// Operations. A History is opened by at most one writer at a time. Each event
// is length-framed JSON and is linked to the previous event with SHA-256.
package history

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
	headerSize    = 12
	maxFrameSize  = 16 << 20
)

var (
	frameMagic = [4]byte{'H', 'S', 'T', '1'}
	zeroHash   = hex.EncodeToString(make([]byte, sha256.Size))

	// ErrLocked means another process or History instance holds the writer lock.
	ErrLocked = errors.New("history is already open for writing")
	// ErrClosed means the History has been closed.
	ErrClosed = errors.New("history is closed")
	// ErrCorrupt means a complete frame or the hash chain failed validation.
	ErrCorrupt = errors.New("history is corrupt")
	// ErrEventTooLarge means the encoded event exceeds the file-format limit.
	ErrEventTooLarge = errors.New("history event is too large")
	// ErrNeedsReopen means an Append could not restore the file after a write
	// failure. The History must be closed and opened again before more writes.
	ErrNeedsReopen = errors.New("history must be closed and reopened")
)

// Head identifies the last durable event. An empty History has Sequence zero
// and a Hash of 64 zeroes.
type Head struct {
	Sequence uint64 `json:"sequence"`
	Hash     string `json:"hash"`
}

// Event is one durable Operation in a History. Data is retained as JSON so
// callers can use domain-specific records without changing the History format.
type Event struct {
	Sequence     uint64          `json:"sequence"`
	Operation    string          `json:"operation"`
	Data         json.RawMessage `json:"data"`
	PreviousHash string          `json:"previous_hash"`
	Hash         string          `json:"hash"`
}

type storedEvent struct {
	Version      int             `json:"version"`
	Sequence     uint64          `json:"sequence"`
	Operation    string          `json:"operation"`
	Data         json.RawMessage `json:"data"`
	PreviousHash string          `json:"previous_hash"`
	Hash         string          `json:"hash"`
}

// History is a single-writer durable execution record. Its methods are safe
// for concurrent use within one process.
type History struct {
	mu     sync.RWMutex
	file   *os.File
	path   string
	events []Event
	head   Head
	closed bool
	failed error
}

// Open opens or creates path, obtains its exclusive writer lock, and replays
// every complete event. If the final frame was only partly written, Open
// truncates that frame and syncs the repaired file before returning.
func Open(path string) (*History, error) {
	if path == "" {
		return nil, fmt.Errorf("open history: empty path")
	}

	_, statErr := os.Stat(path)
	created := errors.Is(statErr, os.ErrNotExist)
	if statErr != nil && !created {
		return nil, fmt.Errorf("open history %q: %w", path, statErr)
	}

	file, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE, 0o600)
	if err != nil {
		return nil, fmt.Errorf("open history %q: %w", path, err)
	}
	cleanup := func() {
		_ = unlock(file)
		_ = file.Close()
	}

	if err := lock(file); err != nil {
		_ = file.Close()
		return nil, fmt.Errorf("open history %q: %w", path, err)
	}

	info, err := file.Stat()
	if err != nil {
		cleanup()
		return nil, fmt.Errorf("stat history %q: %w", path, err)
	}
	if !info.Mode().IsRegular() {
		cleanup()
		return nil, fmt.Errorf("open history %q: not a regular file", path)
	}

	h := &History{
		file: file,
		path: path,
		head: Head{Hash: zeroHash},
	}
	if err := h.replay(); err != nil {
		cleanup()
		return nil, fmt.Errorf("open history %q: %w", path, err)
	}

	if created {
		if err := file.Sync(); err != nil {
			cleanup()
			return nil, fmt.Errorf("sync new history %q: %w", path, err)
		}
		if err := syncDirectory(filepath.Dir(path)); err != nil {
			cleanup()
			return nil, fmt.Errorf("sync history directory for %q: %w", path, err)
		}
	}

	return h, nil
}

// Append encodes data as JSON and durably appends one Operation. It returns
// only after the file has been synced.
func (h *History) Append(operation string, data any) (Event, error) {
	if err := h.appendStateError(); err != nil {
		return Event{}, err
	}
	encoded, err := json.Marshal(data)
	if err != nil {
		return Event{}, fmt.Errorf("encode history data: %w", err)
	}
	return h.AppendJSON(operation, encoded)
}

// AppendJSON durably appends one Operation whose data is already JSON. The
// data is compacted before hashing and storage so later caller mutations cannot
// change the in-memory event.
func (h *History) AppendJSON(operation string, data json.RawMessage) (Event, error) {
	if err := h.appendStateError(); err != nil {
		return Event{}, err
	}
	if operation == "" {
		return Event{}, fmt.Errorf("append history event: empty operation")
	}
	if !json.Valid(data) {
		return Event{}, fmt.Errorf("append history event: invalid JSON data")
	}

	var compact bytes.Buffer
	if err := json.Compact(&compact, data); err != nil {
		return Event{}, fmt.Errorf("compact history data: %w", err)
	}
	ownedData := append(json.RawMessage(nil), compact.Bytes()...)

	h.mu.Lock()
	defer h.mu.Unlock()
	if err := h.appendStateErrorLocked(); err != nil {
		return Event{}, err
	}

	event := Event{
		Sequence:     h.head.Sequence + 1,
		Operation:    operation,
		Data:         ownedData,
		PreviousHash: h.head.Hash,
	}
	event.Hash = hashEvent(event)
	stored := storedEvent{
		Version:      formatVersion,
		Sequence:     event.Sequence,
		Operation:    event.Operation,
		Data:         event.Data,
		PreviousHash: event.PreviousHash,
		Hash:         event.Hash,
	}
	payload, err := json.Marshal(stored)
	if err != nil {
		return Event{}, fmt.Errorf("encode history event: %w", err)
	}
	if len(payload) > maxFrameSize {
		return Event{}, fmt.Errorf("%w: %d bytes", ErrEventTooLarge, len(payload))
	}

	start, err := h.file.Seek(0, io.SeekEnd)
	if err != nil {
		return Event{}, fmt.Errorf("seek history end: %w", err)
	}
	var header [headerSize]byte
	copy(header[:4], frameMagic[:])
	binary.BigEndian.PutUint64(header[4:], uint64(len(payload)))
	if err := writeAll(h.file, header[:]); err != nil {
		return Event{}, h.rollback(start, fmt.Errorf("write history frame header: %w", err))
	}
	if err := writeAll(h.file, payload); err != nil {
		return Event{}, h.rollback(start, fmt.Errorf("write history event: %w", err))
	}
	if err := h.file.Sync(); err != nil {
		return Event{}, h.rollback(start, fmt.Errorf("sync history event: %w", err))
	}

	h.events = append(h.events, cloneEvent(event))
	h.head = Head{Sequence: event.Sequence, Hash: event.Hash}
	return cloneEvent(event), nil
}

// Head returns the last durable event identifier.
func (h *History) Head() Head {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return h.head
}

// Events returns an independent copy of all durable events in order.
func (h *History) Events() []Event {
	h.mu.RLock()
	defer h.mu.RUnlock()
	events := make([]Event, len(h.events))
	for i := range h.events {
		events[i] = cloneEvent(h.events[i])
	}
	return events
}

// Close releases the writer lock and closes the file. It is safe to call more
// than once.
func (h *History) Close() error {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.closed {
		return nil
	}
	h.closed = true
	return errors.Join(unlock(h.file), h.file.Close())
}

func (h *History) replay() error {
	if _, err := h.file.Seek(0, io.SeekStart); err != nil {
		return fmt.Errorf("seek history start: %w", err)
	}

	var offset int64
	for {
		frameStart := offset
		var header [headerSize]byte
		n, err := io.ReadFull(h.file, header[:])
		offset += int64(n)
		if err != nil {
			if errors.Is(err, io.EOF) && n == 0 {
				break
			}
			if errors.Is(err, io.ErrUnexpectedEOF) || errors.Is(err, io.EOF) {
				if !validPartialHeader(header[:n]) {
					return corruption(frameStart, "invalid incomplete frame header")
				}
				return h.truncateTail(frameStart)
			}
			return fmt.Errorf("read history frame header at byte %d: %w", frameStart, err)
		}

		if !bytes.Equal(header[:4], frameMagic[:]) {
			return corruption(frameStart, "invalid frame marker")
		}
		length := binary.BigEndian.Uint64(header[4:])
		if length == 0 || length > maxFrameSize {
			return corruption(frameStart, fmt.Sprintf("invalid frame length %d", length))
		}

		payload := make([]byte, int(length))
		n, err = io.ReadFull(h.file, payload)
		offset += int64(n)
		if err != nil {
			if errors.Is(err, io.ErrUnexpectedEOF) || errors.Is(err, io.EOF) {
				return h.truncateTail(frameStart)
			}
			return fmt.Errorf("read history event at byte %d: %w", frameStart, err)
		}

		event, err := decodeEvent(payload)
		if err != nil {
			return corruption(frameStart, err.Error())
		}
		expectedSequence := h.head.Sequence + 1
		if event.Sequence != expectedSequence {
			return corruption(frameStart, fmt.Sprintf("sequence %d, want %d", event.Sequence, expectedSequence))
		}
		if event.PreviousHash != h.head.Hash {
			return corruption(frameStart, "previous hash does not match History head")
		}
		if event.Hash != hashEvent(event) {
			return corruption(frameStart, "event hash does not match event data")
		}

		h.events = append(h.events, cloneEvent(event))
		h.head = Head{Sequence: event.Sequence, Hash: event.Hash}
	}

	_, err := h.file.Seek(0, io.SeekEnd)
	return err
}

func decodeEvent(payload []byte) (Event, error) {
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	var stored storedEvent
	if err := decoder.Decode(&stored); err != nil {
		return Event{}, fmt.Errorf("decode event: %w", err)
	}
	if err := ensureJSONEnd(decoder); err != nil {
		return Event{}, err
	}
	if stored.Version != formatVersion {
		return Event{}, fmt.Errorf("unsupported format version %d", stored.Version)
	}
	if stored.Sequence == 0 {
		return Event{}, errors.New("event sequence is zero")
	}
	if stored.Operation == "" {
		return Event{}, errors.New("event operation is empty")
	}
	if !json.Valid(stored.Data) {
		return Event{}, errors.New("event data is invalid JSON")
	}
	if !validHash(stored.PreviousHash) {
		return Event{}, errors.New("previous hash is invalid")
	}
	if !validHash(stored.Hash) {
		return Event{}, errors.New("event hash is invalid")
	}
	return Event{
		Sequence:     stored.Sequence,
		Operation:    stored.Operation,
		Data:         append(json.RawMessage(nil), stored.Data...),
		PreviousHash: stored.PreviousHash,
		Hash:         stored.Hash,
	}, nil
}

func ensureJSONEnd(decoder *json.Decoder) error {
	var extra any
	err := decoder.Decode(&extra)
	if errors.Is(err, io.EOF) {
		return nil
	}
	if err == nil {
		return errors.New("event frame contains multiple JSON values")
	}
	return fmt.Errorf("decode event end: %w", err)
}

func hashEvent(event Event) string {
	hash := sha256.New()
	_, _ = hash.Write([]byte("history-event-v1\x00"))
	var number [8]byte
	binary.BigEndian.PutUint64(number[:], event.Sequence)
	_, _ = hash.Write(number[:])
	writeHashPart(hash, []byte(event.PreviousHash))
	writeHashPart(hash, []byte(event.Operation))
	writeHashPart(hash, event.Data)
	return hex.EncodeToString(hash.Sum(nil))
}

type byteWriter interface {
	Write([]byte) (int, error)
}

func writeHashPart(writer byteWriter, value []byte) {
	var length [8]byte
	binary.BigEndian.PutUint64(length[:], uint64(len(value)))
	_, _ = writer.Write(length[:])
	_, _ = writer.Write(value)
}

func validHash(value string) bool {
	if len(value) != sha256.Size*2 {
		return false
	}
	decoded, err := hex.DecodeString(value)
	return err == nil && hex.EncodeToString(decoded) == value
}

func validPartialHeader(header []byte) bool {
	markerBytes := len(header)
	if markerBytes > len(frameMagic) {
		markerBytes = len(frameMagic)
	}
	return bytes.Equal(header[:markerBytes], frameMagic[:markerBytes])
}

func cloneEvent(event Event) Event {
	event.Data = append(json.RawMessage(nil), event.Data...)
	return event
}

func writeAll(writer io.Writer, data []byte) error {
	for len(data) > 0 {
		n, err := writer.Write(data)
		if err != nil {
			return err
		}
		if n == 0 {
			return io.ErrShortWrite
		}
		data = data[n:]
	}
	return nil
}

func (h *History) truncateTail(offset int64) error {
	if err := h.file.Truncate(offset); err != nil {
		return fmt.Errorf("truncate incomplete final history frame at byte %d: %w", offset, err)
	}
	if err := h.file.Sync(); err != nil {
		return fmt.Errorf("sync truncated history at byte %d: %w", offset, err)
	}
	_, err := h.file.Seek(offset, io.SeekStart)
	return err
}

type appendRecoveryFile interface {
	Truncate(int64) error
	Seek(int64, int) (int64, error)
	Sync() error
}

func (h *History) rollback(offset int64, cause error) error {
	return h.rollbackOn(h.file, offset, cause)
}

// rollbackOn exists as a narrow fault-injection boundary for the three file
// operations required to make a failed Append safe. The caller holds h.mu.
func (h *History) rollbackOn(file appendRecoveryFile, offset int64, cause error) error {
	truncateErr := file.Truncate(offset)
	_, seekErr := file.Seek(offset, io.SeekStart)
	syncErr := file.Sync()
	recoveryErr := errors.Join(truncateErr, seekErr, syncErr)
	if recoveryErr == nil {
		return cause
	}

	// The on-disk end is now uncertain. Never let this instance append beyond
	// it: only Close followed by Open can replay and establish a safe end.
	h.failed = recoveryErr
	return errors.Join(cause, ErrNeedsReopen, recoveryErr)
}

func (h *History) appendStateError() error {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return h.appendStateErrorLocked()
}

func (h *History) appendStateErrorLocked() error {
	if h.closed {
		return ErrClosed
	}
	if h.failed != nil {
		return fmt.Errorf("%w: prior Append recovery failed: %v", ErrNeedsReopen, h.failed)
	}
	return nil
}

func corruption(offset int64, reason string) error {
	return fmt.Errorf("%w at byte %d: %s", ErrCorrupt, offset, reason)
}

func lock(file *os.File) error {
	err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
	if errors.Is(err, syscall.EWOULDBLOCK) || errors.Is(err, syscall.EAGAIN) {
		return ErrLocked
	}
	if err != nil {
		return fmt.Errorf("lock history: %w", err)
	}
	return nil
}

func unlock(file *os.File) error {
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_UN); err != nil {
		return fmt.Errorf("unlock history: %w", err)
	}
	return nil
}

func syncDirectory(path string) error {
	directory, err := os.Open(path)
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}
