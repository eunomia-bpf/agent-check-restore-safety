// Package gateway is the mandatory path for protected HTTP Operations. It
// records intent before network I/O, sends a stable operation identity, and
// records a definitive response or an unknown outcome.
package gateway

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strings"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const maxResponseBytes = 64 << 10

var ErrOutcomeUnknown = errors.New("external operation outcome is unknown")

var ErrOperationInFlight = errors.New("external operation is already in flight")

type Request struct {
	ID      string            `json:"id"`
	Domain  string            `json:"domain"`
	Kind    string            `json:"kind"`
	Method  string            `json:"method,omitempty"`
	URL     string            `json:"url"`
	Headers map[string]string `json:"headers,omitempty"`
	Body    []byte            `json:"body,omitempty"`
}

type Outcome struct {
	OperationID      string       `json:"operation_id"`
	Phase            kernel.Phase `json:"phase"`
	StatusCode       int          `json:"status_code,omitempty"`
	Body             []byte       `json:"body,omitempty"`
	ResultHash       string       `json:"result_hash"`
	Reused           bool         `json:"reused"`
	RecoveredByQuery bool         `json:"recovered_by_query"`
}

type Gateway struct {
	control *control.Control
	client  *http.Client
}

func New(c *control.Control, client *http.Client) (*Gateway, error) {
	if c == nil {
		return nil, errors.New("nil control")
	}
	if client == nil {
		client = http.DefaultClient
	}
	// Clone the caller's client so the gateway cannot silently reach a target
	// other than the one frozen in the Operation contract.  A redirect remains
	// an ordinary non-2xx response from the registered target.
	boundClient := *client
	if boundClient.Timeout == 0 {
		boundClient.Timeout = 30 * time.Second
	}
	boundClient.CheckRedirect = func(_ *http.Request, _ []*http.Request) error {
		return http.ErrUseLastResponse
	}
	return &Gateway{control: c, client: &boundClient}, nil
}

type headerPair struct {
	name  string
	value string
}

func requestHash(request *http.Request, body []byte) string {
	headers := make([]headerPair, 0, len(request.Header))
	for name, values := range request.Header {
		value := strings.Join(values, "\x00")
		headers = append(headers, headerPair{name: strings.ToLower(name), value: value})
	}
	sort.Slice(headers, func(i, j int) bool {
		if headers[i].name != headers[j].name {
			return headers[i].name < headers[j].name
		}
		return headers[i].value < headers[j].value
	})
	hash := sha256.New()
	_, _ = io.WriteString(hash, request.Method)
	hash.Write([]byte{0})
	_, _ = io.WriteString(hash, request.URL.String())
	hash.Write([]byte{0})
	for _, header := range headers {
		_, _ = io.WriteString(hash, header.name)
		hash.Write([]byte{':'})
		_, _ = io.WriteString(hash, header.value)
		hash.Write([]byte{0})
	}
	hash.Write(body)
	return hex.EncodeToString(hash.Sum(nil))
}

func resultHash(status int, body []byte) string {
	hash := sha256.New()
	_, _ = fmt.Fprintf(hash, "%d\x00", status)
	hash.Write(body)
	return hex.EncodeToString(hash.Sum(nil))
}

