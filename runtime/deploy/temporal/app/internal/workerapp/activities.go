package workerapp

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/deploy/temporal/app/internal/harness"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
)

const maxEffectResponseBytes = 1 << 20

type Activities struct {
	effectURL string
	client    *http.Client
}

func NewActivities(effectURL string) *Activities {
	return &Activities{
		effectURL: strings.TrimRight(effectURL, "/"),
		// The Activity deadline owns cancellation. A client timeout would make
		// the deterministic before/after-commit holds ambiguous.
		client: &http.Client{},
	}
}

func (a *Activities) ChargePayment(ctx context.Context, request harness.EffectRequest) (harness.EffectReceipt, error) {
	return a.invoke(ctx, "/v1/charge", request)
}

func (a *Activities) CompleteOrder(ctx context.Context, request harness.EffectRequest) (harness.EffectReceipt, error) {
	return a.invoke(ctx, "/v1/complete", request)
}

func (a *Activities) invoke(ctx context.Context, path string, input harness.EffectRequest) (harness.EffectReceipt, error) {
	if input.OrderID == "" || input.OperationID == "" {
		return harness.EffectReceipt{}, errors.New("order_id and operation_id are required")
	}
	body, err := json.Marshal(struct {
		OrderID     string `json:"order_id"`
		AmountCents int64  `json:"amount_cents"`
	}{OrderID: input.OrderID, AmountCents: input.AmountCents})
	if err != nil {
		return harness.EffectReceipt{}, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, a.effectURL+path, bytes.NewReader(body))
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

func activityOptions(name string) activity.RegisterOptions {
	return activity.RegisterOptions{Name: name}
}

func completeOrder(ctx workflow.Context, order harness.Order) error {
	options := workflow.ActivityOptions{
		StartToCloseTimeout: time.Minute,
		RetryPolicy:         &temporal.RetryPolicy{MaximumAttempts: 1},
	}
	activityCtx := workflow.WithActivityOptions(ctx, options)
	request := harness.EffectRequest{
		OrderID: order.OrderID, AmountCents: order.AmountCents,
		OperationID: harness.OperationID("complete:" + order.OrderID),
	}
	return workflow.ExecuteActivity(activityCtx, harness.CompletionActivityName, request).Get(activityCtx, nil)
}
