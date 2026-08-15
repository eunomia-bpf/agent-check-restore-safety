// Package order is a deliberately ordinary business service. It has one
// process-wide release configuration and no logic for translating old order
// states. Stable work identity and old Operation meaning live in the control
// service instead.
package order

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	maxBodyBytes   = 1 << 20
	maxProxyURL    = 2048
	maxRouteBytes  = 128
	maxCallIDBytes = 1024
)

type Config struct {
	Version        string `json:"version"`
	Kind           string `json:"kind"`
	Target         string `json:"target"`
	EffectProxyURL string `json:"effect_proxy_url,omitempty"`
	EffectRoute    string `json:"effect_route,omitempty"`
}

func LoadConfig(path string) (Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Config{}, err
	}
	var config Config
	if err := decodeStrict(data, &config); err != nil {
		return Config{}, err
	}
	legacySelected := config.Kind != "" || config.Target != ""
	proxySelected := config.EffectProxyURL != "" || config.EffectRoute != ""
	if !proxySelected {
		// Keep the original legacy contract, including its validation error,
		// for existing release files.
		if config.Version == "" || config.Kind == "" || config.Target == "" {
			return Config{}, errors.New("order release requires version, kind, and target")
		}
		target, err := url.Parse(config.Target)
		if err != nil || (target.Scheme != "http" && target.Scheme != "https") || target.Host == "" || target.User != nil || target.Fragment != "" {
			return Config{}, errors.New("order release target must be an absolute HTTP URL")
		}
		return config, nil
	}
	if config.Version == "" {
		return Config{}, errors.New("order release requires version")
	}
	if legacySelected == proxySelected {
		return Config{}, errors.New("order release requires exactly one of kind/target or effect_proxy_url/effect_route")
	}
	if _, err := validatedProxyEndpoint(config.EffectProxyURL, config.EffectRoute); err != nil {
		return Config{}, err
	}
	return config, nil
}

// UsesEffectProxy reports which of the two mutually exclusive release modes
// was selected. LoadConfig and NewProxy reject partial or mixed modes.
func (c Config) UsesEffectProxy() bool {
	return c.EffectProxyURL != "" || c.EffectRoute != ""
}

type Service struct {
	config     Config
	controlURL string
	proxyURL   string
	token      string
	client     *http.Client
	proxy      bool
}

func New(config Config, controlURL, token string, client *http.Client) (*Service, error) {
	if config.UsesEffectProxy() {
		return nil, errors.New("legacy order release must not contain effect_proxy_url or effect_route")
	}
	parsed, err := url.Parse(controlURL)
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" || parsed.User != nil || parsed.Fragment != "" {
		return nil, errors.New("control URL must be an absolute HTTP URL")
	}
	if len(token) < 32 {
		return nil, errors.New("Operation API token is too short")
	}
	if client == nil {
		client = &http.Client{Timeout: 35 * time.Second}
	}
	return &Service{
		config: config, controlURL: strings.TrimRight(controlURL, "/"),
		token: token, client: client,
	}, nil
}

// NewProxy constructs an order release that can invoke one named effect but
// has neither an Operation API credential nor a physical payment target.
func NewProxy(config Config, client *http.Client) (*Service, error) {
	if config.Version == "" {
		return nil, errors.New("order release requires version")
	}
	if config.Kind != "" || config.Target != "" {
		return nil, errors.New("proxy order release must not contain kind or target")
	}
	proxyURL, err := validatedProxyEndpoint(config.EffectProxyURL, config.EffectRoute)
	if err != nil {
		return nil, err
	}
	return &Service{
		config: config, proxyURL: proxyURL, client: hardenedProxyClient(client), proxy: true,
	}, nil
}

func hardenedProxyClient(client *http.Client) *http.Client {
	if client == nil {
		client = &http.Client{Timeout: 35 * time.Second}
	}
	copyClient := *client
	if copyClient.Timeout <= 0 {
		copyClient.Timeout = 35 * time.Second
	}
	// A caller-supplied cookie jar is ambient authority just like an
	// environment-selected forward proxy.
	copyClient.Jar = nil
	transport := copyClient.Transport
	if transport == nil {
		transport = http.DefaultTransport
	}
	if standard, ok := transport.(*http.Transport); ok {
		copyTransport := standard.Clone()
		// The proxy is an explicit authority boundary. Never route it through
		// ambient process configuration, and do not add an implicit encoding.
		copyTransport.Proxy = nil
		copyTransport.DisableCompression = true
		copyClient.Transport = copyTransport
	}
	copyClient.CheckRedirect = func(_ *http.Request, _ []*http.Request) error {
		return http.ErrUseLastResponse
	}
	return &copyClient
}

