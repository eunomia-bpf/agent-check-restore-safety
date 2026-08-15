// Package deathstar adapts the unmodified DeathStarBench Hotel Reservation
// frontend and its MongoDB state to the runtime's effect and observation
// contracts. The append-only adapter audit is evidence only: neither service
// reads it to decide whether an Operation ran or may run again.
package deathstar

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

const (
	maxRequestBytes  = 1 << 20
	maxUpstreamBytes = 64 << 10
	maxIdentityBytes = 1024
	maxOperationID   = maxIdentityBytes - len("deathstar/reservation/")
)

// ReservationRequest is the complete input accepted by both endpoints. The
// customer name is deliberately absent: it is derived from the Operation
// identity, so retries and observations address the same durable business row.
type ReservationRequest struct {
	HotelID  string `json:"hotel_id"`
	InDate   string `json:"in_date"`
	OutDate  string `json:"out_date"`
	Rooms    int    `json:"rooms"`
	Username string `json:"username"`
	Password string `json:"password"`
}

// ReservationQuery is the exact durable predicate used by the observer.
type ReservationQuery struct {
	CustomerName string
	HotelID      string
	InDate       string
	OutDate      string
	Rooms        int
}

// ReservationFact is the application-owned document summary on which an
// observation is based. MongoDB's internal _id is intentionally irrelevant.
type ReservationFact struct {
	CustomerName string `json:"customer_name" bson:"customerName"`
	HotelID      string `json:"hotel_id" bson:"hotelId"`
	InDate       string `json:"in_date" bson:"inDate"`
	OutDate      string `json:"out_date" bson:"outDate"`
	Rooms        int    `json:"rooms" bson:"number"`
}

// QueryResult contains the exact number of matching documents and, when the
// count is one, the document on which a settled observation can be based.
type QueryResult struct {
	Count int64
	Facts []ReservationFact
}

// ReservationStore abstracts the Mongo query so protocol and failure behavior
// can be tested without a network or a database process.
type ReservationStore interface {
	FindExact(context.Context, ReservationQuery) (QueryResult, error)
}

type EffectConfig struct {
	FrontendURL       string
	AuditPath         string
	DropFirstResponse bool
	Transport         http.RoundTripper
}

type EffectService struct {
	frontend *url.URL
	client   *http.Client
	audit    *auditLog
}

type auditRecord struct {
	Delivery       uint64 `json:"delivery"`
	OperationID    string `json:"operation_id"`
	UpstreamStatus int    `json:"upstream_status"`
	UpstreamHash   string `json:"upstream_hash"`
	UpstreamOK     bool   `json:"upstream_ok"`
	Drop           bool   `json:"drop"`
}

type auditStats struct {
	Deliveries uint64 `json:"deliveries"`
	UpstreamOK uint64 `json:"upstream_successes"`
	Drops      uint64 `json:"drops"`
}

type auditLog struct {
	mu       sync.Mutex
	file     *os.File
	nextDrop bool
	stats    auditStats
	closed   bool
}

