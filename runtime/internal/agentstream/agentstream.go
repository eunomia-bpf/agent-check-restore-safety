// Package agentstream records and reconciles the two JSONL byte streams of an
// Agent process across a whole-VM snapshot restore.
//
// The package is deliberately transport independent. Callers carry Hello,
// Attach, Frame, and Barrier values over a trusted framing transport. A
// Transcript accepts only complete JSON object lines, hashes the exact line
// bytes plus their terminating newline, and permits replay only through
// Resend, which returns a peer's missing outgoing suffix.
package agentstream

import (
	"bytes"
	"crypto/sha256"
	"encoding"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"hash"
	"io"
	"sync"
	"unicode/utf8"
)

const maxSessionIDBytes = 128

var (
	ErrConfig       = errors.New("agentstream: invalid configuration")
	ErrRole         = errors.New("agentstream: wrong endpoint role")
	ErrSession      = errors.New("agentstream: session mismatch")
	ErrGeneration   = errors.New("agentstream: generation mismatch")
	ErrDirection    = errors.New("agentstream: direction mismatch")
	ErrOffset       = errors.New("agentstream: offset mismatch")
	ErrHash         = errors.New("agentstream: prefix hash mismatch")
	ErrConflict     = errors.New("agentstream: line conflict")
	ErrInvalidLine  = errors.New("agentstream: invalid JSONL line")
	ErrLineTooLarge = errors.New("agentstream: line too large")
	ErrLimit        = errors.New("agentstream: transcript limit exceeded")
	ErrStaleHello   = errors.New("agentstream: stale hello")
	ErrStaleBarrier = errors.New("agentstream: stale barrier")
	ErrNotQuiescent = errors.New("agentstream: transcript is not quiescent")
)

// Role identifies which side owns a Transcript. A Host originates
// HostToGuest lines; a Guest originates GuestToHost lines.
type Role uint8

const (
	Host Role = iota + 1
	Guest
)

// Direction identifies one half of the duplex transcript.
type Direction uint8

const (
	HostToGuest Direction = iota + 1
	GuestToHost
)

// Limits bounds one complete duplex transcript. MaxLineBytes excludes the
// mandatory newline. MaxBytes includes one newline for every line. MaxLines
// and MaxBytes are aggregate limits across both directions.
type Limits struct {
	MaxLineBytes uint64 `json:"max_line_bytes"`
	MaxLines     uint64 `json:"max_lines"`
	MaxBytes     uint64 `json:"max_bytes"`
}

// Digest is a SHA-256 digest. Its text form is exactly 64 lowercase
// hexadecimal characters, which also gives protocol encoders a canonical
// representation.
type Digest [sha256.Size]byte

func (digest Digest) String() string { return hex.EncodeToString(digest[:]) }

func (digest Digest) MarshalText() ([]byte, error) {
	encoded := make([]byte, hex.EncodedLen(len(digest)))
	hex.Encode(encoded, digest[:])
	return encoded, nil
}

func (digest *Digest) UnmarshalText(encoded []byte) error {
	if digest == nil {
		return fmt.Errorf("%w: nil digest", ErrHash)
	}
	if len(encoded) != sha256.Size*2 || !isLowerHex(encoded) {
		return fmt.Errorf("%w: digest must be 64 lowercase hexadecimal characters", ErrHash)
	}
	var decoded Digest
	if _, err := hex.Decode(decoded[:], encoded); err != nil {
		return fmt.Errorf("%w: %v", ErrHash, err)
	}
	*digest = decoded
	return nil
}

// Position names one prefix of one directional transcript. Offset is both the
// number of complete lines in the prefix and the offset of its next line.
// Bytes counts the exact payload bytes plus one newline per line. Hash is
// SHA-256 over those Bytes.
type Position struct {
	Offset uint64 `json:"offset"`
	Bytes  uint64 `json:"bytes"`
	Hash   Digest `json:"hash"`
}

