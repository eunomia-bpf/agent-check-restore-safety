//go:build worker_v2

package workerapp

import (
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/deploy/temporal/app/internal/harness"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

const buildID = "food-order-v2"

const (
	manualPaymentChangeID          = "manual-payment-reconciliation-v1"
	manualPaymentVersion           = workflow.Version(1)
	manualQueryFailedMessage       = "manual payment reconciliation query failed"
	manualInconclusiveMessage      = "manual payment reconciliation was inconclusive"
	manualUnexpectedOutcomeMessage = "manual payment reconciliation returned an unexpected outcome"
	manualReconciliationErrorType  = "ManualPaymentReconciliationFailed"
)

func registerVariantActivities(w worker.Worker, activities *Activities) {
	w.RegisterActivityWithOptions(activities.QueryPayment, activityOptions(harness.PaymentQueryActivityName))
	w.RegisterActivityWithOptions(activities.PrepareFood, activityOptions(harness.PreparationActivityName))
	w.RegisterActivityWithOptions(activities.ScheduleDelivery, activityOptions(harness.DeliveryActivityName))
	w.RegisterActivityWithOptions(activities.CompleteOrder, activityOptions(harness.CompletionActivityName))
}

func runOrderWorkflow(ctx workflow.Context, order harness.Order) (harness.OrderResult, error) {
	status, err := newStatus(ctx, order)
	if err != nil {
		return harness.OrderResult{}, err
	}
	// Target v2 intentionally has no payment call and no payment activity.
	if err := finishFoodOrder(ctx, order, status, ""); err != nil {
		return harness.OrderResult{}, err
	}
	return resultFor(status), nil
}

func runManualBranchOrderWorkflow(ctx workflow.Context, order harness.Order) (harness.OrderResult, error) {
	status, err := newStatus(ctx, order)
	if err != nil {
		return harness.OrderResult{}, err
	}
	version := workflow.GetVersion(ctx, manualPaymentChangeID, workflow.DefaultVersion, manualPaymentVersion)
	if version == workflow.DefaultVersion {
		setPhase(status, "PAYMENT_PENDING")
		payment := harness.EffectRequest{
			OrderID: order.OrderID, AmountCents: order.AmountCents,
			OperationID: harness.OperationID(order.PaymentToken),
		}
		paymentOptions := workflow.ActivityOptions{
			StartToCloseTimeout: 30 * time.Second,
			RetryPolicy:         &temporal.RetryPolicy{MaximumAttempts: 1},
		}
		paymentCtx := workflow.WithActivityOptions(ctx, paymentOptions)
		var receipt harness.EffectReceipt
		err := workflow.ExecuteActivity(paymentCtx, harness.PaymentActivityName, payment).Get(paymentCtx, &receipt)
		if err != nil {
			if !temporal.IsTimeoutError(err) {
				return harness.OrderResult{}, err
			}
			setPhase(status, "PAYMENT_QUERY_PENDING")
			queryOptions := workflow.ActivityOptions{
				StartToCloseTimeout: time.Minute,
				RetryPolicy:         &temporal.RetryPolicy{MaximumAttempts: 1},
			}
			queryCtx := workflow.WithActivityOptions(ctx, queryOptions)
			var observation harness.PaymentObservation
			if err := workflow.ExecuteActivity(queryCtx, harness.PaymentQueryActivityName, payment).Get(queryCtx, &observation); err != nil {
				return harness.OrderResult{}, manualReconciliationError(manualQueryFailedMessage)
			}
			switch observation.Outcome {
			case "succeeded":
				// A strict provider observation settles the timed-out legacy call.
			case "inconclusive":
				return harness.OrderResult{}, manualReconciliationError(manualInconclusiveMessage)
			default:
				return harness.OrderResult{}, manualReconciliationError(manualUnexpectedOutcomeMessage)
			}
		}
		setPhase(status, "PAYMENT_COMMITTED")
	} else if version != manualPaymentVersion {
		return harness.OrderResult{}, manualReconciliationError(manualUnexpectedOutcomeMessage)
	}
	if err := finishFoodOrder(ctx, order, status, ""); err != nil {
		return harness.OrderResult{}, err
	}
	return resultFor(status), nil
}

func manualReconciliationError(message string) error {
	return temporal.NewNonRetryableApplicationError(message, manualReconciliationErrorType, nil)
}
