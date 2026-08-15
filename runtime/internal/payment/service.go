// Package payment implements the independently durable external service used
// by the multi-process system path. It is intentionally outside the control
// History: a local restore cannot erase a committed charge.
package payment

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"syscall"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const maxRequestBytes = 1 << 20

type record struct {
	OperationID     string `json:"operation_id"`
	RequestHash     string `json:"request_hash"`
	ResultHash      string `json:"result_hash"`
	RemoteReference string `json:"remote_reference"`
	Path            string `json:"path"`
}

type Stats struct {
	Deliveries int            `json:"deliveries"`
	Commits    int            `json:"commits"`
	Paths      map[string]int `json:"paths"`
}

type Service struct {
	mu         sync.Mutex
	file       *os.File
	records    map[string]record
	paths      map[string]int
	deliveries int
	dropNext   bool
	closed     bool
}

func Open(path string, dropFirstResponse bool) (*Service, error) {
	_, statErr := os.Stat(path)
	created := errors.Is(statErr, os.ErrNotExist)
	if statErr != nil && !created {
		return nil, statErr
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR|os.O_APPEND, 0o600)
	if err != nil {
		return nil, err
	}
	fail := func(cause error) (*Service, error) {
		_ = file.Close()
		return nil, cause
	}
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return fail(fmt.Errorf("lock payment state: %w", err))
	}
	info, err := file.Stat()
	if err != nil {
		return fail(err)
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0o077 != 0 {
		return fail(errors.New("payment state must be a private regular file"))
	}
	if created {
		directory, err := os.Open(filepath.Dir(path))
		if err != nil {
			return fail(err)
		}
		syncErr := directory.Sync()
		closeErr := directory.Close()
		if syncErr != nil {
			return fail(syncErr)
		}
		if closeErr != nil {
			return fail(closeErr)
		}
	}
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return fail(err)
	}
	service := &Service{
		file: file, records: make(map[string]record), paths: make(map[string]int),
	}
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		var item record
		if err := decodeStrict(scanner.Bytes(), &item); err != nil {
			return fail(fmt.Errorf("decode payment state: %w", err))
		}
		if err := validateRecord(item); err != nil {
			return fail(fmt.Errorf("invalid payment state: %w", err))
		}
		if prior, ok := service.records[item.OperationID]; ok {
			if prior != item {
				return fail(fmt.Errorf("conflicting durable payment identity %q", item.OperationID))
			}
			continue
		}
		service.records[item.OperationID] = item
	}
	if err := scanner.Err(); err != nil {
		return fail(err)
	}
	if _, err := file.Seek(0, io.SeekEnd); err != nil {
		return fail(err)
	}
	service.dropNext = dropFirstResponse && len(service.records) == 0
	return service, nil
}

func validateRecord(item record) error {
	if item.OperationID == "" || len(item.OperationID) > 1024 {
		return errors.New("invalid Operation identity")
	}
	if item.Path != "/v1/charge" && item.Path != "/v2/charge" {
		return errors.New("invalid payment path")
	}
	for _, digest := range []string{item.RequestHash, item.ResultHash} {
		decoded, err := hex.DecodeString(digest)
		if err != nil || len(decoded) != sha256.Size || hex.EncodeToString(decoded) != digest {
			return errors.New("invalid payment digest")
		}
	}
	if item.RemoteReference == "" {
		return errors.New("missing remote reference")
	}
	return nil
}

func decodeStrict(data []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("multiple JSON values")
		}
		return err
	}
	return nil
}

func (s *Service) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return nil
	}
	s.closed = true
	unlockErr := syscall.Flock(int(s.file.Fd()), syscall.LOCK_UN)
	closeErr := s.file.Close()
	return errors.Join(unlockErr, closeErr)
}

func (s *Service) Stats() Stats {
	s.mu.Lock()
	defer s.mu.Unlock()
	paths := make(map[string]int, len(s.paths))
	for path, count := range s.paths {
		paths[path] = count
	}
	return Stats{Deliveries: s.deliveries, Commits: len(s.records), Paths: paths}
}

func (s *Service) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(writer http.ResponseWriter, _ *http.Request) {
		writeJSON(writer, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /v1/stats", func(writer http.ResponseWriter, _ *http.Request) {
		writeJSON(writer, http.StatusOK, s.Stats())
	})
	mux.HandleFunc("POST /v1/charge", s.charge)
	mux.HandleFunc("POST /v2/charge", s.charge)
	return mux
}

func (s *Service) charge(writer http.ResponseWriter, request *http.Request) {
	body, err := io.ReadAll(io.LimitReader(request.Body, maxRequestBytes+1))
	if err != nil {
		writeError(writer, http.StatusBadRequest, err)
		return
	}
	if len(body) > maxRequestBytes {
		writeError(writer, http.StatusRequestEntityTooLarge, errors.New("payment request exceeds size limit"))
		return
	}
	id := request.Header.Get("X-Operation-ID")
	if id == "" || len(id) > 1024 || request.Header.Get("Idempotency-Key") != id {
		writeError(writer, http.StatusBadRequest, errors.New("matching Operation and idempotency identities are required"))
		return
	}
	requestHash := hashRequest(request.Method, request.URL.Path, body)

	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		writeError(writer, http.StatusServiceUnavailable, errors.New("payment service is closed"))
		return
	}
	s.deliveries++
	s.paths[request.URL.Path]++
	item, exists := s.records[id]
	if exists && item.RequestHash != requestHash {
		writeError(writer, http.StatusConflict, errors.New("Operation identity is bound to different payment work"))
		return
	}
	if !exists {
		result := sha256.Sum256([]byte("charged\x00" + id))
		item = record{
			OperationID: id, RequestHash: requestHash,
			ResultHash:      hex.EncodeToString(result[:]),
			RemoteReference: "payment/" + id, Path: request.URL.Path,
		}
		encoded, err := json.Marshal(item)
		if err != nil {
			writeError(writer, http.StatusInternalServerError, err)
			return
		}
		if _, err := s.file.Write(append(encoded, '\n')); err != nil {
			writeError(writer, http.StatusInternalServerError, err)
			return
		}
		if err := s.file.Sync(); err != nil {
			writeError(writer, http.StatusInternalServerError, err)
			return
		}
		s.records[id] = item
		if s.dropNext {
			s.dropNext = false
			hijacker, ok := writer.(http.Hijacker)
			if !ok {
				writeError(writer, http.StatusInternalServerError, errors.New("response loss injection requires an HTTP connection"))
				return
			}
			connection, _, err := hijacker.Hijack()
			if err == nil {
				_ = connection.Close()
			}
			return
		}
	}
	writeJSON(writer, http.StatusOK, map[string]any{
		"schema": 1, "operation_id": id, "outcome": kernel.Succeeded,
		"result_hash": item.ResultHash, "remote_reference": item.RemoteReference,
	})
}

func hashRequest(method, path string, body []byte) string {
	hash := sha256.New()
	_, _ = io.WriteString(hash, method)
	hash.Write([]byte{0})
	_, _ = io.WriteString(hash, path)
	hash.Write([]byte{0})
	hash.Write(body)
	return hex.EncodeToString(hash.Sum(nil))
}

func writeJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}

func writeError(writer http.ResponseWriter, status int, err error) {
	writeJSON(writer, status, map[string]string{"error": err.Error()})
}
