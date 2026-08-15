package provideradapter

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strings"
	"unicode"
)

const (
	// HeaderOperationID carries the stable runtime Operation identity.
	HeaderOperationID = "X-Operation-ID"
	// HeaderOperationRequestHash binds an observation to the request stored in
	// History. It is present only on observation requests.
	HeaderOperationRequestHash = "X-Operation-Request-Hash"
	// HeaderIdempotencyKey is equal to HeaderOperationID on effect requests.
	HeaderIdempotencyKey = "Idempotency-Key"
)

const (
	maxRemoteReferenceBytes = 1024
	operationIDPrefix       = "op-"
)

// Outcome is a provider adapter's conclusion about an external fact.
type Outcome string

const (
	Succeeded    Outcome = "succeeded"
	Failed       Outcome = "failed"
	Inconclusive Outcome = "inconclusive"
)

// Effect is the complete public input passed to Driver.Execute. The
// IdempotencyKey is validated to be exactly equal to OperationID.
type Effect struct {
	OperationID    string
	IdempotencyKey string
	ContentType    string
	Body           []byte
}

// Query is the complete public input passed to Driver.Observe. RequestHash is
// the runtime's hash of the stored effect request; a Driver must not replace
// it with a body-only digest.
type Query struct {
	OperationID string
	RequestHash string
	ContentType string
	Body        []byte
}

// Result describes a settled external fact or an inconclusive observation.
// FactHash should normally be produced from a stable, canonical description
// of that fact with HashFact. It is required for Succeeded and Failed and must
// be empty for Inconclusive.
type Result struct {
	Outcome         Outcome
	FactHash        string
	RemoteReference string
}

type receiptV1 struct {
	Schema          int     `json:"schema"`
	OperationID     string  `json:"operation_id"`
	Outcome         Outcome `json:"outcome"`
	ResultHash      string  `json:"result_hash"`
	RemoteReference string  `json:"remote_reference"`
}

type observationV1 struct {
	Schema          int     `json:"schema"`
	OperationID     string  `json:"operation_id"`
	RequestHash     string  `json:"request_hash"`
	Outcome         Outcome `json:"outcome"`
	FactHash        string  `json:"fact_hash"`
	RemoteReference string  `json:"remote_reference"`
}

// HashFact returns the lowercase SHA-256 digest expected by the adapter wire
// protocol. Callers are responsible for supplying stable, canonical fact
// bytes rather than a provider response containing transient fields.
func HashFact(fact []byte) string {
	digest := sha256.Sum256(fact)
	return hex.EncodeToString(digest[:])
}

func validateEffectResult(result Result) error {
	if result.Outcome == Inconclusive {
		return errors.New("effect result cannot be inconclusive")
	}
	return validateResult(result, false)
}

func validateObservationResult(result Result) error {
	return validateResult(result, true)
}

func validateResult(result Result, allowInconclusive bool) error {
	if len(result.RemoteReference) > maxRemoteReferenceBytes {
		return errors.New("remote reference is too large")
	}
	if strings.IndexFunc(result.RemoteReference, unicode.IsControl) >= 0 {
		return errors.New("remote reference contains a control character")
	}
	switch result.Outcome {
	case Succeeded:
		if !canonicalSHA256(result.FactHash) {
			return errors.New("successful result has an invalid fact hash")
		}
		if result.RemoteReference == "" {
			return errors.New("successful result has no remote reference")
		}
	case Failed:
		if !canonicalSHA256(result.FactHash) {
			return errors.New("failed result has an invalid fact hash")
		}
	case Inconclusive:
		if !allowInconclusive {
			return errors.New("inconclusive result is not allowed")
		}
		if result.FactHash != "" {
			return errors.New("inconclusive result carries a fact hash")
		}
	default:
		return errors.New("result has an invalid outcome")
	}
	return nil
}

func canonicalOperationID(value string) bool {
	return strings.HasPrefix(value, operationIDPrefix) &&
		canonicalSHA256(strings.TrimPrefix(value, operationIDPrefix))
}

func canonicalSHA256(value string) bool {
	if len(value) != sha256.Size*2 {
		return false
	}
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size && hex.EncodeToString(decoded) == value
}