func OpenEffect(config EffectConfig) (*EffectService, error) {
	frontend, err := url.Parse(config.FrontendURL)
	if err != nil || (frontend.Scheme != "http" && frontend.Scheme != "https") || frontend.Host == "" || frontend.User != nil || frontend.Fragment != "" {
		return nil, errors.New("DeathStarBench frontend must be an absolute HTTP(S) URL")
	}
	if frontend.RawQuery != "" {
		return nil, errors.New("DeathStarBench frontend URL cannot contain a query")
	}
	if config.AuditPath == "" {
		return nil, errors.New("effect adapter requires an audit path")
	}
	audit, err := openAudit(config.AuditPath, config.DropFirstResponse)
	if err != nil {
		return nil, err
	}
	transport := config.Transport
	if transport == nil {
		transport = http.DefaultTransport
	}
	return &EffectService{
		frontend: frontend,
		client: &http.Client{
			Transport: transport,
			Timeout:   30 * time.Second,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
		audit: audit,
	}, nil
}

func openAudit(path string, dropFirst bool) (*auditLog, error) {
	_, statErr := os.Stat(path)
	created := errors.Is(statErr, os.ErrNotExist)
	if statErr != nil && !created {
		return nil, statErr
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return nil, err
	}
	fail := func(cause error) (*auditLog, error) {
		_ = file.Close()
		return nil, cause
	}
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return fail(fmt.Errorf("lock adapter audit: %w", err))
	}
	info, err := file.Stat()
	if err != nil {
		return fail(err)
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0o077 != 0 {
		return fail(errors.New("adapter audit must be a private regular file"))
	}
	if created {
		directory, err := os.Open(filepath.Dir(path))
		if err != nil {
			return fail(err)
		}
		syncErr := directory.Sync()
		closeErr := directory.Close()
		if syncErr != nil || closeErr != nil {
			return fail(errors.Join(syncErr, closeErr))
		}
	}
	return &auditLog{file: file, nextDrop: dropFirst}, nil
}

func (a *auditLog) append(operationID string, status int, upstreamHash string, upstreamOK, canDrop bool) (auditRecord, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.closed {
		return auditRecord{}, errors.New("adapter audit is closed")
	}
	record := auditRecord{
		Delivery: a.stats.Deliveries + 1, OperationID: operationID,
		UpstreamStatus: status, UpstreamHash: upstreamHash, UpstreamOK: upstreamOK,
		Drop: upstreamOK && canDrop && a.nextDrop,
	}
	encoded, err := json.Marshal(record)
	if err != nil {
		return auditRecord{}, err
	}
	if _, err := a.file.Write(append(encoded, '\n')); err != nil {
		return auditRecord{}, err
	}
	if err := a.file.Sync(); err != nil {
		return auditRecord{}, err
	}
	a.stats.Deliveries++
	if upstreamOK {
		a.stats.UpstreamOK++
	}
	if record.Drop {
		a.nextDrop = false
		a.stats.Drops++
	}
	return record, nil
}

func (a *auditLog) snapshot() auditStats {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.stats
}

func (a *auditLog) close() error {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.closed {
		return nil
	}
	a.closed = true
	unlockErr := syscall.Flock(int(a.file.Fd()), syscall.LOCK_UN)
	closeErr := a.file.Close()
	return errors.Join(unlockErr, closeErr)
}

func (s *EffectService) Close() error { return s.audit.close() }

func (s *EffectService) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(writer http.ResponseWriter, _ *http.Request) {
		writeJSON(writer, http.StatusOK, map[string]string{"status": "ok", "mode": "effect"})
	})
	mux.HandleFunc("GET /v1/stats/facts", func(writer http.ResponseWriter, _ *http.Request) {
		stats := s.audit.snapshot()
		writeJSON(writer, http.StatusOK, map[string]any{
			"mode": "effect", "deliveries": stats.Deliveries,
			"upstream_successes": stats.UpstreamOK, "drops": stats.Drops,
			"facts": []any{},
		})
	})
	mux.HandleFunc("POST /v1/reserve", s.reserve)
	return mux
}

func (s *EffectService) reserve(writer http.ResponseWriter, request *http.Request) {
	operationID, err := operationIdentity(request)
	if err != nil {
		writeError(writer, http.StatusBadRequest, err)
		return
	}
	input, _, err := readReservationRequest(request.Body)
	if err != nil {
		writeError(writer, http.StatusBadRequest, err)
		return
	}
	upstreamURL := *s.frontend
	upstreamURL.Path = strings.TrimRight(upstreamURL.Path, "/") + "/reservation"
	query := upstreamURL.Query()
	query.Set("inDate", input.InDate)
	query.Set("outDate", input.OutDate)
	query.Set("hotelId", input.HotelID)
	query.Set("customerName", customerName(operationID))
	query.Set("username", input.Username)
	query.Set("password", input.Password)
	query.Set("number", strconv.Itoa(input.Rooms))
	upstreamURL.RawQuery = query.Encode()
	upstreamRequest, err := http.NewRequestWithContext(request.Context(), http.MethodGet, upstreamURL.String(), nil)
	if err != nil {
		writeError(writer, http.StatusInternalServerError, err)
		return
	}
	upstreamRequest.Header.Set("Accept-Encoding", "identity")
	upstreamRequest.Header.Set("User-Agent", "safe-change-deathstar-adapter/1")
	response, callErr := s.client.Do(upstreamRequest)
	status := 0
	body := []byte(nil)
	if callErr == nil {
		status = response.StatusCode
		body, err = io.ReadAll(io.LimitReader(response.Body, maxUpstreamBytes+1))
		closeErr := response.Body.Close()
		if err == nil {
			err = closeErr
		}
		if len(body) > maxUpstreamBytes && err == nil {
			err = errors.New("DeathStarBench response exceeds size limit")
		}
	} else {
		err = callErr
	}
	bodyDigest := sha256.Sum256(body)
	upstreamHash := hex.EncodeToString(bodyDigest[:])
	upstreamOK := err == nil && status == http.StatusOK && successfulUpstreamBody(body)
	hijacker, canHijack := writer.(http.Hijacker)
	record, auditErr := s.audit.append(operationID, status, upstreamHash, upstreamOK, canHijack)
	if auditErr != nil {
		writeError(writer, http.StatusInternalServerError, auditErr)
		return
	}
	if err != nil {
		writeError(writer, http.StatusBadGateway, err)
		return
	}
	if !upstreamOK {
		writeError(writer, http.StatusBadGateway, errors.New("DeathStarBench did not return an explicit reservation success"))
		return
	}
	if record.Drop {
		connection, _, hijackErr := hijacker.Hijack()
		if hijackErr != nil {
			writeError(writer, http.StatusInternalServerError, fmt.Errorf("drop injected response: %w", hijackErr))
			return
		}
		_ = connection.Close()
		return
	}
	result := resultHash(operationID, input)
	writeJSON(writer, http.StatusOK, map[string]any{
		"schema": 1, "operation_id": operationID, "outcome": "succeeded",
		"result_hash": result, "remote_reference": "deathstar/reservation/" + operationID,
	})
}