// State records both directional transcript positions.
type State struct {
	HostToGuest Position `json:"host_to_guest"`
	GuestToHost Position `json:"guest_to_host"`
}

// Hello is the Guest's first attach message.
type Hello struct {
	SessionID  string `json:"session_id"`
	Generation uint64 `json:"generation"`
	State      State  `json:"state"`
}

// Attach is the Host's response to a validated Hello.
type Attach struct {
	SessionID  string `json:"session_id"`
	Generation uint64 `json:"generation"`
	State      State  `json:"state"`
}

// Barrier is a point-in-time assertion of both transcript positions. A
// snapshot is safe at this layer only after both endpoints exchange Barriers
// and each endpoint obtains Quiescent=true.
type Barrier struct {
	SessionID  string `json:"session_id"`
	Generation uint64 `json:"generation"`
	State      State  `json:"state"`
}

// Frame carries exactly one JSON object line without its trailing newline.
// Before and After make gaps, overlaps, byte-count mutations, and hash
// mutations independently rejectable.
type Frame struct {
	SessionID  string    `json:"session_id"`
	Generation uint64    `json:"generation"`
	Direction  Direction `json:"direction"`
	Before     Position  `json:"before"`
	After      Position  `json:"after"`
	Line       []byte    `json:"line"`
}

// ReceiveResult distinguishes a newly appended line from an identical replay
// of a line already present at that offset.
type ReceiveResult uint8

const (
	Received ReceiveResult = iota + 1
	Duplicate
)

// Transcript is a concurrency-safe, in-memory transcript state machine.
// Invalid input never partially mutates it.
type Transcript struct {
	mu         sync.Mutex
	role       Role
	sessionID  string
	generation uint64
	limits     Limits
	host       directionLog
	guest      directionLog
}

type directionLog struct {
	lines     [][]byte
	positions []Position
	hasher    hash.Hash
}

// New constructs an empty transcript. Session IDs are intentionally limited
// to a small printable token alphabet so they can be logged and framed without
// ambiguity. Generation zero is never valid.
func New(role Role, sessionID string, generation uint64, limits Limits) (*Transcript, error) {
	if role != Host && role != Guest {
		return nil, fmt.Errorf("%w: unknown role %d", ErrConfig, role)
	}
	if err := validateSessionID(sessionID); err != nil {
		return nil, err
	}
	if generation == 0 {
		return nil, fmt.Errorf("%w: generation must be positive", ErrConfig)
	}
	if limits.MaxLineBytes == 0 || limits.MaxLines == 0 || limits.MaxBytes == 0 {
		return nil, fmt.Errorf("%w: every limit must be positive", ErrConfig)
	}
	empty := Position{Hash: Digest(sha256.Sum256(nil))}
	return &Transcript{
		role:       role,
		sessionID:  sessionID,
		generation: generation,
		limits:     limits,
		host: directionLog{
			positions: []Position{empty},
			hasher:    sha256.New(),
		},
		guest: directionLog{
			positions: []Position{empty},
			hasher:    sha256.New(),
		},
	}, nil
}

// State returns an immutable value describing the current transcript ends.
func (transcript *Transcript) State() State {
	transcript.mu.Lock()
	defer transcript.mu.Unlock()
	return transcript.stateLocked()
}

// Hello creates the Guest's attach request.
func (transcript *Transcript) Hello() (Hello, error) {
	transcript.mu.Lock()
	defer transcript.mu.Unlock()
	if transcript.role != Guest {
		return Hello{}, fmt.Errorf("%w: only Guest creates Hello", ErrRole)
	}
	return Hello{
		SessionID: transcript.sessionID, Generation: transcript.generation,
		State: transcript.stateLocked(),
	}, nil
}

