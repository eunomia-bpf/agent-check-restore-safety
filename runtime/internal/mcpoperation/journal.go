package mcpoperation

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
)

const (
	JournalSchema        = 1
	journalEventPrepare  = "prepared"
	journalEventComplete = "completed"
	maxJournalLineBytes  = (MaxMessageBytes * 2) + (64 << 10)
)

type Journal struct {
	mu          sync.Mutex
	file        *os.File
	executionID string
	recordSeq   uint64
	callSeq     uint64
	headHash    string
	calls       map[string]journalCall
	pendingID   string
	fenced      bool
	closed      bool
}

type journalCall struct {
	RPCID     string
	Digest    string
	CallID    string
	Sequence  uint64
	Response  []byte
	Completed bool
	Uncertain bool
}

type journalRecord struct {
	Schema         int    `json:"schema"`
	RecordSequence uint64 `json:"record_sequence"`
	CallSequence   uint64 `json:"call_sequence"`
	Event          string `json:"event"`
	ExecutionID    string `json:"execution_id"`
	RPCID          string `json:"rpc_id"`
	RequestDigest  string `json:"request_digest"`
	CallID         string `json:"call_id"`
	Response       []byte `json:"response,omitempty"`
	Uncertain      bool   `json:"uncertain"`
	PreviousHash   string `json:"previous_hash,omitempty"`
	Hash           string `json:"hash"`
}

type journalPayload struct {
	Schema         int    `json:"schema"`
	RecordSequence uint64 `json:"record_sequence"`
	CallSequence   uint64 `json:"call_sequence"`
	Event          string `json:"event"`
	ExecutionID    string `json:"execution_id"`
	RPCID          string `json:"rpc_id"`
	RequestDigest  string `json:"request_digest"`
	CallID         string `json:"call_id"`
	Response       []byte `json:"response,omitempty"`
	Uncertain      bool   `json:"uncertain"`
	PreviousHash   string `json:"previous_hash,omitempty"`
}

func OpenJournal(path, executionID string) (*Journal, error) {
	if !validName(executionID, MaxExecutionIDSize) {
		return nil, fmt.Errorf("execution identity must contain 1 to %d safe name bytes", MaxExecutionIDSize)
	}
	if path == "" || !filepath.IsAbs(path) || filepath.Clean(path) != path || strings.ContainsAny(path, "\x00\r\n") {
		return nil, errors.New("MCP call journal path must be absolute and canonical")
	}
	parent := filepath.Dir(path)
	parentInfo, err := os.Lstat(parent)
	if err != nil {
		return nil, fmt.Errorf("inspect MCP call journal parent: %w", err)
	}
	resolvedParent, err := filepath.EvalSymlinks(parent)
	if err != nil || resolvedParent != parent || !parentInfo.IsDir() || parentInfo.Mode()&os.ModeSymlink != 0 || parentInfo.Mode().Perm() != 0o700 || !ownedByCurrentUser(parentInfo) {
		return nil, errors.New("MCP call journal parent must be a current-user direct directory with mode 0700")
	}
	pathInfo, statErr := os.Lstat(path)
	created := errors.Is(statErr, os.ErrNotExist)
	if statErr != nil && !created {
		return nil, statErr
	}
	if !created && (!pathInfo.Mode().IsRegular() || pathInfo.Mode().Perm() != 0o600 || !ownedByCurrentUser(pathInfo)) {
		return nil, errors.New("MCP call journal must be a current-user direct regular file with mode 0600")
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR|os.O_APPEND, 0o600)
	if err != nil {
		return nil, err
	}
	fail := func(cause error) (*Journal, error) {
		_ = file.Close()
		return nil, cause
	}
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return fail(fmt.Errorf("lock MCP call journal: %w", err))
	}
	opened, err := file.Stat()
	if err != nil || !opened.Mode().IsRegular() || opened.Mode().Perm() != 0o600 || !ownedByCurrentUser(opened) || (!created && !os.SameFile(pathInfo, opened)) {
		return fail(errors.New("MCP call journal changed while it was opened"))
	}
	if created {
		directory, err := os.Open(parent)
		if err != nil {
			return fail(err)
		}
		syncErr := directory.Sync()
		closeErr := directory.Close()
		if syncErr != nil || closeErr != nil {
			return fail(errors.Join(syncErr, closeErr))
		}
	}
	journal := &Journal{
		file: file, executionID: executionID, calls: make(map[string]journalCall),
	}
	if err := journal.replay(); err != nil {
		return fail(err)
	}
	return journal, nil
}