func validatedProxyEndpoint(baseURL, route string) (string, error) {
	if baseURL == "" || len(baseURL) > maxProxyURL || strings.TrimSpace(baseURL) != baseURL || strings.ContainsAny(baseURL, "\r\n\x00") {
		return "", fmt.Errorf("effect_proxy_url must contain between 1 and %d safe bytes", maxProxyURL)
	}
	parsed, err := url.Parse(baseURL)
	if err != nil || !parsed.IsAbs() || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" || parsed.Hostname() == "" {
		return "", errors.New("effect_proxy_url must be an absolute HTTP URL")
	}
	if parsed.Opaque != "" || parsed.User != nil || parsed.Fragment != "" || parsed.RawQuery != "" || parsed.ForceQuery || parsed.RawPath != "" || (parsed.Path != "" && parsed.Path != "/") {
		return "", errors.New("effect_proxy_url must contain only an HTTP origin")
	}
	if !validEffectRoute(route) {
		return "", fmt.Errorf("effect_route must contain between 1 and %d URL-safe bytes", maxRouteBytes)
	}
	parsed.Path = "/v1/effects/" + route
	return parsed.String(), nil
}

func validEffectRoute(route string) bool {
	if route == "" || len(route) > maxRouteBytes {
		return false
	}
	for index, character := range []byte(route) {
		if (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') || (index > 0 && strings.ContainsRune("._-", rune(character))) {
			continue
		}
		return false
	}
	return true
}

func (s *Service) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(writer http.ResponseWriter, _ *http.Request) {
		if s.proxy {
			writeJSON(writer, http.StatusOK, map[string]any{
				"status": "ok", "version": s.config.Version,
				"requested_route": s.config.EffectRoute, "proxy": true,
			})
			return
		}
		writeJSON(writer, http.StatusOK, map[string]string{
			"status": "ok", "version": s.config.Version, "kind": s.config.Kind,
		})
	})
	mux.HandleFunc("POST /v1/orders", s.submit)
	return mux
}

type submitRequest struct {
	OrderID string `json:"order_id"`
	Amount  uint64 `json:"amount"`
}

type paymentRequest struct {
	OrderID string `json:"order_id"`
	Amount  uint64 `json:"amount"`
}

type executeRequest struct {
	CallID string `json:"call_id"`
	Kind   string `json:"kind"`
	Method string `json:"method"`
	URL    string `json:"url"`
	Body   []byte `json:"body"`
}

type submitResponse struct {
	ReleaseVersion  string          `json:"release_version"`
	RequestedKind   string          `json:"requested_kind"`
	RequestedTarget string          `json:"requested_target"`
	Runtime         json.RawMessage `json:"runtime"`
	RequestedRoute  string          `json:"requested_route,omitempty"`
	Proxy           bool            `json:"proxy,omitempty"`
}

type proxySubmitResponse struct {
	ReleaseVersion string          `json:"release_version"`
	Runtime        json.RawMessage `json:"runtime"`
	RequestedRoute string          `json:"requested_route"`
	Proxy          bool            `json:"proxy"`
}

