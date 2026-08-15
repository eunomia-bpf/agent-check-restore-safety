// Command vm-demo boots an unmodified Ubuntu cloud image behind a restricted
// QEMU user network, saves the running guest before an external Operation,
// restores it after the remote commit loses its response, and verifies that
// host History prevents a duplicate commit.
package main

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"time"

	controlapi "github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/api"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/payment"
)

const (
	defaultImageURL = "https://cloud-images.ubuntu.com/releases/noble/release-20260725/ubuntu-24.04-server-cloudimg-amd64.img"
	defaultImageSHA = "d1940f7d69d343355e183dff1e08a59852d32e7309baa7a4bad8365b11b005ac"
	maxImageBytes   = 2 << 30
)

type options struct {
	imagePath string
	imageURL  string
	imageSHA  string
	accel     string
	keep      bool
	timeout   time.Duration
}

func main() {
	var configuration options
	flag.StringVar(&configuration.imagePath, "image", "", "verified Ubuntu cloud image path or default cache path")
	flag.StringVar(&configuration.imageURL, "image-url", defaultImageURL, "download URL used when the image is absent")
	flag.StringVar(&configuration.imageSHA, "image-sha256", defaultImageSHA, "required lowercase SHA-256 for the base image")
	flag.StringVar(&configuration.accel, "accel", "tcg", "QEMU accelerator: tcg or kvm")
	flag.BoolVar(&configuration.keep, "keep", false, "retain the VM evidence directory")
	flag.DurationVar(&configuration.timeout, "timeout", 12*time.Minute, "whole-demo timeout")
	flag.Parse()
	if err := run(configuration); err != nil {
		log.Printf("VM demo failed: %v", err)
		os.Exit(1)
	}
}

