package gateway

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

// ResponseReceiptV1 names the first registered response contract.  A plain
// HTTP status is never enough to settle an Operation under this contract.
const ResponseReceiptV1 = kernel.ResponseReceiptV1

type operationReceiptV1 struct {
	Schema          int    `json:"schema"`
	OperationID     string `json:"operation_id"`
	Outcome         string `json:"outcome"`
	ResultHash      string `json:"result_hash"`
	RemoteReference string `json:"remote_reference,omitempty"`
}

func classifyResponse(classifier string, operationID string, response *http.Response, body []byte) (kernel.Phase, string, error) {
	switch classifier {
	case ResponseReceiptV1:
		return classifyReceiptV1(operationID, response, body)
	default:
		return "", "", fmt.Errorf("unsupported response classifier %q", classifier)
	}
}

func supportedClassifier(classifier string) bool {
	return classifier == ResponseReceiptV1
}

func classifyReceiptV1(operationID string, response *http.Response, body []byte) (kernel.Phase, string, error) {
	if response.StatusCode != http.StatusOK {
		return "", "", fmt.Errorf("receipt response status is %d, want 200", response.StatusCode)
	}
	mediaType, _, err := mime.ParseMediaType(response.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" {
		return "", "", errors.New("receipt response is not application/json")
	}
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	var receipt operationReceiptV1
	if err := decoder.Decode(&receipt); err != nil {
		return "", "", fmt.Errorf("decode operation receipt: %w", err)
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return "", "", errors.New("operation receipt contains multiple JSON values")
		}
		return "", "", fmt.Errorf("decode operation receipt end: %w", err)
	}
	if receipt.Schema != 1 {
		return "", "", fmt.Errorf("unsupported operation receipt schema %d", receipt.Schema)
	}
	if len(receipt.RemoteReference) > 1024 {
		return "", "", errors.New("operation receipt remote reference is too large")
	}
	if receipt.OperationID != operationID {
		return "", "", errors.New("operation receipt identity does not match request")
	}
	if len(receipt.ResultHash) != 64 {
		return "", "", errors.New("operation receipt result hash is invalid")
	}
	decodedHash, err := hex.DecodeString(receipt.ResultHash)
	if err != nil || hex.EncodeToString(decodedHash) != receipt.ResultHash {
		return "", "", errors.New("operation receipt result hash is invalid")
	}
	switch kernel.Phase(receipt.Outcome) {
	case kernel.Succeeded:
		if receipt.RemoteReference == "" {
			return "", "", errors.New("successful operation receipt has no remote reference")
		}
		return kernel.Succeeded, receipt.RemoteReference, nil
	case kernel.Failed:
		return kernel.Failed, receipt.RemoteReference, nil
	default:
		return "", "", fmt.Errorf("operation receipt outcome %q is not settled", receipt.Outcome)
	}
}
