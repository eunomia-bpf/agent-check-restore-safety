package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/deploy/temporal/app/internal/harness"
	"go.temporal.io/sdk/client"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run() error {
	var address, behavior, workflowID, orderID, paymentToken string
	var amountCents int64
	var wait bool
	flag.StringVar(&address, "address", envOr("TEMPORAL_ADDRESS", client.DefaultHostPort), "Temporal frontend address")
	flag.StringVar(&behavior, "behavior", "pinned", "workflow behavior: pinned, autoupgrade, or manual")
	flag.StringVar(&workflowID, "workflow-id", "", "required Temporal Workflow ID")
	flag.StringVar(&orderID, "order-id", "", "required logical order ID")
	flag.StringVar(&paymentToken, "payment-token", "", "required stable external payment identity")
	flag.Int64Var(&amountCents, "amount-cents", 0, "positive payment amount")
	flag.BoolVar(&wait, "wait", false, "wait for the terminal workflow result")
	flag.Parse()
	if workflowID == "" || orderID == "" || paymentToken == "" || amountCents <= 0 {
		return errors.New("workflow-id, order-id, payment-token, and positive amount-cents are required")
	}
	workflowName := harness.PinnedWorkflowName
	if behavior == "autoupgrade" {
		workflowName = harness.AutoUpgradeWorkflowName
	} else if behavior == harness.ManualBranchBehavior {
		workflowName = harness.ManualBranchWorkflowName
	} else if behavior != "pinned" {
		return errors.New("behavior must be pinned, autoupgrade, or manual")
	}
	temporalClient, err := client.Dial(client.Options{
		HostPort: address,
		Identity: "safe-change-temporal-starter",
	})
	if err != nil {
		return err
	}
	defer temporalClient.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	run, err := temporalClient.ExecuteWorkflow(ctx, client.StartWorkflowOptions{
		ID: workflowID, TaskQueue: harness.TaskQueue,
	}, workflowName, harness.Order{
		OrderID: orderID, AmountCents: amountCents, PaymentToken: paymentToken,
	})
	if err != nil {
		return err
	}
	output := struct {
		Schema     int                  `json:"schema"`
		Behavior   string               `json:"behavior"`
		WorkflowID string               `json:"workflow_id"`
		RunID      string               `json:"run_id"`
		Result     *harness.OrderResult `json:"result,omitempty"`
	}{Schema: 1, Behavior: behavior, WorkflowID: run.GetID(), RunID: run.GetRunID()}
	if wait {
		var result harness.OrderResult
		if err := run.Get(context.Background(), &result); err != nil {
			return err
		}
		output.Result = &result
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetEscapeHTML(false)
	return encoder.Encode(output)
}

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
