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
	"maps"
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

var ErrOperationNotFound = errors.New("external operation was not found")

var ErrStoredRequestUnavailable = errors.New("external operation has no stored request")

var ErrOperationNotRecoverable = errors.New("external operation is not eligible for query recovery")

var ErrStoredRequestMismatch = errors.New("stored external request does not match its recorded hash")

var ErrOperationRequestConflict = errors.New("stable operation identity was reused with different request bytes")

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

// singleAttemptReader deliberately hides bytes.Reader's rewind support from
// net/http. The standard Transport may otherwise replay a request carrying an
// Idempotency-Key after a reused-connection failure, bypassing the durable
// Unknown state and the runtime's retry decision.
type singleAttemptReader struct {
	reader *bytes.Reader
}

func (reader *singleAttemptReader) Read(destination []byte) (int, error) {
	return reader.reader.Read(destination)
}

func newSingleAttemptRequest(ctx context.Context, method, target string, body []byte) (*http.Request, error) {
	request, err := http.NewRequestWithContext(ctx, method, target, &singleAttemptReader{
		reader: bytes.NewReader(body),
	})
	if err != nil {
		return nil, err
	}
	request.ContentLength = int64(len(body))
	return request, nil
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
	return g.execute(ctx, nil, request)
}

// ExecuteBound executes on behalf of one host-attached sandbox. The binding
// is supplied by the host endpoint, never by request bytes from the sandbox.
// Its domain replaces any caller value, and every security-sensitive lookup,
// prepare, and pre-network dispatch marker is checked against the same
// binding used by an atomic Rule-and-sandbox cutover.
func (g *Gateway) ExecuteBound(
	ctx context.Context,
	binding control.SandboxBinding,
	request Request,
) (Outcome, error) {
	binding.AllowedKinds = append([]string(nil), binding.AllowedKinds...)
	request.Domain = binding.Domain
	return g.execute(ctx, &binding, request)
}

func (g *Gateway) moveBeforeNetwork(
	binding *control.SandboxBinding,
	id string,
	update kernel.OperationUpdate,
) error {
	if binding == nil {
		return g.control.Move(id, update)
	}
	return g.control.MoveForSandbox(*binding, id, update)
}

func (g *Gateway) cancelPrepared(binding *control.SandboxBinding, id string) {
	_ = g.moveBeforeNetwork(binding, id, kernel.OperationUpdate{Phase: kernel.Cancelled})
}

