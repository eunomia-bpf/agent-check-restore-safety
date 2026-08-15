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
	if len(credentials.Adapters) == 0 {
		return nil, errors.New("at least one adapter credential is required")
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
	server.mux.HandleFunc("POST /v1/activate", server.activate)
	return server, nil
}

func (s *Server) Handler() http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
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
			s.execute(writer, request, adapter)
			return
		} else if !admin {
			writer.Header().Set("WWW-Authenticate", "Bearer")
			writeError(writer, http.StatusUnauthorized, errors.New("admin token required"))
			return
		}
		s.mux.ServeHTTP(writer, request)
	})
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

type errorBody struct {
	Error string `json:"error"`
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

type executeRequest struct {
	CallID  string            `json:"call_id"`
	Kind    string            `json:"kind"`
	Method  string            `json:"method,omitempty"`
	URL     string            `json:"url"`
	Headers map[string]string `json:"headers,omitempty"`
	Body    []byte            `json:"body,omitempty"`
}

func (s *Server) execute(writer http.ResponseWriter, request *http.Request, adapter adapterCredential) {
	var body executeRequest
	if err := decode(request, &body); err != nil {
		writeError(writer, http.StatusBadRequest, err)
		return
	}
	if body.CallID == "" {
		writeError(writer, http.StatusBadRequest, errors.New("adapter call identity is required"))
		return
	}
	if len(body.CallID) > 1024 {
		writeError(writer, http.StatusBadRequest, errors.New("adapter call identity is too large"))
		return
	}
	if !adapter.kinds[body.Kind] {
		writeError(writer, http.StatusForbidden, errors.New("adapter credential does not allow this operation kind"))
		return
	}
	outcome, err := s.gateway.Execute(request.Context(), gateway.Request{
		ID:      deriveOperationID(adapter.domain, body.CallID),
		Domain:  adapter.domain,
		Kind:    body.Kind,
		Method:  body.Method,
		URL:     body.URL,
		Headers: body.Headers,
		Body:    body.Body,
	})
	if err != nil {
		status := http.StatusUnprocessableEntity
		if errors.Is(err, gateway.ErrOutcomeUnknown) {
			status = http.StatusConflict
		}
		writeJSON(writer, status, struct {
			Outcome gateway.Outcome `json:"outcome"`
			Error   string          `json:"error"`
		}{Outcome: outcome, Error: err.Error()})
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
