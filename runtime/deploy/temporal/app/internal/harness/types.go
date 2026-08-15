package harness

import (
	"crypto/sha256"
	"encoding/hex"
)

const (
	TaskQueue               = "safe-change-food-orders"
	DeploymentName          = "safe-change-food-order-worker"
	PinnedWorkflowName      = "FoodOrderPinned"
	AutoUpgradeWorkflowName = "FoodOrderAutoUpgrade"
	StatusQueryName         = "status"
	CompleteSignalName      = "complete"
	PaymentActivityName     = "ChargePayment"
	CompletionActivityName  = "CompleteOrder"
	OperationDomain         = "temporal-order-workflow"
)

func OperationID(identity string) string {
	digest := sha256.Sum256([]byte("operation-id-v1\x00" + OperationDomain + "\x00" + identity))
	return "op-" + hex.EncodeToString(digest[:])
}

type Order struct {
	OrderID      string `json:"order_id"`
	AmountCents  int64  `json:"amount_cents"`
	PaymentToken string `json:"payment_token"`
}

type EffectRequest struct {
	OrderID     string `json:"order_id"`
	AmountCents int64  `json:"amount_cents"`
	OperationID string `json:"operation_id"`
}

type EffectReceipt struct {
	Schema          int    `json:"schema"`
	OperationID     string `json:"operation_id"`
	Outcome         string `json:"outcome"`
	ResultHash      string `json:"result_hash"`
	RemoteReference string `json:"remote_reference"`
}

type OrderStatus struct {
	Schema      int    `json:"schema"`
	OrderID     string `json:"order_id"`
	WorkerBuild string `json:"worker_build"`
	Phase       string `json:"phase"`
}

type OrderResult struct {
	Schema      int    `json:"schema"`
	OrderID     string `json:"order_id"`
	WorkerBuild string `json:"worker_build"`
	Phase       string `json:"phase"`
}