func (s *Service) submit(writer http.ResponseWriter, request *http.Request) {
	body, err := io.ReadAll(io.LimitReader(request.Body, maxBodyBytes+1))
	if err != nil {
		writeError(writer, http.StatusBadRequest, err)
		return
	}
	if len(body) > maxBodyBytes {
		writeError(writer, http.StatusRequestEntityTooLarge, errors.New("order request exceeds size limit"))
		return
	}
	var submitted submitRequest
	if err := decodeStrict(body, &submitted); err != nil {
		writeError(writer, http.StatusBadRequest, err)
		return
	}
	if submitted.OrderID == "" || len(submitted.OrderID) > 256 || submitted.Amount == 0 {
		writeError(writer, http.StatusBadRequest, errors.New("order_id and a positive amount are required"))
		return
	}
	paymentBody, err := json.Marshal(paymentRequest{OrderID: submitted.OrderID, Amount: submitted.Amount})
	if err != nil {
		writeError(writer, http.StatusInternalServerError, err)
		return
	}
	if s.proxy {
		s.submitProxy(writer, request, submitted.OrderID, paymentBody)
		return
	}
	executeBody, err := json.Marshal(executeRequest{
		CallID: "order/" + submitted.OrderID + "/payment",
		Kind:   s.config.Kind, Method: http.MethodPost, URL: s.config.Target, Body: paymentBody,
	})
	if err != nil {
		writeError(writer, http.StatusInternalServerError, err)
		return
	}
	controlRequest, err := http.NewRequestWithContext(
		request.Context(), http.MethodPost, s.controlURL+"/v1/execute", bytes.NewReader(executeBody),
	)
	if err != nil {
		writeError(writer, http.StatusInternalServerError, err)
		return
	}
	controlRequest.Header.Set("Authorization", "Bearer "+s.token)
	controlRequest.Header.Set("Content-Type", "application/json")
	response, err := s.client.Do(controlRequest)
	if err != nil {
		writeError(writer, http.StatusBadGateway, fmt.Errorf("control service: %w", err))
		return
	}
	defer response.Body.Close()
	runtimeBody, err := io.ReadAll(io.LimitReader(response.Body, maxBodyBytes+1))
	if err != nil || len(runtimeBody) > maxBodyBytes {
		if err == nil {
			err = errors.New("control response exceeds size limit")
		}
		writeError(writer, http.StatusBadGateway, err)
		return
	}
	if !json.Valid(runtimeBody) {
		writeError(writer, http.StatusBadGateway, errors.New("control response is not JSON"))
		return
	}
	writeJSON(writer, response.StatusCode, submitResponse{
		ReleaseVersion: s.config.Version, RequestedKind: s.config.Kind,
		RequestedTarget: s.config.Target, Runtime: runtimeBody,
	})
}

func (s *Service) submitProxy(writer http.ResponseWriter, request *http.Request, orderID string, paymentBody []byte) {
	callID := "order/" + orderID + "/payment"
	if !validHeaderValue(callID) {
		writeError(writer, http.StatusBadRequest, errors.New("order_id cannot form a safe payment call identity"))
		return
	}
	proxyRequest, err := http.NewRequestWithContext(
		request.Context(), http.MethodPost, s.proxyURL, io.NopCloser(bytes.NewReader(paymentBody)),
	)
	if err != nil {
		writeError(writer, http.StatusInternalServerError, err)
		return
	}
	proxyRequest.Header.Set("Content-Type", "application/json")
	proxyRequest.Header.Set("X-Safe-Change-Call-ID", callID)
	// Suppress net/http's default User-Agent. DisableCompression on the
	// hardened transport likewise prevents an implicit Accept-Encoding.
	proxyRequest.Header["User-Agent"] = []string{""}
	response, err := s.client.Do(proxyRequest)
	if err != nil {
		writeError(writer, http.StatusBadGateway, fmt.Errorf("effect proxy: %w", err))
		return
	}
	defer response.Body.Close()
	runtimeBody, err := io.ReadAll(io.LimitReader(response.Body, maxBodyBytes+1))
	if err != nil || len(runtimeBody) > maxBodyBytes {
		if err == nil {
			err = errors.New("effect proxy response exceeds size limit")
		}
		writeError(writer, http.StatusBadGateway, err)
		return
	}
	if !json.Valid(runtimeBody) {
		writeError(writer, http.StatusBadGateway, errors.New("effect proxy response is not JSON"))
		return
	}
	writeJSON(writer, response.StatusCode, proxySubmitResponse{
		ReleaseVersion: s.config.Version, Runtime: runtimeBody,
		RequestedRoute: s.config.EffectRoute, Proxy: true,
	})
}

func validHeaderValue(value string) bool {
	if value == "" || len(value) > maxCallIDBytes || !utf8.ValidString(value) || strings.TrimSpace(value) != value {
		return false
	}
	for _, character := range value {
		if unicode.IsControl(character) {
			return false
		}
	}
	return true
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

func writeJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}

func writeError(writer http.ResponseWriter, status int, err error) {
	writeJSON(writer, status, map[string]string{"error": err.Error()})
}
