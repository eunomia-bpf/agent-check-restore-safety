package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const (
	operationDomain         = "temporal-order-workflow"
	maxEffectRequestBytes   = 64 << 10
	maxEffectResponseBytes  = 64 << 10
	maxOrderIDBytes         = 512
	maxAuxHeaderBytes       = 1024
	maxRemoteReferenceBytes = 1024
	maxAmountCents          = int64(1_000_000_000_000)
)

const (
	headerOperationID    = "X-Operation-ID"
	headerIdempotencyKey = "Idempotency-Key"
)

type Executor interface {
	Execute(context.Context, api.ExecuteRequest) (gateway.Outcome, error)
}

type Adapter struct {
	executor         Executor
	routesByPath     map[string][]Route
	executionTimeout time.Duration
}

type effectRequest struct {
	OrderID        string
	AmountCents    int64
	ClosureVersion *string
}

type effectReceipt struct {
	Schema          int    `json:"schema"`
	OperationID     string `json:"operation_id"`
	Outcome         string `json:"outcome"`
	ResultHash      string `json:"result_hash"`
	RemoteReference string `json:"remote_reference"`
}

type operationObservation struct {
	Schema          int
	OperationID     string
	RequestHash     string
	Outcome         string
	FactHash        string
	RemoteReference string
}

type errorResponse struct {
	Schema int    `json:"schema"`
	Error  string `json:"error"`
}

func NewAdapter(executor Executor, config Config, executionTimeout time.Duration) (*Adapter, error) {
	if executor == nil {
		return nil, errors.New("nil control executor")
	}
	if executionTimeout <= 0 || executionTimeout > 10*time.Minute {
		return nil, errors.New("execution timeout must be positive and at most 10m")
	}
	if err := validateConfig(config); err != nil {
		return nil, err
	}
	adapter := &Adapter{
		executor: executor, routesByPath: make(map[string][]Route), executionTimeout: executionTimeout,
	}
	for _, route := range config.Routes {
		adapter.routesByPath[route.Path] = append(adapter.routesByPath[route.Path], route)
	}
	return adapter, nil
}

func (a *Adapter) Handler() http.Handler {
	return http.HandlerFunc(a.serveHTTP)
}

