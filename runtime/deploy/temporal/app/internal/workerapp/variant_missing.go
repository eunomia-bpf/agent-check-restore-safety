//go:build !worker_v1 && !worker_v2 && !worker_compatible_v2

package workerapp

import (
	"errors"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/deploy/temporal/app/internal/harness"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

const buildID = ""

func registerVariantActivities(worker.Worker, *Activities) {}

func runOrderWorkflow(workflow.Context, harness.Order) (harness.OrderResult, error) {
	return harness.OrderResult{}, errors.New("worker build tag is required")
}

func runManualBranchOrderWorkflow(workflow.Context, harness.Order) (harness.OrderResult, error) {
	return harness.OrderResult{}, errors.New("worker build tag is required")
}
