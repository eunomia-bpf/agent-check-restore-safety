package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

func TestEnsureImageDownloadsAndVerifiesOnce(t *testing.T) {
	contents := []byte("small deterministic image fixture")
	digest := sha256.Sum256(contents)
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		requests++
		_, _ = writer.Write(contents)
	}))
	defer server.Close()
	path := filepath.Join(t.TempDir(), "image.qcow2")
	ctx := context.Background()
	expected := hex.EncodeToString(digest[:])
	if err := ensureImage(ctx, path, server.URL, expected); err != nil {
		t.Fatal(err)
	}
	if err := ensureImage(ctx, path, server.URL, expected); err != nil {
		t.Fatal(err)
	}
	if requests != 1 {
		t.Fatalf("download requests=%d", requests)
	}
}

func TestEnsureImageRejectsWrongDigest(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		_, _ = writer.Write([]byte("wrong"))
	}))
	defer server.Close()
	path := filepath.Join(t.TempDir(), "image.qcow2")
	err := ensureImage(context.Background(), path, server.URL, strings.Repeat("0", 64))
	if err == nil {
		t.Fatal("wrong image digest was accepted")
	}
	if _, statErr := os.Stat(path); !os.IsNotExist(statErr) {
		t.Fatalf("failed download remained at final path: %v", statErr)
	}
}