// Attach validates a Guest Hello and returns the Host's current positions.
// A Guest cannot claim HostToGuest lines the Host has never sent, and the Host
// cannot be ahead in GuestToHost because it cannot replay Guest-originated
// lines. Thus HostToGuest may need a Host resend, while GuestToHost may need a
// Guest resend; the opposite direction is rejected instead of stranded.
func (transcript *Transcript) Attach(hello Hello) (Attach, error) {
	transcript.mu.Lock()
	defer transcript.mu.Unlock()
	if transcript.role != Host {
		return Attach{}, fmt.Errorf("%w: only Host accepts Hello", ErrRole)
	}
	if err := transcript.validateIdentityLocked(hello.SessionID, hello.Generation); err != nil {
		return Attach{}, err
	}
	if err := transcript.validateStateBoundsLocked(hello.State); err != nil {
		return Attach{}, err
	}
	local := transcript.stateLocked()
	if hello.State.HostToGuest.Offset > local.HostToGuest.Offset {
		return Attach{}, fmt.Errorf("%w: Guest claims unsent HostToGuest offset %d beyond %d", ErrOffset, hello.State.HostToGuest.Offset, local.HostToGuest.Offset)
	}
	if err := transcript.validateKnownPrefixLocked(HostToGuest, hello.State.HostToGuest); err != nil {
		return Attach{}, err
	}
	if hello.State.GuestToHost.Offset < local.GuestToHost.Offset {
		return Attach{}, fmt.Errorf("%w: GuestToHost offset %d is behind Host offset %d and cannot be replayed by Host", ErrOffset, hello.State.GuestToHost.Offset, local.GuestToHost.Offset)
	}
	if err := transcript.validateOverlapLocked(GuestToHost, hello.State.GuestToHost); err != nil {
		return Attach{}, err
	}
	return Attach{
		SessionID: transcript.sessionID, Generation: transcript.generation,
		State: local,
	}, nil
}

// AcceptAttach validates a Host reply against the exact Hello sent by this
// Guest. If the Guest transcript moved after Hello, the handshake is stale and
// must start again.
func (transcript *Transcript) AcceptAttach(hello Hello, attach Attach) error {
	transcript.mu.Lock()
	defer transcript.mu.Unlock()
	if transcript.role != Guest {
		return fmt.Errorf("%w: only Guest accepts Attach", ErrRole)
	}
	if err := transcript.validateIdentityLocked(hello.SessionID, hello.Generation); err != nil {
		return err
	}
	if hello.State != transcript.stateLocked() {
		return ErrStaleHello
	}
	if err := transcript.validateIdentityLocked(attach.SessionID, attach.Generation); err != nil {
		return err
	}
	if err := transcript.validateStateBoundsLocked(attach.State); err != nil {
		return err
	}
	if attach.State.HostToGuest.Offset < hello.State.HostToGuest.Offset {
		return fmt.Errorf("%w: Host forgot acknowledged HostToGuest lines", ErrOffset)
	}
	if err := transcript.validateOverlapLocked(HostToGuest, attach.State.HostToGuest); err != nil {
		return err
	}
	if attach.State.GuestToHost.Offset > hello.State.GuestToHost.Offset {
		return fmt.Errorf("%w: Host GuestToHost offset %d is ahead of Guest offset %d and cannot be replayed by Host", ErrOffset, attach.State.GuestToHost.Offset, hello.State.GuestToHost.Offset)
	}
	return transcript.validateOverlapLocked(GuestToHost, attach.State.GuestToHost)
}

// Send appends one locally originated line and returns its frame. Line must be
// a complete JSON object without a trailing newline. The returned Line is a
// copy and may be modified by the caller.
func (transcript *Transcript) Send(line []byte) (Frame, error) {
	transcript.mu.Lock()
	defer transcript.mu.Unlock()
	direction := transcript.outgoingDirectionLocked()
	if err := transcript.validateLineLocked(line); err != nil {
		return Frame{}, err
	}
	if err := transcript.validateNewLineBudgetLocked(uint64(len(line)) + 1); err != nil {
		return Frame{}, err
	}
	log := transcript.logLocked(direction)
	before := log.end()
	nextHasher, afterHash, err := hashNext(log.hasher, line)
	if err != nil {
		return Frame{}, err
	}
	after := Position{
		Offset: before.Offset + 1,
		Bytes:  before.Bytes + uint64(len(line)) + 1,
		Hash:   afterHash,
	}
	stored := bytes.Clone(line)
	log.lines = append(log.lines, stored)
	log.positions = append(log.positions, after)
	log.hasher = nextHasher
	return transcript.frameLocked(direction, len(log.lines)-1), nil
}

