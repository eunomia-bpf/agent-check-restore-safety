// Package api exposes the durable control service over a small local HTTP API.
package api

import (
	"bytes"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const maxRequestBytes = 4 << 20

type Server struct {
	control    *control.Control
	gateway    *gateway.Gateway
	adminToken string
	adapters   []adapterCredential
	mux        *http.ServeMux
}

type Credentials struct {
	AdminToken string
	Adapters   []AdapterCredential
}

type AdapterCredential struct {
	Token  string
	Domain string
	Kinds  []string
}

type adapterCredential struct {
	token  string
	domain string
	kinds  map[string]bool
}

func New(c *control.Control, client *http.Client, credentials Credentials) (*Server, error) {
	if c == nil {
		return nil, errors.New("nil control")
	}
	if len(credentials.AdminToken) < 32 {
		return nil, errors.New("admin API token must contain at least 32 bytes")
	}
	g, err := gateway.New(c, client)
	if err != nil {
		return nil, err
	}
	server := &Server{
		control:    c,
		gateway:    g,
		adminToken: credentials.AdminToken,
		mux:        http.NewServeMux(),
	}
	seenDomains := make(map[string]bool)
	seenTokens := make(map[string]bool)
	for _, credential := range credentials.Adapters {
		if len(credential.Token) < 32 || secureEqual(credential.Token, credentials.AdminToken) {
			return nil, errors.New("adapter token must contain at least 32 bytes and differ from admin")
		}
		if seenTokens[credential.Token] {
			return nil, errors.New("adapter tokens must be unique")
		}
		seenTokens[credential.Token] = true
		if credential.Domain == "" || len(credential.Domain) > kernel.MaxNameBytes || seenDomains[credential.Domain] {
			return nil, errors.New("adapter domains must be nonempty and unique")
		}
		seenDomains[credential.Domain] = true
		kinds := make(map[string]bool, len(credential.Kinds))
		for _, kind := range credential.Kinds {
			if kind == "" || len(kind) > kernel.MaxNameBytes || kinds[kind] {
				return nil, errors.New("adapter kinds must be nonempty and unique")
			}
			kinds[kind] = true
		}
		if len(kinds) == 0 {
			return nil, errors.New("adapter credential has no allowed kind")
		}
		server.adapters = append(server.adapters, adapterCredential{
			token: credential.Token, domain: credential.Domain, kinds: kinds,
		})
	}
	server.mux.HandleFunc("GET /v1/state", server.state)
	server.mux.HandleFunc("GET /v1/history", server.history)
	server.mux.HandleFunc("POST /v1/compile", server.compile)
	server.mux.HandleFunc("POST /v1/certificate-state", server.certificateState)
	server.mux.HandleFunc("POST /v1/activate", server.activate)
	server.mux.HandleFunc("POST /v1/cutover", server.cutover)
	server.mux.HandleFunc("GET /v1/sandbox-bindings", server.sandboxBindings)
	server.mux.HandleFunc("POST /v1/operations/{id}/recover", server.recover)
	return server, nil
}

func (s *Server) Handler() http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/healthz" {
			if request.Method != http.MethodGet {
				writer.Header().Set("Allow", http.MethodGet)
				writeError(writer, http.StatusMethodNotAllowed, errors.New("health check requires GET"))
				return
			}
			writeJSON(writer, http.StatusOK, struct {
				Status string `json:"status"`
			}{Status: "ok"})
			return
		}
		token := strings.TrimPrefix(request.Header.Get("Authorization"), "Bearer ")
		admin := secureEqual(token, s.adminToken)
		if request.URL.Path == "/v1/execute" {
			if request.Method != http.MethodPost {
				writer.Header().Set("Allow", http.MethodPost)
				writeError(writer, http.StatusMethodNotAllowed, errors.New("execute requires POST"))
				return
			}
			adapter, ok := s.adapterForToken(token)
			if !ok {
				writer.Header().Set("WWW-Authenticate", "Bearer")
				writeError(writer, http.StatusUnauthorized, errors.New("adapter token required"))
				return
			}
			s.execute(writer, request, adapter.domain, adapter.kinds, nil)
			return
		} else if !admin {
			writer.Header().Set("WWW-Authenticate", "Bearer")
			writeError(writer, http.StatusUnauthorized, errors.New("admin token required"))
			return
		}
		s.mux.ServeHTTP(writer, request)
	})
}

