package provideradapter

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"mime"
	"net/http"
	"path"
	"strings"
)

const (
	// MaxRequestBytes is the largest body the runtime can persist for one
	// Operation. A Handler may choose a smaller limit but never a larger one.
	MaxRequestBytes     int64 = 1 << 20
	maxContentTypeBytes       = 1024
)

// Driver translates a stable runtime Operation into provider-specific work.
// Implementations keep credentials in private startup state and must never
// derive them from Effect or Query fields.
type Driver interface {
	Execute(context.Context, Effect) (Result, error)
	Observe(context.Context, Query) (Result, error)
}

// Config binds one Handler to immutable, versioned effect and observation
// paths. MaxRequestBytes defaults to the package limit when zero.
type Config struct {
	EffectPath      string
	QueryPath       string
	MaxRequestBytes int64
}

// Handler implements the runtime-facing HTTP protocol for one Driver.
type Handler struct {
	driver          Driver
	effectPath      string
	queryPath       string
	maxRequestBytes int64
}

type errorResponse struct {
	Error string `json:"error"`
}

// NewHandler validates and freezes the adapter's paths and request limit.
func NewHandler(config Config, driver Driver) (*Handler, error) {
	if driver == nil {
		return nil, errors.New("provider adapter driver is nil")
	}
	if !validEndpointPath(config.EffectPath) || !validEndpointPath(config.QueryPath) {
		return nil, errors.New("provider adapter paths must be distinct, clean absolute paths")
	}
	if config.EffectPath == config.QueryPath || config.EffectPath == "/healthz" || config.QueryPath == "/healthz" {
		return nil, errors.New("provider adapter paths must be distinct and cannot replace /healthz")
	}
	limit := config.MaxRequestBytes
	if limit == 0 {
		limit = MaxRequestBytes
	}
	if limit < 1 || limit > MaxRequestBytes {
		return nil, errors.New("provider adapter request limit is outside the supported range")
	}
	return &Handler{
		driver: driver, effectPath: config.EffectPath, queryPath: config.QueryPath,
		maxRequestBytes: limit,
	}, nil
}

// ServeHTTP exposes the fixed effect, observation, and health endpoints.
func (handler *Handler) ServeHTTP(writer http.ResponseWriter, request *http.Request) {
	secureResponse(writer)
	if request.URL.Path == "/healthz" {
		if request.Method != http.MethodGet || request.URL.RawQuery != "" {
			writer.Header().Set("Allow", http.MethodGet)
			writeError(writer, http.StatusMethodNotAllowed, "health check requires GET without a query")
			return
		}
		writeJSON(writer, http.StatusOK, struct {
			Status string `json:"status"`
		}{Status: "ok"})
		return
	}

	switch request.URL.Path {
	case handler.effectPath:
		if request.Method != http.MethodPost {
			writer.Header().Set("Allow", http.MethodPost)
			writeError(writer, http.StatusMethodNotAllowed, "effect endpoint requires POST")
			return
		}
		if request.URL.RawQuery != "" {
			writeError(writer, http.StatusBadRequest, "effect endpoint does not accept a query")
			return
		}
		handler.execute(writer, request)
	case handler.queryPath:
		if request.Method != http.MethodPost {
			writer.Header().Set("Allow", http.MethodPost)
			writeError(writer, http.StatusMethodNotAllowed, "observation endpoint requires POST")
			return
		}
		if request.URL.RawQuery != "" {
			writeError(writer, http.StatusBadRequest, "observation endpoint does not accept a query")
			return
		}
		handler.observe(writer, request)
	default:
		writeError(writer, http.StatusNotFound, "provider adapter endpoint not found")
	}
}

func (handler *Handler) execute(writer http.ResponseWriter, request *http.Request) {
	operationID, err := exactlyOneHeader(request.Header, HeaderOperationID)
	if err != nil || !canonicalOperationID(operationID) {
		writeError(writer, http.StatusBadRequest, "effect request has an invalid Operation identity")
		return
	}
	idempotencyKey, err := exactlyOneHeader(request.Header, HeaderIdempotencyKey)
	if err != nil || idempotencyKey != operationID {
		writeError(writer, http.StatusBadRequest, "effect request has a mismatched idempotency identity")
		return
	}
	requestHash, err := exactlyOneHeader(request.Header, HeaderOperationRequestHash)
	if err != nil || !canonicalSHA256(requestHash) {
		writeError(writer, http.StatusBadRequest, "effect request has an invalid request hash")
		return
	}
	contentType, err := contentTypeHeader(request.Header)
	if err != nil {
		writeError(writer, http.StatusBadRequest, "effect request has an invalid Content-Type")
		return
	}
	body, err := handler.readBody(writer, request)
	if err != nil {
		handler.writeBodyError(writer, err)
		return
	}

	result, err := handler.driver.Execute(request.Context(), Effect{
		OperationID: operationID, IdempotencyKey: idempotencyKey,
		RequestHash: requestHash, ContentType: contentType, Body: body,
	})
	if err != nil {
		writeError(writer, http.StatusBadGateway, "provider adapter could not settle the effect")
		return
	}
	if err := validateEffectResult(result); err != nil {
		writeError(writer, http.StatusInternalServerError, "provider adapter returned an invalid effect result")
		return
	}
	writeJSON(writer, http.StatusOK, receiptV1{
		Schema: 1, OperationID: operationID, Outcome: result.Outcome,
		ResultHash: result.FactHash, RemoteReference: result.RemoteReference,
	})
}

