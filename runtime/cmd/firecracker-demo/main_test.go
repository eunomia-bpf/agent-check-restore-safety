package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestRequestCallID(t *testing.T) {
	if got := requestCallID([]byte(`{"call_id":"purchase/17","kind":"audit","body":"e30="}`)); got != "purchase/17" {
		t.Fatalf("requestCallID=%q", got)
	}
}

// TestFirecrackerKVMRestore is opt-in because it executes nested KVM and
// retains approximately 128 MiB of snapshot evidence in a temporary directory.
// It exercises two distinct Firecracker processes and a real vsock reset.
func TestFirecrackerKVMRestore(t *testing.T) {
	if os.Getenv("FIRECRACKER_KVM_INTEGRATION") != "1" {
		t.Skip("set FIRECRACKER_KVM_INTEGRATION=1 and run under a /dev/kvm-capable account")
	}
	firecrackerPath, kernelPath := defaultAssets()
	for _, path := range []string{firecrackerPath, kernelPath} {
		if _, err := os.Stat(path); err != nil {
			t.Fatalf("required pinned asset %s: %v", path, err)
		}
	}
	root := t.TempDir()
	if err := os.Chmod(root, 0o700); err != nil {
		t.Fatal(err)
	}
	guestPath := filepath.Join(root, "firecracker-guest")
	command := exec.Command("go", "build", "-trimpath", "-o", guestPath, "../firecracker-guest")
	command.Env = append(os.Environ(), "CGO_ENABLED=0")
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("build guest: %v: %s", err, output)
	}
	requestPath := filepath.Join(root, "request.json")
	request := []byte(`{"call_id":"fc-kvm/audit","kind":"audit","body":"eyJ2YWx1ZSI6MX0="}`)
	if err := os.WriteFile(requestPath, request, 0o600); err != nil {
		t.Fatal(err)
	}

	sandboxDirectory := filepath.Join(root, "sandbox")
	if err := os.Mkdir(sandboxDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	sandboxPath := filepath.Join(sandboxDirectory, "control.sock")
	listener, err := net.Listen("unix", sandboxPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(sandboxPath, 0o600); err != nil {
		t.Fatal(err)
	}
	var calls atomic.Int32
	requestErrors := make(chan string, 3)
	server := &http.Server{Handler: http.HandlerFunc(func(writer http.ResponseWriter, incoming *http.Request) {
		body, readErr := io.ReadAll(io.LimitReader(incoming.Body, int64(len(request)+1)))
		if readErr != nil || incoming.Method != http.MethodPost || incoming.URL.Path != "/v1/execute" ||
			incoming.Header.Get("Authorization") != "" || incoming.Header.Get("Cookie") != "" || !bytes.Equal(body, request) {
			requestErrors <- "guest did not send the exact credential-free Operation request"
			http.Error(writer, "invalid request", http.StatusBadRequest)
			return
		}
		call := calls.Add(1)
		if call == 1 {
			// Model the ambiguous failure: the sandbox has durably committed the
			// operation, but the connection dies before one response byte reaches
			// the guest. The exact retry must return the durable result as reused.
			hijacker, ok := writer.(http.Hijacker)
			if !ok {
				requestErrors <- "sandbox response writer cannot lose the first response"
				http.Error(writer, "cannot inject response loss", http.StatusInternalServerError)
				return
			}
			connection, _, hijackErr := hijacker.Hijack()
			if hijackErr != nil {
				requestErrors <- "sandbox could not hijack the first committed response"
				return
			}
			_ = connection.Close()
			return
		}
		writer.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(writer).Encode(map[string]any{
			"operation_id": "fake-stable-operation", "phase": "succeeded",
			"status_code": 200, "body": []byte("durable receipt\n"),
			"result_hash": strings.Repeat("a", 64), "reused": call > 1,
			"recovered_by_query": false,
		})
	})}
	go func() { _ = server.Serve(listener) }()
	defer server.Close()

	evidenceDir := filepath.Join(root, "evidence")
	if err := os.Mkdir(evidenceDir, 0o700); err != nil {
		t.Fatal(err)
	}
	config := options{
		accel: "kvm", timeout: 3 * time.Minute,
		firecrackerPath: firecrackerPath, firecrackerSHA: officialFirecrackerSHA256,
		hostInstanceIDG1: "fc-kvm-g1", hostInstanceIDG3: "fc-kvm-g3",
		kernelPath: kernelPath, kernelSHA: officialKernelSHA256, guestPath: guestPath,
		sandboxSocket: sandboxPath, requestPath: requestPath,
		directProbe: "http://127.0.0.1:9/", evidenceDir: evidenceDir,
	}
	var events bytes.Buffer
	if err := run(config, strings.NewReader("start\npause\nrestore\nresume\n"), &events); err != nil {
		logData, _ := os.ReadFile(filepath.Join(evidenceDir, "firecracker-g1.log"))
		restoredLog, _ := os.ReadFile(filepath.Join(evidenceDir, "firecracker-g3.log"))
		t.Fatalf("real Firecracker run: %v\nfirst log:\n%s\nrestored log:\n%s", err, logData, restoredLog)
	}
	if calls.Load() != 3 {
		t.Fatalf("sandbox calls=%d, want lost first response, g1 retry, and g3 reuse", calls.Load())
	}
	select {
	case requestError := <-requestErrors:
		t.Fatal(requestError)
	default:
	}
	checker := exec.Command("go", "run", "../check-firecracker-evidence", "-evidence", evidenceDir)
	if output, err := checker.CombinedOutput(); err != nil {
		gate1, _ := os.ReadFile(filepath.Join(evidenceDir, "firecracker-gate-g1.jsonl"))
		gate3, _ := os.ReadFile(filepath.Join(evidenceDir, "firecracker-gate-g3.jsonl"))
		t.Fatalf("independent evidence checker rejected the real run: %v: %s\ng1 gate:\n%s\ng3 gate:\n%s", err, output, gate1, gate3)
	}
	var result struct {
		FirstReused    bool `json:"first_operation_reused"`
		RestoredReused bool `json:"restored_operation_reused"`
	}
	resultData, err := os.ReadFile(filepath.Join(evidenceDir, "result.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(resultData, &result); err != nil {
		t.Fatal(err)
	}
	if !result.FirstReused || !result.RestoredReused {
		t.Fatalf("reuse evidence=%+v, want g1 retry and g3 restore both reused", result)
	}
	relayData, err := os.ReadFile(filepath.Join(evidenceDir, "firecracker-relay-g1.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(relayData, []byte(`"host_to_guest_bytes":0`)) {
		t.Fatal("g1 relay evidence lacks the deliberately lost first response")
	}
	var processes struct {
		Processes []processRecord `json:"processes"`
	}
	processData, err := os.ReadFile(filepath.Join(evidenceDir, "firecracker-processes.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(processData, &processes); err != nil {
		t.Fatal(err)
	}
	if len(processes.Processes) != 2 || processes.Processes[0].ID != "fc-kvm-g1" || processes.Processes[1].ID != "fc-kvm-g3" {
		t.Fatalf("process instance IDs=%+v, want exact configured generation IDs", processes.Processes)
	}
	var names []string
	for _, line := range strings.Split(strings.TrimSpace(events.String()), "\n") {
		var event map[string]any
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			t.Fatalf("event JSON %q: %v", line, err)
		}
		names = append(names, event["event"].(string))
	}
	want := []string{"snapshot-ready", "first-succeeded", "paused-after-first", "restore-loaded-paused", "completed"}
	if strings.Join(names, ",") != strings.Join(want, ",") {
		t.Fatalf("events=%v, want %v", names, want)
	}
}