// HandlerForSandbox returns a restricted endpoint whose identity and authority
// are captured by a host-owned listener. It attaches the binding to this
// Control boot; the host supervisor must call DetachSandboxHost when it closes
// the endpoint. Sandbox request bytes cannot select an identity, domain,
// generation, HTTP method, or provider target, and this handler exposes no
// control-plane route.
func (s *Server) HandlerForSandbox(binding control.SandboxBinding) (http.Handler, error) {
	binding.AllowedKinds = append([]string(nil), binding.AllowedKinds...)
	if err := s.control.AttachSandboxHost(binding); err != nil {
		return nil, err
	}
	kinds := make(map[string]bool, len(binding.AllowedKinds))
	for _, kind := range binding.AllowedKinds {
		kinds[kind] = true
	}
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/healthz" {
			if request.Method != http.MethodGet {
				writer.Header().Set("Allow", http.MethodGet)
				writeError(writer, http.StatusMethodNotAllowed, errors.New("health check requires GET"))
				return
			}
			if err := s.control.ValidateSandbox(binding); err != nil {
				writeSandboxError(writer, err)
				return
			}
			writeJSON(writer, http.StatusOK, struct {
				Status string `json:"status"`
			}{Status: "ok"})
			return
		}
		if request.URL.Path != "/v1/execute" {
			http.NotFound(writer, request)
			return
		}
		if request.Method != http.MethodPost {
			writer.Header().Set("Allow", http.MethodPost)
			writeError(writer, http.StatusMethodNotAllowed, errors.New("execute requires POST"))
			return
		}
		if request.Header.Get("Authorization") != "" {
			writeError(writer, http.StatusBadRequest, errors.New("sandbox endpoint does not accept guest credentials"))
			return
		}
		s.execute(writer, request, binding.Domain, kinds, &binding)
	}), nil
}

func (s *Server) adapterForToken(token string) (adapterCredential, bool) {
	for _, adapter := range s.adapters {
		if secureEqual(token, adapter.token) {
			return adapter, true
		}
	}
	return adapterCredential{}, false
}

func secureEqual(left, right string) bool {
	if len(left) != len(right) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(left), []byte(right)) == 1
}

func writeJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}

func writeError(writer http.ResponseWriter, status int, err error) {
	writeJSON(writer, status, errorBody{Error: err.Error()})
}

func decode(request *http.Request, target any) error {
	data, err := io.ReadAll(io.LimitReader(request.Body, maxRequestBytes+1))
	if err != nil {
		return err
	}
	if len(data) > maxRequestBytes {
		return errors.New("request exceeds size limit")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("request contains multiple JSON values")
		}
		return err
	}
	return nil
}

func (s *Server) state(writer http.ResponseWriter, _ *http.Request) {
	writeJSON(writer, http.StatusOK, s.control.Snapshot())
}

func (s *Server) history(writer http.ResponseWriter, _ *http.Request) {
	writeJSON(writer, http.StatusOK, s.control.Events())
}

func (s *Server) compile(writer http.ResponseWriter, request *http.Request) {
	var requirement kernel.Requirement
	if err := decode(request, &requirement); err != nil {
		writeError(writer, http.StatusBadRequest, err)
		return
	}
	certificate, err := s.control.Compile(requirement)
	if err != nil {
		writeError(writer, http.StatusUnprocessableEntity, err)
		return
	}
	writeJSON(writer, http.StatusOK, certificate)
}

func (s *Server) certificateState(writer http.ResponseWriter, request *http.Request) {
	var certificate kernel.Certificate
	if err := decode(request, &certificate); err != nil {
		writeError(writer, http.StatusBadRequest, err)
		return
	}
	projection, err := s.control.CertificateState(certificate)
	if err != nil {
		writeError(writer, http.StatusUnprocessableEntity, err)
		return
	}
	writeJSON(writer, http.StatusOK, projection)
}

func (s *Server) activate(writer http.ResponseWriter, request *http.Request) {
	var certificate kernel.Certificate
	if err := decode(request, &certificate); err != nil {
		writeError(writer, http.StatusBadRequest, err)
		return
	}
	if err := s.control.Activate(certificate); err != nil {
		status := http.StatusUnprocessableEntity
		if strings.Contains(err.Error(), "stale") || strings.Contains(err.Error(), "different active rule") {
			status = http.StatusConflict
		}
		writeError(writer, status, err)
		return
	}
	writeJSON(writer, http.StatusOK, s.control.Snapshot())
}

func (s *Server) cutover(writer http.ResponseWriter, request *http.Request) {
	var body CutoverRequest
	if err := decode(request, &body); err != nil {
		writeError(writer, http.StatusBadRequest, err)
		return
	}
	if err := s.control.Cutover(body.Certificate, body.Bindings); err != nil {
		status := http.StatusUnprocessableEntity
		if strings.Contains(err.Error(), "stale") || strings.Contains(err.Error(), "different active rule") ||
			errors.Is(err, control.ErrActiveAdapterDispatch) {
			status = http.StatusConflict
		}
		writeError(writer, status, err)
		return
	}
	state, bindings := s.control.SnapshotWithSandboxBindings()
	writeJSON(writer, http.StatusOK, CutoverResponse{State: state, Bindings: bindings})
}

func (s *Server) sandboxBindings(writer http.ResponseWriter, _ *http.Request) {
	writeJSON(writer, http.StatusOK, s.control.SandboxBindings())
}