// Receive accepts one peer-originated frame. It appends only the exact next
// offset or accepts an exact duplicate of an already stored line. Gaps and
// conflicting overlap are rejected without changing the transcript.
func (transcript *Transcript) Receive(frame Frame) (ReceiveResult, error) {
	transcript.mu.Lock()
	defer transcript.mu.Unlock()
	if err := transcript.validateIdentityLocked(frame.SessionID, frame.Generation); err != nil {
		return 0, err
	}
	wantDirection := transcript.incomingDirectionLocked()
	if frame.Direction != wantDirection {
		return 0, fmt.Errorf("%w: got %d, want %d", ErrDirection, frame.Direction, wantDirection)
	}
	if err := transcript.validateLineLocked(frame.Line); err != nil {
		return 0, err
	}
	if err := transcript.validateFrameShapeLocked(frame); err != nil {
		return 0, err
	}
	log := transcript.logLocked(frame.Direction)
	end := log.end()
	if frame.Before.Offset > end.Offset {
		return 0, fmt.Errorf("%w: frame starts at %d after local end %d", ErrOffset, frame.Before.Offset, end.Offset)
	}
	if frame.Before.Offset < end.Offset {
		index := int(frame.Before.Offset)
		if frame.Before != log.positions[index] {
			return 0, positionDifference(frame.Before, log.positions[index])
		}
		if !bytes.Equal(frame.Line, log.lines[index]) {
			return 0, fmt.Errorf("%w at %s offset %d", ErrConflict, directionName(frame.Direction), frame.Before.Offset)
		}
		if frame.After != log.positions[index+1] {
			return 0, positionDifference(frame.After, log.positions[index+1])
		}
		return Duplicate, nil
	}
	if frame.Before != end {
		return 0, positionDifference(frame.Before, end)
	}
	if err := transcript.validateNewLineBudgetLocked(uint64(len(frame.Line)) + 1); err != nil {
		return 0, err
	}
	nextHasher, afterHash, err := hashNext(log.hasher, frame.Line)
	if err != nil {
		return 0, err
	}
	expectedAfter := Position{
		Offset: end.Offset + 1,
		Bytes:  end.Bytes + uint64(len(frame.Line)) + 1,
		Hash:   afterHash,
	}
	if frame.After != expectedAfter {
		return 0, positionDifference(frame.After, expectedAfter)
	}
	log.lines = append(log.lines, bytes.Clone(frame.Line))
	log.positions = append(log.positions, expectedAfter)
	log.hasher = nextHasher
	return Received, nil
}

// Resend returns only the missing suffix of the caller's outgoing direction.
// peer must name an exact locally known prefix. There is intentionally no API
// for replaying an arbitrary range or replacing an existing prefix.
func (transcript *Transcript) Resend(peer Position) ([]Frame, error) {
	transcript.mu.Lock()
	defer transcript.mu.Unlock()
	direction := transcript.outgoingDirectionLocked()
	log := transcript.logLocked(direction)
	if peer.Offset > log.end().Offset {
		return nil, fmt.Errorf("%w: peer offset %d beyond outgoing end %d", ErrOffset, peer.Offset, log.end().Offset)
	}
	if err := transcript.validateKnownPrefixLocked(direction, peer); err != nil {
		return nil, err
	}
	frames := make([]Frame, 0, log.end().Offset-peer.Offset)
	for index := peer.Offset; index < log.end().Offset; index++ {
		frames = append(frames, transcript.frameLocked(direction, int(index)))
	}
	return frames, nil
}

