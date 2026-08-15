//go:build worker_v2

package workerapp

import (
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/deploy/temporal/app/internal/harness"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

const buildID = "food-order-v2"

func registerVariantActivities(w worker.Worker, activities *Activities) {
	w.RegisterActivityWithOptions(activities.CompleteOrder, activityOptions(harness.CompletionActivityName))
}

func runOrderWorkflow(ctx workflow.Context, order harness.Order) (harness.OrderResult, error) {
	status, err := newStatus(ctx, order)
	if err != nil {
		return harness.OrderResult{}, err
	}
	// Target v2 intentionally has no payment call and no payment activity.
	waitForCompletion(ctx, status)
	if err := completeOrder(ctx, order); err != nil {
		return harness.OrderResult{}, err
	}
	status.Phase = "DELIVERED"
	return resultFor(status), nil
}
