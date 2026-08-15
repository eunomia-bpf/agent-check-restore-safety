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

const OperationObservationV1 = kernel.OperationObservationV1

type operationReceiptV1 struct {
	Schema          int    `json:"schema"`
	OperationID     string `json:"operation_id"`
	Outcome         string `json:"outcome"`
	ResultHash      string `json:"result_hash"`
	RemoteReference string `json:"remote_reference,omitempty"`
}

type operationObservationV1 struct {
	Schema          int    `json:"schema"`
	OperationID     string `json:"operation_id"`
	RequestHash     string `json:"request_hash"`
	Outcome         string `json:"outcome"`
	FactHash        string `json:"fact_hash"`
	RemoteReference string `json:"remote_reference"`
}

func classifyResponse(classifier string, operationID string, response *http.Response, body []byte) (kernel.Phase, string, string, error) {
	switch classifier {
	case ResponseReceiptV1:
		return classifyReceiptV1(operationID, response, body)
	default:
		return "", "", "", fmt.Errorf("unsupported response classifier %q", classifier)
	}
}

func supportedClassifier(classifier string) bool {
	return classifier == ResponseReceiptV1
}

func classifyObservation(classifier, operationID, requestHash string, response *http.Response, body []byte) (kernel.Phase, string, string, error) {
	if classifier != OperationObservationV1 {
		return "", "", "", fmt.Errorf("unsupported query classifier %q", classifier)
	}
	if response.StatusCode != http.StatusOK {
		return "", "", "", fmt.Errorf("observation response status is %d, want 200", response.StatusCode)
	}
	mediaType, _, err := mime.ParseMediaType(response.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" {
		return "", "", "", errors.New("observation response is not application/json")
	}

	fields, err := decodeObservationObject(body)
	if err != nil {
		return "", "", "", err
	}
	var observation operationObservationV1
	for name, target := range map[string]any{
		"schema": &observation.Schema, "operation_id": &observation.OperationID,
		"request_hash": &observation.RequestHash, "outcome": &observation.Outcome,
		"fact_hash": &observation.FactHash, "remote_reference": &observation.RemoteReference,
	} {
		if bytes.Equal(bytes.TrimSpace(fields[name]), []byte("null")) {
			return "", "", "", fmt.Errorf("operation observation field %q is null", name)
		}
		if err := json.Unmarshal(fields[name], target); err != nil {
			return "", "", "", fmt.Errorf("decode operation observation field %q: %w", name, err)
		}
	}
	if observation.Schema != 1 {
		return "", "", "", fmt.Errorf("unsupported operation observation schema %d", observation.Schema)
	}
	if observation.OperationID != operationID {
		return "", "", "", errors.New("operation observation identity does not match request")
	}
	if !canonicalSHA256(observation.RequestHash) {
		return "", "", "", errors.New("operation observation request hash is invalid")
	}
	if observation.RequestHash != requestHash {
		return "", "", "", errors.New("operation observation request hash does not match request")
	}
	if len(observation.RemoteReference) > 1024 {
		return "", "", "", errors.New("operation observation remote reference is too large")
	}
	switch kernel.Phase(observation.Outcome) {
	case kernel.Succeeded, kernel.Failed:
		if !canonicalSHA256(observation.FactHash) {
			return "", "", "", errors.New("settled operation observation fact hash is invalid")
		}
		return kernel.Phase(observation.Outcome), observation.FactHash, observation.RemoteReference, nil
	case kernel.Unknown:
		return "", "", "", errors.New("operation observation outcome must use inconclusive, not unknown")
	default:
		if observation.Outcome != "inconclusive" {
			return "", "", "", fmt.Errorf("operation observation outcome %q is invalid", observation.Outcome)
		}
		if observation.FactHash != "" {
			return "", "", "", errors.New("inconclusive operation observation carries a fact hash")
		}
		return kernel.Unknown, "", observation.RemoteReference, nil
	}
}

func decodeObservationObject(body []byte) (map[string]json.RawMessage, error) {
	required := map[string]bool{
		"schema": true, "operation_id": true, "request_hash": true,
		"outcome": true, "fact_hash": true, "remote_reference": true,
	}
	return decodeJSONObject(body, "operation observation", required, nil)
}