func run(configuration options) error {
	if configuration.accel != "tcg" && configuration.accel != "kvm" {
		return errors.New("-accel must be tcg or kvm")
	}
	decodedSHA, shaErr := hex.DecodeString(configuration.imageSHA)
	if shaErr != nil || len(decodedSHA) != sha256.Size || hex.EncodeToString(decodedSHA) != configuration.imageSHA {
		return errors.New("-image-sha256 must be 64 lowercase hexadecimal characters")
	}
	var netcatPath string
	for _, command := range []string{"qemu-system-x86_64", "qemu-img", "nc"} {
		path, err := exec.LookPath(command)
		if err != nil {
			return fmt.Errorf("required host command %q: %w", command, err)
		}
		if command == "nc" {
			netcatPath = path
		}
	}
	if configuration.imagePath == "" {
		cache, err := os.UserCacheDir()
		if err != nil {
			return err
		}
		configuration.imagePath = filepath.Join(cache, "safe-change-runtime", "images", "ubuntu-24.04-20260725-amd64.img")
	}
	configuration.imagePath, _ = filepath.Abs(configuration.imagePath)
	ctx, cancel := context.WithTimeout(context.Background(), configuration.timeout)
	defer cancel()
	if err := ensureImage(ctx, configuration.imagePath, configuration.imageURL, configuration.imageSHA); err != nil {
		return err
	}

	work, err := os.MkdirTemp("", "safe-change-vm-")
	if err != nil {
		return err
	}
	if configuration.keep {
		log.Printf("VM evidence directory: %s", work)
	} else {
		defer os.RemoveAll(work)
	}
	historyPath := filepath.Join(work, "host.history")
	anchorPath := filepath.Join(work, "host.head")
	paymentPath := filepath.Join(work, "payment.history")
	overlayPath := filepath.Join(work, "guest.qcow2")
	serialPath := filepath.Join(work, "guest.serial.log")
	qemuLogPath := filepath.Join(work, "qemu.log")
	qmpPath := filepath.Join(work, "qmp.sock")

	paymentService, err := payment.Open(paymentPath, true)
	if err != nil {
		return err
	}
	defer paymentService.Close()
	paymentListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	paymentServer := &http.Server{Handler: paymentService.Handler(), ReadHeaderTimeout: 5 * time.Second}
	go serve(paymentServer, paymentListener)
	defer shutdown(paymentServer)
	paymentTarget := "http://" + paymentListener.Addr().String() + "/v1/charge"

	controller, err := control.OpenWithAnchor(historyPath, anchorPath)
	if err != nil {
		return err
	}
	defer controller.Close()
	requirement := kernel.Requirement{
		ID: "vm-restore-v1", Results: map[string]uint32{"written": 1},
		Capacities: map[string]uint32{"slot": 1},
		Kinds: map[string]kernel.KindSpec{
			"vm-write": {
				Costs: map[string]uint32{"slot": 1}, Produces: map[string]uint32{"written": 1},
				RetrySafe: true, Target: paymentTarget, Method: http.MethodPost,
				ResponseClassifier: gateway.ResponseReceiptV1,
			},
		},
	}
	certificate, err := controller.Compile(requirement)
	if err != nil {
		return err
	}
	if err := controller.Activate(certificate); err != nil {
		return err
	}
	adminToken, err := randomToken()
	if err != nil {
		return err
	}
	operationToken, err := randomToken()
	if err != nil {
		return err
	}
	serverAPI, err := controlapi.New(controller, nil, controlapi.Credentials{
		AdminToken: adminToken,
		Adapters: []controlapi.AdapterCredential{{
			Token: operationToken, Domain: "full-linux-vm", Kinds: []string{"vm-write"},
		}},
	})
	if err != nil {
		return err
	}
	controlListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	controlServer := &http.Server{Handler: serverAPI.Handler(), ReadHeaderTimeout: 5 * time.Second}
	go serve(controlServer, controlListener)
	defer shutdown(controlServer)

	executeJSON, err := json.Marshal(map[string]any{
		"call_id": "vm/job-1/write", "kind": "vm-write", "method": http.MethodPost,
		"url": paymentTarget, "body": []byte(`{"job":"job-1","value":42}`),
	})
	if err != nil {
		return err
	}
	var gate atomic.Bool
	guestScript := makeGuestScript(
		operationToken,
		base64.StdEncoding.EncodeToString(executeJSON),
		paymentListener.Addr().(*net.TCPAddr).Port,
	)
	userData := makeUserData(guestScript)
	seedListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	seedServer := &http.Server{Handler: seedHandler(userData, &gate), ReadHeaderTimeout: 5 * time.Second}
	go serve(seedServer, seedListener)
	defer shutdown(seedServer)

	if output, err := exec.CommandContext(ctx, "qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2", "-b", configuration.imagePath, overlayPath, "8G").CombinedOutput(); err != nil {
		return fmt.Errorf("create guest overlay: %w: %s", err, output)
	}
	qemuLog, err := os.OpenFile(qemuLogPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	defer qemuLog.Close()
	netdev := fmt.Sprintf(
		"user,id=opnet,restrict=on,guestfwd=tcp:10.0.2.100:8000-cmd:%s 127.0.0.1 %d,guestfwd=tcp:10.0.2.100:8787-cmd:%s 127.0.0.1 %d",
		netcatPath,
		seedListener.Addr().(*net.TCPAddr).Port,
		netcatPath,
		controlListener.Addr().(*net.TCPAddr).Port,
	)
	qemuArgs := []string{
		"-name", "safe-change-vm", "-machine", "q35", "-m", "1024", "-smp", "2",
		"-drive", "file=" + overlayPath + ",if=virtio,format=qcow2,cache=none",
		"-display", "none", "-serial", "file:" + serialPath, "-monitor", "none",
		"-qmp", "unix:" + qmpPath + ",server=on,wait=off", "-no-reboot", "-nic", "none",
		"-netdev", netdev, "-device", "virtio-net-pci,netdev=opnet",
		"-smbios", "type=1,serial=ds=nocloud;s=http://10.0.2.100:8000/",
	}
	if configuration.accel == "tcg" {
		qemuArgs = append(qemuArgs, "-accel", "tcg,thread=multi")
	} else {
		qemuArgs = append(qemuArgs, "-accel", "kvm")
	}
	qemu := exec.CommandContext(ctx, "qemu-system-x86_64", qemuArgs...)
	qemu.Stdout, qemu.Stderr = qemuLog, qemuLog
	if err := qemu.Start(); err != nil {
		return err
	}
	qemuDone := make(chan error, 1)
	go func() { qemuDone <- qemu.Wait() }()
	finished := false
	defer func() {
		if !finished && qemu.Process != nil {
			_ = qemu.Process.Kill()
			<-qemuDone
		}
	}()

	qmp, err := dialQMP(ctx, qmpPath)
	if err != nil {
		return withQEMULog(err, qemuLogPath)
	}
	defer qmp.Close()
	if err := waitForText(ctx, serialPath, "SAFE_CHANGE_VM_READY", 5*time.Minute); err != nil {
		return withQEMULog(err, qemuLogPath)
	}
	if err := qmp.command("stop", nil); err != nil {
		return err
	}
	if err := qmp.human("savevm before_operation"); err != nil {
		return err
	}
	gate.Store(true)
	if err := qmp.command("cont", nil); err != nil {
		return err
	}
	if err := waitForText(ctx, serialPath, "SAFE_CHANGE_VM_FIRST_UNKNOWN", 2*time.Minute); err != nil {
		return err
	}
	if err := qmp.command("stop", nil); err != nil {
		return err
	}
	if err := qmp.human("loadvm before_operation"); err != nil {
		return err
	}
	if err := qmp.command("cont", nil); err != nil {
		return err
	}
	if err := waitForText(ctx, serialPath, "SAFE_CHANGE_VM_RESTORED_SUCCEEDED", 2*time.Minute); err != nil {
		return err
	}
	select {
	case err := <-qemuDone:
		finished = true
		if err != nil {
			return withQEMULog(err, qemuLogPath)
		}
	case <-time.After(90 * time.Second):
		return errors.New("guest did not power off after the restored Operation succeeded")
	case <-ctx.Done():
		return ctx.Err()
	}

	serial, err := os.ReadFile(serialPath)
	if err != nil {
		return err
	}
	serialText := string(serial)
	if strings.Contains(serialText, "SAFE_CHANGE_VM_DIRECT_BYPASS_REACHABLE") ||
		strings.Count(serialText, "SAFE_CHANGE_VM_DIRECT_BYPASS_BLOCKED") < 2 {
		return errors.New("guest direct-payment isolation check failed")
	}
	guestKernel := markerField(serialText, "SAFE_CHANGE_VM_READY kernel=")
	if guestKernel == "" {
		return errors.New("guest kernel version is missing from serial evidence")
	}
	stats := paymentService.Stats()
	state := controller.Snapshot()
	if stats.Deliveries != 2 || stats.Commits != 1 || len(state.Operations) != 1 {
		return fmt.Errorf("unexpected final facts: payment=%+v operations=%d", stats, len(state.Operations))
	}
	for _, operation := range state.Operations {
		if operation.Phase != kernel.Succeeded || operation.Kind != "vm-write" || operation.Target != paymentTarget {
			return fmt.Errorf("unexpected final Operation: %+v", operation)
		}
	}
	snapshotOutput, err := exec.CommandContext(ctx, "qemu-img", "snapshot", "-l", overlayPath).CombinedOutput()
	if err != nil || !strings.Contains(string(snapshotOutput), "before_operation") {
		return fmt.Errorf("guest snapshot not present: %w: %s", err, snapshotOutput)
	}
	summary := map[string]any{
		"accelerator":                          configuration.accel,
		"base_image_sha256":                    configuration.imageSHA,
		"full_linux_guest":                     true,
		"guest_kernel":                         guestKernel,
		"host_owned_restricted_network":        true,
		"direct_payment_from_guest":            "blocked_before_and_after_restore",
		"snapshot_saved_before_operation":      true,
		"first_network_result":                 kernel.Unknown,
		"whole_vm_restored":                    true,
		"restored_operation":                   kernel.Succeeded,
		"remote_deliveries":                    stats.Deliveries,
		"remote_commits":                       stats.Commits,
		"host_history_sequence":                state.History.Sequence,
		"history_outside_guest_restore_domain": true,
		"payment_outside_guest_restore_domain": true,
	}
	if configuration.keep {
		summary["evidence_directory"] = work
	}
	encoded, _ := json.MarshalIndent(summary, "", "  ")
	fmt.Println(string(encoded))
	return nil
}

func serve(server *http.Server, listener net.Listener) {
	if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Printf("HTTP server failed: %v", err)
	}
}

