package workerapp

import (
	"errors"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/deploy/temporal/app/internal/harness"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
)

func PinnedOrderWorkflow(ctx workflow.Context, order harness.Order) (harness.OrderResult, error) {
	return runOrderWorkflow(ctx, order)
}

func AutoUpgradeOrderWorkflow(ctx workflow.Context, order harness.Order) (harness.OrderResult, error) {
	return runOrderWorkflow(ctx, order)
}

func ManualBranchOrderWorkflow(ctx workflow.Context, order harness.Order) (harness.OrderResult, error) {
	return runManualBranchOrderWorkflow(ctx, order)
}

func newStatus(ctx workflow.Context, order harness.Order) (*harness.OrderStatus, error) {
	quantity, err := productQuantity(order.Products)
	if err != nil {
		return nil, err
	}
	if order.OrderID == "" || order.RestaurantID == "" || order.AmountCents <= 0 ||
		order.DeliveryDelayMillis <= 0 || order.PaymentToken == "" {
		return nil, errors.New("order_id, restaurant_id, products, positive amount_cents, positive delivery_delay_millis, and payment_token are required")
	}
	status := &harness.OrderStatus{
		Schema: 1, OrderID: order.OrderID, RestaurantID: order.RestaurantID,
		ProductCount: quantity, WorkerBuild: buildID, Phase: "CREATED",
		Stages: []string{"RESTAURANT_SELECTED", "CREATED"},
	}
	if err := workflow.SetQueryHandler(ctx, harness.StatusQueryName, func() (harness.OrderStatus, error) {
		return *status, nil
	}); err != nil {
		return nil, err
	}
	return status, nil
}

func setPhase(status *harness.OrderStatus, phase string) {
	status.Phase = phase
	status.Stages = append(status.Stages, phase)
}

func finishFoodOrder(
	ctx workflow.Context, order harness.Order, status *harness.OrderStatus, closureVersion string,
) error {
	// The downstream sequence mirrors the pinned Restate food-ordering fixture:
	// schedule a durable preparation time, ask the selected restaurant to
	// prepare, wait for its callback, request delivery matching, then wait for
	// driver selection, pickup, and final delivery before recording completion.
	setPhase(status, "SCHEDULED")
	if err := workflow.Sleep(ctx, time.Duration(order.DeliveryDelayMillis)*time.Millisecond); err != nil {
		return err
	}

	activityCtx := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{
		StartToCloseTimeout: 30 * time.Second,
		RetryPolicy:         &temporal.RetryPolicy{MaximumAttempts: 1},
	})
	preparationRequest := harness.PreparationRequest{
		OrderID: order.OrderID, RestaurantID: order.RestaurantID, Products: order.Products,
	}
	var preparation harness.PreparationReceipt
	if err := workflow.ExecuteActivity(
		activityCtx, harness.PreparationActivityName, preparationRequest,
	).Get(activityCtx, &preparation); err != nil {
		return err
	}
	if preparation.Schema != 1 || preparation.OrderID != order.OrderID ||
		preparation.RestaurantID != order.RestaurantID ||
		preparation.ProductCount != status.ProductCount || preparation.Outcome != "accepted" {
		return errors.New("restaurant preparation receipt does not match the order")
	}
	setPhase(status, "IN_PREPARATION")
	var preparationFinished struct{}
	workflow.GetSignalChannel(ctx, harness.PreparationFinishedSignalName).Receive(ctx, &preparationFinished)

	setPhase(status, "SCHEDULING_DELIVERY")
	status.DeliveryID = "delivery-" + order.OrderID
	deliveryRequest := harness.DeliveryRequest{
		OrderID: order.OrderID, DeliveryID: status.DeliveryID,
		RestaurantID: order.RestaurantID, Region: harness.DeliveryRegion,
	}
	var dispatch harness.DeliveryDispatch
	if err := workflow.ExecuteActivity(
		activityCtx, harness.DeliveryActivityName, deliveryRequest,
	).Get(activityCtx, &dispatch); err != nil {
		return err
	}
	if dispatch.Schema != 1 || dispatch.OrderID != order.OrderID ||
		dispatch.DeliveryID != status.DeliveryID || dispatch.RestaurantID != order.RestaurantID ||
		dispatch.Region != harness.DeliveryRegion || dispatch.Outcome != "scheduled" {
		return errors.New("delivery dispatch receipt does not match the order")
	}
	var assignment harness.DriverAssignment
	workflow.GetSignalChannel(ctx, harness.DriverSelectedSignalName).Receive(ctx, &assignment)
	if assignment.DeliveryID != status.DeliveryID || assignment.DriverID == "" {
		return errors.New("driver assignment does not match the delivery")
	}
	status.DriverID = assignment.DriverID
	setPhase(status, "WAITING_FOR_DRIVER")

	var driverAtRestaurant struct{}
	workflow.GetSignalChannel(ctx, harness.DriverAtRestaurantSignalName).Receive(ctx, &driverAtRestaurant)
	setPhase(status, "IN_DELIVERY")
	var deliveryFinished struct{}
	workflow.GetSignalChannel(ctx, harness.DeliveryFinishedSignalName).Receive(ctx, &deliveryFinished)

	if err := completeOrderWithClosureVersion(ctx, order, closureVersion); err != nil {
		return err
	}
	setPhase(status, "DELIVERED")
	return nil
}

func resultFor(status *harness.OrderStatus) harness.OrderResult {
	return harness.OrderResult{
		Schema: 1, OrderID: status.OrderID, RestaurantID: status.RestaurantID,
		ProductCount: status.ProductCount, WorkerBuild: status.WorkerBuild, Phase: status.Phase,
		DeliveryID: status.DeliveryID, DriverID: status.DriverID,
		Stages: append([]string(nil), status.Stages...),
	}
}