func TestOpenExecutableIdentitySurvivesPathReplacement(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "tool")
	replacement := filepath.Join(directory, "replacement")
	if err := os.WriteFile(path, []byte("original executable"), 0o700); err != nil {
		t.Fatal(err)
	}
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	original, err := identityForOpenExecutable(file)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(replacement, []byte("replacement executable"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(replacement, path); err != nil {
		t.Fatal(err)
	}
	currentFile, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer currentFile.Close()
	current, err := identityForOpenExecutable(currentFile)
	if err != nil {
		t.Fatal(err)
	}
	if original == current {
		t.Fatal("path replacement retained the original executable identity")
	}
	stillOpen, err := identityForOpenExecutable(file)
	if err != nil {
		t.Fatal(err)
	}
	if stillOpen != original {
		t.Fatal("open executable descriptor did not pin the original inode and bytes")
	}
}

func TestQEMUProcessEvidenceBindsLiveCommandAndExecutable(t *testing.T) {
	tool, err := resolveHostTool("qemu-system-x86_64")
	if err != nil {
		t.Fatal(err)
	}
	arguments := []string{
		"-S", "-display", "none", "-nodefaults", "-machine", "none",
		"-monitor", "none", "-serial", "none",
	}
	command := exec.Command(tool.path, arguments...)
	if err := command.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() {
		_ = command.Process.Kill()
		_ = command.Wait()
	}()
	path := filepath.Join(t.TempDir(), "qemu-process-command.json")
	if err := writeQEMUProcessCommand(
		path, command.Process.Pid, arguments, tool, t.TempDir(), "/base.img",
	); err != nil {
		t.Fatal(err)
	}
	var evidence map[string]any
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(data, &evidence); err != nil {
		t.Fatal(err)
	}
	if evidence["executable_sha256"] != tool.identity.sha256 ||
		evidence["source"] != "linux-proc-cmdline-and-exe-fd" {
		t.Fatalf("process evidence=%+v", evidence)
	}
}

func TestReadNonemptyProcessCommandObservesLiveProcess(t *testing.T) {
	data, err := readNonemptyProcessCommand(os.Getpid(), time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if len(bytes.Split(data, []byte{0})) < 2 {
		t.Fatalf("live process command=%q", data)
	}
}

func TestAgentQEMUCommandKillsChildWhenRunnerDies(t *testing.T) {
	command := agentQEMUCommand(context.Background(), "/bin/true", []string{"argument"})
	if command.SysProcAttr == nil || command.SysProcAttr.Pdeathsig != syscall.SIGKILL {
		t.Fatalf("QEMU parent-death signal=%+v", command.SysProcAttr)
	}
}

func TestWaitForText(t *testing.T) {
	path := filepath.Join(t.TempDir(), "serial.log")
	go func() {
		time.Sleep(20 * time.Millisecond)
		_ = os.WriteFile(path, []byte("boot\nREADY\n"), 0o600)
	}()
	if err := waitForText(context.Background(), path, "READY", time.Second); err != nil {
		t.Fatal(err)
	}
}

func TestMarkerField(t *testing.T) {
	serial := "boot\r\nSAFE_CHANGE_VM_READY kernel=6.8.0-90-generic\r\n"
	if got := markerField(serial, "SAFE_CHANGE_VM_READY kernel="); got != "6.8.0-90-generic" {
		t.Fatalf("kernel marker=%q", got)
	}
}

func TestStandaloneGuestUsesOnlyHostBoundOperationFields(t *testing.T) {
	request, err := makeSandboxExecuteJSON(
		"vm/job-1/write", "vm-write", []byte(`{"job":"job-1"}`),
	)
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]any
	if err := json.Unmarshal(request, &fields); err != nil {
		t.Fatal(err)
	}
	if len(fields) != 3 || fields["call_id"] != "vm/job-1/write" || fields["kind"] != "vm-write" {
		t.Fatalf("sandbox request fields = %+v", fields)
	}
	for _, forbidden := range []string{"url", "method", "headers", "token", "sandbox_id", "generation"} {
		if _, exists := fields[forbidden]; exists {
			t.Fatalf("sandbox request contains host-owned field %q", forbidden)
		}
	}
	script := makeGuestScript(base64.StdEncoding.EncodeToString(request), 12345)
	for _, forbidden := range []string{"Authorization", "Bearer", "provider.example", "/v1/charge"} {
		if strings.Contains(script, forbidden) {
			t.Fatalf("standalone guest script contains %q", forbidden)
		}
	}
	if !strings.Contains(script, "http://10.0.2.100:8787/v1/execute") {
		t.Fatal("standalone guest script omits its host-owned endpoint")
	}
	providerTarget := "http://127.0.0.1:45678/v1/charge"
	if err := validateStandaloneGuestBoundary(request, script, providerTarget); err != nil {
		t.Fatal(err)
	}
	if err := validateStandaloneGuestBoundary(request, script+providerTarget, providerTarget); err == nil {
		t.Fatal("guest boundary accepted a provider target")
	}
}

func TestEvidenceManifestCoversDeclaredFiles(t *testing.T) {
	directory := t.TempDir()
	if err := writePrivateFile(filepath.Join(directory, "a.txt"), []byte("a\n")); err != nil {
		t.Fatal(err)
	}
	if err := writePrivateFile(filepath.Join(directory, "b.txt"), []byte("b\n")); err != nil {
		t.Fatal(err)
	}
	if err := writeEvidenceManifest(directory, []string{"b.txt", "a.txt"}); err != nil {
		t.Fatal(err)
	}
	manifest, err := os.ReadFile(filepath.Join(directory, "SHA256SUMS"))
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(manifest)), "\n")
	if len(lines) != 2 || !strings.HasSuffix(lines[0], "  a.txt") || !strings.HasSuffix(lines[1], "  b.txt") {
		t.Fatalf("manifest = %q", manifest)
	}
	if err := writeEvidenceManifest(directory, []string{"../a.txt"}); err == nil {
		t.Fatal("manifest accepted an unsafe path")
	}
}

func TestSyncedTraceSerializesConcurrentRecords(t *testing.T) {
	path := filepath.Join(t.TempDir(), "trace.jsonl")
	trace, err := openSyncedTrace(path)
	if err != nil {
		t.Fatal(err)
	}
	var wait sync.WaitGroup
	errorsFromWriters := make(chan error, 8)
	for index := 0; index < 8; index++ {
		wait.Add(1)
		go func(value int) {
			defer wait.Done()
			errorsFromWriters <- trace.Record("request", map[string]any{"value": value})
		}(index)
	}
	wait.Wait()
	close(errorsFromWriters)
	for err := range errorsFromWriters {
		if err != nil {
			t.Fatal(err)
		}
	}
	if trace.Count() != 8 {
		t.Fatalf("trace count = %d", trace.Count())
	}
	if err := trace.Close(); err != nil {
		t.Fatal(err)
	}
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	sequence := 0
	for scanner.Scan() {
		sequence++
		var record map[string]any
		if err := json.Unmarshal(scanner.Bytes(), &record); err != nil {
			t.Fatal(err)
		}
		if record["sequence"] != float64(sequence) {
			t.Fatalf("trace record %d = %+v", sequence, record)
		}
	}
	if err := scanner.Err(); err != nil {
		t.Fatal(err)
	}
	if sequence != 8 {
		t.Fatalf("trace lines = %d", sequence)
	}
}