func shutdown(server *http.Server) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = server.Shutdown(ctx)
}

func randomToken() (string, error) {
	data := make([]byte, 32)
	if _, err := rand.Read(data); err != nil {
		return "", err
	}
	return hex.EncodeToString(data), nil
}

func ensureImage(ctx context.Context, path, source, expected string) error {
	if _, err := os.Stat(path); err == nil {
		actual, err := fileSHA(path)
		if err != nil {
			return err
		}
		if actual != expected {
			return fmt.Errorf("cached image %q has SHA-256 %s, want %s", path, actual, expected)
		}
		log.Printf("using verified VM image %s", path)
		return nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if source == "" {
		return fmt.Errorf("VM image %q is absent and -image-url is empty", path)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	temporary := fmt.Sprintf("%s.partial-%d", path, os.Getpid())
	file, err := os.OpenFile(temporary, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = file.Close()
		if !ok {
			_ = os.Remove(temporary)
		}
	}()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, source, nil)
	if err != nil {
		return err
	}
	response, err := (&http.Client{Timeout: 20 * time.Minute}).Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("download VM image: HTTP %d", response.StatusCode)
	}
	if response.ContentLength > maxImageBytes {
		return fmt.Errorf("VM image is %d bytes, limit is %d", response.ContentLength, maxImageBytes)
	}
	log.Printf("downloading verified VM image from %s", source)
	hash := sha256.New()
	written, err := io.Copy(io.MultiWriter(file, hash), io.LimitReader(response.Body, maxImageBytes+1))
	if err != nil {
		return err
	}
	if written > maxImageBytes {
		return fmt.Errorf("VM image exceeds the %d-byte limit", maxImageBytes)
	}
	actual := hex.EncodeToString(hash.Sum(nil))
	if actual != expected {
		return fmt.Errorf("downloaded VM image has SHA-256 %s, want %s", actual, expected)
	}
	if err := file.Sync(); err != nil {
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	if err := os.Rename(temporary, path); err != nil {
		return err
	}
	directory, err := os.Open(filepath.Dir(path))
	if err != nil {
		return err
	}
	syncErr := directory.Sync()
	closeErr := directory.Close()
	if syncErr != nil || closeErr != nil {
		return errors.Join(syncErr, closeErr)
	}
	ok = true
	return nil
}

func fileSHA(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func makeUserData(script string) string {
	return "#cloud-config\n" +
		"write_files:\n" +
		"  - path: /usr/local/sbin/safe-change-guest\n" +
		"    owner: root:root\n" +
		"    permissions: '0700'\n" +
		"    encoding: b64\n" +
		"    content: " + base64.StdEncoding.EncodeToString([]byte(script)) + "\n" +
		"runcmd:\n" +
		"  - [bash, -lc, /usr/local/sbin/safe-change-guest]\n"
}

func makeGuestScript(operationToken, encodedRequest string, paymentPort int) string {
	return fmt.Sprintf(`#!/usr/bin/env bash
set -uo pipefail
log_marker() { printf '%%s\n' "$1" > /dev/ttyS0; }
log_marker "SAFE_CHANGE_VM_READY kernel=$(uname -r)"
until curl -fsS --connect-timeout 2 --max-time 3 http://10.0.2.100:8000/go >/dev/null; do sleep 1; done
if curl -fsS --connect-timeout 2 --max-time 3 http://10.0.2.2:%d/v1/stats >/dev/null; then
  log_marker SAFE_CHANGE_VM_DIRECT_BYPASS_REACHABLE
  /sbin/poweroff -f
  exit 1
fi
log_marker SAFE_CHANGE_VM_DIRECT_BYPASS_BLOCKED
printf '%%s' '%s' | base64 -d > /run/safe-change-execute.json
status=$(curl -sS --max-time 45 -o /run/safe-change-response.json -w '%%{http_code}' \
  -X POST -H 'Authorization: Bearer %s' -H 'Content-Type: application/json' \
  --data-binary @/run/safe-change-execute.json http://10.0.2.100:8787/v1/execute) || status=transport-error
phase=$(python3 -c 'import json; d=json.load(open("/run/safe-change-response.json")); print((d.get("outcome") or d).get("phase", ""))' 2>/dev/null || true)
if [[ "$status" == 409 && "$phase" == unknown ]]; then
  log_marker SAFE_CHANGE_VM_FIRST_UNKNOWN
  sync
  while true; do sleep 60; done
fi
if [[ "$status" == 200 && "$phase" == succeeded ]]; then
  log_marker SAFE_CHANGE_VM_RESTORED_SUCCEEDED
  sync
  /sbin/poweroff -f
  exit 0
fi
log_marker "SAFE_CHANGE_VM_UNEXPECTED status=$status phase=$phase"
/sbin/poweroff -f
exit 1
`, paymentPort, encodedRequest, operationToken)
}

func seedHandler(userData string, gate *atomic.Bool) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/meta-data":
			writer.Header().Set("Content-Type", "text/plain")
			_, _ = io.WriteString(writer, "instance-id: safe-change-vm-1\nlocal-hostname: safe-change-vm\n")
		case "/user-data":
			writer.Header().Set("Content-Type", "text/plain")
			_, _ = io.WriteString(writer, userData)
		case "/vendor-data":
			writer.Header().Set("Content-Type", "text/plain")
			_, _ = io.WriteString(writer, "#cloud-config\n{}\n")
		case "/go":
			if !gate.Load() {
				http.Error(writer, "not yet", http.StatusServiceUnavailable)
				return
			}
			_, _ = io.WriteString(writer, "go\n")
		default:
			http.NotFound(writer, request)
		}
	})
}