func (journal *Journal) replay() error {
	if _, err := journal.file.Seek(0, io.SeekStart); err != nil {
		return err
	}
	scanner := bufio.NewScanner(journal.file)
	scanner.Buffer(make([]byte, 64<<10), maxJournalLineBytes)
	for scanner.Scan() {
		line := append([]byte(nil), scanner.Bytes()...)
		if len(line) == 0 {
			return errors.New("MCP call journal contains an empty record")
		}
		if err := rejectDuplicateJSONNames(line); err != nil {
			return fmt.Errorf("decode MCP call journal record: %w", err)
		}
		var record journalRecord
		if err := decodeStrictJSON(line, &record); err != nil {
			return fmt.Errorf("decode MCP call journal record: %w", err)
		}
		if err := journal.applyRecord(record); err != nil {
			return err
		}
	}
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("scan MCP call journal: %w", err)
	}
	_, err := journal.file.Seek(0, io.SeekEnd)
	return err
}

func (journal *Journal) applyRecord(record journalRecord) error {
	if record.Schema != JournalSchema || record.RecordSequence != journal.recordSeq+1 || record.ExecutionID != journal.executionID ||
		record.RPCID == "" || len(record.RPCID) > 2048 || !validDigest(record.RequestDigest) ||
		record.CallSequence == 0 || record.CallID != journalCallIdentity(record.ExecutionID, record.CallSequence) ||
		record.PreviousHash != journal.headHash || record.Hash != hashJournalRecord(record) {
		return fmt.Errorf("MCP call journal record %d violates its hash chain or identity binding", record.RecordSequence)
	}
	prior, exists := journal.calls[record.RPCID]
	switch record.Event {
	case journalEventPrepare:
		if exists || journal.pendingID != "" || journal.fenced || record.CallSequence != journal.callSeq+1 || len(record.Response) != 0 || record.Uncertain {
			return fmt.Errorf("MCP call journal prepare record %d has invalid lifecycle order", record.RecordSequence)
		}
		journal.callSeq = record.CallSequence
		journal.pendingID = record.RPCID
		journal.calls[record.RPCID] = journalCall{
			RPCID: record.RPCID, Digest: record.RequestDigest, CallID: record.CallID, Sequence: record.CallSequence,
		}
	case journalEventComplete:
		if !exists || prior.Completed || journal.pendingID != record.RPCID || prior.Digest != record.RequestDigest ||
			prior.CallID != record.CallID || prior.Sequence != record.CallSequence || len(record.Response) == 0 || len(record.Response) > MaxMessageBytes {
			return fmt.Errorf("MCP call journal completion record %d has invalid lifecycle order", record.RecordSequence)
		}
		prior.Completed = true
		prior.Response = append([]byte(nil), record.Response...)
		prior.Uncertain = record.Uncertain
		journal.calls[record.RPCID] = prior
		journal.pendingID = ""
		journal.fenced = record.Uncertain
	default:
		return fmt.Errorf("MCP call journal record %d has unknown event %q", record.RecordSequence, record.Event)
	}
	journal.recordSeq = record.RecordSequence
	journal.headHash = record.Hash
	return nil
}

func (journal *Journal) Lookup(rpcID, digest string) (journalCall, bool, error) {
	journal.mu.Lock()
	defer journal.mu.Unlock()
	if journal.closed {
		return journalCall{}, false, errors.New("MCP call journal is closed")
	}
	call, exists := journal.calls[rpcID]
	if exists && call.Digest != digest {
		return journalCall{}, true, errors.New("JSON-RPC identity was reused for a different protected call")
	}
	call.Response = append([]byte(nil), call.Response...)
	return call, exists, nil
}

func (journal *Journal) Prepare(rpcID, digest string) (journalCall, error) {
	journal.mu.Lock()
	defer journal.mu.Unlock()
	if journal.closed {
		return journalCall{}, errors.New("MCP call journal is closed")
	}
	if journal.fenced {
		return journalCall{}, errors.New("MCP call journal is fenced")
	}
	if journal.pendingID != "" {
		return journalCall{}, fmt.Errorf("MCP call journal has pending request %s", journal.pendingID)
	}
	if _, exists := journal.calls[rpcID]; exists {
		return journalCall{}, errors.New("JSON-RPC identity is already recorded")
	}
	if rpcID == "" || len(rpcID) > 2048 || !validDigest(digest) {
		return journalCall{}, errors.New("MCP call journal received an invalid request identity or digest")
	}
	callSequence := journal.callSeq + 1
	call := journalCall{
		RPCID: rpcID, Digest: digest, Sequence: callSequence,
		CallID: journalCallIdentity(journal.executionID, callSequence),
	}
	record := journal.newRecord(journalEventPrepare, call, nil, false)
	if err := journal.append(record); err != nil {
		return journalCall{}, err
	}
	journal.callSeq = callSequence
	journal.pendingID = rpcID
	journal.calls[rpcID] = call
	return call, nil
}

