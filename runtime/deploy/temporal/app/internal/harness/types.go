package harness

import (
	"crypto/sha256"
	"encoding/hex"
)

const (
	TaskQueue                     = "safe-change-food-orders"
	DeploymentName                = "safe-change-food-order-worker"
	PinnedWorkflowName            = "FoodOrderPinned"
	AutoUpgradeWorkflowName       = "FoodOrderAutoUpgrade"
	ManualBranchWorkflowName      = "FoodOrderManualBranch"
	ManualBranchBehavior          = "manual"
	StatusQueryName               = "status"
	PreparationFinishedSignalName = "preparation_finished"
	DriverSelectedSignalName      = "driver_selected"
	DriverAtRestaurantSignalName  = "driver_at_restaurant"
	DeliveryFinishedSignalName    = "delivery_finished"
	PaymentActivityName           = "ChargePayment"
	PaymentQueryActivityName      = "QueryPayment"
	PreparationActivityName       = "PrepareFood"
	DeliveryActivityName          = "ScheduleDelivery"
	CompletionActivityName        = "CompleteOrder"
	OperationDomain               = "temporal-order-workflow"
	DeliveryRegion                = "San Jose (CA)"
)

func OperationID(identity string) string {
	digest := sha256.Sum256([]byte("operation-id-v1\x00" + OperationDomain + "\x00" + identity))
	return "op-" + hex.EncodeToString(digest[:])
}

type Order struct {
	OrderID             string    `json:"order_id"`
	RestaurantID        string    `json:"restaurant_id"`
	Products            []Product `json:"products"`
	AmountCents         int64     `json:"amount_cents"`
	DeliveryDelayMillis int64     `json:"delivery_delay_millis"`
	PaymentToken        string    `json:"payment_token"`
}

type Product struct {
	ProductID   string `json:"product_id"`
	Description string `json:"description"`
	Quantity    int    `json:"quantity"`
}

type EffectRequest struct {
	OrderID        string `json:"order_id"`
	AmountCents    int64  `json:"amount_cents"`
	OperationID    string `json:"operation_id"`
	ClosureVersion string `json:"closure_version,omitempty"`
}

type EffectReceipt struct {
	Schema          int    `json:"schema"`
	OperationID     string `json:"operation_id"`
	Outcome         string `json:"outcome"`
	ResultHash      string `json:"result_hash"`
	RemoteReference string `json:"remote_reference"`
}

type PaymentObservation struct {
	Schema          int    `json:"schema"`
	OperationID     string `json:"operation_id"`
	RequestHash     string `json:"request_hash"`
	Outcome         string `json:"outcome"`
	FactHash        string `json:"fact_hash"`
	RemoteReference string `json:"remote_reference"`
}

type PreparationRequest struct {
	OrderID      string    `json:"order_id"`
	RestaurantID string    `json:"restaurant_id"`
	Products     []Product `json:"products"`
}

type PreparationReceipt struct {
	Schema       int    `json:"schema"`
	OrderID      string `json:"order_id"`
	RestaurantID string `json:"restaurant_id"`
	ProductCount int    `json:"product_count"`
	Outcome      string `json:"outcome"`
}

type DeliveryRequest struct {
	OrderID      string `json:"order_id"`
	DeliveryID   string `json:"delivery_id"`
	RestaurantID string `json:"restaurant_id"`
	Region       string `json:"region"`
}

type DeliveryDispatch struct {
	Schema       int    `json:"schema"`
	OrderID      string `json:"order_id"`
	DeliveryID   string `json:"delivery_id"`
	RestaurantID string `json:"restaurant_id"`
	Region       string `json:"region"`
	Outcome      string `json:"outcome"`
}

type DriverAssignment struct {
	DeliveryID string `json:"delivery_id"`
	DriverID   string `json:"driver_id"`
}

type OrderStatus struct {
	Schema       int      `json:"schema"`
	OrderID      string   `json:"order_id"`
	RestaurantID string   `json:"restaurant_id"`
	ProductCount int      `json:"product_count"`
	WorkerBuild  string   `json:"worker_build"`
	Phase        string   `json:"phase"`
	DeliveryID   string   `json:"delivery_id"`
	DriverID     string   `json:"driver_id"`
	Stages       []string `json:"stages"`
}

type OrderResult struct {
	Schema       int      `json:"schema"`
	OrderID      string   `json:"order_id"`
	RestaurantID string   `json:"restaurant_id"`
	ProductCount int      `json:"product_count"`
	WorkerBuild  string   `json:"worker_build"`
	Phase        string   `json:"phase"`
	DeliveryID   string   `json:"delivery_id"`
	DriverID     string   `json:"driver_id"`
	Stages       []string `json:"stages"`
}