func (handler *Handler) observe(writer http.ResponseWriter, request *http.Request) {
	operationID, err := exactlyOneHeader(request.Header, HeaderOperationID)
	if err != nil || !canonicalOperationID(operationID) {
		writeError(writer, http.StatusBadRequest, "observation request has an invalid Operation identity")
		return
	}
	requestHash, err := exactlyOneHeader(request.Header, HeaderOperationRequestHash)
	if err != nil || !canonicalSHA256(requestHash) {
		writeError(writer, http.StatusBadRequest, "observation request has an invalid request hash")
		return
	}
	if len(headerValues(request.Header, HeaderIdempotencyKey)) != 0 {
		writeError(writer, http.StatusBadRequest, "observation request carries an effect idempotency key")
		return
	}
	contentType, err := contentTypeHeader(request.Header)
	if err != nil {
		writeError(writer, http.StatusBadRequest, "observation request has an invalid Content-Type")
		return
	}
	body, err := handler.readBody(writer, request)
	if err != nil {
		handler.writeBodyError(writer, err)
		return
	}

	result, err := handler.driver.Observe(request.Context(), Query{
		OperationID: operationID, RequestHash: requestHash,
		ContentType: contentType, Body: body,
	})
	if err != nil {
		writeError(writer, http.StatusBadGateway, "provider adapter could not observe the effect")
		return
	}
	if err := validateObservationResult(result); err != nil {
		writeError(writer, http.StatusInternalServerError, "provider adapter returned an invalid observation result")
		return
	}
	writeJSON(writer, http.StatusOK, observationV1{
		Schema: 1, OperationID: operationID, RequestHash: requestHash,
		Outcome: result.Outcome, FactHash: result.FactHash,
		RemoteReference: result.RemoteReference,
	})
}

var errBodyTooLarge = errors.New("provider adapter request body is too large")

func (handler *Handler) readBody(writer http.ResponseWriter, request *http.Request) ([]byte, error) {
	if request.ContentLength > handler.maxRequestBytes {
		return nil, errBodyTooLarge
	}
	if request.Body == nil {
		return []byte{}, nil
	}
	limited := http.MaxBytesReader(writer, request.Body, handler.maxRequestBytes)
	body, err := io.ReadAll(limited)
	if err != nil {
		var maxBytesError *http.MaxBytesError
		if errors.As(err, &maxBytesError) {
			return nil, errBodyTooLarge
		}
		return nil, err
	}
	return body, nil
}

func (handler *Handler) writeBodyError(writer http.ResponseWriter, err error) {
	if errors.Is(err, errBodyTooLarge) {
		writeError(writer, http.StatusRequestEntityTooLarge, "provider adapter request body exceeds its limit")
		return
	}
	writeError(writer, http.StatusBadRequest, "provider adapter could not read the request body")
}

func exactlyOneHeader(header http.Header, name string) (string, error) {
	values := headerValues(header, name)
	if len(values) != 1 || values[0] == "" || strings.TrimSpace(values[0]) != values[0] || strings.ContainsAny(values[0], "\r\n\x00") {
		return "", errors.New("header must occur exactly once with a stable value")
	}
	return values[0], nil
}

func headerValues(header http.Header, name string) []string {
	var values []string
	for candidate, candidateValues := range header {
		if strings.EqualFold(candidate, name) {
			values = append(values, candidateValues...)
		}
	}
	return values
}

func contentTypeHeader(header http.Header) (string, error) {
	values := headerValues(header, "Content-Type")
	if len(values) == 0 {
		return "", nil
	}
	if len(values) != 1 || values[0] == "" || len(values[0]) > maxContentTypeBytes || strings.ContainsAny(values[0], "\r\n\x00") {
		return "", errors.New("invalid Content-Type header")
	}
	if _, _, err := mime.ParseMediaType(values[0]); err != nil {
		return "", errors.New("invalid Content-Type media type")
	}
	return values[0], nil
}

func validEndpointPath(value string) bool {
	return value != "" && len(value) <= 256 && strings.HasPrefix(value, "/") &&
		!strings.ContainsAny(value, "?#\\\x00") && path.Clean(value) == value
}

func secureResponse(writer http.ResponseWriter) {
	writer.Header().Set("Cache-Control", "no-store")
	writer.Header().Set("X-Content-Type-Options", "nosniff")
}

func writeError(writer http.ResponseWriter, status int, message string) {
	writeJSON(writer, status, errorResponse{Error: message})
}

func writeJSON(writer http.ResponseWriter, status int, value any) {
	encoded, err := json.Marshal(value)
	if err != nil {
		encoded = []byte(`{"error":"provider adapter could not encode its response"}`)
		status = http.StatusInternalServerError
	}
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_, _ = writer.Write(encoded)
}
