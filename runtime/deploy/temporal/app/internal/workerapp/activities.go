package workerapp

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"strings"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/deploy/temporal/app/internal/harness"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
)

const maxEffectResponseBytes = 1 << 20

const (
	paymentEffectPath = "/v1/charge"
	paymentQueryPath  = "/v1/query"
)

type Activities struct {
	paymentURL    string
	completionURL string
	client        *http.Client
}

func NewActivities(paymentURL, completionURL string) *Activities {
	return &Activities{
		paymentURL:    strings.TrimRight(paymentURL, "/"),
		completionURL: strings.TrimRight(completionURL, "/"),
		// The Activity deadline owns cancellation. A client timeout would make
		// the deterministic before/after-commit holds ambiguous.
		client: &http.Client{},
	}
}

func (a *Activities) ChargePayment(ctx context.Context, request harness.EffectRequest) (harness.EffectReceipt, error) {
	return a.invoke(ctx, a.paymentURL, paymentEffectPath, request)
}

func (a *Activities) CompleteOrder(ctx context.Context, request harness.EffectRequest) (harness.EffectReceipt, error) {
	return a.invoke(ctx, a.completionURL, "/v1/complete", request)
}

// PrepareFood is the matched Temporal boundary for the official application's
// restaurant point-of-sale request. The Restate fixture performs an HTTP call
// and then waits for a separate preparation-finished callback; the Temporal
// port keeps those as a distinct Activity and Signal rather than collapsing
// fulfillment into the terminal completion effect.
func (a *Activities) PrepareFood(ctx context.Context, request harness.PreparationRequest) (harness.PreparationReceipt, error) {
	if err := ctx.Err(); err != nil {
		return harness.PreparationReceipt{}, err
	}
	quantity, err := productQuantity(request.Products)
	if err != nil {
		return harness.PreparationReceipt{}, err
	}
	if request.OrderID == "" || request.RestaurantID == "" {
		return harness.PreparationReceipt{}, errors.New("order_id and restaurant_id are required for preparation")
	}
	return harness.PreparationReceipt{
		Schema: 1, OrderID: request.OrderID, RestaurantID: request.RestaurantID,
		ProductCount: quantity, Outcome: "accepted",
	}, nil
}

// ScheduleDelivery models the official delivery-manager request. Driver
// selection itself arrives later through the driver-selected Signal, matching
// the fixture's awakeable/promise boundary.
func (a *Activities) ScheduleDelivery(ctx context.Context, request harness.DeliveryRequest) (harness.DeliveryDispatch, error) {
	if err := ctx.Err(); err != nil {
		return harness.DeliveryDispatch{}, err
	}
	if request.OrderID == "" || request.DeliveryID == "" || request.RestaurantID == "" || request.Region == "" {
		return harness.DeliveryDispatch{}, errors.New("complete delivery request is required")
	}
	return harness.DeliveryDispatch{
		Schema: 1, OrderID: request.OrderID, DeliveryID: request.DeliveryID,
		RestaurantID: request.RestaurantID, Region: request.Region, Outcome: "scheduled",
	}, nil
}