// Barrier captures the current transcript positions.
func (transcript *Transcript) Barrier() Barrier {
	transcript.mu.Lock()
	defer transcript.mu.Unlock()
	return Barrier{
		SessionID: transcript.sessionID, Generation: transcript.generation,
		State: transcript.stateLocked(),
	}
}

// Quiescent validates two exchanged Barriers. ours must still describe this
// endpoint's current state. It returns true only when both endpoints confirm
// exactly the same offsets, byte counts, and hashes in both directions.
func (transcript *Transcript) Quiescent(ours, peer Barrier) (bool, error) {
	transcript.mu.Lock()
	defer transcript.mu.Unlock()
	return transcript.quiescentLocked(ours, peer)
}

// AdvanceGeneration moves a quiescent transcript to a strictly newer VM
// generation. Both old-generation Barriers are required so a restored Guest
// cannot silently relabel an unacknowledged stream. A failed transition leaves
// the generation unchanged.
func (transcript *Transcript) AdvanceGeneration(next uint64, ours, peer Barrier) error {
	transcript.mu.Lock()
	defer transcript.mu.Unlock()
	if next == 0 || next <= transcript.generation {
		return fmt.Errorf("%w: next generation %d must be greater than %d", ErrGeneration, next, transcript.generation)
	}
	quiescent, err := transcript.quiescentLocked(ours, peer)
	if err != nil {
		return err
	}
	if !quiescent {
		return ErrNotQuiescent
	}
	transcript.generation = next
	return nil
}

func (transcript *Transcript) quiescentLocked(ours, peer Barrier) (bool, error) {
	if err := transcript.validateIdentityLocked(ours.SessionID, ours.Generation); err != nil {
		return false, err
	}
	if ours.State != transcript.stateLocked() {
		return false, ErrStaleBarrier
	}
	if err := transcript.validateIdentityLocked(peer.SessionID, peer.Generation); err != nil {
		return false, err
	}
	if err := transcript.validateStateBoundsLocked(peer.State); err != nil {
		return false, err
	}
	if err := transcript.validateOverlapLocked(HostToGuest, peer.State.HostToGuest); err != nil {
		return false, err
	}
	if err := transcript.validateOverlapLocked(GuestToHost, peer.State.GuestToHost); err != nil {
		return false, err
	}
	return peer.State == transcript.stateLocked(), nil
}

func (transcript *Transcript) stateLocked() State {
	return State{HostToGuest: transcript.host.end(), GuestToHost: transcript.guest.end()}
}

func (transcript *Transcript) outgoingDirectionLocked() Direction {
	if transcript.role == Host {
		return HostToGuest
	}
	return GuestToHost
}

func (transcript *Transcript) incomingDirectionLocked() Direction {
	if transcript.role == Host {
		return GuestToHost
	}
	return HostToGuest
}

func (transcript *Transcript) logLocked(direction Direction) *directionLog {
	if direction == HostToGuest {
		return &transcript.host
	}
	return &transcript.guest
}

func (transcript *Transcript) frameLocked(direction Direction, index int) Frame {
	log := transcript.logLocked(direction)
	return Frame{
		SessionID: transcript.sessionID, Generation: transcript.generation,
		Direction: direction, Before: log.positions[index], After: log.positions[index+1],
		Line: bytes.Clone(log.lines[index]),
	}
}

func (transcript *Transcript) validateIdentityLocked(sessionID string, generation uint64) error {
	if sessionID != transcript.sessionID {
		return fmt.Errorf("%w: got %q, want %q", ErrSession, sessionID, transcript.sessionID)
	}
	if generation != transcript.generation {
		return fmt.Errorf("%w: got %d, want %d", ErrGeneration, generation, transcript.generation)
	}
	return nil
}

