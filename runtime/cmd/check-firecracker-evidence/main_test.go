package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestCheckFixtureAndMutations(t *testing.T) {
	mutations := []struct {
		name   string
		mutate func(t *testing.T, dir string)
	}{
		{"missing required file", func(t *testing.T, d string) {
			if err := os.Remove(filepath.Join(d, "assets.json")); err != nil {
				t.Fatal(err)
			}
		}},
		{"resumed snapshot load", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "firecracker-api-g3.jsonl"), `"resume_vm":false`, `"resume_vm":true`)
		}},
		{"network API", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "firecracker-api-g1.jsonl"), `"path":"/machine-config"`, `"path":"/network-interfaces/eth0"`)
		}},
		{"same successor pid", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "firecracker-processes.json"), `"pid":300`, `"pid":100`)
		}},
		{"snapshot hash changed", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "snapshot-provenance.json"), `"load_count":1`, `"load_count":2`)
		}},
		{"gate without go", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "firecracker-gate-g3.jsonl"), `"event":"go"`, `"event":"no-go"`)
		}},
		{"unconfirmed process exit", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "firecracker-processes.json"), `"exit_confirmed":true`, `"exit_confirmed":false`)
		}},
		{"missing sandbox peer pid", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "firecracker-relay-g1.jsonl"), `"sandbox_peer_pid":1100`, `"sandbox_peer_pid":0`)
		}},
		{"unsealed load input", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "snapshot-provenance.json"), `"linux_seals":15`, `"linux_seals":0`)
		}},
		{"wrong sealed boot fd", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "assets.json"), `"child_fd":4`, `"child_fd":6`)
		}},
		{"unsealed boot path", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "firecracker-api-g1.jsonl"), `/proc/self/fd/4`, `/kernel`)
		}},
		{"supervisor sequence changed", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "firecracker-supervisor.jsonl"), `"sequence":1`, `"sequence":9`)
		}},
		{"guest result ID differs", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "guest-results.json"), `"operation_id":"stable"`, `"operation_id":"other"`)
		}},
		{"wrong fixed version", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "assets.json"), `"firecracker_version":"1.16.1"`, `"firecracker_version":"1.15.0"`)
		}},
		{"GET response wrong instance", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "firecracker-api-g3.jsonl"), `"id":"g3"`, `"id":"g1"`)
		}},
		{"summary call id differs", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "result.json"), `"operation_call_id":"a"`, `"operation_call_id":"other"`)
		}},
		{"gate allow reordered", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "firecracker-gate-g1.jsonl"), `"event":"allow"`, `"event":"go-first"`)
		}},
		{"gate allowed twice", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "firecracker-gate-g3.jsonl"), `"event":"go"`, `"event":"allow"`)
		}},
		{"gate go omits generation role", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "firecracker-gate-g3.jsonl"), `"bytes":5`, `"bytes":3`)
		}},
		{"process time reversed", func(t *testing.T, d string) {
			replace(t, filepath.Join(d, "firecracker-processes.json"), `"started_time_ns":10,"stopped_time_ns":30`, `"started_time_ns":30,"stopped_time_ns":10`)
		}},
		{"retained snapshot byte changed", func(t *testing.T, d string) {
			path := filepath.Join(d, "snapshot.memory")
			if err := os.Chmod(path, 0o600); err != nil {
				t.Fatal(err)
			}
			data, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			data[0] ^= 1
			if err := os.WriteFile(path, data, 0o600); err != nil {
				t.Fatal(err)
			}
			if err := os.Chmod(path, 0o400); err != nil {
				t.Fatal(err)
			}
		}},
	}
	dir := fixture(t)
	if err := check(dir); err != nil {
		t.Fatalf("fixture rejected: %v", err)
	}
	t.Run("first committed response lost and retry reused", func(t *testing.T) {
		d := fixture(t)
		setFirstReused(t, d, true)
		if err := check(d); err != nil {
			t.Fatalf("reused first outcome with prior lost response rejected: %v", err)
		}
	})
	t.Run("first reused without lost response evidence", func(t *testing.T) {
		d := fixture(t)
		setFirstReused(t, d, false)
		if err := check(d); err == nil {
			t.Fatal("reused first outcome without prior lost response accepted")
		}
	})
	for _, tt := range mutations {
		t.Run(tt.name, func(t *testing.T) {
			d := fixture(t)
			tt.mutate(t, d)
			if err := check(d); err == nil {
				t.Fatal("mutation accepted")
			}
		})
	}
}