func (a *Activities) QueryPayment(ctx context.Context, input harness.EffectRequest) (harness.PaymentObservation, error) {
	body, err := effectBody(input)
	if err != nil {
		return harness.PaymentObservation{}, err
	}
	requestHash := effectRequestHash(http.MethodPost, paymentEffectPath, body)
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, a.paymentURL+paymentQueryPath, bytes.NewReader(body))
	if err != nil {
		return harness.PaymentObservation{}, err
	}
	request.Header.Set("Accept", "application/json")
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Operation-ID", input.OperationID)
	request.Header.Set("X-Operation-Request-Hash", requestHash)
	response, err := a.client.Do(request)
	if err != nil {
		return harness.PaymentObservation{}, err
	}
	defer response.Body.Close()
	encoded, err := io.ReadAll(io.LimitReader(response.Body, maxEffectResponseBytes+1))
	if err != nil {
		return harness.PaymentObservation{}, err
	}
	if len(encoded) > maxEffectResponseBytes {
		return harness.PaymentObservation{}, errors.New("payment query response exceeds size limit")
	}
	if response.StatusCode != http.StatusOK {
		return harness.PaymentObservation{}, fmt.Errorf(
			"payment query returned %s: %s", response.Status, strings.TrimSpace(string(encoded)),
		)
	}
	mediaType, _, err := mime.ParseMediaType(response.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" {
		return harness.PaymentObservation{}, errors.New("payment query response is not application/json")
	}
	observation, err := decodePaymentObservation(encoded)
	if err != nil {
		return harness.PaymentObservation{}, err
	}
	if observation.Schema != 1 {
		return harness.PaymentObservation{}, fmt.Errorf("unsupported payment observation schema %d", observation.Schema)
	}
	if observation.OperationID != input.OperationID {
		return harness.PaymentObservation{}, errors.New("payment observation identity does not match request")
	}
	if observation.RequestHash != requestHash || !canonicalSHA256(observation.RequestHash) {
		return harness.PaymentObservation{}, errors.New("payment observation request hash does not match request")
	}
	if len(observation.RemoteReference) > 1024 {
		return harness.PaymentObservation{}, errors.New("payment observation remote reference is too large")
	}
	switch observation.Outcome {
	case "succeeded", "failed":
		if !canonicalSHA256(observation.FactHash) {
			return harness.PaymentObservation{}, errors.New("settled payment observation fact hash is invalid")
		}
		if observation.Outcome == "succeeded" && observation.RemoteReference == "" {
			return harness.PaymentObservation{}, errors.New("successful payment observation has no remote reference")
		}
	case "inconclusive":
		if observation.FactHash != "" {
			return harness.PaymentObservation{}, errors.New("inconclusive payment observation carries a fact hash")
		}
	default:
		return harness.PaymentObservation{}, fmt.Errorf("payment observation outcome %q is invalid", observation.Outcome)
	}
	return observation, nil
}

func (a *Activities) invoke(ctx context.Context, baseURL, path string, input harness.EffectRequest) (harness.EffectReceipt, error) {
	body, err := effectBody(input)
	if err != nil {
		return harness.EffectReceipt{}, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, baseURL+path, bytes.NewReader(body))
	if err != nil {
		return harness.EffectReceipt{}, err
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Operation-ID", input.OperationID)
	request.Header.Set("Idempotency-Key", input.OperationID)
	response, err := a.client.Do(request)
	if err != nil {
		return harness.EffectReceipt{}, err
	}
	defer response.Body.Close()
	encoded, err := io.ReadAll(io.LimitReader(response.Body, maxEffectResponseBytes+1))
	if err != nil {
		return harness.EffectReceipt{}, err
	}
	if len(encoded) > maxEffectResponseBytes {
		return harness.EffectReceipt{}, errors.New("effect response exceeds size limit")
	}
	if response.StatusCode != http.StatusOK {
		return harness.EffectReceipt{}, fmt.Errorf("effect %s returned %s: %s", path, response.Status, strings.TrimSpace(string(encoded)))
	}
	var receipt harness.EffectReceipt
	decoder := json.NewDecoder(bytes.NewReader(encoded))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&receipt); err != nil {
		return harness.EffectReceipt{}, fmt.Errorf("decode effect receipt: %w", err)
	}
	if receipt.Schema != 1 || receipt.OperationID != input.OperationID || receipt.Outcome != "succeeded" || receipt.ResultHash == "" || receipt.RemoteReference == "" {
		return harness.EffectReceipt{}, errors.New("effect returned an invalid receipt")
	}
	return receipt, nil
}

func effectBody(input harness.EffectRequest) ([]byte, error) {
	if input.OrderID == "" || input.OperationID == "" {
		return nil, errors.New("order_id and operation_id are required")
	}
	return json.Marshal(struct {
		OrderID        string `json:"order_id"`
		AmountCents    int64  `json:"amount_cents"`
		ClosureVersion string `json:"closure_version,omitempty"`
	}{
		OrderID: input.OrderID, AmountCents: input.AmountCents,
		ClosureVersion: input.ClosureVersion,
	})
}

func productQuantity(products []harness.Product) (int, error) {
	if len(products) == 0 {
		return 0, errors.New("at least one product is required")
	}
	total := 0
	for _, product := range products {
		if product.ProductID == "" || product.Description == "" || product.Quantity <= 0 {
			return 0, errors.New("every product requires an id, description, and positive quantity")
		}
		total += product.Quantity
	}
	return total, nil
}