func successfulUpstreamBody(body []byte) bool {
	var response struct {
		Message string `json:"message"`
	}
	if err := decodeStrict(body, &response); err != nil {
		return false
	}
	return response.Message == "Reserve successfully!"
}

func resultHash(operationID string, input ReservationRequest) string {
	summary := struct {
		OperationID  string `json:"operation_id"`
		CustomerName string `json:"customer_name"`
		HotelID      string `json:"hotel_id"`
		InDate       string `json:"in_date"`
		OutDate      string `json:"out_date"`
		Rooms        int    `json:"rooms"`
	}{operationID, customerName(operationID), input.HotelID, input.InDate, input.OutDate, input.Rooms}
	encoded, _ := json.Marshal(summary)
	digest := sha256.Sum256(encoded)
	return hex.EncodeToString(digest[:])
}

type Observation struct {
	Schema          int    `json:"schema"`
	OperationID     string `json:"operation_id"`
	RequestHash     string `json:"request_hash"`
	Outcome         string `json:"outcome"`
	FactHash        string `json:"fact_hash"`
	RemoteReference string `json:"remote_reference"`
}

type observedFact struct {
	Observation
	Count int64             `json:"count"`
	Facts []ReservationFact `json:"facts"`
}

type ObserverService struct {
	store ReservationStore
	mu    sync.Mutex
	items []observedFact
}

func NewObserver(store ReservationStore) (*ObserverService, error) {
	if store == nil {
		return nil, errors.New("observer requires a reservation store")
	}
	return &ObserverService{store: store}, nil
}

func (s *ObserverService) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(writer http.ResponseWriter, _ *http.Request) {
		writeJSON(writer, http.StatusOK, map[string]string{"status": "ok", "mode": "observer"})
	})
	mux.HandleFunc("GET /v1/stats/facts", s.writeFacts)
	mux.HandleFunc("POST /v1/query", s.query)
	return mux
}

func (s *ObserverService) query(writer http.ResponseWriter, request *http.Request) {
	operationID, err := operationIdentity(request)
	if err != nil {
		writeError(writer, http.StatusBadRequest, err)
		return
	}
	requestHash := request.Header.Get("X-Operation-Request-Hash")
	if !validDigest(requestHash) {
		writeError(writer, http.StatusBadRequest, errors.New("valid Operation request hash is required"))
		return
	}
	input, _, err := readReservationRequest(request.Body)
	if err != nil {
		writeError(writer, http.StatusBadRequest, err)
		return
	}
	query := ReservationQuery{
		CustomerName: customerName(operationID), HotelID: input.HotelID,
		InDate: input.InDate, OutDate: input.OutDate, Rooms: input.Rooms,
	}
	match, err := s.store.FindExact(request.Context(), query)
	if err != nil {
		writeError(writer, http.StatusBadGateway, fmt.Errorf("query reservation facts: %w", err))
		return
	}
	if match.Count < 0 || (match.Count == 1 && len(match.Facts) != 1) || (match.Count != 1 && len(match.Facts) != 0) {
		writeError(writer, http.StatusInternalServerError, errors.New("reservation store returned an inconsistent result"))
		return
	}
	outcome := "inconclusive"
	factHash := ""
	facts := append([]ReservationFact(nil), match.Facts...)
	if match.Count == 1 {
		outcome = "succeeded"
		factHash = canonicalFactHash(facts)
	}
	observation := Observation{
		Schema: 1, OperationID: operationID, RequestHash: requestHash,
		Outcome: outcome, FactHash: factHash,
		RemoteReference: fmt.Sprintf("reservation-db.reservation/count=%d", match.Count),
	}
	s.mu.Lock()
	s.items = append(s.items, observedFact{Observation: observation, Count: match.Count, Facts: facts})
	s.mu.Unlock()
	writeJSON(writer, http.StatusOK, observation)
}