func fixture(t *testing.T) string {
	t.Helper()
	d := t.TempDir()
	if err := os.Chmod(d, 0o700); err != nil {
		t.Fatal(err)
	}
	request := []byte(`{"call_id":"a","kind":"audit","body":"e30="}`)
	guestBytes := []byte("guest")
	initramfs := newcFixture(t, guestBytes, request)
	stateBytes := []byte("state")
	memoryBytes := []byte("memory")
	guest := fixtureArtifact("firecracker-guest", guestBytes)
	init := fixtureArtifact("guest-initramfs.cpio", initramfs)
	state := fixtureArtifact("snapshot.state", stateBytes)
	memory := fixtureArtifact("snapshot.memory", memoryBytes)
	fc := artifact{Name: "fc", Size: 1, Mode: 0o500, SHA256: officialFirecrackerSHA256}
	kernel := artifact{Name: "kernel", Size: 1, Mode: 0o400, SHA256: officialKernelSHA256}
	sealedBoot := []sealedArtifact{{Artifact: kernel, ChildFD: 4, LinuxSeals: 15}, {Artifact: init, ChildFD: 5, LinuxSeals: 15}}
	sealedLoad := []sealedArtifact{{Artifact: state, ChildFD: 4, LinuxSeals: 15}, {Artifact: memory, ChildFD: 5, LinuxSeals: 15}}
	if err := os.WriteFile(filepath.Join(d, "snapshot.state"), stateBytes, 0o400); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(d, "snapshot.memory"), memoryBytes, 0o400); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(d, "guest-initramfs.cpio"), initramfs, 0o400); err != nil {
		t.Fatal(err)
	}
	write(t, d, "assets.json", map[string]any{"schema": 1, "firecracker_version": officialFirecrackerVersion, "snapshot_format": "v10.0.0", "firecracker": fc, "kernel": kernel, "guest": guest, "initramfs": init, "kernel_source": "official-firecracker-ci-v1.15", "sealed_boot_inputs": sealedBoot})
	g1 := process{Generation: 1, ID: "g1", PID: 100, Executable: "firecracker", ExecutableSHA256: officialFirecrackerSHA256, Device: 1, Inode: 11, Start: 1, StartedNS: 10, StoppedNS: 30, ExitConfirmed: true, Termination: "supervisor", APISocket: socket{Name: "api-g1.sock", Device: 1, Inode: 21, Mode: 0o600}, Vsock: socket{Name: "vsock-g1", Device: 1, Inode: 31, Mode: 0o600}}
	g3 := process{Generation: 3, ID: "g3", PID: 300, Executable: "firecracker", ExecutableSHA256: officialFirecrackerSHA256, Device: 1, Inode: 12, Start: 2, StartedNS: 40, StoppedNS: 90, ExitConfirmed: true, Termination: "supervisor", APISocket: socket{Name: "api-g3.sock", Device: 1, Inode: 22, Mode: 0o600}, Vsock: socket{Name: "vsock-g3", Device: 1, Inode: 32, Mode: 0o600}}
	write(t, d, "firecracker-processes.json", map[string]any{"schema": 1, "processes": []process{g1, g3}})
	write(t, d, "snapshot-provenance.json", map[string]any{"schema": 1, "state_before": state, "state_after": state, "memory_before": memory, "memory_after": memory, "sealed_load_inputs": sealedLoad, "load_count": 1, "original_resumed_after_snapshot": true, "original_stopped_before_successor_start": true})
	write(t, d, "timeline.json", map[string]int64{"snapshot_created_ns": 20, "first_relay_armed_ns": 21, "first_vm_resumed_ns": 22, "first_vm_stopped_ns": 30, "restore_loaded_paused_ns": 50, "restored_relay_armed_ns": 60, "restored_vm_resumed_ns": 70, "run_completed_ns": 100})
	write(t, d, "result.json", map[string]any{"schema": 1, "backend": "firecracker", "accelerator": "kvm", "nested_virtualization": false, "firecracker_version": officialFirecrackerVersion, "guest_kernel": officialKernelVersion, "microvm_processes": 2, "distinct_processes": true, "firecracker_pids": []int{100, 300}, "guest_cid": 3, "network_interfaces": 0, "root_block_devices": 0, "guest_credential_free": true, "guest_request_fields": []string{"call_id", "kind", "body"}, "sandbox_transport": "generation-bound-vsock-to-host-unix-socket", "direct_effect": "unreachable-no-guest-network-device", "direct_probe_host": "127.0.0.1", "successor_termination": "host-after-final-result", "snapshot_loads": 1, "restore_loaded_before_resume": true, "relay_armed_while_paused": true, "first_operation_reused": false, "restored_operation_reused": true, "operation_id": "stable", "operation_call_id": "a"})
	outcome := func(reused bool) map[string]any {
		return map[string]any{
			"phase": "succeeded", "reused": reused, "operation_id": "stable",
			"status_code": 200, "body": []byte("durable receipt\n"),
			"result_hash": strings.Repeat("a", 64), "recovered_by_query": false,
		}
	}
	write(t, d, "guest-results.json", map[string]any{
		"schema":   1,
		"first":    map[string]any{"event": "RESULT", "status": 200, "body": outcome(false)},
		"restored": map[string]any{"event": "RESULT", "status": 200, "body": outcome(true)},
	})
	if err := os.WriteFile(filepath.Join(d, "guest-request.json"), request, 0o600); err != nil {
		t.Fatal(err)
	}
	g1api := []apiCall{call(1, "GET", "/", "", 200, `{"app_name":"Firecracker","id":"g1","state":"Not started","vmm_version":"1.16.1"}`), call(2, "PUT", "/machine-config", `{"vcpu_count":1,"mem_size_mib":128,"smt":false,"track_dirty_pages":false}`, 204, ""), call(3, "PUT", "/boot-source", `{"kernel_image_path":"/proc/self/fd/4","boot_args":"x","initrd_path":"/proc/self/fd/5"}`, 204, ""), call(4, "PUT", "/vsock", `{"guest_cid":3,"uds_path":"/e/vsock-g1"}`, 204, ""), call(5, "PUT", "/actions", `{"action_type":"InstanceStart"}`, 204, ""), call(6, "PATCH", "/vm", `{"state":"Paused"}`, 204, ""), call(7, "GET", "/", "", 200, `{"app_name":"Firecracker","id":"g1","state":"Paused","vmm_version":"1.16.1"}`), call(8, "PUT", "/snapshot/create", `{"snapshot_type":"Full","snapshot_path":"/e/snapshot.state","mem_file_path":"/e/snapshot.memory"}`, 204, ""), call(9, "PATCH", "/vm", `{"state":"Resumed"}`, 204, ""), call(10, "PATCH", "/vm", `{"state":"Paused"}`, 204, ""), call(11, "GET", "/", "", 200, `{"app_name":"Firecracker","id":"g1","state":"Paused","vmm_version":"1.16.1"}`)}
	g3api := []apiCall{call(1, "GET", "/", "", 200, `{"app_name":"Firecracker","id":"g3","state":"Not started","vmm_version":"1.16.1"}`), call(2, "PUT", "/snapshot/load", `{"snapshot_path":"/proc/self/fd/4","mem_backend":{"backend_type":"File","backend_path":"/proc/self/fd/5"},"resume_vm":false,"vsock_override":{"uds_path":"/e/vsock-g3"}}`, 204, ""), call(3, "GET", "/", "", 200, `{"app_name":"Firecracker","id":"g3","state":"Paused","vmm_version":"1.16.1"}`), call(4, "PATCH", "/vm", `{"state":"Resumed"}`, 204, "")}
	jsonl(t, d, "firecracker-api-g1.jsonl", g1api)
	jsonl(t, d, "firecracker-api-g3.jsonl", g3api)
	supervisor := []supervisorEvent{}
	for index, item := range []struct {
		event      string
		generation uint64
	}{{"run-started", 0}, {"process-started", 1}, {"guest-ready", 1}, {"snapshot-created-paused", 1}, {"relay-armed-paused", 1}, {"vm-resumed", 1}, {"operation-result", 1}, {"vm-paused", 1}, {"process-stopped", 1}, {"process-started", 3}, {"snapshot-loaded-paused", 3}, {"relay-armed-paused", 3}, {"vm-resumed", 3}, {"operation-result", 3}, {"process-stopped", 3}, {"run-completed", 0}} {
		record := supervisorEvent{Schema: 1, Sequence: uint64(index + 1), Event: item.event, TimeNS: int64(index + 1), ElapsedNS: int64(index + 1), Generation: item.generation}
		if item.generation == 1 {
			record.InstanceID = "g1"
			record.PID = 100
			record.StartTimeTicks = 1
		}
		if item.generation == 3 {
			record.InstanceID = "g3"
			record.PID = 300
			record.StartTimeTicks = 2
		}
		if item.event == "snapshot-created-paused" || item.event == "snapshot-loaded-paused" {
			record.Details = map[string]json.RawMessage{"state_sha256": json.RawMessage(`"` + state.SHA256 + `"`), "memory_sha256": json.RawMessage(`"` + memory.SHA256 + `"`)}
		}
		if item.event == "operation-result" {
			reused := "false"
			if item.generation == 3 {
				reused = "true"
			}
			record.Details = map[string]json.RawMessage{"operation_id": json.RawMessage(`"stable"`), "reused": json.RawMessage(reused)}
		}
		if item.event == "process-stopped" {
			record.Details = map[string]json.RawMessage{"exit_confirmed": json.RawMessage(`true`), "termination": json.RawMessage(`"supervisor"`)}
		}
		supervisor = append(supervisor, record)
	}
	jsonl(t, d, "firecracker-supervisor.jsonl", supervisor)
	for _, x := range []struct {
		name string
		gen  uint64
		pid  int
	}{{"g1", 1, 100}, {"g3", 3, 300}} {
		now := time.Unix(1, 0)
		events := []string{"accept", "ready", "allow", "go", "accept", "ready", "go", "accept", "result"}
		if x.name == "g3" {
			events = []string{"allow", "accept", "ready", "go", "accept", "result"}
		}
		gate := make([]audit, 0, len(events))
		for _, event := range events {
			record := audit{Event: event, Time: now, Generation: x.gen, Port: 8000}
			if event == "accept" {
				record.PID = x.pid
			}
			if event == "result" {
				record.Status, record.Bytes = 200, 1
			}
			if event == "go" {
				record.Bytes = len(fmt.Sprintf("GO %d\n", x.gen))
			}
			gate = append(gate, record)
		}
		jsonl(t, d, "firecracker-gate-"+x.name+".jsonl", gate)
		jsonl(t, d, "firecracker-relay-"+x.name+".jsonl", []audit{
			{Event: "accept", Time: now, Generation: x.gen, Port: 8787, PID: x.pid, SandboxDevice: 7, SandboxInode: 1000 + x.gen},
			{Event: "bytes", Time: now, Generation: x.gen, Port: 8787, SandboxPID: x.pid + 1000, GuestToHost: 4, HostToGuest: 4, SandboxDevice: 7, SandboxInode: 1000 + x.gen},
		})
	}
	return d
}

