package harness

import "testing"

func TestOperationIDIsStableAndSeparated(t *testing.T) {
	first := OperationID("payment-token-17")
	if first != OperationID("payment-token-17") {
		t.Fatal("same identity produced different Operation IDs")
	}
	if first == OperationID("payment-token-18") {
		t.Fatal("different identities produced the same Operation ID")
	}
	if len(first) != 67 || first[:3] != "op-" {
		t.Fatalf("unexpected Operation ID shape: %q", first)
	}
}
