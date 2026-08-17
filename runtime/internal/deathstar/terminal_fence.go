package deathstar

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"syscall"
	"time"
)

const terminalFenceSchema = 1

type terminalFenceRecord struct {
	Schema         int    `json:"schema"`
	OperationID    string `json:"operation_id"`
	RequestHash    string `json:"request_hash"`
	Disposition    string `json:"disposition"`
	FactHash       string `json:"fact_hash"`
	RecordedTimeNS int64  `json:"recorded_time_ns"`
}

type terminalFenceStore struct {
	directory string
}

func openTerminalFenceStore(directory string) (*terminalFenceStore, error) {
	if directory == "" || !filepath.IsAbs(directory) || filepath.Clean(directory) != directory {
		return nil, errors.New("terminal fence directory must be absolute and canonical")
	}
	info, err := os.Lstat(directory)
	if err != nil {
		return nil, err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || info.Mode().Perm() != 0o700 {
		return nil, errors.New("terminal fence directory must be a private real directory")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(stat.Uid) != os.Geteuid() {
		return nil, errors.New("terminal fence directory must be owned by the current uid")
	}
	return &terminalFenceStore{directory: directory}, nil
}

func (store *terminalFenceStore) record(operationID, requestHash string) (terminalFenceRecord, error) {
	if store == nil {
		return terminalFenceRecord{}, errors.New("terminal fence store is unavailable")
	}
	factHash := terminalFenceFactHash(operationID, requestHash)
	record := terminalFenceRecord{
		Schema: terminalFenceSchema, OperationID: operationID, RequestHash: requestHash,
		Disposition: "terminal-pre-upstream-abort", FactHash: factHash,
		RecordedTimeNS: time.Now().UnixNano(),
	}
	path := store.path(operationID)
	encoded, err := json.Marshal(record)
	if err != nil {
		return terminalFenceRecord{}, err
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if errors.Is(err, os.ErrExist) {
		prior, found, readErr := store.lookup(operationID, requestHash)
		if readErr != nil {
			return terminalFenceRecord{}, readErr
		}
		if !found {
			return terminalFenceRecord{}, errors.New("terminal fence disappeared during replay")
		}
		return prior, nil
	}
	if err != nil {
		return terminalFenceRecord{}, err
	}
	writeErr := error(nil)
	if _, err := file.Write(append(encoded, '\n')); err != nil {
		writeErr = err
	} else if err := file.Sync(); err != nil {
		writeErr = err
	}
	closeErr := file.Close()
	if writeErr != nil || closeErr != nil {
		return terminalFenceRecord{}, errors.Join(writeErr, closeErr)
	}
	directory, err := os.Open(store.directory)
	if err != nil {
		return terminalFenceRecord{}, err
	}
	syncErr := directory.Sync()
	closeErr = directory.Close()
	if syncErr != nil || closeErr != nil {
		return terminalFenceRecord{}, errors.Join(syncErr, closeErr)
	}
	return record, nil
}

func (store *terminalFenceStore) lookup(operationID, requestHash string) (terminalFenceRecord, bool, error) {
	if store == nil {
		return terminalFenceRecord{}, false, nil
	}
	data, err := os.ReadFile(store.path(operationID))
	if errors.Is(err, os.ErrNotExist) {
		return terminalFenceRecord{}, false, nil
	}
	if err != nil {
		return terminalFenceRecord{}, false, err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var record terminalFenceRecord
	if err := decoder.Decode(&record); err != nil {
		return terminalFenceRecord{}, false, fmt.Errorf("decode terminal fence: %w", err)
	}
	var extra any
	if err := decoder.Decode(&extra); err == nil {
		return terminalFenceRecord{}, false, errors.New("terminal fence has trailing JSON")
	} else if !errors.Is(err, io.EOF) {
		return terminalFenceRecord{}, false, errors.New("terminal fence has trailing bytes")
	}
	if record.Schema != terminalFenceSchema || record.OperationID != operationID ||
		record.RequestHash != requestHash || record.Disposition != "terminal-pre-upstream-abort" ||
		record.FactHash != terminalFenceFactHash(operationID, requestHash) || record.RecordedTimeNS <= 0 {
		return terminalFenceRecord{}, false, errors.New("terminal fence does not match the exact Operation")
	}
	return record, true, nil
}

func (store *terminalFenceStore) path(operationID string) string {
	digest := sha256.Sum256([]byte(operationID))
	return filepath.Join(store.directory, hex.EncodeToString(digest[:])+".json")
}

func terminalFenceFactHash(operationID, requestHash string) string {
	canonical, _ := json.Marshal(struct {
		Schema      int    `json:"schema"`
		OperationID string `json:"operation_id"`
		RequestHash string `json:"request_hash"`
		Disposition string `json:"disposition"`
	}{terminalFenceSchema, operationID, requestHash, "terminal-pre-upstream-abort"})
	digest := sha256.Sum256(canonical)
	return hex.EncodeToString(digest[:])
}