func TestValidateExternalOptionsRequiresCompleteBoundary(t *testing.T) {
	valid := options{
		externalSandboxSocket:   "/private/vm.sock",
		externalRequestPath:     "/private/request.json",
		externalDirectProbe:     "http://172.30.0.4:8081/v1/stats",
		externalEvidenceDirPath: "/private/evidence",
	}
	external, err := validateExternalOptions(valid)
	if err != nil || !external {
		t.Fatalf("valid external options: external=%v err=%v", external, err)
	}
	incomplete := valid
	incomplete.externalSandboxSocket = ""
	if _, err := validateExternalOptions(incomplete); err == nil {
		t.Fatal("incomplete external boundary was accepted")
	}
	unsafeProbe := valid
	unsafeProbe.externalDirectProbe = "https://effect.example/v1/stats"
	if _, err := validateExternalOptions(unsafeProbe); err == nil {
		t.Fatal("non-local TLS probe was accepted as an isolated effect target")
	}
}

func TestReadExternalRequestIsStrictAndPreservesBytes(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "request.json")
	data := []byte(`{"call_id":"purchase/A-17/audit","kind":"append-audit",` +
		`"body":"eyJwdXJjaGFzZV9pZCI6IkEtMTcifQ=="}`)
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	retained, request, err := readExternalRequest(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(retained) != string(data) || request.CallID != "purchase/A-17/audit" || string(request.Body) != `{"purchase_id":"A-17"}` {
		t.Fatalf("request mismatch: retained=%q request=%+v", retained, request)
	}
	if err := os.WriteFile(path, append(data, []byte(` {}`)...), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := readExternalRequest(path); err == nil {
		t.Fatal("multiple request documents were accepted")
	}
	forged := []byte(`{"call_id":"purchase/A-17/audit","kind":"append-audit",` +
		`"url":"http://ledger:8081/v1/charge","headers":{"Authorization":"forged"}}`)
	if err := os.WriteFile(path, forged, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := readExternalRequest(path); err == nil {
		t.Fatal("guest request accepted provider routing or headers")
	}
}

func TestExternalGuestScriptContainsNoCredentialPath(t *testing.T) {
	script := makeExternalGuestScript(
		base64.StdEncoding.EncodeToString([]byte(`{"call_id":"vm"}`)),
		base64.StdEncoding.EncodeToString([]byte("http://172.30.0.4:8081/v1/stats")),
	)
	if strings.Contains(script, "Authorization") || strings.Contains(script, "Bearer") || strings.Contains(script, "token") {
		t.Fatal("guest script contains a credential path")
	}
	for _, marker := range []string{
		"SAFE_CHANGE_VM_FIRST_SUCCEEDED reused=false",
		"SAFE_CHANGE_VM_RESTORED_SUCCEEDED reused=true",
		"http://10.0.2.100:8787/v1/execute",
	} {
		if !strings.Contains(script, marker) {
			t.Fatalf("guest script omitted %q", marker)
		}
	}
}

func TestAgentGuestScriptProbesModelAndUsesPrivateWorkspace(t *testing.T) {
	script := agentGuestScript(strings.Repeat("a", 64))
	modelReady := strings.Index(script, "http://10.0.2.100:9000/health")
	workspace := strings.Index(script, "cd /run/claude-workspace")
	claudeStarted := strings.Index(script, "SAFE_CHANGE_QEMU_AGENT_CLAUDE_STARTED")
	if modelReady < 0 || workspace < 0 || claudeStarted < 0 ||
		modelReady >= workspace || workspace >= claudeStarted {
		t.Fatalf("Agent guest does not prove model reachability and enter its private workspace before Claude: %s", script)
	}
}

func TestExpectExternalCommandIsExact(t *testing.T) {
	scanner := bufio.NewScanner(strings.NewReader("start\npause\nrestore\nresume\n"))
	if err := expectExternalCommand(context.Background(), scanner, "start"); err != nil {
		t.Fatal(err)
	}
	if err := expectExternalCommand(context.Background(), scanner, "pause"); err != nil {
		t.Fatal(err)
	}
	if err := expectExternalCommand(context.Background(), scanner, "restore"); err != nil {
		t.Fatal(err)
	}
	if err := expectExternalCommand(context.Background(), scanner, "resume"); err != nil {
		t.Fatal(err)
	}
	wrong := bufio.NewScanner(strings.NewReader("continue\n"))
	if err := expectExternalCommand(context.Background(), wrong, "start"); err == nil {
		t.Fatal("unexpected VM control command was accepted")
	}
}

func TestCopyVerifiedImagePinsPrivateBackingBytes(t *testing.T) {
	directory := t.TempDir()
	source := filepath.Join(directory, "source.img")
	destination := filepath.Join(directory, "private.img")
	contents := []byte("verified backing bytes")
	if err := os.WriteFile(source, contents, 0o644); err != nil {
		t.Fatal(err)
	}
	evidence, err := copyVerifiedImage(source, destination, dataSHA256(contents))
	if err != nil {
		t.Fatal(err)
	}
	if evidence["private_backing_copy"] != true || evidence["file_mode"] != "0600" ||
		evidence["bytes"] != int64(len(contents)) || evidence["sha256"] != dataSHA256(contents) {
		t.Fatalf("copy evidence=%+v", evidence)
	}
	data, err := os.ReadFile(destination)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(data, contents) {
		t.Fatalf("private copy=%q, want %q", data, contents)
	}
	info, err := os.Stat(destination)
	if err != nil {
		t.Fatal(err)
	}
	if mode := info.Mode().Perm(); mode != 0o600 {
		t.Fatalf("private copy mode=%#o", mode)
	}
	if _, err := copyVerifiedImage(source, filepath.Join(directory, "wrong.img"), strings.Repeat("0", 64)); err == nil {
		t.Fatal("base image with another digest was accepted")
	}
}

func TestQEMUCommandRedactsPrivatePaths(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "qemu-command.json")
	image := filepath.Join(directory, "base.qcow2")
	arguments := []string{
		"-drive", "file=" + filepath.Join(directory, "guest.qcow2"),
		"-netdev", "user,id=opnet,restrict=on",
		"-image", image,
	}
	if err := writeQEMUCommand(path, arguments, directory, image); err != nil {
		t.Fatal(err)
	}
	contents, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	text := string(contents)
	if strings.Contains(text, directory) || strings.Contains(text, image) {
		t.Fatalf("private path was retained: %s", text)
	}
	if !strings.Contains(text, "restrict=on") || !strings.Contains(text, "<vm-evidence>") {
		t.Fatalf("QEMU boundary projection is incomplete: %s", text)
	}
}

func TestValidateQEMUStatusDistinguishesInitialHaltFromStop(t *testing.T) {
	if err := validateQEMUStatus([]byte(`{"status":"prelaunch","running":false}`), "prelaunch"); err != nil {
		t.Fatal(err)
	}
	if err := validateQEMUStatus([]byte(`{"status":"paused","running":false}`), "prelaunch"); err == nil {
		t.Fatal("an explicit stop state was accepted as the initial -S halt")
	}
	if err := validateQEMUStatus([]byte(`{"status":"prelaunch","running":true}`), "prelaunch"); err == nil {
		t.Fatal("a running VM was accepted as initially halted")
	}
}

func TestOpenAgentControlClientRequiresPrivateLoopbackAuthority(t *testing.T) {
	state := kernel.NewState()
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.Header.Get("Authorization") != "Bearer agent-control-token-00000000000000000000" {
			t.Errorf("Authorization=%q", request.Header.Get("Authorization"))
		}
		writer.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(writer).Encode(state)
	}))
	defer server.Close()
	tokenPath := filepath.Join(t.TempDir(), "admin.token")
	if err := os.WriteFile(tokenPath, []byte("agent-control-token-00000000000000000000\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	manifest := agentGuardManifest{ControlURL: server.URL, ControlTokenPath: tokenPath}
	client, err := openAgentControlClient(manifest)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := client.State(context.Background()); err != nil {
		t.Fatal(err)
	}
	manifest.ControlURL = "http://control.example:8080"
	if _, err := openAgentControlClient(manifest); err == nil {
		t.Fatal("non-loopback Control authority was accepted")
	}
	manifest.ControlURL = server.URL
	if err := os.Chmod(tokenPath, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := openAgentControlClient(manifest); err == nil {
		t.Fatal("public Control token was accepted")
	}
}