func markerField(text, marker string) string {
	start := strings.Index(text, marker)
	if start == -1 {
		return ""
	}
	value := text[start+len(marker):]
	if end := strings.IndexAny(value, "\r\n "); end != -1 {
		value = value[:end]
	}
	return value
}

func waitForText(ctx context.Context, path, marker string, timeout time.Duration) error {
	deadline := time.NewTimer(timeout)
	defer deadline.Stop()
	ticker := time.NewTicker(200 * time.Millisecond)
	defer ticker.Stop()
	for {
		data, err := os.ReadFile(path)
		if err == nil && strings.Contains(string(data), marker) {
			log.Printf("guest marker: %s", marker)
			return nil
		}
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-deadline.C:
			return fmt.Errorf("timed out waiting for guest marker %q", marker)
		case <-ticker.C:
		}
	}
}

func withQEMULog(cause error, path string) error {
	data, _ := os.ReadFile(path)
	if len(data) > 8192 {
		data = data[len(data)-8192:]
	}
	return fmt.Errorf("%w; QEMU log: %s", cause, data)
}

type qmpClient struct {
	connection net.Conn
	decoder    *json.Decoder
	encoder    *json.Encoder
	nextID     uint64
}

func dialQMP(ctx context.Context, path string) (*qmpClient, error) {
	var connection net.Conn
	var err error
	for connection == nil {
		connection, err = (&net.Dialer{}).DialContext(ctx, "unix", path)
		if err == nil {
			break
		}
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(100 * time.Millisecond):
		}
	}
	client := &qmpClient{connection: connection, decoder: json.NewDecoder(connection), encoder: json.NewEncoder(connection)}
	var greeting map[string]json.RawMessage
	if err := client.decoder.Decode(&greeting); err != nil {
		connection.Close()
		return nil, err
	}
	if _, ok := greeting["QMP"]; !ok {
		connection.Close()
		return nil, errors.New("QMP greeting is missing")
	}
	if err := client.command("qmp_capabilities", nil); err != nil {
		connection.Close()
		return nil, err
	}
	return client, nil
}

