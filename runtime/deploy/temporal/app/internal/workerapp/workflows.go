package workerapp

import (
	"errors"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/deploy/temporal/app/internal/harness"
	"go.temporal.io/sdk/workflow"
)

func PinnedOrderWorkflow(ctx workflow.Context, order harness.Order) (harness.OrderResult, error) {
	return runOrderWorkflow(ctx, order)
}

func AutoUpgradeOrderWorkflow(ctx workflow.Context, order harness.Order) (harness.OrderResult, error) {
	return runOrderWorkflow(ctx, order)
}

func newStatus(ctx workflow.Context, order harness.Order) (*harness.OrderStatus, error) {
	if order.OrderID == "" || order.AmountCents <= 0 || order.PaymentToken == "" {
		return nil, errors.New("order_id, positive amount_cents, and payment_token are required")
	}
	status := &harness.OrderStatus{
		Schema: 1, OrderID: order.OrderID, WorkerBuild: buildID, Phase: "STARTED",
	}
	if err := workflow.SetQueryHandler(ctx, harness.StatusQueryName, func() (harness.OrderStatus, error) {
		return *status, nil
	}); err != nil {
		return nil, err
	}
	return status, nil
}

func waitForCompletion(ctx workflow.Context, status *harness.OrderStatus) {
	status.Phase = "WAITING_FOR_COMPLETION"
	var signal struct{}
	workflow.GetSignalChannel(ctx, harness.CompleteSignalName).Receive(ctx, &signal)
}

func resultFor(status *harness.OrderStatus) harness.OrderResult {
	return harness.OrderResult{
		Schema: 1, OrderID: status.OrderID, WorkerBuild: status.WorkerBuild, Phase: status.Phase,
	}
}