func (a *Adapter) serveHTTP(writer http.ResponseWriter, request *http.Request) {
	secureResponse(writer)
	// A reverse adapter has no reason to accept the absolute-form request target
	// used by HTTP proxies. Refuse it before looking at any configured path.
	if request.URL.IsAbs() || request.URL.Host != "" {
		writeError(writer, http.StatusBadRequest, "absolute-form requests are not accepted")
		return
	}
	if request.URL.Path == "/healthz" {
		a.serveHealth(writer, request)
		return
	}
	candidates, declared := a.routesByPath[request.URL.Path]
	if !declared || request.URL.RawPath != "" {
		writeError(writer, http.StatusNotFound, "provider route not found")
		return
	}
	if request.Method != http.MethodPost {
		writer.Header().Set("Allow", http.MethodPost)
		writeError(writer, http.StatusMethodNotAllowed, "provider route requires POST")
		return
	}
	if request.URL.RawQuery != "" || request.URL.ForceQuery {
		writeError(writer, http.StatusBadRequest, "provider route does not accept query parameters")
		return
	}
	operationID, idempotencyKey, contentType, err := validateRequestHeaders(request.Header)
	if err != nil {
		status := http.StatusBadRequest
		if errors.Is(err, errUnsupportedContentType) {
			status = http.StatusUnsupportedMediaType
		}
		writeError(writer, status, err.Error())
		return
	}
	if len(request.TransferEncoding) != 0 || len(request.Trailer) != 0 {
		writeError(writer, http.StatusBadRequest, "streamed or trailer-bearing requests are not accepted")
		return
	}
	if request.ContentLength < 0 {
		writeError(writer, http.StatusLengthRequired, "a bounded Content-Length is required")
		return
	}
	if request.ContentLength > maxEffectRequestBytes {
		writeError(writer, http.StatusRequestEntityTooLarge, "effect request exceeds size limit")
		return
	}
	if !contentLengthHeaderMatches(request.Header, request.ContentLength) {
		writeError(writer, http.StatusBadRequest, "Content-Length does not match the parsed request length")
		return
	}
	request.Body = http.MaxBytesReader(writer, request.Body, maxEffectRequestBytes)
	body, err := io.ReadAll(request.Body)
	if err != nil {
		var maxBytesError *http.MaxBytesError
		if errors.As(err, &maxBytesError) {
			writeError(writer, http.StatusRequestEntityTooLarge, "effect request exceeds size limit")
			return
		}
		writeError(writer, http.StatusBadRequest, "read effect request body")
		return
	}
	if int64(len(body)) != request.ContentLength {
		writeError(writer, http.StatusBadRequest, "effect request length does not match Content-Length")
		return
	}
	input, err := decodeEffectRequest(body)
	if err != nil {
		writeError(writer, http.StatusBadRequest, err.Error())
		return
	}
	route, ok := selectRoute(candidates, input.ClosureVersion)
	if !ok {
		writeError(writer, http.StatusBadRequest, "closure_version is not declared for this provider path")
		return
	}
	callID := input.OrderID
	if route.CallIDMode == callIDCompleteOrder {
		callID = "complete:" + input.OrderID
	}
	expectedOperationID := deriveOperationID(callID)
	if operationID != expectedOperationID || idempotencyKey != expectedOperationID {
		writeError(writer, http.StatusBadRequest, "Operation and idempotency identities do not match the declared call")
		return
	}

	ctx, cancel := context.WithTimeout(request.Context(), a.executionTimeout)
	defer cancel()
	outcome, executeErr := a.executor.Execute(ctx, api.ExecuteRequest{
		CallID: callID, Kind: route.Kind, Method: http.MethodPost, URL: route.Target,
		Headers: map[string]string{"Content-Type": contentType}, Body: body,
	})
	if executeErr != nil {
		a.writeExecuteError(writer, outcome, executeErr)
		return
	}
	if outcome.OperationID != expectedOperationID {
		writeError(writer, http.StatusBadGateway, "control API returned the wrong Operation identity")
		return
	}
	if len(outcome.Body) > maxEffectResponseBytes {
		writeError(writer, http.StatusBadGateway, "control API returned an oversized provider record")
		return
	}
	if outcome.RecoveredByQuery {
		receipt, err := receiptFromObservation(outcome, expectedOperationID)
		if err != nil {
			writeError(writer, http.StatusBadGateway, "control API returned an invalid provider observation")
			return
		}
		encoded, err := json.Marshal(receipt)
		if err != nil {
			writeError(writer, http.StatusInternalServerError, "encode provider receipt")
			return
		}
		writeRawJSON(writer, http.StatusOK, encoded)
		return
	}
	if err := validateProviderReceipt(outcome, expectedOperationID); err != nil {
		writeError(writer, http.StatusBadGateway, "control API returned an invalid provider receipt")
		return
	}
	// The ordinary path preserves both status and bytes. Re-encoding here would
	// make the same provider fact look different depending on settlement path.
	writeRawJSON(writer, outcome.StatusCode, outcome.Body)
}

func (a *Adapter) serveHealth(writer http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet {
		writer.Header().Set("Allow", http.MethodGet)
		writeError(writer, http.StatusMethodNotAllowed, "health check requires GET")
		return
	}
	if request.URL.RawQuery != "" || request.URL.ForceQuery {
		writeError(writer, http.StatusBadRequest, "health check does not accept query parameters")
		return
	}
	writeRawJSON(writer, http.StatusOK, []byte(`{"status":"ok"}`))
}

func (a *Adapter) writeExecuteError(writer http.ResponseWriter, outcome gateway.Outcome, err error) {
	status := http.StatusBadGateway
	message := "control API failed to execute provider Operation"
	switch {
	case errors.Is(err, context.DeadlineExceeded), errors.Is(err, context.Canceled):
		status = http.StatusGatewayTimeout
		message = "control API execution deadline expired"
	case errors.Is(err, gateway.ErrOutcomeUnknown), errors.Is(err, gateway.ErrOperationInFlight),
		errors.Is(err, gateway.ErrOperationRequestConflict), outcome.Phase == kernel.Unknown,
		outcome.Phase == kernel.Dispatched:
		status = http.StatusConflict
		message = "provider Operation is not safely settled"
	}
	writeError(writer, status, message)
}

func selectRoute(candidates []Route, closureVersion *string) (Route, bool) {
	for _, route := range candidates {
		switch route.ClosureVersion.Mode {
		case closureAbsent:
			if closureVersion == nil {
				return route, true
			}
		case closureExact:
			if closureVersion != nil && *closureVersion == route.ClosureVersion.Value {
				return route, true
			}
		}
	}
	return Route{}, false
}

