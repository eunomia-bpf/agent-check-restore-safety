package main

import (
	"os"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/order"
)

func TestServiceForProxyReleaseNeedsNoControlCredential(t *testing.T) {
	config := order.Config{
		Version: "v2", EffectProxyURL: "http://effect-proxy:8788", EffectRoute: "payment",
	}
	if _, err := serviceForRelease(config, "not a control URL", ""); err != nil {
		t.Fatalf("proxy release depended on control authority: %v", err)
	}
	if _, err := serviceForRelease(config, "not a control URL", "/unexpected/operation-token"); err == nil {
		t.Fatal("proxy release accepted an Operation credential")
	}
}

func TestServiceForLegacyReleaseStillRequiresToken(t *testing.T) {
	config := order.Config{Version: "v1", Kind: "charge-v1", Target: "http://payment/v1/charge"}
	if _, err := serviceForRelease(config, "http://control:8787", ""); err == nil || !strings.Contains(err.Error(), "-operation-token-file") {
		t.Fatalf("legacy release accepted no token: %v", err)
	}
	path := t.TempDir() + "/operation-token"
	if err := os.WriteFile(path, []byte("01234567890123456789012345678901\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := serviceForRelease(config, "http://control:8787", path); err != nil {
		t.Fatal(err)
	}
}
