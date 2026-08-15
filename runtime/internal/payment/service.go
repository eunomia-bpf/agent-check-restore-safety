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
	"strings"
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

// Options keeps the default service idempotent while making provider behavior
// and fault timing explicit for experiments. At most one fault mode can be
// selected. The hold modes publish their progress through the existing Stats
// counters, release the service lock, and wait until the client connection is
// canceled without writing an HTTP response.
type Options struct {
	DropFirstResponse      bool
	AlwaysDropBeforeCommit bool
	HoldBeforeCommit       bool
	HoldAfterCommit        bool
	NonIdempotent          bool
	ReferencePrefix        string
}

type Service struct {
	mu               sync.Mutex
	file             *os.File
	records          map[string][]record
	paths            map[string]int
	deliveries       int
	dropNext         bool
	dropBeforeCommit bool
	holdBeforeCommit bool
	holdAfterCommit  bool
	nonIdempotent    bool
	referencePrefix  string
	closed           bool
}

func Open(path string, dropFirstResponse bool) (*Service, error) {
	return OpenWithOptions(path, Options{DropFirstResponse: dropFirstResponse})
}

func OpenWithOptions(path string, options Options) (*Service, error) {
	if options.ReferencePrefix == "" {
		options.ReferencePrefix = "payment"
	}
	if !validReferencePrefix(options.ReferencePrefix) {
		return nil, errors.New("payment reference prefix must use letters, digits, dot, underscore, or hyphen")
	}
	faultModes := 0
	for _, enabled := range []bool{
		options.DropFirstResponse, options.AlwaysDropBeforeCommit,
		options.HoldBeforeCommit, options.HoldAfterCommit,
	} {
		if enabled {
			faultModes++
		}
	}
	if faultModes > 1 {
		return nil, errors.New("payment response-loss modes are mutually exclusive")
	}
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
		file: file, records: make(map[string][]record), paths: make(map[string]int),
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
		if prior := service.records[item.OperationID]; len(prior) > 0 {
			if prior[0].RequestHash != item.RequestHash || prior[0].Path != item.Path {
				return fail(fmt.Errorf("conflicting durable payment identity %q", item.OperationID))
			}
		}
		service.records[item.OperationID] = append(service.records[item.OperationID], item)
	}
	if err := scanner.Err(); err != nil {
		return fail(err)
	}
	if _, err := file.Seek(0, io.SeekEnd); err != nil {
		return fail(err)
	}
	service.dropNext = options.DropFirstResponse && len(service.records) == 0
	service.dropBeforeCommit = options.AlwaysDropBeforeCommit
	service.holdBeforeCommit = options.HoldBeforeCommit
	service.holdAfterCommit = options.HoldAfterCommit
	service.nonIdempotent = options.NonIdempotent
	service.referencePrefix = options.ReferencePrefix
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
	commits := 0
	for _, items := range s.records {
		commits += len(items)
	}
	return Stats{Deliveries: s.deliveries, Commits: commits, Paths: paths}
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
	mux.HandleFunc("POST /v1/complete", s.charge)
	mux.HandleFunc("POST /v1/query", s.observe)
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
	if s.closed {
		s.mu.Unlock()
		writeError(writer, http.StatusServiceUnavailable, errors.New("payment service is closed"))
		return
	}
	s.deliveries++
	s.paths[request.URL.Path]++
	items := s.records[id]
	if len(items) > 0 && (items[0].RequestHash != requestHash || items[0].Path != request.URL.Path) {
		s.mu.Unlock()
		writeError(writer, http.StatusConflict, errors.New("Operation identity is bound to different payment work"))
		return
	}
	willCommit := len(items) == 0 || s.nonIdempotent
	if willCommit && (s.dropBeforeCommit || s.holdBeforeCommit) {
		drop := s.dropBeforeCommit
		s.mu.Unlock()
		if drop {
			if err := dropResponse(writer); err != nil {
				writeError(writer, http.StatusInternalServerError, err)
			}
		} else {
			holdUntilCanceled(request)
		}
		return
	}

	var item record
	drop := false
	hold := false
	if willCommit {
		item = newRecord(id, requestHash, request.URL.Path, len(items)+1, s.nonIdempotent, s.referencePrefix)
		encoded, err := json.Marshal(item)
		if err != nil {
			s.mu.Unlock()
			writeError(writer, http.StatusInternalServerError, err)
			return
		}
		if _, err := s.file.Write(append(encoded, '\n')); err != nil {
			s.mu.Unlock()
			writeError(writer, http.StatusInternalServerError, err)
			return
		}
		if err := s.file.Sync(); err != nil {
			s.mu.Unlock()
			writeError(writer, http.StatusInternalServerError, err)
			return
		}
		s.records[id] = append(items, item)
		drop = s.dropNext
		if drop {
			s.dropNext = false
		}
		hold = s.holdAfterCommit
	} else {
		item = items[0]
	}
	s.mu.Unlock()
	if hold {
		holdUntilCanceled(request)
		return
	}
	if drop {
		if err := dropResponse(writer); err != nil {
			writeError(writer, http.StatusInternalServerError, err)
		}
		return
	}
	writeJSON(writer, http.StatusOK, map[string]any{
		"schema": 1, "operation_id": id, "outcome": kernel.Succeeded,
		"result_hash": item.ResultHash, "remote_reference": item.RemoteReference,
	})
}

