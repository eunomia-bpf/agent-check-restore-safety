package effectproxy

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
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
	MaxRequestBytes = int64(kernel.MaxOperationRequestBodyBytes)
	MaxCallIDBytes  = 1024
)

const (
	headerCallID           = "X-Safe-Change-Call-ID"
	headerOperationID      = "X-Safe-Change-Operation-ID"
	headerPhase            = "X-Safe-Change-Phase"
	headerResultHash       = "X-Safe-Change-Result-Hash"
	headerReused           = "X-Safe-Change-Reused"
	headerRecoveredByQuery = "X-Safe-Change-Recovered-By-Query"
)

// Executor is the only control-plane capability held by the proxy. In
// production it is implemented by apiclient.Client; tests inject a one-call
// recorder so retries and request authority are directly observable.
type Executor interface {
	Execute(context.Context, api.ExecuteRequest) (gateway.Outcome, error)
}

type Options struct {
	ExecutionTimeout time.Duration
}

type Proxy struct {
	executor         Executor
	routes           map[string]boundRoute
	executionTimeout time.Duration
}

type boundRoute struct {
	kind         string
	method       string
	url          string
	contentTypes map[string]bool
}

type errorBody struct {
	Error       string       `json:"error"`
	Detail      string       `json:"detail,omitempty"`
	OperationID string       `json:"operation_id,omitempty"`
	Phase       kernel.Phase `json:"phase,omitempty"`
}

func New(executor Executor, config Config, options Options) (*Proxy, error) {
	if executor == nil {
		return nil, errors.New("nil effect executor")
	}
	if options.ExecutionTimeout <= 0 {
		return nil, errors.New("effect execution timeout must be positive")
	}
	// Validate a copy. This also canonicalizes Content-Types without mutating a
	// caller-owned configuration while the proxy is serving requests.
	copyConfig := Config{Schema: config.Schema, Routes: make([]Route, len(config.Routes))}
	for index, route := range config.Routes {
		copyConfig.Routes[index] = route
		copyConfig.Routes[index].ContentTypes = append([]string(nil), route.ContentTypes...)
	}
	if err := validateConfig(&copyConfig); err != nil {
		return nil, err
	}
	proxy := &Proxy{
		executor: executor, routes: make(map[string]boundRoute, len(copyConfig.Routes)),
		executionTimeout: options.ExecutionTimeout,
	}
	for _, route := range copyConfig.Routes {
		contentTypes := make(map[string]bool, len(route.ContentTypes))
		for _, contentType := range route.ContentTypes {
			contentTypes[contentType] = true
		}
		proxy.routes[route.Name] = boundRoute{
			kind: route.Kind, method: route.Method, url: route.URL, contentTypes: contentTypes,
		}
	}
	return proxy, nil
}

func (p *Proxy) Handler() http.Handler {
	return http.HandlerFunc(p.serveHTTP)
}

func (p *Proxy) serveHTTP(writer http.ResponseWriter, request *http.Request) {
	secureResponse(writer)
	if request.URL.Path == "/healthz" {
		if request.Method != http.MethodGet {
			writer.Header().Set("Allow", http.MethodGet)
			writeError(writer, http.StatusMethodNotAllowed, errorBody{Error: "health check requires GET"})
			return
		}
		writeJSON(writer, http.StatusOK, struct {
			Status string `json:"status"`
		}{Status: "ok"})
		return
	}
	const routePrefix = "/v1/effects/"
	if !strings.HasPrefix(request.URL.Path, routePrefix) {
		writeError(writer, http.StatusNotFound, errorBody{Error: "effect route not found"})
		return
	}
	if request.Method != http.MethodPost {
		writer.Header().Set("Allow", http.MethodPost)
		writeError(writer, http.StatusMethodNotAllowed, errorBody{Error: "effect invocation requires POST"})
		return
	}
	routeName := strings.TrimPrefix(request.URL.Path, routePrefix)
	if routeName == "" || strings.Contains(routeName, "/") {
		writeError(writer, http.StatusNotFound, errorBody{Error: "effect route not found"})
		return
	}
	route, ok := p.routes[routeName]
	if !ok {
		writeError(writer, http.StatusNotFound, errorBody{Error: "effect route not found"})
		return
	}
	if request.URL.RawQuery != "" {
		writeError(writer, http.StatusBadRequest, errorBody{Error: "effect route does not accept query parameters"})
		return
	}
	callID, err := callIdentity(request.Header.Values(headerCallID))
	if err != nil {
		writeError(writer, http.StatusBadRequest, errorBody{Error: err.Error()})
		return
	}
	contentType, err := requestContentType(request.Header.Values("Content-Type"), route.contentTypes)
	if err != nil {
		writeError(writer, http.StatusUnsupportedMediaType, errorBody{Error: err.Error()})
		return
	}
	if request.ContentLength > MaxRequestBytes {
		writeError(writer, http.StatusRequestEntityTooLarge, errorBody{Error: "effect request exceeds size limit"})
		return
	}
	request.Body = http.MaxBytesReader(writer, request.Body, MaxRequestBytes)
	body, err := io.ReadAll(request.Body)
	if err != nil {
		var maxBytesError *http.MaxBytesError
		if errors.As(err, &maxBytesError) {
			writeError(writer, http.StatusRequestEntityTooLarge, errorBody{Error: "effect request exceeds size limit"})
			return
		}
		writeError(writer, http.StatusBadRequest, errorBody{Error: "read effect request body"})
		return
	}

	ctx, cancel := context.WithTimeout(request.Context(), p.executionTimeout)
	defer cancel()
	outcome, executeErr := p.executor.Execute(ctx, api.ExecuteRequest{
		CallID: callID, Kind: route.kind, Method: route.method, URL: route.url,
		Headers: map[string]string{"Content-Type": contentType}, Body: body,
	})
	if executeErr != nil {
		p.writeExecutionError(writer, outcome, executeErr)
		return
	}
	if outcome.Phase != kernel.Succeeded && outcome.Phase != kernel.Failed {
		p.writeExecutionError(writer, outcome, errors.New("control API returned an unsettled effect"))
		return
	}
	if outcome.StatusCode < 200 || outcome.StatusCode > 599 {
		writeError(writer, http.StatusBadGateway, errorBody{Error: "control API returned an invalid provider status"})
		return
	}
	if outcome.OperationID == "" || outcome.ResultHash == "" {
		writeError(writer, http.StatusBadGateway, errorBody{Error: "control API omitted required operation metadata"})
		return
	}
	if !writeOutcomeHeaders(writer.Header(), outcome) {
		writeError(writer, http.StatusBadGateway, errorBody{Error: "control API returned invalid operation metadata"})
		return
	}
	writer.Header().Set("Content-Type", "application/octet-stream")
	writer.WriteHeader(outcome.StatusCode)
	_, _ = writer.Write(outcome.Body)
}

