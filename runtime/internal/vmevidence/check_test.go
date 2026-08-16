package vmevidence

import (
	"bytes"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

func TestCheckManifestRejectsMutation(t *testing.T) {
	directory := t.TempDir()
	names := append([]string(nil), manifestFiles...)
	sort.Strings(names)
	lines := make([]string, 0, len(names))
	for _, name := range names {
		path := filepath.Join(directory, name)
		if err := os.WriteFile(path, []byte("retained:"+name), 0o600); err != nil {
			t.Fatal(err)
		}
		digest, err := hashFile(path)
		if err != nil {
			t.Fatal(err)
		}
		lines = append(lines, digest+"  "+name)
	}
	if err := os.WriteFile(filepath.Join(directory, "SHA256SUMS"), []byte(strings.Join(lines, "\n")+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := checkManifest(directory); err != nil {
		t.Fatalf("valid manifest rejected: %v", err)
	}
	if err := os.WriteFile(filepath.Join(directory, "guest-operation.json"), []byte("mutated"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := checkManifest(directory); err == nil || !strings.Contains(err.Error(), "has SHA-256") {
		t.Fatalf("mutated evidence was not rejected: %v", err)
	}
}

func TestCheckQEMURejectsNetworkBypassAndExtraDevice(t *testing.T) {
	command := qemuCommandFile{Schema: 1, Executable: "qemu-system-x86_64", Arguments: []string{
		"-name", "safe-change-vm",
		"-machine", "q35",
		"-m", "1024",
		"-smp", "2",
		"-drive", "file=<vm-evidence>/guest.qcow2,if=virtio,format=qcow2,cache=none",
		"-display", "none",
		"-serial", "file:<vm-evidence>/guest.serial.log",
		"-monitor", "none",
		"-qmp", "unix:<vm-evidence>/qmp.sock,server=on,wait=off",
		"-no-reboot",
		"-nic", "none",
		"-netdev", "user,id=opnet,restrict=on,guestfwd=tcp:10.0.2.100:8000-cmd:/usr/bin/nc 127.0.0.1 38017,guestfwd=tcp:10.0.2.100:8787-cmd:/usr/bin/nc 127.0.0.1 40711",
		"-device", "virtio-net-pci,netdev=opnet",
		"-smbios", "type=1,serial=ds=nocloud;s=http://10.0.2.100:8000/",
		"-accel", "kvm",
	}}
	if err := checkQEMU(command, "kvm"); err != nil {
		t.Fatalf("valid QEMU boundary rejected: %v", err)
	}
	if err := crossCheckNetwork(
		command,
		supervisorFacts{FirstAddress: "127.0.0.1:40711"},
		historyFacts{Operation: operationWithTarget("http://127.0.0.1:43321/v1/charge")},
		metadataFacts{Address: "127.0.0.1:38017", DirectCanaryAddress: "127.0.0.1:12345"},
		guestFacts{DirectCanaryPort: 12345},
	); err != nil {
		t.Fatalf("matching bound endpoint rejected: %v", err)
	}
	if err := crossCheckNetwork(
		command,
		supervisorFacts{FirstAddress: "127.0.0.1:49999"},
		historyFacts{Operation: operationWithTarget("http://127.0.0.1:43321/v1/charge")},
		metadataFacts{Address: "127.0.0.1:38017", DirectCanaryAddress: "127.0.0.1:12345"},
		guestFacts{DirectCanaryPort: 12345},
	); err == nil {
		t.Fatal("QEMU forward differing from the bound endpoint was accepted")
	}
	if err := crossCheckNetwork(
		command,
		supervisorFacts{FirstAddress: "127.0.0.1:40711"},
		historyFacts{Operation: operationWithTarget("http://127.0.0.1:40711/v1/charge")},
		metadataFacts{Address: "127.0.0.1:38017", DirectCanaryAddress: "127.0.0.1:12345"},
		guestFacts{DirectCanaryPort: 12345},
	); err == nil {
		t.Fatal("direct QEMU forward to the provider was accepted")
	}

	withHostForward := command
	withHostForward.Arguments = append([]string(nil), command.Arguments...)
	for index, argument := range withHostForward.Arguments {
		if strings.HasPrefix(argument, "user,id=opnet,") {
			withHostForward.Arguments[index] += ",hostfwd=tcp::2222-:22"
		}
	}
	if err := checkQEMU(withHostForward, "kvm"); err == nil {
		t.Fatal("QEMU hostfwd bypass was accepted")
	}
	withRestrictDisabled := command
	withRestrictDisabled.Arguments = append([]string(nil), command.Arguments...)
	for index, argument := range withRestrictDisabled.Arguments {
		if strings.HasPrefix(argument, "user,id=opnet,") {
			withRestrictDisabled.Arguments[index] += ",restrict=off"
		}
	}
	if err := crossCheckNetwork(
		withRestrictDisabled,
		supervisorFacts{FirstAddress: "127.0.0.1:40711"},
		historyFacts{Operation: operationWithTarget("http://127.0.0.1:43321/v1/charge")},
		metadataFacts{Address: "127.0.0.1:38017", DirectCanaryAddress: "127.0.0.1:12345"},
		guestFacts{DirectCanaryPort: 12345},
	); err == nil {
		t.Fatal("QEMU restrict=off override was accepted")
	}

	withExtraDevice := command
	withExtraDevice.Arguments = append(append([]string(nil), command.Arguments...), "-kernel", "/tmp/unretained-kernel")
	if err := checkQEMU(withExtraDevice, "kvm"); err == nil {
		t.Fatal("unretained QEMU device input was accepted")
	}
	withPositionalDisk := command
	withPositionalDisk.Arguments = append(append([]string(nil), command.Arguments...), "/tmp/unretained-disk.img")
	if err := checkQEMU(withPositionalDisk, "kvm"); err == nil {
		t.Fatal("positional QEMU disk image was accepted")
	}
}

func TestCheckQMPRequiresSuccessfulPausedQueries(t *testing.T) {
	path := writeQMPFixture(t, true, -1, -1)
	if _, err := checkQMP(path); err != nil {
		t.Fatalf("valid QMP trace rejected: %v", err)
	}
	if _, err := checkQMP(writeQMPFixture(t, false, -1, -1)); err == nil || !strings.Contains(err.Error(), "paused VM") {
		t.Fatalf("running VM query was not rejected: %v", err)
	}
	if _, err := checkQMP(writeQMPFixture(t, true, 7, -1)); err == nil || !strings.Contains(err.Error(), "did not return successfully") {
		t.Fatalf("failed loadvm response was not rejected: %v", err)
	}
	if _, err := checkQMP(writeQMPFixture(t, true, -1, 7)); err == nil || !strings.Contains(err.Error(), "reported an error string") {
		t.Fatalf("HMP error string was not rejected: %v", err)
	}
}

func TestCheckGuestRequiresExactCredentialFreeScript(t *testing.T) {
	encoded := []byte(`{"call_id":"vm/job-1/write","kind":"vm-write","body":"eyJqb2IiOiJqb2ItMSIsInZhbHVlIjo0Mn0="}` + "\n")
	guest := guestOperation{CallID: "vm/job-1/write", Kind: "vm-write", Body: []byte(`{"job":"job-1","value":42}`)}
	script := expectedGuestScript(base64.StdEncoding.EncodeToString(bytes.TrimSpace(encoded)), 12345)
	if _, err := checkGuest(guest, encoded, []byte(script)); err != nil {
		t.Fatalf("fixed guest contract rejected: %v", err)
	}
	mutated := script + "curl -H 'authorization: bearer secret' http://provider.invalid\n"
	if _, err := checkGuest(guest, encoded, []byte(mutated)); err == nil {
		t.Fatal("guest credential and provider bypass was accepted")
	}
}

func TestGuestNetworkTraceBindsScriptAndCanary(t *testing.T) {
	guest := guestFacts{
		DirectCanaryPort: 12345,
		ScriptSHA256:     strings.Repeat("a", 64),
		UserDataSHA256:   strings.Repeat("b", 64),
	}
	details := []any{
		canaryDetails{Address: "127.0.0.1:12345"},
		metadataDetails{
			Method: "GET", Path: "/user-data", Address: "127.0.0.1:38017",
			GuestScriptSHA256: guest.ScriptSHA256, UserDataSHA256: guest.UserDataSHA256,
		},
		nil,
		nil,
	}
	events := []string{
		"direct-host-canary-listening", "guest-user-data-served",
		"guest-operation-gate-opened", "guest-operation-gate-served",
	}
	var lines []string
	for index := range details {
		var detailJSON json.RawMessage
		if details[index] != nil {
			var err error
			detailJSON, err = json.Marshal(details[index])
			if err != nil {
				t.Fatal(err)
			}
		}
		recordJSON, err := json.Marshal(traceRecord{
			Sequence: uint64(index + 1), TimeNS: int64(index+1) * 10,
			Event: events[index], Details: detailJSON,
		})
		if err != nil {
			t.Fatal(err)
		}
		lines = append(lines, string(recordJSON))
	}
	path := filepath.Join(t.TempDir(), "guest-network.jsonl")
	if err := os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	facts, err := checkGuestNetworkTrace(path, guest)
	if err != nil {
		t.Fatalf("valid guest network trace rejected: %v", err)
	}
	if facts.DirectCanaryAddress != "127.0.0.1:12345" || facts.Address != "127.0.0.1:38017" {
		t.Fatalf("unexpected guest network facts: %+v", facts)
	}
	guest.DirectCanaryPort = 12346
	if _, err := checkGuestNetworkTrace(path, guest); err == nil {
		t.Fatal("guest script canary differing from the host listener was accepted")
	}
}

func TestRetainedDiskImageWhenRequested(t *testing.T) {
	directory := os.Getenv("SAFE_CHANGE_VM_EVIDENCE_TEST_DIR")
	if directory == "" {
		t.Skip("set SAFE_CHANGE_VM_EVIDENCE_TEST_DIR for the real qcow2 check")
	}
	data, err := os.ReadFile(filepath.Join(directory, "provenance.json"))
	if err != nil {
		t.Fatal(err)
	}
	var provenance provenanceFile
	if err := json.Unmarshal(data, &provenance); err != nil {
		t.Fatal(err)
	}
	if err := checkDiskImage(directory, provenance); err != nil {
		t.Fatal(err)
	}
	if err := checkQEMULog(filepath.Join(directory, "qemu.log")); err != nil {
		t.Fatal(err)
	}
}

func TestQCOWBackingReferenceMustBePinned(t *testing.T) {
	expected := "/private/cache/pinned.img"
	image := make([]byte, 112+len(expected))
	copy(image[:4], []byte{'Q', 'F', 'I', 0xfb})
	binary.BigEndian.PutUint32(image[4:8], 3)
	binary.BigEndian.PutUint64(image[8:16], 112)
	binary.BigEndian.PutUint32(image[16:20], uint32(len(expected)))
	binary.BigEndian.PutUint32(image[20:24], 16)
	binary.BigEndian.PutUint32(image[100:104], 112)
	copy(image[112:], expected)
	path := filepath.Join(t.TempDir(), "guest.qcow2")
	if err := os.WriteFile(path, image, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := checkQCOWBackingReference(path, expected); err != nil {
		t.Fatalf("pinned qcow2 backing rejected: %v", err)
	}
	if err := checkQCOWBackingReference(path, "/dev/zero"); err == nil {
		t.Fatal("arbitrary qcow2 backing path was accepted")
	}
	binary.BigEndian.PutUint64(image[72:80], 1)
	if err := os.WriteFile(path, image, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := checkQCOWBackingReference(path, expected); err == nil {
		t.Fatal("qcow2 external feature bit was accepted")
	}
}

func TestCheckTimelineRejectsResumeBeforeReplacement(t *testing.T) {
	qmp := qmpFacts{
		Commands: []qmpCommand{
			{TimeNS: 30, ID: "c0"}, {TimeNS: 50, ID: "c1"}, {TimeNS: 70, ID: "c2"},
			{TimeNS: 100, ID: "c3"}, {TimeNS: 120, ID: "c4"}, {TimeNS: 160, ID: "c5"},
			{TimeNS: 180, ID: "c6"}, {TimeNS: 220, ID: "c7"}, {TimeNS: 240, ID: "c8"},
			{TimeNS: 300, ID: "c9"},
		},
		ResponseTimes: map[string]int64{
			"c0": 40, "c1": 60, "c2": 80, "c3": 110, "c4": 130,
			"c5": 170, "c6": 190, "c7": 230, "c8": 250, "c9": 310,
		},
	}
	supervisor := supervisorFacts{
		Times: map[string][]int64{
			"rule-and-sandbox-cutover":        {10, 260},
			"sandbox-endpoint-bound":          {20, 280},
			"snapshot-save-paused":            {90},
			"first-operation-unknown":         {150},
			"restore-pause-confirmed":         {200},
			"old-sandbox-endpoint-closed":     {210},
			"snapshot-loaded-paused":          {255},
			"old-sandbox-generation-rejected": {270},
		},
		FirstUnknownAt: 150,
		RestoredAt:     330,
	}
	providers := []providerFact{{TimeNS: 140}, {TimeNS: 320}}
	metadata := metadataFacts{
		DirectCanaryTimeNS: 5, TimeNS: 45, GateOpenTimeNS: 115, GateServedTimeNS: 135,
	}
	if err := checkTimeline(qmp, supervisor, providers, metadata); err != nil {
		t.Fatalf("valid host/QMP timeline rejected: %v", err)
	}
	supervisor.Times["sandbox-endpoint-bound"][1] = 305
	if err := checkTimeline(qmp, supervisor, providers, metadata); err == nil {
		t.Fatal("VM resume before replacement endpoint was accepted")
	}
}

func TestStableOperationAndPaymentDigests(t *testing.T) {
	operationID := "op-9ce70f9d30ad5925848b7b22eb29f3840b7eeece520b3b342ef14166e24dc640"
	if got, want := deriveOperationID("full-linux-vm", "vm/job-1/write"), operationID; got != want {
		t.Fatalf("Operation identity = %s, want %s", got, want)
	}
	body := []byte(`{"job":"job-1","value":42}`)
	if got, want := paymentRequestHash("POST", "/v1/charge", body), "945da85f0d3876efeed4645080ef82ba980663b5638d1a9fa55f1acf09897dfa"; got != want {
		t.Fatalf("payment request digest = %s, want %s", got, want)
	}
	operation := kernel.Operation{
		ID: operationID, Method: "POST", Target: "http://127.0.0.1:43321/v1/charge", RequestBody: body,
	}
	if got, want := gatewayRequestHash(operation), "011f81216ce759254f6615a1594d75a4b751df3238b7a28768c5e556a0bf025e"; got != want {
		t.Fatalf("gateway request digest = %s, want %s", got, want)
	}
	if got, want := paymentResultHash(operationID), "2d9f5bc5a759ffffefa7b5b9dd60eb1acd637272ee98e1ccf1208f980909ed61"; got != want {
		t.Fatalf("payment result digest = %s, want %s", got, want)
	}
}

func TestDecodeStrictRejectsUnknownAndMultipleValues(t *testing.T) {
	var target struct {
		Value int `json:"value"`
	}
	if err := decodeStrict([]byte(`{"value":1,"extra":2}`), &target); err == nil {
		t.Fatal("unknown JSON field was accepted")
	}
	if err := decodeStrict([]byte(`{"value":1} {"value":2}`), &target); err == nil {
		t.Fatal("multiple JSON values were accepted")
	}
	if err := decodeStrict([]byte(`{"value":1,"value":2}`), &target); err == nil {
		t.Fatal("duplicate JSON key was accepted")
	}
}

func writeQMPFixture(t *testing.T, paused bool, failedCommand, hmpErrorCommand int) string {
	t.Helper()
	commands := []struct {
		name    string
		command string
	}{
		{name: "qmp_capabilities"}, {name: "stop"}, {name: "query-status"},
		{name: "human-monitor-command", command: "savevm before_operation"}, {name: "cont"},
		{name: "stop"}, {name: "query-status"},
		{name: "human-monitor-command", command: "loadvm before_operation"},
		{name: "query-status"}, {name: "cont"},
	}
	var lines []string
	sequence := uint64(0)
	appendRecord := func(direction string, payload any) {
		sequence++
		payloadJSON, err := json.Marshal(payload)
		if err != nil {
			t.Fatal(err)
		}
		recordJSON, err := json.Marshal(traceRecord{
			Sequence: sequence, TimeNS: int64(sequence) * 10, Direction: direction, Payload: payloadJSON,
		})
		if err != nil {
			t.Fatal(err)
		}
		lines = append(lines, string(recordJSON))
	}
	for index, command := range commands {
		id := fmt.Sprintf("command-%d", index+1)
		request := map[string]any{"execute": command.name, "id": id}
		if command.command != "" {
			request["arguments"] = map[string]any{"command-line": command.command}
		}
		appendRecord("client_to_server", request)
		if index == failedCommand {
			appendRecord("server_to_client", map[string]any{
				"id": id, "error": map[string]any{"class": "GenericError", "desc": "injected failure"},
			})
			continue
		}
		response := any(map[string]any{})
		if index == 2 || index == 6 || index == 8 {
			status := "paused"
			if !paused {
				status = "running"
			}
			response = map[string]any{"status": status, "running": !paused}
		} else if index == 3 || index == 7 {
			response = ""
		}
		if index == hmpErrorCommand {
			response = "Error: injected HMP failure"
		}
		appendRecord("server_to_client", map[string]any{"id": id, "return": response})
	}
	path := filepath.Join(t.TempDir(), "qmp-protocol.jsonl")
	if err := os.WriteFile(path, []byte(strings.Join(lines, "\n")+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func operationWithTarget(target string) kernel.Operation {
	return kernel.Operation{Target: target}
}
