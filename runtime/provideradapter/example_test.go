package provideradapter_test

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/provideradapter"
)

type exampleDriver struct{}

func (exampleDriver) Execute(_ context.Context, effect provideradapter.Effect) (provideradapter.Result, error) {
	return provideradapter.Result{
		Outcome: provideradapter.Succeeded,
		FactHash: provideradapter.HashFact(
			[]byte("provider-charge\x00" + effect.OperationID),
		),
		RemoteReference: "provider/charge-42",
	}, nil
}

func (exampleDriver) Observe(_ context.Context, query provideradapter.Query) (provideradapter.Result, error) {
	return provideradapter.Result{
		Outcome:         provideradapter.Inconclusive,
		RemoteReference: "provider/search/" + query.OperationID,
	}, nil
}

func ExampleNewHandler() {
	handler, err := provideradapter.NewHandler(provideradapter.Config{
		EffectPath: "/v1/payment",
		QueryPath:  "/v1/payment/query",
	}, exampleDriver{})
	if err != nil {
		panic(err)
	}

	operationID := "op-" + strings.Repeat("a", 64)
	request := httptest.NewRequest(http.MethodPost, "http://adapter/v1/payment", strings.NewReader(`{"amount":4200}`))
	request.Header.Set(provideradapter.HeaderOperationID, operationID)
	request.Header.Set(provideradapter.HeaderIdempotencyKey, operationID)
	request.Header.Set("Content-Type", "application/json")
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, request)

	var receipt struct {
		Outcome string `json:"outcome"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &receipt); err != nil {
		panic(err)
	}
	fmt.Println(recorder.Code, receipt.Outcome)
	// Output: 200 succeeded
}