func effectRequestHash(method, path string, body []byte) string {
	digest := sha256.New()
	_, _ = io.WriteString(digest, method)
	digest.Write([]byte{0})
	_, _ = io.WriteString(digest, path)
	digest.Write([]byte{0})
	digest.Write(body)
	return hex.EncodeToString(digest.Sum(nil))
}

func canonicalSHA256(value string) bool {
	if len(value) != sha256.Size*2 {
		return false
	}
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size && hex.EncodeToString(decoded) == value
}

func decodePaymentObservation(encoded []byte) (harness.PaymentObservation, error) {
	decoder := json.NewDecoder(bytes.NewReader(encoded))
	start, err := decoder.Token()
	if err != nil || start != json.Delim('{') {
		return harness.PaymentObservation{}, errors.New("payment observation is not a JSON object")
	}
	wanted := map[string]bool{
		"schema": true, "operation_id": true, "request_hash": true,
		"outcome": true, "fact_hash": true, "remote_reference": true,
	}
	fields := make(map[string]json.RawMessage, len(wanted))
	for decoder.More() {
		token, err := decoder.Token()
		if err != nil {
			return harness.PaymentObservation{}, fmt.Errorf("decode payment observation key: %w", err)
		}
		name, ok := token.(string)
		if !ok {
			return harness.PaymentObservation{}, errors.New("payment observation key is not a string")
		}
		if !wanted[name] {
			return harness.PaymentObservation{}, fmt.Errorf("payment observation contains unknown field %q", name)
		}
		if _, duplicate := fields[name]; duplicate {
			return harness.PaymentObservation{}, fmt.Errorf("payment observation contains duplicate field %q", name)
		}
		var raw json.RawMessage
		if err := decoder.Decode(&raw); err != nil {
			return harness.PaymentObservation{}, fmt.Errorf("decode payment observation field %q: %w", name, err)
		}
		if bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
			return harness.PaymentObservation{}, fmt.Errorf("payment observation field %q is null", name)
		}
		fields[name] = raw
	}
	end, err := decoder.Token()
	if err != nil || end != json.Delim('}') {
		return harness.PaymentObservation{}, errors.New("payment observation has an invalid terminator")
	}
	for name := range wanted {
		if _, ok := fields[name]; !ok {
			return harness.PaymentObservation{}, fmt.Errorf("payment observation is missing field %q", name)
		}
	}
	var observation harness.PaymentObservation
	for name, target := range map[string]any{
		"schema": &observation.Schema, "operation_id": &observation.OperationID,
		"request_hash": &observation.RequestHash, "outcome": &observation.Outcome,
		"fact_hash": &observation.FactHash, "remote_reference": &observation.RemoteReference,
	} {
		if err := json.Unmarshal(fields[name], target); err != nil {
			return harness.PaymentObservation{}, fmt.Errorf("decode payment observation field %q: %w", name, err)
		}
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return harness.PaymentObservation{}, errors.New("payment observation contains multiple JSON values")
		}
		return harness.PaymentObservation{}, fmt.Errorf("decode payment observation end: %w", err)
	}
	return observation, nil
}

func activityOptions(name string) activity.RegisterOptions {
	return activity.RegisterOptions{Name: name}
}

func completeOrder(ctx workflow.Context, order harness.Order) error {
	return completeOrderWithClosureVersion(ctx, order, "")
}

func completeOrderWithClosureVersion(ctx workflow.Context, order harness.Order, closureVersion string) error {
	options := workflow.ActivityOptions{
		StartToCloseTimeout: time.Minute,
		RetryPolicy:         &temporal.RetryPolicy{MaximumAttempts: 1},
	}
	activityCtx := workflow.WithActivityOptions(ctx, options)
	request := harness.EffectRequest{
		OrderID: order.OrderID, AmountCents: order.AmountCents,
		OperationID: harness.OperationID("complete:" + order.OrderID), ClosureVersion: closureVersion,
	}
	return workflow.ExecuteActivity(activityCtx, harness.CompletionActivityName, request).Get(activityCtx, nil)
}