func TestCheckRelayAllowsLostNonFinalResponse(t *testing.T) {
	now := time.Unix(1, 0)
	records := []audit{
		{Event: "accept", Time: now, Generation: 1, Port: 8787, PID: 100, SandboxDevice: 7, SandboxInode: 8},
		{Event: "bytes", Time: now, Generation: 1, Port: 8787, SandboxPID: 200, GuestToHost: 4, HostToGuest: 0, SandboxDevice: 7, SandboxInode: 8},
		{Event: "accept", Time: now, Generation: 1, Port: 8787, PID: 100, SandboxDevice: 7, SandboxInode: 8},
		{Event: "bytes", Time: now, Generation: 1, Port: 8787, SandboxPID: 200, GuestToHost: 4, HostToGuest: 4, SandboxDevice: 7, SandboxInode: 8},
	}
	if err := checkRelay(records, 1, 100, true); err != nil {
		t.Fatalf("lost non-final response rejected: %v", err)
	}
	records[len(records)-1].SandboxPID++
	if err := checkRelay(records, 1, 100, true); err == nil {
		t.Fatal("changed sandbox peer PID accepted")
	}
	records[len(records)-1].SandboxPID--
	records[len(records)-1].HostToGuest = 0
	if err := checkRelay(records, 1, 100, true); err == nil {
		t.Fatal("lost final response accepted")
	}
}