func (g *Gateway) execute(
	ctx context.Context,
	binding *control.SandboxBinding,
	request Request,
) (outcome Outcome, returnErr error) {
	var release func()
	var err error
	if binding == nil {
		release, err = g.control.BeginAdapterDispatch(request.Domain)
	} else {
		release, err = g.control.BeginSandboxDispatch(*binding)
	}
	if err != nil {
		return Outcome{}, err
	}
	defer release()
	if binding != nil {
		// A cutover may happen after an external request was sent. Host-owned
		// settlement still belongs in History, but a stale sandbox must not
		// receive the result or use it to continue acting.
		defer func() {
			if err := g.control.ValidateSandbox(*binding); err != nil {
				outcome = Outcome{}
				returnErr = err
			}
		}()
	}
	var prior kernel.Operation
	var exists bool
	if binding == nil {
		prior, exists = g.control.Operation(request.ID)
	} else {
		prior, exists, err = g.control.OperationForSandbox(*binding, request.ID)
		if err != nil {
			return Outcome{}, err
		}
	}
	if exists {
		if prior.Domain != request.Domain {
			return Outcome{}, errors.New("stable operation identity belongs to another adapter domain")
		}
		if !prior.RequestStored {
			return Outcome{}, fmt.Errorf("%w: operation %q", ErrStoredRequestUnavailable, prior.ID)
		}
		callerHeaders, err := canonicalCallerHeaders(request.Headers)
		if err != nil {
			return Outcome{}, err
		}
		if !bytes.Equal(request.Body, prior.RequestBody) || !maps.Equal(callerHeaders, prior.RequestHeaders) {
			return Outcome{OperationID: prior.ID, Phase: prior.Phase},
				fmt.Errorf("%w: operation %q", ErrOperationRequestConflict, prior.ID)
		}
		// History, rather than replacement caller state, supplies the complete
		// method, target, kind, and request for an existing Operation. The
		// replacement caller still has to prove that its business bytes match.
		request, err = requestFromOperation(prior)
		if err != nil {
			return Outcome{}, err
		}
	}
	if request.Method == "" {
		request.Method = http.MethodPost
	}
	httpRequest, body, callerHeaders, err := finalizedRequest(ctx, request)
	if err != nil {
		return Outcome{}, err
	}
	digest := requestHash(httpRequest, body)
	if exists && digest != prior.RequestHash {
		return Outcome{}, ErrStoredRequestMismatch
	}
	var operation kernel.Operation
	if binding == nil {
		operation, err = g.control.PrepareWithRequest(
			request.ID, request.Domain, request.Kind, digest, callerHeaders, body,
		)
	} else {
		operation, err = g.control.PrepareWithRequestForSandbox(
			*binding, request.ID, request.Kind, digest, callerHeaders, body,
		)
	}
	if err != nil {
		return Outcome{}, err
	}
	registeredMethod := operation.Method
	if registeredMethod == "" {
		registeredMethod = http.MethodPost
	}
	if operation.Target == "" || operation.Target != httpRequest.URL.String() || registeredMethod != httpRequest.Method {
		if operation.Phase == kernel.Prepared {
			g.cancelPrepared(binding, operation.ID)
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
		if err := g.moveBeforeNetwork(binding, operation.ID, kernel.OperationUpdate{
			Phase: kernel.Unknown, RemoteReference: operation.RemoteReference,
		}); err != nil {
			return Outcome{}, err
		}
		operation.Phase = kernel.Unknown
		fallthrough
	case kernel.Unknown:
		if operation.Queryable {
			recovered, settled, observeErr := g.settleUnknownByQuery(
				ctx, operation, httpRequest.Header.Get("Content-Type"), body,
			)
			if observeErr != nil {
				return Outcome{OperationID: operation.ID, Phase: kernel.Unknown},
					fmt.Errorf("%w: query operation %q: %v", ErrOutcomeUnknown, operation.ID, observeErr)
			}
			if settled {
				return recovered, nil
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
			g.cancelPrepared(binding, operation.ID)
		}
		return Outcome{}, errors.New("operation has no registered response classifier")
	}
	if !supportedClassifier(operation.ResponseClassifier) {
		if operation.Phase == kernel.Prepared {
			g.cancelPrepared(binding, operation.ID)
		}
		return Outcome{}, fmt.Errorf("unsupported response classifier %q", operation.ResponseClassifier)
	}

	dispatch := kernel.OperationUpdate{
		Phase:              kernel.Dispatched,
		RemoteReference:    operation.RemoteReference,
		DispatchOwner:      g.control.BootID(),
		DispatchGeneration: operation.DispatchGeneration + 1,
	}
	err = g.moveBeforeNetwork(binding, operation.ID, dispatch)
	if err != nil {
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
	rawHash := resultHash(response.StatusCode, body)
	phase, factHash, remoteReference, classifyErr := classifyResponse(
		operation.ResponseClassifier, operation.ID, response, body,
	)
	if classifyErr != nil {
		if moveErr := g.control.Move(operation.ID, kernel.OperationUpdate{Phase: kernel.Unknown}); moveErr != nil {
			return Outcome{}, errors.Join(classifyErr, moveErr)
		}
		return Outcome{
			OperationID: operation.ID,
			Phase:       kernel.Unknown,
			StatusCode:  response.StatusCode,
			ResultHash:  rawHash,
		}, fmt.Errorf("%w: %v", ErrOutcomeUnknown, classifyErr)
	}
	if err := g.control.Move(operation.ID, kernel.OperationUpdate{
		Phase:           phase,
		ResultHash:      factHash,
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
		ResultHash:  factHash,
	}, nil
}

// Recover queries exactly one frozen, unknown Operation by its durable ID. It
// never dispatches the effect endpoint and never compiles or activates a Rule.
func (g *Gateway) Recover(ctx context.Context, operationID string) (Outcome, error) {
	release, err := g.control.BeginDispatch()
	if err != nil {
		return Outcome{}, err
	}
	defer release()
	operation, ok := g.control.Operation(operationID)
	if !ok {
		return Outcome{}, fmt.Errorf("%w: %q", ErrOperationNotFound, operationID)
	}
	if operation.Phase != kernel.Unknown || !operation.Queryable {
		return Outcome{}, fmt.Errorf(
			"%w: operation %q is %s and queryable=%t",
			ErrOperationNotRecoverable, operation.ID, operation.Phase, operation.Queryable,
		)
	}
	request, err := requestFromOperation(operation)
	if err != nil {
		return Outcome{}, err
	}
	httpRequest, body, _, err := finalizedRequest(ctx, request)
	if err != nil {
		return Outcome{}, err
	}
	if requestHash(httpRequest, body) != operation.RequestHash {
		return Outcome{}, ErrStoredRequestMismatch
	}
	outcome, settled, err := g.settleUnknownByQuery(
		ctx, operation, httpRequest.Header.Get("Content-Type"), body,
	)
	if err != nil {
		return Outcome{OperationID: operation.ID, Phase: kernel.Unknown},
			fmt.Errorf("%w: query operation %q: %v", ErrOutcomeUnknown, operation.ID, err)
	}
	if !settled {
		return Outcome{OperationID: operation.ID, Phase: kernel.Unknown},
			fmt.Errorf("%w: query operation %q was inconclusive", ErrOutcomeUnknown, operation.ID)
	}
	return outcome, nil
}

func (g *Gateway) settleUnknownByQuery(
	ctx context.Context,
	operation kernel.Operation,
	contentType string,
	effectBody []byte,
) (Outcome, bool, error) {
	observed, err := g.queryUnknown(ctx, operation, contentType, effectBody)
	if err != nil {
		return Outcome{}, false, err
	}
	if observed.Phase != kernel.Succeeded && observed.Phase != kernel.Failed {
		return Outcome{OperationID: operation.ID, Phase: kernel.Unknown}, false, nil
	}
	if err := g.control.Move(operation.ID, kernel.OperationUpdate{
		Phase: observed.Phase, ResultHash: observed.FactHash,
		StatusCode: observed.StatusCode, ResultBody: observed.Body,
		RemoteReference: observed.RemoteReference, Settlement: kernel.SettlementQuery,
	}); err != nil {
		return Outcome{}, false, err
	}
	return Outcome{
		OperationID: operation.ID, Phase: observed.Phase,
		StatusCode: observed.StatusCode, Body: observed.Body,
		ResultHash: observed.FactHash, RecoveredByQuery: true,
	}, true, nil
}

type queryOutcome struct {
	Phase           kernel.Phase
	StatusCode      int
	Body            []byte
	FactHash        string
	RemoteReference string
}

// queryUnknown asks the endpoint frozen in the Operation contract to observe
// the external fact. The effect body comes from the request stored in History.
// No caller-owned header other than Content-Type crosses this trust boundary.
func (g *Gateway) queryUnknown(ctx context.Context, operation kernel.Operation, contentType string, effectBody []byte) (queryOutcome, error) {
	if operation.QueryTarget == "" || operation.QueryMethod == "" || operation.QueryClassifier == "" {
		return queryOutcome{}, errors.New("queryable operation has an incomplete query contract")
	}
	if operation.QueryClassifier != kernel.OperationObservationV1 {
		return queryOutcome{}, fmt.Errorf("unsupported query classifier %q", operation.QueryClassifier)
	}
	request, err := newSingleAttemptRequest(ctx, operation.QueryMethod, operation.QueryTarget, effectBody)
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

func requestFromOperation(operation kernel.Operation) (Request, error) {
	if !operation.RequestStored {
		return Request{}, fmt.Errorf("%w: operation %q", ErrStoredRequestUnavailable, operation.ID)
	}
	headers := make(map[string]string, len(operation.RequestHeaders))
	for name, value := range operation.RequestHeaders {
		headers[name] = value
	}
	if len(headers) == 0 {
		headers = nil
	}
	return Request{
		ID: operation.ID, Domain: operation.Domain, Kind: operation.Kind,
		Method: operation.Method, URL: operation.Target, Headers: headers,
		Body: append([]byte(nil), operation.RequestBody...),
	}, nil
}

func finalizedRequest(ctx context.Context, request Request) (*http.Request, []byte, map[string]string, error) {
	if request.ID == "" {
		return nil, nil, nil, errors.New("external operation identity is empty")
	}
	if request.URL == "" {
		return nil, nil, nil, errors.New("external operation URL is empty")
	}
	body := append([]byte(nil), request.Body...)
	httpRequest, err := newSingleAttemptRequest(ctx, request.Method, request.URL, body)
	if err != nil {
		return nil, nil, nil, err
	}
	if httpRequest.URL.Scheme != "http" && httpRequest.URL.Scheme != "https" {
		return nil, nil, nil, errors.New("external operation URL must use http or https")
	}
	if httpRequest.URL.Host == "" || httpRequest.URL.Fragment != "" || httpRequest.URL.User != nil {
		return nil, nil, nil, errors.New("external operation URL has unsupported authority or fragment")
	}
	// Make transport defaults explicit so the durable digest covers them.
	httpRequest.Header.Set("User-Agent", "safe-change-runtime/1")
	httpRequest.Header.Set("Accept-Encoding", "identity")
	callerHeaders, err := canonicalCallerHeaders(request.Headers)
	if err != nil {
		return nil, nil, nil, err
	}
	for name, value := range callerHeaders {
		httpRequest.Header.Set(name, value)
	}
	httpRequest.Header.Set("Idempotency-Key", request.ID)
	httpRequest.Header.Set("X-Operation-ID", request.ID)
	return httpRequest, body, callerHeaders, nil
}

func canonicalCallerHeaders(headers map[string]string) (map[string]string, error) {
	seen := make(map[string]bool, len(headers))
	canonical := make(map[string]string, len(headers))
	for name, value := range headers {
		lower := strings.ToLower(name)
		if seen[lower] {
			return nil, fmt.Errorf("duplicate case-insensitive HTTP header %q", name)
		}
		seen[lower] = true
		if reservedHeader(lower) {
			return nil, fmt.Errorf("HTTP header %q is owned by the gateway", name)
		}
		if !validHeaderName(name) || strings.ContainsAny(value, "\r\n\x00") {
			return nil, fmt.Errorf("invalid HTTP header %q", name)
		}
		canonicalName := http.CanonicalHeaderKey(name)
		canonical[canonicalName] = value
	}
	if len(canonical) == 0 {
		return nil, nil
	}
	return canonical, nil
}

func reservedHeader(lower string) bool {
	switch lower {
	case "host", "content-length", "transfer-encoding", "connection", "trailer",
		"idempotency-key", "x-operation-id", "x-operation-request-hash",
		"authorization", "proxy-authorization", "cookie", "set-cookie",
		"x-api-key", "api-key", "apikey":
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