func (s *Server) execute(
	writer http.ResponseWriter,
	request *http.Request,
	domain string,
	kinds map[string]bool,
	binding *control.SandboxBinding,
) {
	var body ExecuteRequest
	if binding == nil {
		if err := decode(request, &body); err != nil {
			writeError(writer, http.StatusBadRequest, err)
			return
		}
	} else {
		var guest sandboxExecuteRequest
		if err := decode(request, &guest); err != nil {
			writeError(writer, http.StatusBadRequest, err)
			return
		}
		body = ExecuteRequest{
			CallID: guest.CallID, Kind: guest.Kind, Headers: guest.Headers, Body: guest.Body,
		}
	}
	if body.CallID == "" {
		writeError(writer, http.StatusBadRequest, errors.New("adapter call identity is required"))
		return
	}
	if len(body.CallID) > 1024 {
		writeError(writer, http.StatusBadRequest, errors.New("adapter call identity is too large"))
		return
	}
	operationID := deriveOperationID(domain, body.CallID)
	var prior kernel.Operation
	var exists bool
	var err error
	if binding == nil {
		prior, exists, err = s.control.OperationForAdapter(domain, operationID)
	} else {
		prior, exists, err = s.control.OperationForSandbox(*binding, operationID)
	}
	if err != nil {
		writeSandboxError(writer, err)
		return
	}
	if exists && prior.Domain != domain {
		writeError(writer, http.StatusForbidden, errors.New("operation identity belongs to another adapter domain"))
		return
	}
	if !exists && !kinds[body.Kind] {
		writeError(writer, http.StatusForbidden, errors.New("adapter credential does not allow this operation kind"))
		return
	}
	if binding != nil {
		if exists {
			body.Method = prior.Method
			body.URL = prior.Target
		} else {
			body.Method, body.URL, err = s.control.OperationRouteForSandbox(*binding, body.Kind)
			if err != nil {
				writeSandboxError(writer, err)
				return
			}
		}
	}
	operationRequest := gateway.Request{
		ID:      operationID,
		Domain:  domain,
		Kind:    body.Kind,
		Method:  body.Method,
		URL:     body.URL,
		Headers: body.Headers,
		Body:    body.Body,
	}
	var outcome gateway.Outcome
	if binding == nil {
		outcome, err = s.gateway.Execute(request.Context(), operationRequest)
	} else {
		outcome, err = s.gateway.ExecuteBound(request.Context(), *binding, operationRequest)
	}
	if binding != nil {
		release, responseErr := s.control.BeginSandboxResponse(*binding)
		if responseErr != nil {
			writeSandboxError(writer, responseErr)
			return
		}
		defer release()
	}
	if err != nil {
		status := http.StatusUnprocessableEntity
		code := ""
		if errors.Is(err, gateway.ErrOutcomeUnknown) {
			status = http.StatusConflict
			code = OperationErrorOutcomeUnknown
		} else if errors.Is(err, gateway.ErrOperationRequestConflict) {
			status = http.StatusConflict
			code = OperationErrorRequestConflict
		} else if errors.Is(err, control.ErrStaleSandboxBinding) ||
			errors.Is(err, control.ErrSandboxNotAttached) ||
			errors.Is(err, control.ErrSandboxBindingRequired) {
			status = http.StatusConflict
			code = OperationErrorSandboxStale
		}
		writeJSON(writer, status, OperationError{Outcome: outcome, Error: err.Error(), Code: code})
		if binding != nil {
			_ = http.NewResponseController(writer).Flush()
		}
		return
	}
	writeJSON(writer, http.StatusOK, outcome)
	if binding != nil {
		_ = http.NewResponseController(writer).Flush()
	}
}

func writeSandboxError(writer http.ResponseWriter, err error) {
	status := http.StatusUnprocessableEntity
	code := ""
	if errors.Is(err, control.ErrStaleSandboxBinding) || errors.Is(err, control.ErrSandboxNotAttached) ||
		errors.Is(err, control.ErrSandboxBindingRequired) {
		status = http.StatusConflict
		code = OperationErrorSandboxStale
	}
	writeJSON(writer, status, OperationError{Error: err.Error(), Code: code})
}

func (s *Server) recover(writer http.ResponseWriter, request *http.Request) {
	operationID := request.PathValue("id")
	if operationID == "" || len(operationID) > kernel.MaxNameBytes {
		writeError(writer, http.StatusBadRequest, errors.New("valid operation identity is required"))
		return
	}
	outcome, err := s.gateway.Recover(request.Context(), operationID)
	if err != nil {
		status := http.StatusUnprocessableEntity
		code := ""
		switch {
		case errors.Is(err, gateway.ErrOperationNotFound):
			status = http.StatusNotFound
		case errors.Is(err, gateway.ErrOutcomeUnknown):
			status = http.StatusConflict
			code = OperationErrorOutcomeUnknown
		}
		writeJSON(writer, status, OperationError{Outcome: outcome, Error: err.Error(), Code: code})
		return
	}
	writeJSON(writer, http.StatusOK, outcome)
}

func deriveOperationID(domain, callID string) string {
	hash := sha256.New()
	_, _ = hash.Write([]byte("operation-id-v1\x00"))
	_, _ = hash.Write([]byte(domain))
	_, _ = hash.Write([]byte{0})
	_, _ = hash.Write([]byte(callID))
	return "op-" + hex.EncodeToString(hash.Sum(nil))
}