func decodeEffectRequest(body []byte) (effectRequest, error) {
	fields, err := decodeExactObject(body, "effect request", map[string]bool{
		"order_id": true, "amount_cents": true,
	}, map[string]bool{"closure_version": true})
	if err != nil {
		return effectRequest{}, err
	}
	var input effectRequest
	if err := decodeNonNullField(fields, "order_id", &input.OrderID); err != nil {
		return effectRequest{}, fmt.Errorf("effect request %w", err)
	}
	if !safeOrderID(input.OrderID) {
		return effectRequest{}, fmt.Errorf("effect request order_id must contain between 1 and %d stable bytes", maxOrderIDBytes)
	}
	amountRaw := strings.TrimSpace(string(fields["amount_cents"]))
	amount, err := parseCanonicalPositiveInteger(amountRaw)
	if err != nil || amount > maxAmountCents {
		return effectRequest{}, fmt.Errorf("effect request amount_cents must be a canonical integer between 1 and %d", maxAmountCents)
	}
	input.AmountCents = amount
	if _, present := fields["closure_version"]; present {
		var closure string
		if err := decodeNonNullField(fields, "closure_version", &closure); err != nil {
			return effectRequest{}, fmt.Errorf("effect request %w", err)
		}
		if !safeConfigText(closure, kernel.MaxNameBytes) {
			return effectRequest{}, errors.New("effect request closure_version is invalid")
		}
		input.ClosureVersion = &closure
	}
	return input, nil
}

func parseCanonicalPositiveInteger(value string) (int64, error) {
	if value == "" || value == "0" || value[0] == '-' || (len(value) > 1 && value[0] == '0') {
		return 0, errors.New("not a canonical positive integer")
	}
	for _, character := range []byte(value) {
		if character < '0' || character > '9' {
			return 0, errors.New("not a canonical positive integer")
		}
	}
	return strconv.ParseInt(value, 10, 64)
}

func safeOrderID(value string) bool {
	if value == "" || len(value) > maxOrderIDBytes || !utf8.ValidString(value) || strings.TrimSpace(value) != value {
		return false
	}
	// Excluding ':' keeps charge(order_id) disjoint from
	// completion("complete:"+order_id) within the fixed Operation domain.
	for _, character := range []byte(value) {
		if (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') || strings.ContainsRune("._-", rune(character)) {
			continue
		}
		return false
	}
	return true
}

var errUnsupportedContentType = errors.New("exactly one application/json Content-Type is required")

func validateRequestHeaders(header http.Header) (string, string, string, error) {
	allowed := map[string]bool{
		"content-type": true, "x-operation-id": true, "idempotency-key": true,
		"user-agent": true, "accept": true, "accept-encoding": true, "content-length": true,
	}
	seen := make(map[string]bool, len(header))
	for name, values := range header {
		lower := strings.ToLower(name)
		if !allowed[lower] || seen[lower] {
			return "", "", "", fmt.Errorf("HTTP header %q is not accepted", name)
		}
		seen[lower] = true
		if len(values) != 1 || !safeHeaderValue(values[0], maxAuxHeaderBytes) {
			return "", "", "", fmt.Errorf("HTTP header %q must contain one bounded value", name)
		}
	}
	contentTypeValues := headerValues(header, "content-type")
	if len(contentTypeValues) != 1 {
		return "", "", "", errUnsupportedContentType
	}
	mediaType, parameters, err := mime.ParseMediaType(contentTypeValues[0])
	if err != nil || mediaType != "application/json" || len(parameters) != 0 {
		return "", "", "", errUnsupportedContentType
	}
	if values := headerValues(header, "accept"); len(values) == 1 && values[0] != "application/json" {
		return "", "", "", errors.New("Accept, when present, must be application/json")
	}
	if values := headerValues(header, "accept-encoding"); len(values) == 1 && values[0] != "gzip" && values[0] != "identity" {
		return "", "", "", errors.New("Accept-Encoding is not supported")
	}
	operationValues := headerValues(header, "x-operation-id")
	idempotencyValues := headerValues(header, "idempotency-key")
	if len(operationValues) != 1 || len(idempotencyValues) != 1 ||
		!canonicalOperationID(operationValues[0]) || !canonicalOperationID(idempotencyValues[0]) {
		return "", "", "", errors.New("exactly one canonical Operation and idempotency identity is required")
	}
	return operationValues[0], idempotencyValues[0], "application/json", nil
}

func contentLengthHeaderMatches(header http.Header, parsed int64) bool {
	values := headerValues(header, "content-length")
	return len(values) == 0 || len(values) == 1 && values[0] == strconv.FormatInt(parsed, 10)
}

func headerValues(header http.Header, lowerName string) []string {
	var values []string
	for name, candidates := range header {
		if strings.ToLower(name) == lowerName {
			values = append(values, candidates...)
		}
	}
	return values
}

func safeHeaderValue(value string, maxBytes int) bool {
	if len(value) > maxBytes || !utf8.ValidString(value) {
		return false
	}
	for _, character := range value {
		if unicode.IsControl(character) {
			return false
		}
	}
	return true
}

