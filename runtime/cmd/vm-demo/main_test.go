package main

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
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

func TestValidateExternalOptionsRequiresCompleteBoundary(t *testing.T) {
	valid := options{
		externalControlPort:     18787,
		externalTokenPath:       "/private/vm.token",
		externalRequestPath:     "/private/request.json",
		externalDirectProbe:     "http://172.30.0.4:8081/v1/stats",
		externalEvidenceDirPath: "/private/evidence",
	}
	external, err := validateExternalOptions(valid)
	if err != nil || !external {
		t.Fatalf("valid external options: external=%v err=%v", external, err)
	}
	incomplete := valid
	incomplete.externalTokenPath = ""
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
		`"method":"POST","url":"http://ledger:8081/v1/charge",` +
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
}

func TestExternalGuestScriptDoesNotContainPlainCredential(t *testing.T) {
	token := "PLAIN-CREDENTIAL-MUST-NOT-APPEAR"
	script := makeExternalGuestScript(
		base64.StdEncoding.EncodeToString([]byte(token)),
		base64.StdEncoding.EncodeToString([]byte(`{"call_id":"vm"}`)),
		base64.StdEncoding.EncodeToString([]byte("http://172.30.0.4:8081/v1/stats")),
	)
	if strings.Contains(script, token) {
		t.Fatal("guest script contains the plaintext credential")
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

func TestExpectExternalCommandIsExact(t *testing.T) {
	scanner := bufio.NewScanner(strings.NewReader("start\nrestore\n"))
	if err := expectExternalCommand(context.Background(), scanner, "start"); err != nil {
		t.Fatal(err)
	}
	if err := expectExternalCommand(context.Background(), scanner, "restore"); err != nil {
		t.Fatal(err)
	}
	wrong := bufio.NewScanner(strings.NewReader("continue\n"))
	if err := expectExternalCommand(context.Background(), wrong, "start"); err == nil {
		t.Fatal("unexpected VM control command was accepted")
	}
}

func TestExternalQEMUCommandRedactsPrivatePaths(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "qemu-command.json")
	image := filepath.Join(directory, "base.qcow2")
	arguments := []string{
		"-drive", "file=" + filepath.Join(directory, "guest.qcow2"),
		"-netdev", "user,id=opnet,restrict=on",
		"-image", image,
	}
	if err := writeExternalQEMUCommand(path, arguments, directory, image); err != nil {
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