func (p *Proxy) writeExecutionError(writer http.ResponseWriter, outcome gateway.Outcome, err error) {
	if !writeOutcomeHeaders(writer.Header(), outcome) {
		writeError(writer, http.StatusBadGateway, errorBody{Error: "control API returned invalid operation metadata"})
		return
	}
	status := http.StatusBadGateway
	message := "control API failed to execute effect"
	if errors.Is(err, gateway.ErrOutcomeUnknown) || outcome.Phase == kernel.Unknown || outcome.Phase == kernel.Dispatched {
		status = http.StatusConflict
		message = "effect outcome is not safely settled"
	} else if errors.Is(err, gateway.ErrOperationRequestConflict) {
		status = http.StatusConflict
		message = "effect call identity conflicts with its recorded request"
	}
	writeError(writer, status, errorBody{
		Error: message, Detail: err.Error(), OperationID: outcome.OperationID, Phase: outcome.Phase,
	})
}

func callIdentity(values []string) (string, error) {
	if len(values) != 1 {
		return "", errors.New("exactly one X-Safe-Change-Call-ID header is required")
	}
	value := values[0]
	if value == "" || len(value) > MaxCallIDBytes || strings.TrimSpace(value) != value || !utf8.ValidString(value) {
		return "", fmt.Errorf("X-Safe-Change-Call-ID must contain between 1 and %d stable bytes", MaxCallIDBytes)
	}
	for _, character := range value {
		if unicode.IsControl(character) {
			return "", errors.New("X-Safe-Change-Call-ID contains a control character")
		}
	}
	return value, nil
}

func requestContentType(values []string, allowed map[string]bool) (string, error) {
	if len(values) != 1 {
		return "", errors.New("exactly one allowed Content-Type header is required")
	}
	canonical, err := canonicalContentType(values[0])
	if err != nil || !allowed[canonical] {
		return "", errors.New("Content-Type is not allowed for this effect route")
	}
	return canonical, nil
}

func writeOutcomeHeaders(header http.Header, outcome gateway.Outcome) bool {
	metadata := []struct {
		name  string
		value string
		max   int
	}{
		{headerOperationID, outcome.OperationID, kernel.MaxNameBytes},
		{headerPhase, string(outcome.Phase), 32},
		{headerResultHash, outcome.ResultHash, 256},
	}
	for _, field := range metadata {
		if !safeHeaderValue(field.value, field.max) {
			return false
		}
	}
	for _, field := range metadata {
		if field.value != "" {
			header.Set(field.name, field.value)
		}
	}
	header.Set(headerReused, strconv.FormatBool(outcome.Reused))
	header.Set(headerRecoveredByQuery, strconv.FormatBool(outcome.RecoveredByQuery))
	return true
}

func safeHeaderValue(value string, max int) bool {
	if len(value) > max {
		return false
	}
	for _, character := range value {
		if character < 0x20 || character > 0x7e {
			return false
		}
	}
	return true
}

func secureResponse(writer http.ResponseWriter) {
	writer.Header().Set("Cache-Control", "no-store")
	writer.Header().Set("X-Content-Type-Options", "nosniff")
}

func writeJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}

func writeError(writer http.ResponseWriter, status int, body errorBody) {
	writeJSON(writer, status, body)
}
