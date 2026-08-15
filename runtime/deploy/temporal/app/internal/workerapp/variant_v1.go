//go:build worker_v1

package workerapp

import (
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/deploy/temporal/app/internal/harness"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

const buildID = "food-order-v1"

func registerVariantActivities(w worker.Worker, activities *Activities) {
	w.RegisterActivityWithOptions(activities.ChargePayment, activityOptions(harness.PaymentActivityName))
	w.RegisterActivityWithOptions(activities.CompleteOrder, activityOptions(harness.CompletionActivityName))
}

func runOrderWorkflow(ctx workflow.Context, order harness.Order) (harness.OrderResult, error) {
	status, err := newStatus(ctx, order)
	if err != nil {
		return harness.OrderResult{}, err
	}
	options := workflow.ActivityOptions{
		StartToCloseTimeout: 30 * time.Second,
		RetryPolicy:         &temporal.RetryPolicy{MaximumAttempts: 1},
	}
	activityCtx := workflow.WithActivityOptions(ctx, options)
	status.Phase = "PAYMENT_PENDING"
	payment := harness.EffectRequest{
		OrderID: order.OrderID, AmountCents: order.AmountCents,
		OperationID: harness.OperationID(order.PaymentToken),
	}
	var receipt harness.EffectReceipt
	if err := workflow.ExecuteActivity(activityCtx, harness.PaymentActivityName, payment).Get(activityCtx, &receipt); err != nil {
		return harness.OrderResult{}, err
	}
	status.Phase = "PAYMENT_COMMITTED"
	waitForCompletion(ctx, status)
	if err := completeOrder(ctx, order); err != nil {
		return harness.OrderResult{}, err
	}
	status.Phase = "DELIVERED"
	return resultFor(status), nil
}

func runManualBranchOrderWorkflow(ctx workflow.Context, order harness.Order) (harness.OrderResult, error) {
	// Keep the v1 manual branch byte-for-byte on the existing payment path so
	// its Activity type, input, timeout, and retry policy are unchanged.
	return runOrderWorkflow(ctx, order)
}