func deriveOperationID(callID string) string {
	digest := sha256.Sum256([]byte("operation-id-v1\x00" + operationDomain + "\x00" + callID))
	return "op-" + hex.EncodeToString(digest[:])
}

func canonicalOperationID(value string) bool {
	if len(value) != 3+sha256.Size*2 || !strings.HasPrefix(value, "op-") {
		return false
	}
	return canonicalSHA256(strings.TrimPrefix(value, "op-"))
}

func canonicalSHA256(value string) bool {
	if len(value) != sha256.Size*2 {
		return false
	}
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size && hex.EncodeToString(decoded) == value
}

func validateProviderReceipt(outcome gateway.Outcome, operationID string) error {
	if outcome.StatusCode != http.StatusOK || (outcome.Phase != kernel.Succeeded && outcome.Phase != kernel.Failed) ||
		!canonicalSHA256(outcome.ResultHash) {
		return errors.New("invalid provider receipt outcome metadata")
	}
	fields, err := decodeExactObject(outcome.Body, "provider receipt", map[string]bool{
		"schema": true, "operation_id": true, "outcome": true,
		"result_hash": true, "remote_reference": true,
	}, nil)
	if err != nil {
		return err
	}
	var receipt effectReceipt
	for name, target := range map[string]any{
		"schema": &receipt.Schema, "operation_id": &receipt.OperationID,
		"outcome": &receipt.Outcome, "result_hash": &receipt.ResultHash,
		"remote_reference": &receipt.RemoteReference,
	} {
		if err := decodeNonNullField(fields, name, target); err != nil {
			return err
		}
	}
	if receipt.Schema != 1 || receipt.OperationID != operationID || receipt.Outcome != string(outcome.Phase) ||
		receipt.ResultHash != outcome.ResultHash || !canonicalSHA256(receipt.ResultHash) ||
		len(receipt.RemoteReference) > maxRemoteReferenceBytes ||
		(receipt.RemoteReference != "" && !safeConfigText(receipt.RemoteReference, maxRemoteReferenceBytes)) ||
		(outcome.Phase == kernel.Succeeded && receipt.RemoteReference == "") {
		return errors.New("provider receipt does not match control outcome")
	}
	return nil
}

func receiptFromObservation(outcome gateway.Outcome, operationID string) (effectReceipt, error) {
	if outcome.StatusCode != http.StatusOK || (outcome.Phase != kernel.Succeeded && outcome.Phase != kernel.Failed) ||
		!canonicalSHA256(outcome.ResultHash) {
		return effectReceipt{}, errors.New("invalid provider observation outcome metadata")
	}
	fields, err := decodeExactObject(outcome.Body, "provider observation", map[string]bool{
		"schema": true, "operation_id": true, "request_hash": true,
		"outcome": true, "fact_hash": true, "remote_reference": true,
	}, nil)
	if err != nil {
		return effectReceipt{}, err
	}
	var observation operationObservation
	for name, target := range map[string]any{
		"schema": &observation.Schema, "operation_id": &observation.OperationID,
		"request_hash": &observation.RequestHash, "outcome": &observation.Outcome,
		"fact_hash": &observation.FactHash, "remote_reference": &observation.RemoteReference,
	} {
		if err := decodeNonNullField(fields, name, target); err != nil {
			return effectReceipt{}, err
		}
	}
	if observation.Schema != 1 || observation.OperationID != operationID ||
		observation.Outcome != string(outcome.Phase) || !canonicalSHA256(observation.RequestHash) ||
		observation.FactHash != outcome.ResultHash || !canonicalSHA256(observation.FactHash) ||
		len(observation.RemoteReference) > maxRemoteReferenceBytes ||
		(observation.RemoteReference != "" && !safeConfigText(observation.RemoteReference, maxRemoteReferenceBytes)) ||
		(outcome.Phase == kernel.Succeeded && observation.RemoteReference == "") {
		return effectReceipt{}, errors.New("provider observation does not match control outcome")
	}
	return effectReceipt{
		Schema: 1, OperationID: observation.OperationID, Outcome: observation.Outcome,
		ResultHash: observation.FactHash, RemoteReference: observation.RemoteReference,
	}, nil
}

func secureResponse(writer http.ResponseWriter) {
	writer.Header().Set("Cache-Control", "no-store")
	writer.Header().Set("X-Content-Type-Options", "nosniff")
}

func writeRawJSON(writer http.ResponseWriter, status int, body []byte) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_, _ = writer.Write(body)
}

func writeError(writer http.ResponseWriter, status int, message string) {
	encoded, err := json.Marshal(errorResponse{Schema: 1, Error: message})
	if err != nil {
		http.Error(writer, "internal error", http.StatusInternalServerError)
		return
	}
	writeRawJSON(writer, status, encoded)
}