func (s *Service) observe(writer http.ResponseWriter, request *http.Request) {
	body, err := io.ReadAll(io.LimitReader(request.Body, maxRequestBytes+1))
	if err != nil {
		writeError(writer, http.StatusBadRequest, err)
		return
	}
	if len(body) > maxRequestBytes {
		writeError(writer, http.StatusRequestEntityTooLarge, errors.New("payment observation request exceeds size limit"))
		return
	}
	id := request.Header.Get("X-Operation-ID")
	requestHash := request.Header.Get("X-Operation-Request-Hash")
	if id == "" || len(id) > 1024 {
		writeError(writer, http.StatusBadRequest, errors.New("valid Operation identity is required"))
		return
	}
	if !validDigest(requestHash) {
		writeError(writer, http.StatusBadRequest, errors.New("valid Operation request hash is required"))
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		writeError(writer, http.StatusServiceUnavailable, errors.New("payment service is closed"))
		return
	}
	items := s.records[id]
	// The observer receives the exact stored effect body from the gateway. The
	// durable record freezes the original effect path, so hashing that path and
	// this body checks both the Operation identity and its complete work.
	if len(items) > 0 && hashRequest(http.MethodPost, items[0].Path, body) != items[0].RequestHash {
		writeError(writer, http.StatusConflict, errors.New("Operation observation body does not match durable payment work"))
		return
	}
	observation := operationObservationV1{
		Schema: 1, OperationID: id, RequestHash: requestHash,
		Outcome: "inconclusive", FactHash: "",
		RemoteReference: fmt.Sprintf("%s/%s/count=%d", s.referencePrefix, id, len(items)),
	}
	if len(items) == 1 {
		observation.Outcome = string(kernel.Succeeded)
		observation.FactHash = items[0].ResultHash
		observation.RemoteReference = items[0].RemoteReference
	}
	writeJSON(writer, http.StatusOK, observation)
}

type operationObservationV1 struct {
	Schema          int    `json:"schema"`
	OperationID     string `json:"operation_id"`
	RequestHash     string `json:"request_hash"`
	Outcome         string `json:"outcome"`
	FactHash        string `json:"fact_hash"`
	RemoteReference string `json:"remote_reference"`
}

func newRecord(id, requestHash, path string, instance int, nonIdempotent bool, referencePrefix string) record {
	resultInput := "charged\x00" + id
	remoteReference := referencePrefix + "/" + id
	if nonIdempotent {
		resultInput = fmt.Sprintf("charged\x00%s\x00%d", id, instance)
		remoteReference = fmt.Sprintf("%s/%s/commit-%d", referencePrefix, id, instance)
	}
	result := sha256.Sum256([]byte(resultInput))
	return record{
		OperationID: id, RequestHash: requestHash,
		ResultHash: hex.EncodeToString(result[:]), RemoteReference: remoteReference, Path: path,
	}
}

func validReferencePrefix(value string) bool {
	if value == "" || len(value) > 64 {
		return false
	}
	for _, character := range value {
		if (character >= 'a' && character <= 'z') ||
			(character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') ||
			strings.ContainsRune("._-", character) {
			continue
		}
		return false
	}
	return true
}

func holdUntilCanceled(request *http.Request) {
	<-request.Context().Done()
}

func dropResponse(writer http.ResponseWriter) error {
	hijacker, ok := writer.(http.Hijacker)
	if !ok {
		return errors.New("response loss injection requires an HTTP connection")
	}
	connection, _, err := hijacker.Hijack()
	if err != nil {
		return fmt.Errorf("inject response loss: %w", err)
	}
	return connection.Close()
}

func validDigest(value string) bool {
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size && hex.EncodeToString(decoded) == value
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