func (q *qmpClient) Close() error { return q.connection.Close() }

func (q *qmpClient) command(name string, arguments any) error {
	_, err := q.commandResult(name, arguments)
	return err
}

func (q *qmpClient) commandResult(name string, arguments any) (json.RawMessage, error) {
	q.nextID++
	id := fmt.Sprintf("command-%d", q.nextID)
	request := map[string]any{"execute": name, "id": id}
	if arguments != nil {
		request["arguments"] = arguments
	}
	if err := q.encoder.Encode(request); err != nil {
		return nil, err
	}
	for {
		var response struct {
			ID     string          `json:"id"`
			Return json.RawMessage `json:"return"`
			Error  *struct {
				Class string `json:"class"`
				Desc  string `json:"desc"`
			} `json:"error"`
		}
		if err := q.decoder.Decode(&response); err != nil {
			return nil, err
		}
		if response.ID != id {
			continue
		}
		if response.Error != nil {
			return nil, fmt.Errorf("QMP %s: %s: %s", name, response.Error.Class, response.Error.Desc)
		}
		return response.Return, nil
	}
}

func (q *qmpClient) human(command string) error {
	result, err := q.commandResult("human-monitor-command", map[string]string{"command-line": command})
	if err != nil {
		return err
	}
	var output string
	if err := json.Unmarshal(result, &output); err != nil {
		return fmt.Errorf("decode HMP %q response: %w", command, err)
	}
	if strings.TrimSpace(output) != "" {
		return fmt.Errorf("HMP %q failed: %s", command, strings.TrimSpace(output))
	}
	return nil
}