func (transcript *Transcript) validateStateBoundsLocked(state State) error {
	if err := transcript.validatePositionBoundsLocked(state.HostToGuest); err != nil {
		return fmt.Errorf("HostToGuest: %w", err)
	}
	if err := transcript.validatePositionBoundsLocked(state.GuestToHost); err != nil {
		return fmt.Errorf("GuestToHost: %w", err)
	}
	if state.HostToGuest.Offset > transcript.limits.MaxLines-state.GuestToHost.Offset {
		return fmt.Errorf("%w: aggregate line count exceeds %d", ErrLimit, transcript.limits.MaxLines)
	}
	if state.HostToGuest.Bytes > transcript.limits.MaxBytes-state.GuestToHost.Bytes {
		return fmt.Errorf("%w: aggregate byte count exceeds %d", ErrLimit, transcript.limits.MaxBytes)
	}
	return nil
}

func (transcript *Transcript) validatePositionBoundsLocked(position Position) error {
	if position.Offset > transcript.limits.MaxLines {
		return fmt.Errorf("%w: line offset %d exceeds %d", ErrLimit, position.Offset, transcript.limits.MaxLines)
	}
	if position.Bytes > transcript.limits.MaxBytes {
		return fmt.Errorf("%w: byte offset %d exceeds %d", ErrLimit, position.Bytes, transcript.limits.MaxBytes)
	}
	emptyHash := Digest(sha256.Sum256(nil))
	if position.Offset == 0 {
		if position.Bytes != 0 {
			return fmt.Errorf("%w: empty prefix has %d bytes", ErrOffset, position.Bytes)
		}
		if position.Hash != emptyHash {
			return fmt.Errorf("%w: empty prefix digest differs", ErrHash)
		}
		return nil
	}
	// The shortest accepted line is "{}\n". Reject positions that cannot
	// possibly describe a sequence of accepted JSON object lines, even when
	// the position is beyond the locally known prefix.
	if position.Offset > ^uint64(0)/3 || position.Bytes < position.Offset*3 {
		return fmt.Errorf("%w: %d lines cannot occupy %d bytes", ErrOffset, position.Offset, position.Bytes)
	}
	if transcript.limits.MaxLineBytes != ^uint64(0) {
		maximumLineBytes := transcript.limits.MaxLineBytes + 1
		if position.Offset <= ^uint64(0)/maximumLineBytes && position.Bytes > position.Offset*maximumLineBytes {
			return fmt.Errorf("%w: %d lines cannot occupy %d bytes with a %d-byte line limit", ErrLimit, position.Offset, position.Bytes, transcript.limits.MaxLineBytes)
		}
	}
	return nil
}

func (transcript *Transcript) validateKnownPrefixLocked(direction Direction, position Position) error {
	if err := transcript.validatePositionBoundsLocked(position); err != nil {
		return err
	}
	log := transcript.logLocked(direction)
	if position.Offset > log.end().Offset {
		return fmt.Errorf("%w: %s prefix %d beyond %d", ErrOffset, directionName(direction), position.Offset, log.end().Offset)
	}
	return comparePosition(position, log.positions[int(position.Offset)])
}

func (transcript *Transcript) validateOverlapLocked(direction Direction, remote Position) error {
	if err := transcript.validatePositionBoundsLocked(remote); err != nil {
		return err
	}
	log := transcript.logLocked(direction)
	local := log.end()
	if remote.Offset <= local.Offset {
		return comparePosition(remote, log.positions[int(remote.Offset)])
	}
	if remote.Bytes <= local.Bytes {
		return fmt.Errorf("%w: longer %s prefix has non-increasing byte count", ErrOffset, directionName(direction))
	}
	return nil
}

func (transcript *Transcript) validateLineLocked(line []byte) error {
	if uint64(len(line)) > transcript.limits.MaxLineBytes {
		return fmt.Errorf("%w: %d bytes exceeds %d", ErrLineTooLarge, len(line), transcript.limits.MaxLineBytes)
	}
	return validateJSONObjectLine(line)
}