func (s *ObserverService) writeFacts(writer http.ResponseWriter, _ *http.Request) {
	s.mu.Lock()
	items := make([]observedFact, len(s.items))
	copy(items, s.items)
	s.mu.Unlock()
	outcomes := map[string]int{"succeeded": 0, "inconclusive": 0}
	for _, item := range items {
		outcomes[item.Outcome]++
	}
	writeJSON(writer, http.StatusOK, map[string]any{
		"mode": "observer", "queries": len(items), "outcomes": outcomes, "facts": items,
	})
}

func canonicalFactHash(facts []ReservationFact) string {
	canonical := append([]ReservationFact(nil), facts...)
	sort.Slice(canonical, func(i, j int) bool {
		left, right := canonical[i], canonical[j]
		if left.CustomerName != right.CustomerName {
			return left.CustomerName < right.CustomerName
		}
		if left.HotelID != right.HotelID {
			return left.HotelID < right.HotelID
		}
		if left.InDate != right.InDate {
			return left.InDate < right.InDate
		}
		if left.OutDate != right.OutDate {
			return left.OutDate < right.OutDate
		}
		return left.Rooms < right.Rooms
	})
	encoded, _ := json.Marshal(canonical)
	digest := sha256.Sum256(encoded)
	return hex.EncodeToString(digest[:])
}

func operationIdentity(request *http.Request) (string, error) {
	identity := request.Header.Get("X-Operation-ID")
	if identity == "" || len(identity) > maxOperationID || strings.ContainsAny(identity, "\r\n\x00") {
		return "", errors.New("valid gateway-owned Operation identity is required")
	}
	return identity, nil
}

func customerName(operationID string) string { return "safe-" + operationID }

func readReservationRequest(reader io.Reader) (ReservationRequest, []byte, error) {
	body, err := io.ReadAll(io.LimitReader(reader, maxRequestBytes+1))
	if err != nil {
		return ReservationRequest{}, nil, err
	}
	if len(body) > maxRequestBytes {
		return ReservationRequest{}, nil, errors.New("reservation request exceeds size limit")
	}
	var input ReservationRequest
	if err := decodeStrict(body, &input); err != nil {
		return ReservationRequest{}, nil, fmt.Errorf("decode reservation request: %w", err)
	}
	if err := validateReservation(input); err != nil {
		return ReservationRequest{}, nil, err
	}
	return input, body, nil
}

func validateReservation(input ReservationRequest) error {
	for name, value := range map[string]string{
		"hotel_id": input.HotelID, "username": input.Username, "password": input.Password,
	} {
		if value == "" || len(value) > maxIdentityBytes || strings.ContainsRune(value, '\x00') {
			return fmt.Errorf("invalid %s", name)
		}
	}
	inDate, err := time.Parse("2006-01-02", input.InDate)
	if err != nil || inDate.Format("2006-01-02") != input.InDate {
		return errors.New("invalid in_date")
	}
	outDate, err := time.Parse("2006-01-02", input.OutDate)
	if err != nil || outDate.Format("2006-01-02") != input.OutDate || !outDate.After(inDate) {
		return errors.New("invalid out_date")
	}
	// DeathStarBench stores one document per night. Limiting this contract to
	// one night makes a unique exact document a complete effect fact rather
	// than mistaking one row of a multi-night reservation for completion.
	if !outDate.Equal(inDate.AddDate(0, 0, 1)) {
		return errors.New("reservation observation requires a one-night interval")
	}
	if input.Rooms <= 0 || int64(input.Rooms) > int64(^uint32(0)>>1) {
		return errors.New("rooms must fit a positive int32")
	}
	return nil
}

func decodeStrict(data []byte, target any) error {
	object := json.NewDecoder(bytes.NewReader(data))
	start, err := object.Token()
	if err != nil || start != json.Delim('{') {
		return errors.New("JSON value is not an object")
	}
	seen := make(map[string]bool)
	for object.More() {
		token, err := object.Token()
		if err != nil {
			return err
		}
		name, ok := token.(string)
		if !ok {
			return errors.New("JSON object key is not a string")
		}
		if seen[name] {
			return fmt.Errorf("duplicate JSON field %q", name)
		}
		seen[name] = true
		var raw json.RawMessage
		if err := object.Decode(&raw); err != nil {
			return err
		}
	}
	end, err := object.Token()
	if err != nil || end != json.Delim('}') {
		return errors.New("JSON object has an invalid terminator")
	}
	var trailing any
	if err := object.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("multiple JSON values")
		}
		return err
	}

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

func validDigest(value string) bool {
	if len(value) != sha256.Size*2 {
		return false
	}
	decoded, err := hex.DecodeString(value)
	return err == nil && hex.EncodeToString(decoded) == value
}

func writeJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}

func writeError(writer http.ResponseWriter, status int, err error) {
	writeJSON(writer, status, map[string]string{"error": err.Error()})
}
