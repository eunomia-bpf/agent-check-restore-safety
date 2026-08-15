package provideradapter

import (
	"strings"
	"testing"
)

func TestHashFact(t *testing.T) {
	const want = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
	if got := HashFact([]byte("abc")); got != want {
		t.Fatalf("HashFact(abc) = %q, want %q", got, want)
	}
	if got := HashFact([]byte("abc")); got != want {
		t.Fatalf("HashFact is not deterministic: %q", got)
	}
}

func TestResultValidationSeparatesEffectsFromObservations(t *testing.T) {
	validHash := HashFact([]byte("fact"))
	tests := []struct {
		name             string
		result           Result
		effectValid      bool
		observationValid bool
	}{
		{
			name: "success", result: Result{
				Outcome: Succeeded, FactHash: validHash, RemoteReference: "provider/object-1",
			}, effectValid: true, observationValid: true,
		},
		{
			name: "failure", result: Result{
				Outcome: Failed, FactHash: validHash,
			}, effectValid: true, observationValid: true,
		},
		{
			name: "inconclusive", result: Result{
				Outcome: Inconclusive, RemoteReference: "provider/search",
			}, observationValid: true,
		},
		{
			name: "inconclusive-with-fact", result: Result{
				Outcome: Inconclusive, FactHash: validHash,
			},
		},
		{
			name: "success-without-reference", result: Result{
				Outcome: Succeeded, FactHash: validHash,
			},
		},
		{
			name: "bad-hash", result: Result{
				Outcome: Failed, FactHash: strings.Repeat("A", 64),
			},
		},
		{
			name: "control-in-reference", result: Result{
				Outcome: Failed, FactHash: validHash, RemoteReference: "provider\nsecret",
			},
		},
		{
			name: "large-reference", result: Result{
				Outcome: Failed, FactHash: validHash,
				RemoteReference: strings.Repeat("r", maxRemoteReferenceBytes+1),
			},
		},
		{name: "unknown-outcome", result: Result{Outcome: "unknown", FactHash: validHash}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := validateEffectResult(test.result) == nil; got != test.effectValid {
				t.Fatalf("effect valid = %t, want %t", got, test.effectValid)
			}
			if got := validateObservationResult(test.result) == nil; got != test.observationValid {
				t.Fatalf("observation valid = %t, want %t", got, test.observationValid)
			}
		})
	}
}

func TestCanonicalProtocolIdentities(t *testing.T) {
	if !canonicalOperationID("op-" + strings.Repeat("a", 64)) {
		t.Fatal("canonical Operation identity was rejected")
	}
	for _, invalid := range []string{
		"", strings.Repeat("a", 64), "op-" + strings.Repeat("A", 64),
		"op-" + strings.Repeat("a", 63), "op-" + strings.Repeat("z", 64),
	} {
		if canonicalOperationID(invalid) {
			t.Fatalf("invalid Operation identity %q was accepted", invalid)
		}
	}
}