func decodeReceiptV1(body []byte) (operationReceiptV1, error) {
	required := map[string]bool{
		"schema": true, "operation_id": true, "outcome": true, "result_hash": true,
	}
	optional := map[string]bool{"remote_reference": true}
	fields, err := decodeJSONObject(body, "operation receipt", required, optional)
	if err != nil {
		return operationReceiptV1{}, err
	}
	var receipt operationReceiptV1
	for name, target := range map[string]any{
		"schema": &receipt.Schema, "operation_id": &receipt.OperationID,
		"outcome": &receipt.Outcome, "result_hash": &receipt.ResultHash,
		"remote_reference": &receipt.RemoteReference,
	} {
		raw, present := fields[name]
		if !present {
			continue
		}
		if bytes.Equal(bytes.TrimSpace(raw), []byte("null")) {
			return operationReceiptV1{}, fmt.Errorf("operation receipt field %q is null", name)
		}
		if err := json.Unmarshal(raw, target); err != nil {
			return operationReceiptV1{}, fmt.Errorf("decode operation receipt field %q: %w", name, err)
		}
	}
	return receipt, nil
}

func decodeJSONObject(
	body []byte,
	label string,
	required map[string]bool,
	optional map[string]bool,
) (map[string]json.RawMessage, error) {
	decoder := json.NewDecoder(bytes.NewReader(body))
	start, err := decoder.Token()
	if err != nil || start != json.Delim('{') {
		return nil, fmt.Errorf("%s is not a JSON object", label)
	}
	allowed := make(map[string]bool, len(required)+len(optional))
	for name := range required {
		allowed[name] = true
	}
	for name := range optional {
		allowed[name] = true
	}
	fields := make(map[string]json.RawMessage, len(allowed))
	for decoder.More() {
		token, err := decoder.Token()
		if err != nil {
			return nil, fmt.Errorf("decode %s key: %w", label, err)
		}
		name, ok := token.(string)
		if !ok {
			return nil, fmt.Errorf("%s key is not a string", label)
		}
		if !allowed[name] {
			return nil, fmt.Errorf("%s contains unknown field %q", label, name)
		}
		if _, duplicate := fields[name]; duplicate {
			return nil, fmt.Errorf("%s contains duplicate field %q", label, name)
		}
		var raw json.RawMessage
		if err := decoder.Decode(&raw); err != nil {
			return nil, fmt.Errorf("decode %s field %q: %w", label, name, err)
		}
		fields[name] = raw
	}
	end, err := decoder.Token()
	if err != nil || end != json.Delim('}') {
		return nil, fmt.Errorf("%s has an invalid terminator", label)
	}
	for name := range required {
		if _, ok := fields[name]; !ok {
			return nil, fmt.Errorf("%s is missing field %q", label, name)
		}
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return nil, fmt.Errorf("%s contains multiple JSON values", label)
		}
		return nil, fmt.Errorf("decode %s end: %w", label, err)
	}
	return fields, nil
}

func canonicalSHA256(value string) bool {
	if len(value) != 64 {
		return false
	}
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == 32 && hex.EncodeToString(decoded) == value
}

func classifyReceiptV1(operationID string, response *http.Response, body []byte) (kernel.Phase, string, string, error) {
	if response.StatusCode != http.StatusOK {
		return "", "", "", fmt.Errorf("receipt response status is %d, want 200", response.StatusCode)
	}
	mediaType, _, err := mime.ParseMediaType(response.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" {
		return "", "", "", errors.New("receipt response is not application/json")
	}
	receipt, err := decodeReceiptV1(body)
	if err != nil {
		return "", "", "", err
	}
	if receipt.Schema != 1 {
		return "", "", "", fmt.Errorf("unsupported operation receipt schema %d", receipt.Schema)
	}
	if len(receipt.RemoteReference) > 1024 {
		return "", "", "", errors.New("operation receipt remote reference is too large")
	}
	if receipt.OperationID != operationID {
		return "", "", "", errors.New("operation receipt identity does not match request")
	}
	if !canonicalSHA256(receipt.ResultHash) {
		return "", "", "", errors.New("operation receipt result hash is invalid")
	}
	switch kernel.Phase(receipt.Outcome) {
	case kernel.Succeeded:
		if receipt.RemoteReference == "" {
			return "", "", "", errors.New("successful operation receipt has no remote reference")
		}
		return kernel.Succeeded, receipt.ResultHash, receipt.RemoteReference, nil
	case kernel.Failed:
		return kernel.Failed, receipt.ResultHash, receipt.RemoteReference, nil
	default:
		return "", "", "", fmt.Errorf("operation receipt outcome %q is not settled", receipt.Outcome)
	}
}