func setFirstReused(t *testing.T, directory string, includeLostResponse bool) {
	t.Helper()
	replace(t, filepath.Join(directory, "result.json"), `"first_operation_reused":false`, `"first_operation_reused":true`)
	replace(t, filepath.Join(directory, "guest-results.json"), `"reused":false`, `"reused":true`)
	replace(t, filepath.Join(directory, "firecracker-supervisor.jsonl"), `"reused":false`, `"reused":true`)
	if !includeLostResponse {
		return
	}
	path := filepath.Join(directory, "firecracker-relay-g1.jsonl")
	records, err := readJSONL[audit](path)
	if err != nil {
		t.Fatal(err)
	}
	if len(records) != 2 {
		t.Fatalf("fixture relay records=%d, want 2", len(records))
	}
	lostAccept, lostBytes := records[0], records[1]
	lostBytes.HostToGuest = 0
	jsonl(t, directory, "firecracker-relay-g1.jsonl", []audit{lostAccept, lostBytes, records[0], records[1]})
}

func fixtureArtifact(name string, data []byte) artifact {
	digest := sha256.Sum256(data)
	return artifact{Name: name, Size: int64(len(data)), Mode: 0o400, SHA256: fmt.Sprintf("%x", digest)}
}

func newcFixture(t *testing.T, init, request []byte) []byte {
	t.Helper()
	entries := []struct {
		name string
		mode uint32
		data []byte
	}{
		{"dev", 0040755, nil}, {"dev/console", 0020600, nil},
		{"init", 0100555, init}, {"proc", 0040555, nil},
		{"request.json", 0100444, request}, {"run", 0040755, nil},
		{"sys", 0040555, nil}, {"tmp", 0041777, nil}, {"TRAILER!!!", 0, nil},
	}
	var out []byte
	for inode, entry := range entries {
		header := fmt.Sprintf(
			"070701%08x%08x%08x%08x%08x%08x%08x%08x%08x%08x%08x%08x%08x",
			inode+1, entry.mode, 0, 0, 1, 0, len(entry.data), 0, 0, 0, 0, len(entry.name)+1, 0,
		)
		out = append(out, header...)
		out = append(out, entry.name...)
		out = append(out, 0)
		for len(out)%4 != 0 {
			out = append(out, 0)
		}
		out = append(out, entry.data...)
		for len(out)%4 != 0 {
			out = append(out, 0)
		}
	}
	for len(out)%512 != 0 {
		out = append(out, 0)
	}
	return out
}
func call(seq uint64, method, path, req string, status int, response string) apiCall {
	c := apiCall{Sequence: seq, TimeNS: int64(seq), Method: method, Path: path, Status: status}
	if req != "" {
		c.Request = json.RawMessage(req)
	}
	if response != "" {
		c.Response = json.RawMessage(response)
	}
	return c
}
func write(t *testing.T, d, name string, v any) {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(d, name), b, 0o600); err != nil {
		t.Fatal(err)
	}
}
func jsonl(t *testing.T, d, name string, v any) {
	t.Helper()
	values := reflect.ValueOf(v)
	var output []byte
	if values.Kind() == reflect.Slice {
		for index := 0; index < values.Len(); index++ {
			encoded, err := json.Marshal(values.Index(index).Interface())
			if err != nil {
				t.Fatal(err)
			}
			output = append(output, encoded...)
			output = append(output, '\n')
		}
	} else {
		encoded, err := json.Marshal(v)
		if err != nil {
			t.Fatal(err)
		}
		output = append(output, encoded...)
		output = append(output, '\n')
	}
	if err := os.WriteFile(filepath.Join(d, name), output, 0o600); err != nil {
		t.Fatal(err)
	}
}
func replace(t *testing.T, path, old, new string) {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(b), old) {
		t.Fatalf("%s lacks %q", path, old)
	}
	if err = os.WriteFile(path, []byte(strings.Replace(string(b), old, new, 1)), 0o600); err != nil {
		t.Fatal(err)
	}
}
