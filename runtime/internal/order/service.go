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
)

const maxBodyBytes = 1 << 20

type Config struct {
	Version string `json:"version"`
	Kind    string `json:"kind"`
	Target  string `json:"target"`
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
	if config.Version == "" || config.Kind == "" || config.Target == "" {
		return Config{}, errors.New("order release requires version, kind, and target")
	}
	target, err := url.Parse(config.Target)
	if err != nil || (target.Scheme != "http" && target.Scheme != "https") || target.Host == "" || target.User != nil || target.Fragment != "" {
		return Config{}, errors.New("order release target must be an absolute HTTP URL")
	}
	return config, nil
}

type Service struct {
	config     Config
	controlURL string
	token      string
	client     *http.Client
}

func New(config Config, controlURL, token string, client *http.Client) (*Service, error) {
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

func (s *Service) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(writer http.ResponseWriter, _ *http.Request) {
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
