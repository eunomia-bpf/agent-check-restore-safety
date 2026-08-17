//go:build historyguard

package main

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/firecracker"
	"golang.org/x/sys/unix"
)

func TestRequireNotStartedRequiresExactInstance(t *testing.T) {
	valid := firecracker.InstanceInfo{
		AppName: "Firecracker", ID: "cell-1", State: firecracker.StateNotStarted,
		VMMVersion: officialFirecrackerVersion,
	}
	if err := requireNotStarted(valid, "cell-1"); err != nil {
		t.Fatal(err)
	}
	changed := valid
	changed.State = firecracker.StateRunning
	if err := requireNotStarted(changed, "cell-1"); err == nil {
		t.Fatal("accepted a running Firecracker instance")
	}
	changed = valid
	changed.ID = "cell-2"
	if err := requireNotStarted(changed, "cell-1"); err == nil {
		t.Fatal("accepted a different Firecracker instance")
	}
}

func TestCaptureHistoryArtifactRequiresFullSeals(t *testing.T) {
	fd, err := unix.MemfdCreate("history-artifact-test", unix.MFD_CLOEXEC|unix.MFD_ALLOW_SEALING)
	if err != nil {
		t.Fatal(err)
	}
	file := os.NewFile(uintptr(fd), "history-artifact-test")
	defer file.Close()
	if _, err := file.Write([]byte("immutable")); err != nil {
		t.Fatal(err)
	}
	record := artifactRecord{Name: "payload", Size: 9, SHA256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
	if _, err := captureHistoryArtifact("payload", file, record); err == nil {
		t.Fatal("accepted an unsealed artifact")
	}
	wanted := unix.F_SEAL_SEAL | unix.F_SEAL_SHRINK | unix.F_SEAL_GROW | unix.F_SEAL_WRITE
	if _, err := unix.FcntlInt(file.Fd(), unix.F_ADD_SEALS, wanted); err != nil {
		t.Fatal(err)
	}
	fact, err := captureHistoryArtifact("payload", file, record)
	if err != nil {
		t.Fatal(err)
	}
	if fact.Name != "payload" || fact.Size != 9 || fact.Seals != wanted || fact.Inode == 0 {
		t.Fatalf("artifact fact is incomplete: %+v", fact)
	}
}

func TestDecodeStrictHistoryJSONRejectsUnknownAndTrailingData(t *testing.T) {
	var target struct {
		Schema int `json:"schema"`
	}
	if err := decodeStrictHistoryJSON([]byte(`{"schema":1}`), &target); err != nil || target.Schema != 1 {
		t.Fatalf("valid JSON error=%v target=%+v", err, target)
	}
	if err := decodeStrictHistoryJSON([]byte(`{"schema":1,"extra":true}`), &target); err == nil {
		t.Fatal("accepted an unknown field")
	}
	if err := decodeStrictHistoryJSON([]byte(`{"schema":1}{}`), &target); err == nil {
		t.Fatal("accepted trailing JSON")
	}
}

func TestEncodeCanonicalHistoryJSONSortsNestedFactsWithoutLosingIntegers(t *testing.T) {
	encoded, err := encodeCanonicalHistoryJSON(struct {
		Schema int            `json:"schema"`
		Facts  map[string]any `json:"facts"`
	}{Schema: 1, Facts: map[string]any{"z": uint64(1<<63 + 9), "a": true}})
	if err != nil {
		t.Fatal(err)
	}
	const expected = `{"facts":{"a":true,"z":9223372036854775817},"schema":1}`
	if string(encoded) != expected || !json.Valid(encoded) {
		t.Fatalf("canonical facts=%s", encoded)
	}
}
