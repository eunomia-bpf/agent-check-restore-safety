package workerapp

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/deploy/temporal/app/internal/harness"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
)

func fulfillmentTestWorkflow(ctx workflow.Context, order harness.Order, closureVersion string) (harness.OrderResult, error) {
	status, err := newStatus(ctx, order)
	if err != nil {
		return harness.OrderResult{}, err
	}
	if err := finishFoodOrder(ctx, order, status, closureVersion); err != nil {
		return harness.OrderResult{}, err
	}
	return resultFor(status), nil
}

func fullTestOrder() harness.Order {
	return harness.Order{
		OrderID: "order-1", RestaurantID: "restaurant-1",
		Products: []harness.Product{{
			ProductID: "pizza-1", Description: "Margherita Pizza", Quantity: 2,
		}},
		AmountCents: 4200, DeliveryDelayMillis: 25, PaymentToken: "payment-token-1",
	}
}

func registerFulfillmentTestActivities(
	t *testing.T, env *testsuite.TestWorkflowEnvironment,
	preparationRequests chan<- harness.PreparationRequest,
	deliveryRequests chan<- harness.DeliveryRequest,
	completionRequests chan<- harness.EffectRequest,
) {
	t.Helper()
	env.RegisterActivityWithOptions(
		func(_ context.Context, request harness.PreparationRequest) (harness.PreparationReceipt, error) {
			preparationRequests <- request
			quantity, err := productQuantity(request.Products)
			if err != nil {
				return harness.PreparationReceipt{}, err
			}
			return harness.PreparationReceipt{
				Schema: 1, OrderID: request.OrderID, RestaurantID: request.RestaurantID,
				ProductCount: quantity, Outcome: "accepted",
			}, nil
		},
		activity.RegisterOptions{Name: harness.PreparationActivityName},
	)
	env.RegisterActivityWithOptions(
		func(_ context.Context, request harness.DeliveryRequest) (harness.DeliveryDispatch, error) {
			deliveryRequests <- request
			return harness.DeliveryDispatch{
				Schema: 1, OrderID: request.OrderID, DeliveryID: request.DeliveryID,
				RestaurantID: request.RestaurantID, Region: request.Region, Outcome: "scheduled",
			}, nil
		},
		activity.RegisterOptions{Name: harness.DeliveryActivityName},
	)
	env.RegisterActivityWithOptions(
		func(_ context.Context, request harness.EffectRequest) (harness.EffectReceipt, error) {
			completionRequests <- request
			return harness.EffectReceipt{
				Schema: 1, OperationID: request.OperationID, Outcome: "succeeded",
				ResultHash: strings.Repeat("a", 64), RemoteReference: "completion/" + request.OperationID,
			}, nil
		},
		activity.RegisterOptions{Name: harness.CompletionActivityName},
	)
}

func TestFulfillmentPreservesAllFoodOrderingStages(t *testing.T) {
	testSuite := &testsuite.WorkflowTestSuite{}
	env := testSuite.NewTestWorkflowEnvironment()
	preparationRequests := make(chan harness.PreparationRequest, 1)
	deliveryRequests := make(chan harness.DeliveryRequest, 1)
	completionRequests := make(chan harness.EffectRequest, 1)
	registerFulfillmentTestActivities(t, env, preparationRequests, deliveryRequests, completionRequests)

	env.RegisterDelayedCallback(func() {
		env.SignalWorkflow(harness.PreparationFinishedSignalName, nil)
	}, 30*time.Millisecond)
	env.RegisterDelayedCallback(func() {
		env.SignalWorkflow(harness.DriverSelectedSignalName, harness.DriverAssignment{
			DeliveryID: "delivery-order-1", DriverID: "driver-1",
		})
	}, 40*time.Millisecond)
	env.RegisterDelayedCallback(func() {
		env.SignalWorkflow(harness.DriverAtRestaurantSignalName, nil)
	}, 50*time.Millisecond)
	env.RegisterDelayedCallback(func() {
		env.SignalWorkflow(harness.DeliveryFinishedSignalName, nil)
	}, 60*time.Millisecond)

	env.ExecuteWorkflow(fulfillmentTestWorkflow, fullTestOrder(), "compatible-v2")
	require.True(t, env.IsWorkflowCompleted())
	require.NoError(t, env.GetWorkflowError())

	var result harness.OrderResult
	require.NoError(t, env.GetWorkflowResult(&result))
	require.Equal(t, harness.OrderResult{
		Schema: 1, OrderID: "order-1", RestaurantID: "restaurant-1", ProductCount: 2,
		WorkerBuild: buildID, Phase: "DELIVERED", DeliveryID: "delivery-order-1", DriverID: "driver-1",
		Stages: []string{
			"RESTAURANT_SELECTED", "CREATED", "SCHEDULED", "IN_PREPARATION",
			"SCHEDULING_DELIVERY", "WAITING_FOR_DRIVER", "IN_DELIVERY", "DELIVERED",
		},
	}, result)
	require.Equal(t, harness.PreparationRequest{
		OrderID: "order-1", RestaurantID: "restaurant-1",
		Products: []harness.Product{{ProductID: "pizza-1", Description: "Margherita Pizza", Quantity: 2}},
	}, <-preparationRequests)
	require.Equal(t, harness.DeliveryRequest{
		OrderID: "order-1", DeliveryID: "delivery-order-1",
		RestaurantID: "restaurant-1", Region: harness.DeliveryRegion,
	}, <-deliveryRequests)
	require.Equal(t, harness.EffectRequest{
		OrderID: "order-1", AmountCents: 4200,
		OperationID:    harness.OperationID("complete:order-1"),
		ClosureVersion: "compatible-v2",
	}, <-completionRequests)
}

func TestFulfillmentRejectsDriverForAnotherDelivery(t *testing.T) {
	testSuite := &testsuite.WorkflowTestSuite{}
	env := testSuite.NewTestWorkflowEnvironment()
	preparationRequests := make(chan harness.PreparationRequest, 1)
	deliveryRequests := make(chan harness.DeliveryRequest, 1)
	completionRequests := make(chan harness.EffectRequest, 1)
	registerFulfillmentTestActivities(t, env, preparationRequests, deliveryRequests, completionRequests)

	env.RegisterDelayedCallback(func() {
		env.SignalWorkflow(harness.PreparationFinishedSignalName, nil)
	}, 30*time.Millisecond)
	env.RegisterDelayedCallback(func() {
		env.SignalWorkflow(harness.DriverSelectedSignalName, harness.DriverAssignment{
			DeliveryID: "delivery-another-order", DriverID: "driver-1",
		})
	}, 40*time.Millisecond)

	env.ExecuteWorkflow(fulfillmentTestWorkflow, fullTestOrder(), "")
	require.True(t, env.IsWorkflowCompleted())
	require.ErrorContains(t, env.GetWorkflowError(), "driver assignment does not match the delivery")
	select {
	case request := <-completionRequests:
		t.Fatalf("completion ran after mismatched driver assignment: %+v", request)
	default:
	}
}

func TestNewStatusRejectsIncompleteFoodOrder(t *testing.T) {
	order := fullTestOrder()
	order.RestaurantID = ""
	testSuite := &testsuite.WorkflowTestSuite{}
	env := testSuite.NewTestWorkflowEnvironment()
	env.ExecuteWorkflow(fulfillmentTestWorkflow, order, "")
	require.Error(t, env.GetWorkflowError())
}