func (transcript *Transcript) validateNewLineBudgetLocked(lineBytes uint64) error {
	state := transcript.stateLocked()
	if state.HostToGuest.Offset > ^uint64(0)-state.GuestToHost.Offset ||
		state.HostToGuest.Offset+state.GuestToHost.Offset >= transcript.limits.MaxLines {
		return fmt.Errorf("%w: maximum line count %d reached", ErrLimit, transcript.limits.MaxLines)
	}
	if state.HostToGuest.Bytes > ^uint64(0)-state.GuestToHost.Bytes {
		return fmt.Errorf("%w: byte count overflow", ErrLimit)
	}
	total := state.HostToGuest.Bytes + state.GuestToHost.Bytes
	if lineBytes > transcript.limits.MaxBytes || total > transcript.limits.MaxBytes-lineBytes {
		return fmt.Errorf("%w: maximum byte count %d exceeded", ErrLimit, transcript.limits.MaxBytes)
	}
	return nil
}

func (transcript *Transcript) validateFrameShapeLocked(frame Frame) error {
	if err := transcript.validatePositionBoundsLocked(frame.Before); err != nil {
		return fmt.Errorf("frame before: %w", err)
	}
	if err := transcript.validatePositionBoundsLocked(frame.After); err != nil {
		return fmt.Errorf("frame after: %w", err)
	}
	if frame.Before.Offset == ^uint64(0) || frame.After.Offset != frame.Before.Offset+1 {
		return fmt.Errorf("%w: frame offsets %d -> %d", ErrOffset, frame.Before.Offset, frame.After.Offset)
	}
	lineBytes := uint64(len(frame.Line)) + 1
	if frame.Before.Bytes > ^uint64(0)-lineBytes || frame.After.Bytes != frame.Before.Bytes+lineBytes {
		return fmt.Errorf("%w: frame bytes %d -> %d for %d-byte line", ErrOffset, frame.Before.Bytes, frame.After.Bytes, len(frame.Line))
	}
	return nil
}

func (log *directionLog) end() Position { return log.positions[len(log.positions)-1] }

func hashNext(current hash.Hash, line []byte) (hash.Hash, Digest, error) {
	marshaler, ok := current.(encoding.BinaryMarshaler)
	if !ok {
		return nil, Digest{}, fmt.Errorf("%w: SHA-256 state is not serializable", ErrConfig)
	}
	state, err := marshaler.MarshalBinary()
	if err != nil {
		return nil, Digest{}, fmt.Errorf("%w: marshal SHA-256 state: %v", ErrConfig, err)
	}
	next := sha256.New()
	unmarshaler, ok := next.(encoding.BinaryUnmarshaler)
	if !ok {
		return nil, Digest{}, fmt.Errorf("%w: SHA-256 state is not restorable", ErrConfig)
	}
	if err := unmarshaler.UnmarshalBinary(state); err != nil {
		return nil, Digest{}, fmt.Errorf("%w: restore SHA-256 state: %v", ErrConfig, err)
	}
	_, _ = next.Write(line)
	_, _ = next.Write([]byte{'\n'})
	var digest Digest
	copy(digest[:], next.Sum(nil))
	return next, digest, nil
}

func comparePosition(actual, expected Position) error {
	if actual.Offset != expected.Offset || actual.Bytes != expected.Bytes {
		return positionDifference(actual, expected)
	}
	if actual.Hash != expected.Hash {
		return fmt.Errorf("%w at offset %d", ErrHash, expected.Offset)
	}
	return nil
}

func positionDifference(actual, expected Position) error {
	if actual.Offset != expected.Offset || actual.Bytes != expected.Bytes {
		return fmt.Errorf("%w: got offset/bytes %d/%d, want %d/%d", ErrOffset, actual.Offset, actual.Bytes, expected.Offset, expected.Bytes)
	}
	return fmt.Errorf("%w at offset %d", ErrHash, expected.Offset)
}