func (g *Gateway) Execute(ctx context.Context, request Request) (Outcome, error) {
	release, err := g.control.BeginDispatch()
	if err != nil {
		return Outcome{}, err
	}
	defer release()
	if prior, ok := g.control.Operation(request.ID); ok {
		if prior.Domain != request.Domain {
			return Outcome{}, errors.New("stable operation identity belongs to another adapter domain")
		}
		// A changed caller need not retain an old per-state migration branch.
		// History supplies the frozen operation kind and network target. The
		// request body and non-owned headers must still hash identically.
		request.Kind = prior.Kind
		request.URL = prior.Target
		request.Method = prior.Method
	}
	if request.Method == "" {
		request.Method = http.MethodPost
	}
	httpRequest, body, err := finalizedRequest(ctx, request)
	if err != nil {
		return Outcome{}, err
	}
	digest := requestHash(httpRequest, body)
	operation, err := g.control.Prepare(request.ID, request.Domain, request.Kind, digest)
	if err != nil {
		return Outcome{}, err
	}
	registeredMethod := operation.Method
	if registeredMethod == "" {
		registeredMethod = http.MethodPost
	}
	if operation.Target == "" || operation.Target != httpRequest.URL.String() || registeredMethod != httpRequest.Method {
		if operation.Phase == kernel.Prepared {
			_ = g.control.Move(operation.ID, kernel.OperationUpdate{Phase: kernel.Cancelled})
		}
		return Outcome{}, errors.New("external request differs from the registered operation target")
	}
	switch operation.Phase {
	case kernel.Succeeded, kernel.Failed:
		return Outcome{
			OperationID:      operation.ID,
			Phase:            operation.Phase,
			StatusCode:       operation.StatusCode,
			Body:             append([]byte(nil), operation.ResultBody...),
			ResultHash:       operation.ResultHash,
			Reused:           true,
			RecoveredByQuery: operation.Settlement == kernel.SettlementQuery,
		}, nil
	case kernel.Dispatched:
		if operation.DispatchOwner == g.control.BootID() {
			return Outcome{OperationID: operation.ID, Phase: kernel.Dispatched},
				fmt.Errorf("%w: operation %q", ErrOperationInFlight, operation.ID)
		}
		// A crash after the durable dispatch marker cannot reveal whether the
		// request crossed the network boundary.
		if err := g.control.Move(operation.ID, kernel.OperationUpdate{
			Phase: kernel.Unknown, RemoteReference: operation.RemoteReference,
		}); err != nil {
			return Outcome{}, err
		}
		operation.Phase = kernel.Unknown
		fallthrough
	case kernel.Unknown:
		if operation.Queryable {
			observed, observeErr := g.queryUnknown(ctx, operation, httpRequest.Header.Get("Content-Type"), body)
			if observeErr != nil {
				return Outcome{OperationID: operation.ID, Phase: kernel.Unknown},
					fmt.Errorf("%w: query operation %q: %v", ErrOutcomeUnknown, operation.ID, observeErr)
			}
			if observed.Phase == kernel.Succeeded || observed.Phase == kernel.Failed {
				if err := g.control.Move(operation.ID, kernel.OperationUpdate{
					Phase: observed.Phase, ResultHash: observed.FactHash,
					StatusCode: observed.StatusCode, ResultBody: observed.Body,
					RemoteReference: observed.RemoteReference, Settlement: kernel.SettlementQuery,
				}); err != nil {
					return Outcome{}, err
				}
				return Outcome{
					OperationID: operation.ID, Phase: observed.Phase,
					StatusCode: observed.StatusCode, Body: observed.Body,
					ResultHash: observed.FactHash, RecoveredByQuery: true,
				}, nil
			}
		}
		if !operation.RetrySafe {
			return Outcome{OperationID: operation.ID, Phase: kernel.Unknown},
				fmt.Errorf("%w: operation %q has no safe retry", ErrOutcomeUnknown, operation.ID)
		}
	case kernel.Prepared:
		if !operation.RetrySafe && !operation.Queryable {
			return Outcome{}, fmt.Errorf("operation %q has no implemented safe recovery", operation.ID)
		}
	default:
		return Outcome{}, fmt.Errorf("operation %q has unsupported phase %q", operation.ID, operation.Phase)
	}
	if operation.ResponseClassifier == "" {
		if operation.Phase == kernel.Prepared {
			_ = g.control.Move(operation.ID, kernel.OperationUpdate{Phase: kernel.Cancelled})
		}
		return Outcome{}, errors.New("operation has no registered response classifier")
	}
	if !supportedClassifier(operation.ResponseClassifier) {
		if operation.Phase == kernel.Prepared {
			_ = g.control.Move(operation.ID, kernel.OperationUpdate{Phase: kernel.Cancelled})
		}
		return Outcome{}, fmt.Errorf("unsupported response classifier %q", operation.ResponseClassifier)
	}

	if err := g.control.Move(operation.ID, kernel.OperationUpdate{
		Phase:              kernel.Dispatched,
		RemoteReference:    operation.RemoteReference,
		DispatchOwner:      g.control.BootID(),
		DispatchGeneration: operation.DispatchGeneration + 1,
	}); err != nil {
		return Outcome{}, err
	}

	response, err := g.client.Do(httpRequest)
	if err != nil {
		if moveErr := g.control.Move(operation.ID, kernel.OperationUpdate{
			Phase: kernel.Unknown, RemoteReference: operation.RemoteReference,
		}); moveErr != nil {
			return Outcome{}, errors.Join(err, moveErr)
		}
		return Outcome{OperationID: operation.ID, Phase: kernel.Unknown}, fmt.Errorf("%w: %v", ErrOutcomeUnknown, err)
	}
	defer response.Body.Close()
	body, readErr := io.ReadAll(io.LimitReader(response.Body, maxResponseBytes+1))
	if readErr != nil || len(body) > maxResponseBytes {
		if moveErr := g.control.Move(operation.ID, kernel.OperationUpdate{
			Phase: kernel.Unknown, RemoteReference: operation.RemoteReference,
		}); moveErr != nil {
			return Outcome{}, errors.Join(readErr, moveErr)
		}
		if readErr == nil {
			readErr = errors.New("external response exceeds size limit")
		}
		return Outcome{OperationID: operation.ID, Phase: kernel.Unknown}, fmt.Errorf("%w: %v", ErrOutcomeUnknown, readErr)
	}
	hash := resultHash(response.StatusCode, body)
	phase, remoteReference, classifyErr := classifyResponse(operation.ResponseClassifier, operation.ID, response, body)
	if classifyErr != nil {
		if moveErr := g.control.Move(operation.ID, kernel.OperationUpdate{Phase: kernel.Unknown}); moveErr != nil {
			return Outcome{}, errors.Join(classifyErr, moveErr)
		}
		return Outcome{
			OperationID: operation.ID,
			Phase:       kernel.Unknown,
			StatusCode:  response.StatusCode,
			ResultHash:  hash,
		}, fmt.Errorf("%w: %v", ErrOutcomeUnknown, classifyErr)
	}
	if err := g.control.Move(operation.ID, kernel.OperationUpdate{
		Phase:           phase,
		ResultHash:      hash,
		StatusCode:      response.StatusCode,
		ResultBody:      body,
		RemoteReference: remoteReference,
	}); err != nil {
		return Outcome{}, err
	}
	return Outcome{
		OperationID: operation.ID,
		Phase:       phase,
		StatusCode:  response.StatusCode,
		Body:        body,
		ResultHash:  hash,
	}, nil
}

