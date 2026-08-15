package workerapp

import (
	"errors"
	"log"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/deploy/temporal/app/internal/harness"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

func Run(address, paymentURL, completionURL string) error {
	if buildID == "" {
		return errors.New("build the worker with exactly one of -tags worker_v1 or -tags worker_v2")
	}
	if address == "" {
		address = client.DefaultHostPort
	}
	if paymentURL == "" {
		paymentURL = "http://127.0.0.1:8081"
	}
	if completionURL == "" {
		completionURL = paymentURL
	}
	temporalClient, err := client.Dial(client.Options{
		HostPort: address,
		Identity: "safe-change-" + buildID + "-client",
	})
	if err != nil {
		return err
	}
	defer temporalClient.Close()

	w := worker.New(temporalClient, harness.TaskQueue, worker.Options{
		Identity: "safe-change-" + buildID + "-worker",
		DeploymentOptions: worker.DeploymentOptions{
			UseVersioning: true,
			Version: worker.WorkerDeploymentVersion{
				DeploymentName: harness.DeploymentName,
				BuildID:        buildID,
			},
		},
	})
	w.RegisterWorkflowWithOptions(PinnedOrderWorkflow, workflow.RegisterOptions{
		Name:               harness.PinnedWorkflowName,
		VersioningBehavior: workflow.VersioningBehaviorPinned,
	})
	w.RegisterWorkflowWithOptions(AutoUpgradeOrderWorkflow, workflow.RegisterOptions{
		Name:               harness.AutoUpgradeWorkflowName,
		VersioningBehavior: workflow.VersioningBehaviorAutoUpgrade,
	})
	w.RegisterWorkflowWithOptions(ManualBranchOrderWorkflow, workflow.RegisterOptions{
		Name:               harness.ManualBranchWorkflowName,
		VersioningBehavior: workflow.VersioningBehaviorAutoUpgrade,
	})
	registerVariantActivities(w, NewActivities(paymentURL, completionURL))
	log.Printf("Temporal worker deployment=%s build_id=%s task_queue=%s", harness.DeploymentName, buildID, harness.TaskQueue)
	return w.Run(worker.InterruptCh())
}