func validateJSONObjectLine(line []byte) error {
	if len(line) == 0 {
		return fmt.Errorf("%w: line is empty", ErrInvalidLine)
	}
	if bytes.IndexByte(line, '\n') >= 0 || bytes.IndexByte(line, '\r') >= 0 {
		return fmt.Errorf("%w: line contains CR or LF", ErrInvalidLine)
	}
	if !utf8.Valid(line) {
		return fmt.Errorf("%w: line is not valid UTF-8", ErrInvalidLine)
	}
	decoder := json.NewDecoder(bytes.NewReader(line))
	decoder.UseNumber()
	first, err := decoder.Token()
	if err != nil {
		return fmt.Errorf("%w: %v", ErrInvalidLine, err)
	}
	opening, ok := first.(json.Delim)
	if !ok || opening != '{' {
		return fmt.Errorf("%w: line must be one JSON object", ErrInvalidLine)
	}
	if err := validateJSONObject(decoder); err != nil {
		return err
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return fmt.Errorf("%w: trailing JSON value %v", ErrInvalidLine, token)
		}
		return fmt.Errorf("%w: trailing data: %v", ErrInvalidLine, err)
	}
	return nil
}

// validateJSONObject validates the rest of an object after its opening token.
// It walks nested values rather than decoding into a map so duplicate keys at
// every depth remain observable and rejectable.
func validateJSONObject(decoder *json.Decoder) error {
	seen := make(map[string]struct{})
	for decoder.More() {
		keyToken, err := decoder.Token()
		if err != nil {
			return fmt.Errorf("%w: %v", ErrInvalidLine, err)
		}
		key, ok := keyToken.(string)
		if !ok {
			return fmt.Errorf("%w: object key is not a string", ErrInvalidLine)
		}
		if _, duplicate := seen[key]; duplicate {
			return fmt.Errorf("%w: duplicate object key %q", ErrInvalidLine, key)
		}
		seen[key] = struct{}{}
		if err := validateJSONValue(decoder); err != nil {
			return fmt.Errorf("field %q: %w", key, err)
		}
	}
	closing, err := decoder.Token()
	if err != nil {
		return fmt.Errorf("%w: %v", ErrInvalidLine, err)
	}
	if delimiter, ok := closing.(json.Delim); !ok || delimiter != '}' {
		return fmt.Errorf("%w: object is not closed", ErrInvalidLine)
	}
	return nil
}

func validateJSONValue(decoder *json.Decoder) error {
	token, err := decoder.Token()
	if err != nil {
		return fmt.Errorf("%w: %v", ErrInvalidLine, err)
	}
	delimiter, compound := token.(json.Delim)
	if !compound {
		return nil
	}
	switch delimiter {
	case '{':
		return validateJSONObject(decoder)
	case '[':
		for decoder.More() {
			if err := validateJSONValue(decoder); err != nil {
				return err
			}
		}
		closing, err := decoder.Token()
		if err != nil {
			return fmt.Errorf("%w: %v", ErrInvalidLine, err)
		}
		if closeDelimiter, ok := closing.(json.Delim); !ok || closeDelimiter != ']' {
			return fmt.Errorf("%w: array is not closed", ErrInvalidLine)
		}
		return nil
	default:
		return fmt.Errorf("%w: unexpected delimiter %q", ErrInvalidLine, delimiter)
	}
}

func validateSessionID(sessionID string) error {
	if len(sessionID) == 0 || len(sessionID) > maxSessionIDBytes {
		return fmt.Errorf("%w: session ID must contain 1 to %d bytes", ErrConfig, maxSessionIDBytes)
	}
	for _, character := range []byte(sessionID) {
		if (character >= 'a' && character <= 'z') ||
			(character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') ||
			character == '-' || character == '_' || character == '.' || character == ':' {
			continue
		}
		return fmt.Errorf("%w: session ID contains byte %#x", ErrConfig, character)
	}
	return nil
}

func directionName(direction Direction) string {
	if direction == HostToGuest {
		return "HostToGuest"
	}
	if direction == GuestToHost {
		return "GuestToHost"
	}
	return fmt.Sprintf("Direction(%d)", direction)
}

func isLowerHex(encoded []byte) bool {
	for _, character := range encoded {
		if (character >= '0' && character <= '9') || (character >= 'a' && character <= 'f') {
			continue
		}
		return false
	}
	return true
}