type queryOutcome struct {
	Phase           kernel.Phase
	StatusCode      int
	Body            []byte
	FactHash        string
	RemoteReference string
}

// queryUnknown asks the endpoint frozen in the Operation contract to observe
// the external fact. The effect body is copied only after Execute has checked
// that it still hashes to the frozen RequestHash. No caller-owned header other
// than Content-Type crosses this separate trust boundary.
func (g *Gateway) queryUnknown(ctx context.Context, operation kernel.Operation, contentType string, effectBody []byte) (queryOutcome, error) {
	if operation.QueryTarget == "" || operation.QueryMethod == "" || operation.QueryClassifier == "" {
		return queryOutcome{}, errors.New("queryable operation has an incomplete query contract")
	}
	if operation.QueryClassifier != kernel.OperationObservationV1 {
		return queryOutcome{}, fmt.Errorf("unsupported query classifier %q", operation.QueryClassifier)
	}
	request, err := http.NewRequestWithContext(ctx, operation.QueryMethod, operation.QueryTarget, bytes.NewReader(effectBody))
	if err != nil {
		return queryOutcome{}, err
	}
	if request.URL.Scheme != "http" && request.URL.Scheme != "https" {
		return queryOutcome{}, errors.New("external query URL must use http or https")
	}
	if request.URL.Host == "" || request.URL.Fragment != "" || request.URL.User != nil {
		return queryOutcome{}, errors.New("external query URL has unsupported authority or fragment")
	}
	request.Header.Set("User-Agent", "safe-change-runtime/1")
	request.Header.Set("Accept-Encoding", "identity")
	request.Header.Set("X-Operation-ID", operation.ID)
	request.Header.Set("X-Operation-Request-Hash", operation.RequestHash)
	if contentType != "" {
		request.Header.Set("Content-Type", contentType)
	}
	response, err := g.client.Do(request)
	if err != nil {
		return queryOutcome{}, err
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, maxResponseBytes+1))
	if err != nil {
		return queryOutcome{}, err
	}
	if len(body) > maxResponseBytes {
		return queryOutcome{}, errors.New("external query response exceeds size limit")
	}
	phase, factHash, remoteReference, err := classifyObservation(
		operation.QueryClassifier, operation.ID, operation.RequestHash, response, body,
	)
	if err != nil {
		return queryOutcome{}, err
	}
	return queryOutcome{
		Phase: phase, StatusCode: response.StatusCode, Body: body,
		FactHash: factHash, RemoteReference: remoteReference,
	}, nil
}

