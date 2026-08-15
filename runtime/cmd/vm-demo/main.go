// Command vm-demo boots an unmodified Ubuntu cloud image behind a restricted
// QEMU user network, saves the running guest before an external Operation,
// restores it after the remote commit loses its response, and verifies that
// host History prevents a duplicate commit.
package main

import (
	"bufio"
	"bytes"
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
	"net/url"
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
	imagePath               string
	imageURL                string
	imageSHA                string
	accel                   string
	keep                    bool
	timeout                 time.Duration
	externalControlPort     int
	externalTokenPath       string
	externalRequestPath     string
	externalDirectProbe     string
	externalEvidenceDirPath string
}

func main() {
	var configuration options
	flag.StringVar(&configuration.imagePath, "image", "", "verified Ubuntu cloud image path or default cache path")
	flag.StringVar(&configuration.imageURL, "image-url", defaultImageURL, "download URL used when the image is absent")
	flag.StringVar(&configuration.imageSHA, "image-sha256", defaultImageSHA, "required lowercase SHA-256 for the base image")
	flag.StringVar(&configuration.accel, "accel", "tcg", "QEMU accelerator: tcg or kvm")
	flag.BoolVar(&configuration.keep, "keep", false, "retain the VM evidence directory")
	flag.DurationVar(&configuration.timeout, "timeout", 12*time.Minute, "whole-demo timeout")
	flag.IntVar(&configuration.externalControlPort, "external-control-port", 0, "host loopback port for an existing shared control service")
	flag.StringVar(&configuration.externalTokenPath, "external-token-file", "", "private VM adapter token for shared-control mode")
	flag.StringVar(&configuration.externalRequestPath, "external-request", "", "strict execute-request JSON for shared-control mode")
	flag.StringVar(&configuration.externalDirectProbe, "external-direct-probe", "", "effect URL that the restored guest must not reach directly")
	flag.StringVar(&configuration.externalEvidenceDirPath, "external-evidence-dir", "", "empty directory for sanitized shared-control VM evidence")
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
	external, err := validateExternalOptions(configuration)
	if err != nil {
		return err
	}
	if err := ensureImage(ctx, configuration.imagePath, configuration.imageURL, configuration.imageSHA); err != nil {
		return err
	}
	if external {
		return runExternal(ctx, configuration, netcatPath, os.Stdin, os.Stdout)
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

type externalExecuteRequest struct {
	CallID  string            `json:"call_id"`
	Kind    string            `json:"kind"`
	Method  string            `json:"method"`
	URL     string            `json:"url"`
	Headers map[string]string `json:"headers,omitempty"`
	Body    []byte            `json:"body"`
}

func validateExternalOptions(configuration options) (bool, error) {
	requested := configuration.externalControlPort != 0 ||
		configuration.externalTokenPath != "" ||
		configuration.externalRequestPath != "" ||
		configuration.externalDirectProbe != "" ||
		configuration.externalEvidenceDirPath != ""
	if !requested {
		return false, nil
	}
	if configuration.externalControlPort <= 0 || configuration.externalControlPort > 65535 {
		return false, errors.New("shared-control mode requires -external-control-port between 1 and 65535")
	}
	if configuration.externalTokenPath == "" || configuration.externalRequestPath == "" ||
		configuration.externalDirectProbe == "" || configuration.externalEvidenceDirPath == "" {
		return false, errors.New("shared-control mode requires token, request, direct probe, and evidence directory")
	}
	if configuration.keep {
		return false, errors.New("-keep cannot be combined with shared-control mode")
	}
	probe, err := url.Parse(configuration.externalDirectProbe)
	if err != nil || probe.Scheme != "http" || probe.Host == "" || probe.User != nil || probe.Fragment != "" {
		return false, errors.New("external direct probe must be an absolute plain HTTP URL")
	}
	return true, nil
}

func runExternal(ctx context.Context, configuration options, netcatPath string, input io.Reader, output io.Writer) error {
	token, err := readExternalToken(configuration.externalTokenPath)
	if err != nil {
		return err
	}
	requestData, request, err := readExternalRequest(configuration.externalRequestPath)
	if err != nil {
		return err
	}
	evidenceDirectory, err := filepath.Abs(configuration.externalEvidenceDirPath)
	if err != nil {
		return err
	}
	if err := requireEmptyPrivateDirectory(evidenceDirectory); err != nil {
		return err
	}
	overlayPath := filepath.Join(evidenceDirectory, "guest.qcow2")
	serialPath := filepath.Join(evidenceDirectory, "guest.serial.log")
	qemuLogPath := filepath.Join(evidenceDirectory, "qemu.log")
	qmpPath := filepath.Join(evidenceDirectory, "qmp.sock")
	if commandOutput, err := exec.CommandContext(
		ctx,
		"qemu-img",
		"create",
		"-q",
		"-f",
		"qcow2",
		"-F",
		"qcow2",
		"-b",
		configuration.imagePath,
		overlayPath,
		"8G",
	).CombinedOutput(); err != nil {
		return fmt.Errorf("create external guest overlay: %w: %s", err, commandOutput)
	}

	var gate atomic.Bool
	guestScript := makeExternalGuestScript(
		base64.StdEncoding.EncodeToString([]byte(token)),
		base64.StdEncoding.EncodeToString(requestData),
		base64.StdEncoding.EncodeToString([]byte(configuration.externalDirectProbe)),
	)
	userData := makeUserData(guestScript)
	seedListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	seedServer := &http.Server{
		Handler: seedHandler(userData, &gate), ReadHeaderTimeout: 5 * time.Second,
	}
	go serve(seedServer, seedListener)
	defer shutdown(seedServer)

	qemuLog, err := os.OpenFile(qemuLogPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	qemuLogClosed := false
	defer func() {
		if !qemuLogClosed {
			_ = qemuLog.Close()
		}
	}()
	netdev := fmt.Sprintf(
		"user,id=opnet,restrict=on,guestfwd=tcp:10.0.2.100:8000-cmd:%s 127.0.0.1 %d,guestfwd=tcp:10.0.2.100:8787-cmd:%s 127.0.0.1 %d",
		netcatPath,
		seedListener.Addr().(*net.TCPAddr).Port,
		netcatPath,
		configuration.externalControlPort,
	)
	qemuArgs := []string{
		"-name", "safe-change-shared-history-vm", "-machine", "q35", "-m", "1024", "-smp", "2",
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
	if err := writeExternalQEMUCommand(
		filepath.Join(evidenceDirectory, "qemu-command.json"),
		qemuArgs,
		evidenceDirectory,
		configuration.imagePath,
	); err != nil {
		return err
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

	qmp, err := dialQMPWithTrace(
		ctx,
		qmpPath,
		filepath.Join(evidenceDirectory, "qmp-protocol.jsonl"),
	)
	if err != nil {
		return withQEMULog(err, qemuLogPath)
	}
	defer qmp.Close()
	if err := waitForText(ctx, serialPath, "SAFE_CHANGE_VM_EXTERNAL_READY", 5*time.Minute); err != nil {
		return withQEMULog(err, qemuLogPath)
	}
	guestKernel := markerFieldFromLast(serialPath, "SAFE_CHANGE_VM_EXTERNAL_READY kernel=")
	if guestKernel == "" {
		return errors.New("shared-control guest kernel marker is missing")
	}
	if err := qmp.command("stop", nil); err != nil {
		return err
	}
	if err := qmp.human("savevm before_purchase"); err != nil {
		return err
	}
	if err := writeExternalEvent(output, map[string]any{
		"event": "snapshot-ready", "guest_kernel": guestKernel,
	}); err != nil {
		return err
	}
	commands := bufio.NewScanner(input)
	if err := expectExternalCommand(ctx, commands, "start"); err != nil {
		return err
	}
	gate.Store(true)
	if err := qmp.command("cont", nil); err != nil {
		return err
	}
	if err := waitForText(ctx, serialPath, "SAFE_CHANGE_VM_FIRST_SUCCEEDED reused=false", 2*time.Minute); err != nil {
		return err
	}
	if err := writeExternalEvent(output, map[string]any{
		"event": "first-succeeded", "operation_call_id": request.CallID,
	}); err != nil {
		return err
	}
	if err := expectExternalCommand(ctx, commands, "restore"); err != nil {
		return err
	}
	if err := qmp.command("stop", nil); err != nil {
		return err
	}
	if err := qmp.human("loadvm before_purchase"); err != nil {
		return err
	}
	if err := qmp.command("cont", nil); err != nil {
		return err
	}
	if err := waitForText(ctx, serialPath, "SAFE_CHANGE_VM_RESTORED_SUCCEEDED reused=true", 2*time.Minute); err != nil {
		return err
	}
	select {
	case err := <-qemuDone:
		finished = true
		if err != nil {
			return withQEMULog(err, qemuLogPath)
		}
	case <-time.After(90 * time.Second):
		return errors.New("shared-control guest did not power off after reused Operation")
	case <-ctx.Done():
		return ctx.Err()
	}
	if err := qemuLog.Sync(); err != nil {
		return err
	}
	if err := qemuLog.Close(); err != nil {
		return err
	}
	qemuLogClosed = true

	serial, err := os.ReadFile(serialPath)
	if err != nil {
		return err
	}
	serialText := string(serial)
	if strings.Contains(serialText, "SAFE_CHANGE_VM_DIRECT_EFFECT_REACHABLE") ||
		strings.Count(serialText, "SAFE_CHANGE_VM_DIRECT_EFFECT_BLOCKED") != 2 {
		return errors.New("shared-control guest direct-effect isolation check failed")
	}
	snapshotOutput, err := exec.CommandContext(ctx, "qemu-img", "snapshot", "-l", overlayPath).CombinedOutput()
	if err != nil || !strings.Contains(string(snapshotOutput), "before_purchase") {
		return fmt.Errorf("shared-control guest snapshot is absent: %w: %s", err, snapshotOutput)
	}
	if err := os.WriteFile(filepath.Join(evidenceDirectory, "snapshots.txt"), snapshotOutput, 0o600); err != nil {
		return err
	}
	projection := map[string]any{
		"schema":                    1,
		"accelerator":               configuration.accel,
		"base_image_sha256":         configuration.imageSHA,
		"full_linux_guest":          true,
		"guest_kernel":              guestKernel,
		"machine":                   "q35",
		"memory_mib":                1024,
		"cpus":                      2,
		"implicit_nics_disabled":    true,
		"network_backend":           "qemu-user-restrict-on",
		"guest_forwards":            []string{"metadata-gate", "shared-control"},
		"direct_effect":             "blocked_before_and_after_restore",
		"snapshot":                  "before_purchase",
		"whole_vm_restored":         true,
		"first_operation_reused":    false,
		"restored_operation_reused": true,
		"operation_call_id":         request.CallID,
		"operation_kind":            request.Kind,
	}
	encodedProjection, err := json.MarshalIndent(projection, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(evidenceDirectory, "result.json"), append(encodedProjection, '\n'), 0o600); err != nil {
		return err
	}
	if err := removeExternalPrivateFiles(overlayPath, qmpPath); err != nil {
		return err
	}
	completed := make(map[string]any, len(projection)+1)
	for key, value := range projection {
		completed[key] = value
	}
	completed["event"] = "completed"
	return writeExternalEvent(output, completed)
}

func readExternalToken(path string) (string, error) {
	info, err := os.Stat(path)
	if err != nil {
		return "", err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0o077 != 0 {
		return "", errors.New("external VM token must be a private regular file")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	token := strings.TrimSpace(string(data))
	if len(token) < 32 {
		return "", errors.New("external VM token is too short")
	}
	return token, nil
}

func readExternalRequest(path string) ([]byte, externalExecuteRequest, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, externalExecuteRequest{}, err
	}
	if len(data) > 1<<20 {
		return nil, externalExecuteRequest{}, errors.New("external VM request exceeds 1 MiB")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var request externalExecuteRequest
	if err := decoder.Decode(&request); err != nil {
		return nil, externalExecuteRequest{}, err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return nil, externalExecuteRequest{}, errors.New("external VM request has trailing JSON")
	}
	target, parseErr := url.Parse(request.URL)
	if request.CallID == "" || request.Kind == "" || request.Method != http.MethodPost ||
		parseErr != nil || target.Scheme != "http" || target.Host == "" || target.User != nil || target.Fragment != "" {
		return nil, externalExecuteRequest{}, errors.New("external VM request has an invalid identity or HTTP contract")
	}
	return data, request, nil
}

func requireEmptyPrivateDirectory(path string) error {
	info, err := os.Stat(path)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode().Perm()&0o077 != 0 {
		return errors.New("external VM evidence directory must be private")
	}
	entries, err := os.ReadDir(path)
	if err != nil {
		return err
	}
	if len(entries) != 0 {
		return errors.New("external VM evidence directory must be empty")
	}
	return nil
}

func makeExternalGuestScript(encodedToken, encodedRequest, encodedDirectProbe string) string {
	return fmt.Sprintf(`#!/usr/bin/env bash
set -uo pipefail
log_marker() { printf '%%s\n' "$1" > /dev/ttyS0; }
log_marker "SAFE_CHANGE_VM_EXTERNAL_READY kernel=$(uname -r)"
until curl -fsS --connect-timeout 2 --max-time 3 http://10.0.2.100:8000/go >/dev/null; do sleep 1; done
direct_url=$(printf '%%s' '%s' | base64 -d)
if curl -fsS --connect-timeout 2 --max-time 3 "$direct_url" >/dev/null; then
  log_marker SAFE_CHANGE_VM_DIRECT_EFFECT_REACHABLE
  /sbin/poweroff -f
  exit 1
fi
log_marker SAFE_CHANGE_VM_DIRECT_EFFECT_BLOCKED
printf '%%s' '%s' | base64 -d > /run/safe-change-execute.json
token=$(printf '%%s' '%s' | base64 -d)
status=$(curl -sS --max-time 45 -o /run/safe-change-response.json -w '%%{http_code}' \
  -X POST -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  --data-binary @/run/safe-change-execute.json http://10.0.2.100:8787/v1/execute) || status=transport-error
read -r phase reused < <(python3 -c 'import json; d=json.load(open("/run/safe-change-response.json")); print(d.get("phase", ""), str(bool(d.get("reused", False))).lower())' 2>/dev/null || true)
if [[ "$status" == 200 && "$phase" == succeeded && "$reused" == false ]]; then
  log_marker "SAFE_CHANGE_VM_FIRST_SUCCEEDED reused=false"
  sync
  while true; do sleep 60; done
fi
if [[ "$status" == 200 && "$phase" == succeeded && "$reused" == true ]]; then
  log_marker "SAFE_CHANGE_VM_RESTORED_SUCCEEDED reused=true"
  sync
  /sbin/poweroff -f
  exit 0
fi
log_marker "SAFE_CHANGE_VM_EXTERNAL_UNEXPECTED status=$status phase=$phase reused=$reused"
/sbin/poweroff -f
exit 1
`, encodedDirectProbe, encodedRequest, encodedToken)
}

func expectExternalCommand(ctx context.Context, scanner *bufio.Scanner, expected string) error {
	result := make(chan error, 1)
	go func() {
		if !scanner.Scan() {
			if err := scanner.Err(); err != nil {
				result <- err
				return
			}
			result <- fmt.Errorf("shared-control VM input closed while waiting for %q", expected)
			return
		}
		if strings.TrimSpace(scanner.Text()) != expected {
			result <- fmt.Errorf("shared-control VM expected %q command", expected)
			return
		}
		result <- nil
	}()
	select {
	case err := <-result:
		return err
	case <-ctx.Done():
		return ctx.Err()
	}
}

func writeExternalEvent(writer io.Writer, value map[string]any) error {
	return json.NewEncoder(writer).Encode(value)
}

func writeExternalQEMUCommand(path string, arguments []string, evidenceDirectory, imagePath string) error {
	redacted := make([]string, len(arguments))
	for index, argument := range arguments {
		argument = strings.ReplaceAll(argument, evidenceDirectory, "<vm-evidence>")
		argument = strings.ReplaceAll(argument, imagePath, "<verified-base-image>")
		redacted[index] = argument
	}
	value := map[string]any{
		"schema":     1,
		"executable": "qemu-system-x86_64",
		"arguments":  redacted,
	}
	var encoded bytes.Buffer
	encoder := json.NewEncoder(&encoded)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(value); err != nil {
		return err
	}
	return os.WriteFile(path, encoded.Bytes(), 0o600)
}

func markerFieldFromLast(path, marker string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return markerField(string(data), marker)
}

func removeExternalPrivateFiles(paths ...string) error {
	for _, path := range paths {
		if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
	}
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
	trace      *os.File
	traceSeq   uint64
	nextID     uint64
}

func dialQMP(ctx context.Context, path string) (*qmpClient, error) {
	return dialQMPWithTrace(ctx, path, "")
}

func dialQMPWithTrace(ctx context.Context, path, tracePath string) (*qmpClient, error) {
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
	client := &qmpClient{
		connection: connection,
		decoder:    json.NewDecoder(connection),
		encoder:    json.NewEncoder(connection),
	}
	if tracePath != "" {
		client.trace, err = os.OpenFile(
			tracePath,
			os.O_CREATE|os.O_EXCL|os.O_WRONLY,
			0o600,
		)
		if err != nil {
			connection.Close()
			return nil, err
		}
	}
	var greeting map[string]json.RawMessage
	if err := client.decoder.Decode(&greeting); err != nil {
		client.Close()
		return nil, err
	}
	if err := client.record("server_to_client", greeting); err != nil {
		client.Close()
		return nil, err
	}
	if _, ok := greeting["QMP"]; !ok {
		client.Close()
		return nil, errors.New("QMP greeting is missing")
	}
	if err := client.command("qmp_capabilities", nil); err != nil {
		client.Close()
		return nil, err
	}
	return client, nil
}

func (q *qmpClient) Close() error {
	connectionErr := q.connection.Close()
	var traceErr error
	if q.trace != nil {
		traceErr = q.trace.Close()
		q.trace = nil
	}
	return errors.Join(connectionErr, traceErr)
}

func (q *qmpClient) record(direction string, payload any) error {
	if q.trace == nil {
		return nil
	}
	q.traceSeq++
	record := map[string]any{
		"sequence":  q.traceSeq,
		"time_ns":   time.Now().UnixNano(),
		"direction": direction,
		"payload":   payload,
	}
	if err := json.NewEncoder(q.trace).Encode(record); err != nil {
		return err
	}
	return q.trace.Sync()
}

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
	if err := q.record("client_to_server", request); err != nil {
		return nil, err
	}
	if err := q.encoder.Encode(request); err != nil {
		return nil, err
	}
	for {
		var raw map[string]json.RawMessage
		if err := q.decoder.Decode(&raw); err != nil {
			return nil, err
		}
		if err := q.record("server_to_client", raw); err != nil {
			return nil, err
		}
		var response struct {
			ID     string          `json:"id"`
			Return json.RawMessage `json:"return"`
			Error  *struct {
				Class string `json:"class"`
				Desc  string `json:"desc"`
			} `json:"error"`
		}
		encoded, err := json.Marshal(raw)
		if err != nil {
			return nil, err
		}
		if err := json.Unmarshal(encoded, &response); err != nil {
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