func (journal *Journal) Complete(call journalCall, response []byte, uncertain bool) error {
	journal.mu.Lock()
	defer journal.mu.Unlock()
	if journal.closed {
		return errors.New("MCP call journal is closed")
	}
	prior, exists := journal.calls[call.RPCID]
	if !exists || prior.Completed || journal.pendingID != call.RPCID || prior.Digest != call.Digest || prior.CallID != call.CallID || prior.Sequence != call.Sequence {
		return errors.New("MCP call journal completion does not match its prepared request")
	}
	if len(response) == 0 || len(response) > MaxMessageBytes {
		return errors.New("MCP call journal response is empty or too large")
	}
	record := journal.newRecord(journalEventComplete, prior, response, uncertain)
	if err := journal.append(record); err != nil {
		return err
	}
	prior.Completed = true
	prior.Response = append([]byte(nil), response...)
	prior.Uncertain = uncertain
	journal.calls[call.RPCID] = prior
	journal.pendingID = ""
	journal.fenced = uncertain
	return nil
}

func (journal *Journal) Fenced() (bool, bool, error) {
	journal.mu.Lock()
	defer journal.mu.Unlock()
	if journal.closed {
		return false, false, errors.New("MCP call journal is closed")
	}
	return journal.fenced, journal.pendingID != "", nil
}

func (journal *Journal) newRecord(event string, call journalCall, response []byte, uncertain bool) journalRecord {
	record := journalRecord{
		Schema: JournalSchema, RecordSequence: journal.recordSeq + 1,
		CallSequence: call.Sequence, Event: event, ExecutionID: journal.executionID,
		RPCID: call.RPCID, RequestDigest: call.Digest, CallID: call.CallID,
		Response: append([]byte(nil), response...), Uncertain: uncertain,
		PreviousHash: journal.headHash,
	}
	record.Hash = hashJournalRecord(record)
	return record
}

func (journal *Journal) append(record journalRecord) error {
	encoded, err := json.Marshal(record)
	if err != nil {
		return err
	}
	encoded = append(encoded, '\n')
	written, err := journal.file.Write(encoded)
	if err != nil {
		return fmt.Errorf("append MCP call journal: %w", err)
	}
	if written != len(encoded) {
		return io.ErrShortWrite
	}
	if err := journal.file.Sync(); err != nil {
		return fmt.Errorf("sync MCP call journal: %w", err)
	}
	journal.recordSeq = record.RecordSequence
	journal.headHash = record.Hash
	return nil
}

func hashJournalRecord(record journalRecord) string {
	payload := journalPayload{
		Schema: record.Schema, RecordSequence: record.RecordSequence, CallSequence: record.CallSequence,
		Event: record.Event, ExecutionID: record.ExecutionID, RPCID: record.RPCID,
		RequestDigest: record.RequestDigest, CallID: record.CallID,
		Response: record.Response, Uncertain: record.Uncertain, PreviousHash: record.PreviousHash,
	}
	encoded, _ := json.Marshal(payload)
	digest := sha256.Sum256(encoded)
	return hex.EncodeToString(digest[:])
}

func journalCallIdentity(executionID string, sequence uint64) string {
	return fmt.Sprintf("mcp-call-v1:%d:%s:%d", len(executionID), executionID, sequence)
}

func validDigest(value string) bool {
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size && hex.EncodeToString(decoded) == value
}

func ownedByCurrentUser(info os.FileInfo) bool {
	stat, ok := info.Sys().(*syscall.Stat_t)
	return ok && int(stat.Uid) == os.Geteuid()
}

func (journal *Journal) Close() error {
	journal.mu.Lock()
	defer journal.mu.Unlock()
	if journal.closed {
		return nil
	}
	journal.closed = true
	unlockErr := syscall.Flock(int(journal.file.Fd()), syscall.LOCK_UN)
	closeErr := journal.file.Close()
	return errors.Join(unlockErr, closeErr)
}