func finalizedRequest(ctx context.Context, request Request) (*http.Request, []byte, error) {
	if request.ID == "" {
		return nil, nil, errors.New("external operation identity is empty")
	}
	if request.URL == "" {
		return nil, nil, errors.New("external operation URL is empty")
	}
	body := append([]byte(nil), request.Body...)
	httpRequest, err := http.NewRequestWithContext(ctx, request.Method, request.URL, bytes.NewReader(body))
	if err != nil {
		return nil, nil, err
	}
	if httpRequest.URL.Scheme != "http" && httpRequest.URL.Scheme != "https" {
		return nil, nil, errors.New("external operation URL must use http or https")
	}
	if httpRequest.URL.Host == "" || httpRequest.URL.Fragment != "" || httpRequest.URL.User != nil {
		return nil, nil, errors.New("external operation URL has unsupported authority or fragment")
	}
	// Make transport defaults explicit so the durable digest covers them.
	httpRequest.Header.Set("User-Agent", "safe-change-runtime/1")
	httpRequest.Header.Set("Accept-Encoding", "identity")
	seen := make(map[string]bool, len(request.Headers))
	for name, value := range request.Headers {
		lower := strings.ToLower(name)
		if seen[lower] {
			return nil, nil, fmt.Errorf("duplicate case-insensitive HTTP header %q", name)
		}
		seen[lower] = true
		if reservedHeader(lower) {
			return nil, nil, fmt.Errorf("HTTP header %q is owned by the gateway", name)
		}
		if !validHeaderName(name) || strings.ContainsAny(value, "\r\n") {
			return nil, nil, fmt.Errorf("invalid HTTP header %q", name)
		}
		httpRequest.Header.Set(http.CanonicalHeaderKey(name), value)
	}
	httpRequest.Header.Set("Idempotency-Key", request.ID)
	httpRequest.Header.Set("X-Operation-ID", request.ID)
	return httpRequest, body, nil
}

func reservedHeader(lower string) bool {
	switch lower {
	case "host", "content-length", "transfer-encoding", "connection", "trailer",
		"idempotency-key", "x-operation-id", "x-operation-request-hash":
		return true
	default:
		return false
	}
}

func validHeaderName(name string) bool {
	if name == "" {
		return false
	}
	for _, character := range name {
		if (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') || strings.ContainsRune("!#$%&'*+-.^_`|~", character) {
			continue
		}
		return false
	}
	return true
}
