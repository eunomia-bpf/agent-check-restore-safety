package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type fixture struct {
	opts        options
	workspace   string
	guestBinary []byte
	result      resultRecord
}

func TestVerifyAcceptsCompleteIndependentEvidence(t *testing.T) {
	f := newFixture(t)
	if err := verify(f.opts); err != nil {
		t.Fatalf("valid fixture rejected: %v", err)
	}
}

func TestVerifyAcceptsCrossDirectionBridgeAuditOverlap(t *testing.T) {
	f := newFixture(t)
	adapterPath := f.opts.adapterJSONL
	adapterLines := bytes.Split(bytes.TrimSpace(mustRead(t, adapterPath)), []byte{'\n'})
	input := map[string]any{
		"sequence": 2, "time_ns": 600, "direction": "client_to_server",
		"payload": map[string]any{"id": 42, "method": "preflight/ping", "params": map[string]any{}},
	}
	for index := 1; index < len(adapterLines); index++ {
		var record map[string]any
		mustJSON(t, adapterLines[index], &record)
		record["sequence"] = index + 2
		adapterLines[index] = mustMarshal(t, record)
	}
	adapterLines = append(adapterLines[:1], append([][]byte{mustMarshal(t, input)}, adapterLines[1:]...)...)
	mustWrite(t, adapterPath, append(bytes.Join(adapterLines, []byte{'\n'}), '\n'), 0o600)

	bridgePath := filepath.Join(f.opts.evidence, "bridge-io.jsonl")
	bridgeLines := bytes.Split(bytes.TrimSpace(mustRead(t, bridgePath)), []byte{'\n'})
	canonical := mustMarshal(t, input["payload"])
	overlapped := map[string]any{
		"schema": 1, "sequence": 2, "phase": "observed", "direction": "client_to_server",
		"time_ns": 642, "canonical_size": len(canonical), "canonical_sha256": hashBytes(canonical),
	}
	for index := 1; index < len(bridgeLines); index++ {
		var record map[string]any
		mustJSON(t, bridgeLines[index], &record)
		record["sequence"] = index + 2
		bridgeLines[index] = mustMarshal(t, record)
	}
	bridgeLines = append(bridgeLines[:1], append([][]byte{mustMarshal(t, overlapped)}, bridgeLines[1:]...)...)
	mustWrite(t, bridgePath, append(bytes.Join(bridgeLines, []byte{'\n'}), '\n'), 0o600)
	refreshRetainedArtifact(t, f, "bridge_io", "bridge-io.jsonl")
	if err := verify(f.opts); err != nil {
		t.Fatalf("valid cross-direction overlap rejected: %v", err)
	}
}

func TestVerifyRejectsMutations(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*testing.T, *fixture)
	}{
		{"result duplicate field", func(t *testing.T, f *fixture) {
			path := filepath.Join(f.opts.evidence, "result.json")
			data := mustRead(t, path)
			data = bytes.Replace(data, []byte(`"schema":1`), []byte(`"schema":1,"schema":1`), 1)
			mustWrite(t, path, data, 0o600)
		}},
		{"result unknown field", func(t *testing.T, f *fixture) {
			mutateObject(t, filepath.Join(f.opts.evidence, "result.json"), func(x map[string]any) { x["trust_me"] = true })
		}},
		{"result missing field", func(t *testing.T, f *fixture) {
			mutateObject(t, filepath.Join(f.opts.evidence, "result.json"), func(x map[string]any) { delete(x, "checkpoint") })
		}},
		{"missing runner", func(t *testing.T, f *fixture) { f.opts.runner = "" }},
		{"runner is not executable", func(t *testing.T, f *fixture) {
			if err := os.Chmod(f.opts.runner, 0o400); err != nil {
				t.Fatal(err)
			}
		}},
		{"runner is a symlink", func(t *testing.T, f *fixture) {
			link := filepath.Join(filepath.Dir(f.opts.runner), "runner-link")
			if err := os.Symlink(f.opts.runner, link); err != nil {
				t.Fatal(err)
			}
			f.opts.runner = link
		}},
		{"runner bytes changed", func(t *testing.T, f *fixture) {
			mustRewriteExecutable(t, f.opts.runner, []byte("changed-runner"))
		}},
		{"runner bytes and result rebound but event stale", func(t *testing.T, f *fixture) {
			changed := []byte("changed-and-rebound-runner")
			mustRewriteExecutable(t, f.opts.runner, changed)
			mustWrite(t, filepath.Join(f.opts.evidence, "runner"), changed, 0o600)
			changedHash := hashBytes(changed)
			mutateObject(t, filepath.Join(f.opts.evidence, "result.json"), func(x map[string]any) {
				x["runner_sha256"] = changedHash
				runner := x["artifacts"].(map[string]any)["runner"].(map[string]any)
				runner["name"], runner["size"], runner["mode"], runner["sha256"] = "runner", len(changed), 0o600, changedHash
			})
		}},
		{"run-started runner differs from result with event artifact rebound", func(t *testing.T, f *fixture) {
			mutateEvent(t, f, 0, func(x map[string]any) {
				x["details"].(map[string]any)["runner_sha256"] = strings.Repeat("0", 64)
			})
		}},
		{"result runner differs from artifact and executable", func(t *testing.T, f *fixture) {
			mutateObject(t, filepath.Join(f.opts.evidence, "result.json"), func(x map[string]any) {
				x["runner_sha256"] = strings.Repeat("f", 64)
			})
		}},
		{"payload byte changed", func(t *testing.T, f *fixture) { mustWrite(t, f.opts.payload, []byte("changed payload"), 0o600) }},
		{"payload manifest digest changed", func(t *testing.T, f *fixture) {
			mutateObject(t, f.opts.payloadResult, func(x map[string]any) { x["payload"].(map[string]any)["manifest_sha256"] = strings.Repeat("0", 64) })
		}},
		{"payload Codex record changed", func(t *testing.T, f *fixture) {
			mutateObject(t, f.opts.payloadResult, func(x map[string]any) { x["codex"].(map[string]any)["sha256"] = strings.Repeat("1", 64) })
		}},
		{"snapshot retained bytes changed", func(t *testing.T, f *fixture) {
			mustWrite(t, filepath.Join(f.opts.evidence, "snapshot.memory"), []byte("tampered"), 0o600)
		}},
		{"initramfs mode changed with hashes rebound", func(t *testing.T, f *fixture) {
			archive := buildTestInitramfs(t, f.guestBinary, mustRead(t, filepath.Join(f.opts.evidence, "guest-config.json")), 0o100444)
			mustWrite(t, filepath.Join(f.opts.evidence, "guest-initramfs.cpio"), archive, 0o600)
			rebindInitramfs(t, f, archive)
		}},
		{"process identity reused", func(t *testing.T, f *fixture) {
			mutateObject(t, filepath.Join(f.opts.evidence, "result.json"), func(x map[string]any) {
				ps := x["processes"].([]any)
				g1 := ps[0].(map[string]any)
				g3 := ps[1].(map[string]any)
				g3["pid"] = g1["pid"]
				g3["start_time_ticks"] = g1["start_time_ticks"]
			})
		}},
		{"event lifecycle reordered with artifact rebound", func(t *testing.T, f *fixture) {
			path := filepath.Join(f.opts.evidence, "events.jsonl")
			lines := bytes.Split(bytes.TrimSuffix(mustRead(t, path), []byte{'\n'}), []byte{'\n'})
			lines[7], lines[8] = lines[8], lines[7]
			for i := range lines {
				var x map[string]any
				mustJSON(t, lines[i], &x)
				x["sequence"] = i + 1
				lines[i] = mustMarshal(t, x)
			}
			mustWrite(t, path, append(bytes.Join(lines, []byte{'\n'}), '\n'), 0o600)
			refreshRetainedArtifact(t, f, "events", "events.jsonl")
		}},
		{"event unknown detail", func(t *testing.T, f *fixture) {
			mutateEvent(t, f, 4, func(x map[string]any) { x["details"].(map[string]any)["other"] = 1 })
		}},
		{"payload drive writable", func(t *testing.T, f *fixture) {
			mutateJSONLRecord(t, filepath.Join(f.opts.evidence, "firecracker-api-g1.jsonl"), 4, func(x map[string]any) { x["request"].(map[string]any)["is_read_only"] = false })
		}},
		{"snapshot load resumes", func(t *testing.T, f *fixture) {
			mutateJSONLRecord(t, filepath.Join(f.opts.evidence, "firecracker-api-g3.jsonl"), 1, func(x map[string]any) { x["request"].(map[string]any)["resume_vm"] = true })
		}},
		{"snapshot load pathname instead of fd", func(t *testing.T, f *fixture) {
			mutateJSONLRecord(t, filepath.Join(f.opts.evidence, "firecracker-api-g3.jsonl"), 1, func(x map[string]any) {
				x["request"].(map[string]any)["snapshot_path"] = filepath.Join(f.opts.evidence, "snapshot.state")
			})
		}},
		{"relay Firecracker PID changed", func(t *testing.T, f *fixture) {
			mutateJSONLRecord(t, filepath.Join(f.opts.evidence, "firecracker-relay-g1.jsonl"), 0, func(x map[string]any) { x["pid"] = 99999 })
		}},
		{"g1 model traffic crosses checkpoint", func(t *testing.T, f *fixture) {
			mutateJSONLRecord(t, filepath.Join(f.opts.evidence, "firecracker-relay-g1.jsonl"), 1, func(x map[string]any) { x["time"] = time.Unix(0, 710).UTC() })
		}},
		{"proxy byte record removed", func(t *testing.T, f *fixture) {
			path := filepath.Join(f.opts.evidence, "model-proxy.jsonl")
			lines := bytes.Split(bytes.TrimSpace(mustRead(t, path)), []byte{'\n'})
			mustWrite(t, path, append(bytes.Join(lines[:len(lines)-1], []byte{'\n'}), '\n'), 0o600)
		}},
		{"bridge callback commitment changed with artifact rebound", func(t *testing.T, f *fixture) {
			path := filepath.Join(f.opts.evidence, "bridge-io.jsonl")
			mutateJSONLRecord(t, path, 2, func(x map[string]any) { x["canonical_sha256"] = strings.Repeat("0", 64) })
			mutateJSONLRecord(t, path, 3, func(x map[string]any) { x["canonical_sha256"] = strings.Repeat("0", 64) })
			refreshRetainedArtifact(t, f, "bridge_io", "bridge-io.jsonl")
		}},
		{"bridge callback precedes runtime authorization with artifact rebound", func(t *testing.T, f *fixture) {
			path := filepath.Join(f.opts.evidence, "bridge-io.jsonl")
			mutateJSONLRecord(t, path, 2, func(x map[string]any) { x["time_ns"] = 1850 })
			mutateJSONLRecord(t, path, 3, func(x map[string]any) { x["time_ns"] = 1860 })
			refreshRetainedArtifact(t, f, "bridge_io", "bridge-io.jsonl")
		}},
		{"bridge delivery removed with artifact rebound", func(t *testing.T, f *fixture) {
			path := filepath.Join(f.opts.evidence, "bridge-io.jsonl")
			lines := bytes.Split(bytes.TrimSpace(mustRead(t, path)), []byte{'\n'})
			lines = append(lines[:3], lines[4:]...)
			for index := 3; index < len(lines); index++ {
				var record map[string]any
				mustJSON(t, lines[index], &record)
				record["sequence"] = index + 1
				lines[index] = mustMarshal(t, record)
			}
			mustWrite(t, path, append(bytes.Join(lines, []byte{'\n'}), '\n'), 0o600)
			refreshRetainedArtifact(t, f, "bridge_io", "bridge-io.jsonl")
		}},
		{"protected turn delivered after session completion with artifact rebound", func(t *testing.T, f *fixture) {
			path := filepath.Join(f.opts.evidence, "bridge-io.jsonl")
			mutateJSONLRecord(t, path, 8, func(x map[string]any) { x["time_ns"] = 2110 })
			refreshRetainedArtifact(t, f, "bridge_io", "bridge-io.jsonl")
		}},
		{"adapter nested duplicate", func(t *testing.T, f *fixture) {
			path := f.opts.adapterJSONL
			data := mustRead(t, path)
			data = bytes.Replace(data, []byte(`"method":"item/tool/call"`), []byte(`"method":"item/tool/call","method":"item/tool/call"`), 1)
			mustWrite(t, path, data, 0o600)
		}},
		{"adapter nonzero process exit", func(t *testing.T, f *fixture) {
			mutateJSONLRecord(t, f.opts.adapterJSONL, 6, func(x map[string]any) { x["payload"].(map[string]any)["returncode"] = 1 })
		}},
		{"dynamic tool completion identity changed", func(t *testing.T, f *fixture) {
			mutateJSONLRecord(t, f.opts.adapterJSONL, 4, func(x map[string]any) {
				x["payload"].(map[string]any)["params"].(map[string]any)["item"].(map[string]any)["id"] = "other-call"
			})
		}},
		{"adapter call exposed before g3 attach", func(t *testing.T, f *fixture) {
			mutateJSONLRecord(t, f.opts.adapterJSONL, 2, func(x map[string]any) { x["time_ns"] = 1750 })
		}},
		{"adapter response precedes call", func(t *testing.T, f *fixture) {
			path := f.opts.adapterJSONL
			lines := bytes.Split(bytes.TrimSuffix(mustRead(t, path), []byte{'\n'}), []byte{'\n'})
			var response, call map[string]any
			mustJSON(t, lines[3], &response)
			mustJSON(t, lines[2], &call)
			response["sequence"], response["time_ns"] = 3, 1805
			call["sequence"], call["time_ns"] = 4, 1810
			lines[2], lines[3] = mustMarshal(t, response), mustMarshal(t, call)
			mustWrite(t, path, append(bytes.Join(lines, []byte{'\n'}), '\n'), 0o600)
		}},
		{"second tool call exposed", func(t *testing.T, f *fixture) {
			path := f.opts.adapterJSONL
			lines := bytes.Split(bytes.TrimSpace(mustRead(t, path)), []byte{'\n'})
			var extra map[string]any
			mustJSON(t, lines[2], &extra)
			extra["sequence"] = 4
			extra["time_ns"] = 1940
			for index := 3; index < len(lines); index++ {
				var record map[string]any
				mustJSON(t, lines[index], &record)
				record["sequence"] = index + 2
				lines[index] = mustMarshal(t, record)
			}
			lines = append(lines[:3], append([][]byte{mustMarshal(t, extra)}, lines[3:]...)...)
			mustWrite(t, path, append(bytes.Join(lines, []byte{'\n'}), '\n'), 0o600)
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			f := newFixture(t)
			test.mutate(t, f)
			if err := verify(f.opts); err == nil {
				t.Fatal("mutated evidence was accepted")
			}
		})
	}
}

func TestValidatePinnedGuestArgumentsRejectsAuthorityExpansion(t *testing.T) {
	valid := pinnedArguments("http://127.0.0.1:12345/v1")
	if target, err := validatePinnedGuestArguments(valid, 12345); err != nil || target != "127.0.0.1:12345" {
		t.Fatalf("valid pinned arguments = %q, %v", target, err)
	}
	tests := []struct {
		name string
		port uint32
		edit func([]string) []string
	}{
		{"guest port mismatch", 12346, func(args []string) []string { return args }},
		{"extra option", 12345, func(args []string) []string { return append(args, "--dangerously-bypass-approvals-and-sandbox") }},
		{"auth enabled", 12345, func(args []string) []string {
			args[7] = strings.Replace(args[7], "requires_openai_auth=false", "requires_openai_auth=true", 1)
			return args
		}},
		{"duplicate base url", 12345, func(args []string) []string { return append(args, "-c", `base_url="http://127.0.0.1:12345/v1"`) }},
		{"query authority", 12345, func(args []string) []string {
			args[7] = strings.Replace(args[7], "/v1\"", "/v1?token=x\"", 1)
			return args
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			arguments := append([]string(nil), valid...)
			if _, err := validatePinnedGuestArguments(test.edit(arguments), test.port); err == nil {
				t.Fatal("authority-expanding arguments were accepted")
			}
		})
	}
}

func TestParseNewcRejectsMetadataAndPaddingMutations(t *testing.T) {
	config := []byte(`{"schema":1}`)
	archive := buildTestInitramfs(t, []byte("guest"), config, 0o100400)
	for _, test := range []struct {
		name   string
		mutate func([]byte)
	}{
		{"magic", func(x []byte) { x[0] = '1' }},
		{"name padding", func(x []byte) { x[114] = 1 }},
		{"trailer padding", func(x []byte) { x[len(x)-1] = 1 }},
	} {
		t.Run(test.name, func(t *testing.T) {
			changed := append([]byte(nil), archive...)
			test.mutate(changed)
			if _, err := parseNewc(changed); err == nil {
				t.Fatal("mutated newc accepted")
			}
		})
	}
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	root := t.TempDir()
	evidence := filepath.Join(root, "evidence")
	adapterDir := filepath.Join(root, "adapter")
	payloadDir := filepath.Join(root, "payload")
	runnerDir := filepath.Join(root, "runner")
	workspace := filepath.Join(root, "workspace")
	for _, path := range []string{evidence, adapterDir, payloadDir, runnerDir, workspace} {
		if err := os.Mkdir(path, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	f := &fixture{workspace: workspace, guestBinary: []byte("static-guest-binary")}
	f.opts = options{evidence: evidence, adapterJSONL: filepath.Join(adapterDir, "app-server.jsonl"), payload: filepath.Join(payloadDir, "codex.squashfs"), payloadResult: filepath.Join(payloadDir, "payload.json"), runner: filepath.Join(runnerDir, "firecracker-codex-shim")}
	runnerBytes := []byte("retained-firecracker-codex-shim")
	mustWrite(t, f.opts.runner, runnerBytes, 0o500)
	mustWrite(t, filepath.Join(evidence, "runner"), runnerBytes, 0o600)
	payloadBytes := []byte("deterministic-squashfs-image")
	mustWrite(t, f.opts.payload, payloadBytes, 0o600)
	codexBytes := []byte("native-codex-binary")
	codex := manifestEntry{Path: "bin/codex", Type: "file", Mode: 0o755, Size: int64(len(codexBytes)), SHA256: hashBytes(codexBytes)}
	manifestValue := manifest{Schema: 1, Entries: []manifestEntry{{Path: ".", Type: "directory", Mode: 0o755}, {Path: "bin", Type: "directory", Mode: 0o755}, codex}}
	manifestJSON := mustMarshal(t, manifestValue)
	payload := payloadRecord{Schema: 1, Payload: payloadBuild{ImagePath: f.opts.payload, ImageSHA256: hashBytes(payloadBytes), ImageSize: int64(len(payloadBytes)), Manifest: manifestValue, ManifestSHA256: hashBytes(manifestJSON)}, Codex: codex}
	writeJSON(t, f.opts.payloadResult, payload)

	session := strings.Repeat("1", 32)
	args := pinnedArguments("http://127.0.0.1:12345/v1")
	guest := guestConfig{Schema: 1, SessionID: session, CodexSHA256: codex.SHA256, Arguments: args, StreamPort: 7000, ModelPort: 12345, PayloadDrive: "/dev/vda"}
	configBytes := mustMarshal(t, guest)
	mustWrite(t, filepath.Join(evidence, "guest-config.json"), configBytes, 0o600)
	initramfs := buildTestInitramfs(t, f.guestBinary, configBytes, 0o100400)
	mustWrite(t, filepath.Join(evidence, "guest-initramfs.cpio"), initramfs, 0o600)
	mustWrite(t, filepath.Join(evidence, "snapshot.state"), []byte("snapshot-state"), 0o600)
	mustWrite(t, filepath.Join(evidence, "snapshot.memory"), []byte("snapshot-memory"), 0o600)

	state := transcriptState{HostToGuest: position{Offset: 1, Bytes: 10, Hash: hashBytes([]byte("host-log\n"))}, GuestToHost: position{Offset: 1, Bytes: 11, Hash: hashBytes([]byte("guest-log\n"))}}
	barrierValue := barrier{SessionID: session, Generation: 1, State: state}
	checkpointValue := checkpoint{HostBarrier: barrierValue, GuestBarrier: barrierValue}
	artifacts := map[string]artifact{
		"kernel":          {Name: "kernel", Size: 100, Mode: 0o400, SHA256: hashBytes([]byte("kernel"))},
		"payload":         {Name: "payload", Size: int64(len(payloadBytes)), Mode: 0o400, SHA256: hashBytes(payloadBytes)},
		"guest":           {Name: "guest", Size: int64(len(f.guestBinary)), Mode: 0o400, SHA256: hashBytes(f.guestBinary)},
		"guest_config":    artifactFromBytes("guest-config.json", configBytes, 0o600),
		"initramfs":       artifactFromBytes("guest-initramfs.cpio", initramfs, 0o600),
		"firecracker":     {Name: "firecracker", Size: 1000, Mode: 0o755, SHA256: hashBytes([]byte("firecracker"))},
		"runner":          artifactFromBytes("runner", runnerBytes, 0o600),
		"snapshot_state":  artifactFromBytes("snapshot.state", []byte("snapshot-state"), 0o600),
		"snapshot_memory": artifactFromBytes("snapshot.memory", []byte("snapshot-memory"), 0o600),
	}
	boot := []sealedArtifact{
		{Artifact: artifacts["kernel"], ChildFD: 4, LinuxSeals: 15},
		{Artifact: artifact{Name: "runtime-initramfs", Size: artifacts["initramfs"].Size, Mode: 0o400, SHA256: artifacts["initramfs"].SHA256}, ChildFD: 5, LinuxSeals: 15},
		{Artifact: artifacts["payload"], ChildFD: 6, LinuxSeals: 15},
	}
	load := []sealedArtifact{
		{Artifact: artifact{Name: "snapshot-state", Size: artifacts["snapshot_state"].Size, Mode: 0o400, SHA256: artifacts["snapshot_state"].SHA256}, ChildFD: 4, LinuxSeals: 15},
		{Artifact: artifact{Name: "snapshot-memory", Size: artifacts["snapshot_memory"].Size, Mode: 0o400, SHA256: artifacts["snapshot_memory"].SHA256}, ChildFD: 5, LinuxSeals: 15},
		{Artifact: artifacts["payload"], ChildFD: 6, LinuxSeals: 15},
	}
	g1 := testProcess(evidence, 1, "g1-instance", 101, 10, 350, 1050, artifacts["firecracker"].SHA256)
	g3 := testProcess(evidence, 3, "g3-instance", 202, 20, 1350, 2150, artifacts["firecracker"].SHA256)
	f.result = resultRecord{Schema: 1, Success: true, SessionID: session, CodexSHA256: codex.SHA256, RunnerSHA256: artifacts["runner"].SHA256, ArgumentsSHA256: hashBytes(mustMarshal(t, args)), ArgumentsEncoding: "compact-json-array", ArgumentsCount: len(args), WorkspaceMapping: workspaceMapping{Host: workspace, Guest: "/workspace"}, Artifacts: artifacts, SealedBootInputs: boot, SealedLoadInputs: load, Checkpoint: checkpointValue, Processes: []processRecord{g1, g3}, G1SIGKILLConfirmed: true, SnapshotLoadedPaused: true, RelayArmedBeforeResume: true, ToolReleasedAfterAttach: true, CompletedTimeNS: 2250}
	writeFixtureEvents(t, f)
	writeFixtureAPI(t, f)
	writeFixtureTransport(t, f)
	writeFixtureAdapter(t, f)
	writeFixtureBridge(t, f)
	for key, name := range map[string]string{
		"bridge_io": "bridge-io.jsonl", "events": "events.jsonl",
		"firecracker_api_g1": "firecracker-api-g1.jsonl", "firecracker_api_g3": "firecracker-api-g3.jsonl",
		"firecracker_relay_g1": "firecracker-relay-g1.jsonl", "firecracker_relay_g3": "firecracker-relay-g3.jsonl",
		"model_proxy": "model-proxy.jsonl",
	} {
		data := mustRead(t, filepath.Join(evidence, name))
		f.result.Artifacts[key] = artifactFromBytes(name, data, 0o600)
	}
	writeResult(t, f)
	return f
}

func testProcess(evidence string, generation uint64, id string, pid int, startTicks uint64, started, stopped int64, hash string) processRecord {
	label := fmt.Sprintf("g%d", generation)
	return processRecord{Generation: generation, ID: id, PID: pid, Executable: "/usr/bin/firecracker", ExecutableSHA256: hash, Device: 1, Inode: uint64(900 + generation), StartTimeTicks: startTicks, VMMVersion: "1.16.1", StartedTimeNS: started, StoppedTimeNS: stopped, Termination: "supervisor", APISocket: socketRecord{Path: filepath.Join(evidence, "api-"+label+".sock"), Device: uint64(100 + generation), Inode: uint64(200 + generation), Mode: 0o600, UID: uint32(os.Geteuid())}, VsockBackend: socketRecord{Path: filepath.Join(evidence, "vsock-"+label), Device: uint64(300 + generation), Inode: uint64(400 + generation), Mode: 0o600, UID: uint32(os.Geteuid())}}
}

func writeFixtureEvents(t *testing.T, f *fixture) {
	t.Helper()
	r := f.result
	guest := sealedArtifact{Artifact: r.Artifacts["guest"], ChildFD: 0, LinuxSeals: 15}
	details := []any{
		map[string]any{"session_id": r.SessionID, "g1_id": r.Processes[0].ID, "g3_id": r.Processes[1].ID, "codex_sha256": r.CodexSHA256, "runner_sha256": r.RunnerSHA256, "arguments_sha256": r.ArgumentsSHA256, "workspace_mapping": r.WorkspaceMapping},
		map[string]any{"kernel": r.SealedBootInputs[0], "payload": r.SealedBootInputs[2], "guest": guest, "initramfs": r.SealedBootInputs[1]},
		map[string]any{"target": "127.0.0.1:12345", "socket": filepath.Join(f.opts.evidence, "model-proxy.sock")},
		nil, map[string]any{"stream_port": 7000, "model_port": 12345}, nil,
		map[string]any{"host_barrier": r.Checkpoint.HostBarrier, "guest_barrier": r.Checkpoint.GuestBarrier}, nil, nil,
		map[string]any{"state": r.Artifacts["snapshot_state"], "memory": r.Artifacts["snapshot_memory"]},
		map[string]any{"disposition": "supervisor"},
		map[string]any{"state": r.SealedLoadInputs[0], "memory": r.SealedLoadInputs[1]},
		map[string]any{"generation": 3}, nil,
		map[string]any{"state_sha256": r.Artifacts["snapshot_state"].SHA256, "memory_sha256": r.Artifacts["snapshot_memory"].SHA256},
		map[string]any{"stream_port": 7000, "model_port": 12345}, nil, nil, nil, nil, nil, map[string]any{"error": ""},
	}
	var lines [][]byte
	for index, want := range expectedEvents {
		x := map[string]any{"schema": 1, "sequence": index + 1, "event": want.name, "time_ns": int64((index + 1) * 100)}
		if want.generation != 0 {
			p := r.Processes[0]
			if want.generation == 3 {
				p = r.Processes[1]
			}
			x["generation"] = want.generation
			x["instance_id"] = p.ID
			x["pid"] = p.PID
		}
		if want.details {
			x["details"] = details[index]
		}
		lines = append(lines, mustMarshal(t, x))
	}
	mustWrite(t, filepath.Join(f.opts.evidence, "events.jsonl"), append(bytes.Join(lines, []byte{'\n'}), '\n'), 0o600)
}

func writeFixtureAPI(t *testing.T, f *fixture) {
	g1 := f.result.Processes[0]
	g3 := f.result.Processes[1]
	state := func(p processRecord, value string) map[string]any {
		return map[string]any{"app_name": "Firecracker", "id": p.ID, "state": value, "vmm_version": p.VMMVersion}
	}
	g1Calls := []map[string]any{
		apiResponse(1, 360, "GET", "/", 200, state(g1, "Not started")),
		apiRequest(2, 410, "PUT", "/machine-config", 204, map[string]any{"vcpu_count": 1, "mem_size_mib": 1024, "smt": false, "track_dirty_pages": false}),
		apiRequest(3, 420, "PUT", "/boot-source", 204, map[string]any{"kernel_image_path": fdKernel, "boot_args": "console=ttyS0 reboot=k panic=1 pci=off rdinit=/init", "initrd_path": fdInitramfs}),
		apiRequest(4, 430, "PUT", "/vsock", 204, map[string]any{"guest_cid": 3, "uds_path": g1.VsockBackend.Path}),
		apiRequest(5, 440, "PUT", "/drives/payload", 204, map[string]any{"drive_id": "payload", "path_on_host": fdPayload, "is_root_device": false, "is_read_only": true}),
		apiRequest(6, 510, "PUT", "/actions", 204, map[string]any{"action_type": "InstanceStart"}),
		apiResponse(7, 550, "GET", "/", 200, state(g1, "Running")),
		apiRequest(8, 810, "PATCH", "/vm", 204, map[string]any{"state": "Paused"}),
		apiResponse(9, 850, "GET", "/", 200, state(g1, "Paused")),
		apiRequest(10, 950, "PUT", "/snapshot/create", 204, map[string]any{"snapshot_type": "Full", "snapshot_path": filepath.Join(f.opts.evidence, "snapshot.state"), "mem_file_path": filepath.Join(f.opts.evidence, "snapshot.memory")}),
	}
	g3Calls := []map[string]any{
		apiResponse(1, 1360, "GET", "/", 200, state(g3, "Not started")),
		apiRequest(2, 1410, "PUT", "/snapshot/load", 204, map[string]any{"snapshot_path": fdKernel, "mem_backend": map[string]any{"backend_type": "File", "backend_path": fdInitramfs}, "resume_vm": false, "vsock_override": map[string]any{"uds_path": g3.VsockBackend.Path}}),
		apiResponse(3, 1450, "GET", "/", 200, state(g3, "Paused")),
		apiRequest(4, 1610, "PATCH", "/vm", 204, map[string]any{"state": "Resumed"}),
		apiResponse(5, 1650, "GET", "/", 200, state(g3, "Running")),
	}
	writeJSONLMaps(t, filepath.Join(f.opts.evidence, "firecracker-api-g1.jsonl"), g1Calls)
	writeJSONLMaps(t, filepath.Join(f.opts.evidence, "firecracker-api-g3.jsonl"), g3Calls)
}

func apiRequest(sequence int, timeNS int64, method, path string, status int, request any) map[string]any {
	return map[string]any{"sequence": sequence, "time_ns": timeNS, "method": method, "path": path, "request": request, "status": status}
}
func apiResponse(sequence int, timeNS int64, method, path string, status int, response any) map[string]any {
	return map[string]any{"sequence": sequence, "time_ns": timeNS, "method": method, "path": path, "status": status, "response": response}
}

func writeFixtureTransport(t *testing.T, f *fixture) {
	device, inode := uint64(88), uint64(99)
	shimPID := 4242
	relay := func(generation uint64, pid int, left, right, startNS int64) []map[string]any {
		return []map[string]any{
			{"event": "accept", "time": time.Unix(0, startNS).UTC(), "generation": generation, "port": 12345, "pid": pid, "sandbox_device": device, "sandbox_inode": inode, "guest_to_host_bytes": 0, "host_to_guest_bytes": 0},
			{"event": "bytes", "time": time.Unix(0, startNS+10).UTC(), "generation": generation, "port": 12345, "sandbox_peer_pid": shimPID, "sandbox_device": device, "sandbox_inode": inode, "guest_to_host_bytes": left, "host_to_guest_bytes": right},
		}
	}
	writeJSONLMaps(t, filepath.Join(f.opts.evidence, "firecracker-relay-g1.jsonl"), relay(1, 101, 100, 200, 610))
	writeJSONLMaps(t, filepath.Join(f.opts.evidence, "firecracker-relay-g3.jsonl"), relay(3, 202, 300, 400, 2010))
	proxy := []map[string]any{
		{"event": "accept", "time": time.Unix(0, 610).UTC(), "target": "127.0.0.1:12345", "pid": shimPID, "uid": os.Geteuid(), "gid": os.Getegid(), "socket_device": device, "socket_inode": inode, "client_to_target_bytes": 0, "target_to_client_bytes": 0},
		{"event": "bytes", "time": time.Unix(0, 620).UTC(), "target": "127.0.0.1:12345", "pid": 0, "uid": 0, "gid": 0, "socket_device": device, "socket_inode": inode, "client_to_target_bytes": 100, "target_to_client_bytes": 200},
		{"event": "accept", "time": time.Unix(0, 2010).UTC(), "target": "127.0.0.1:12345", "pid": shimPID, "uid": os.Geteuid(), "gid": os.Getegid(), "socket_device": device, "socket_inode": inode, "client_to_target_bytes": 0, "target_to_client_bytes": 0},
		{"event": "bytes", "time": time.Unix(0, 2020).UTC(), "target": "127.0.0.1:12345", "pid": 0, "uid": 0, "gid": 0, "socket_device": device, "socket_inode": inode, "client_to_target_bytes": 300, "target_to_client_bytes": 400},
	}
	writeJSONLMaps(t, filepath.Join(f.opts.evidence, "model-proxy.jsonl"), proxy)
}

func writeFixtureAdapter(t *testing.T, f *fixture) {
	var guest guestConfig
	mustJSON(t, mustRead(t, filepath.Join(f.opts.evidence, "guest-config.json")), &guest)
	call := map[string]any{"id": 7, "method": "item/tool/call", "params": map[string]any{"arguments": map[string]any{"effect_id": "preflight-effect-1"}, "callId": "preflight-call-1", "namespace": nil, "threadId": "thread-1", "tool": "protected_commit", "turnId": "turn-1"}}
	response := map[string]any{"id": 7, "result": map[string]any{"contentItems": []any{map[string]any{"type": "inputText", "text": "receipt:preflight-effect-1"}}, "success": true}}
	startedItem := map[string]any{"arguments": map[string]any{"effect_id": "preflight-effect-1"}, "contentItems": nil, "durationMs": nil, "id": "preflight-call-1", "namespace": nil, "status": "inProgress", "success": nil, "tool": "protected_commit", "type": "dynamicToolCall"}
	completedItems := []any{map[string]any{"type": "inputText", "text": "receipt:preflight-effect-1"}}
	completedItem := map[string]any{"arguments": map[string]any{"effect_id": "preflight-effect-1"}, "contentItems": completedItems, "durationMs": 12, "id": "preflight-call-1", "namespace": nil, "status": "completed", "success": true, "tool": "protected_commit", "type": "dynamicToolCall"}
	command := append([]string{"/tmp/codex"}, guest.Arguments...)
	records := []map[string]any{
		{"sequence": 1, "time_ns": 50, "direction": "meta", "payload": map[string]any{"event": "process_start", "command": command}},
		{"sequence": 2, "time_ns": 650, "direction": "server_to_client", "payload": map[string]any{"method": "item/started", "params": map[string]any{"item": startedItem, "startedAtMs": 1, "threadId": "thread-1", "turnId": "turn-1"}}},
		{"sequence": 3, "time_ns": 1930, "direction": "server_to_client", "payload": call},
		{"sequence": 4, "time_ns": 2020, "direction": "client_to_server", "payload": response},
		{"sequence": 5, "time_ns": 2030, "direction": "server_to_client", "payload": map[string]any{"method": "item/completed", "params": map[string]any{"completedAtMs": 2, "item": completedItem, "threadId": "thread-1", "turnId": "turn-1"}}},
		{"sequence": 6, "time_ns": 2050, "direction": "server_to_client", "payload": map[string]any{"method": "turn/completed", "params": map[string]any{"threadId": "thread-1", "turn": map[string]any{"completedAt": 2, "durationMs": 1, "error": nil, "id": "turn-1", "items": []any{}, "itemsView": "summary", "startedAt": 1, "status": "completed"}}}},
		{"sequence": 7, "time_ns": 2300, "direction": "meta", "payload": map[string]any{"event": "process_stop", "returncode": 0}},
	}
	writeJSONLMaps(t, f.opts.adapterJSONL, records)
}

func writeFixtureBridge(t *testing.T, f *fixture) {
	t.Helper()
	lines := bytes.Split(bytes.TrimSpace(mustRead(t, f.opts.adapterJSONL)), []byte{'\n'})
	bridgeTime := []int64{640, 645, 1910, 1920, 2022, 2025, 2026, 2040, 2041}
	var records []map[string]any
	for _, line := range lines {
		var adapter rawAdapterRecord
		mustJSON(t, line, &adapter)
		if adapter.Direction != "client_to_server" && adapter.Direction != "server_to_client" {
			continue
		}
		canonical, err := canonicalJSONObject(adapter.Payload)
		if err != nil {
			t.Fatal(err)
		}
		appendRecord := func(phase string) {
			index := len(records)
			records = append(records, map[string]any{
				"schema": 1, "sequence": index + 1, "phase": phase, "direction": adapter.Direction,
				"time_ns": bridgeTime[index], "canonical_size": len(canonical), "canonical_sha256": hashBytes(canonical),
			})
		}
		if adapter.Direction == "client_to_server" {
			appendRecord("observed")
		} else {
			appendRecord("authorized")
			appendRecord("delivered")
		}
	}
	writeJSONLMaps(t, filepath.Join(f.opts.evidence, "bridge-io.jsonl"), records)
}

func writeResult(t *testing.T, f *fixture) {
	writeJSON(t, filepath.Join(f.opts.evidence, "result.json"), f.result)
}
func writeJSON(t *testing.T, path string, value any) {
	t.Helper()
	mustWrite(t, path, append(mustMarshal(t, value), '\n'), 0o600)
}
func writeJSONLMaps(t *testing.T, path string, values []map[string]any) {
	t.Helper()
	var lines [][]byte
	for _, value := range values {
		lines = append(lines, mustMarshal(t, value))
	}
	mustWrite(t, path, append(bytes.Join(lines, []byte{'\n'}), '\n'), 0o600)
}
func artifactFromBytes(name string, data []byte, mode uint32) artifact {
	return artifact{Name: name, Size: int64(len(data)), Mode: mode, SHA256: hashBytes(data)}
}

type testNewcEntry struct {
	name                 string
	mode                 uint32
	nlink                uint32
	rdevMajor, rdevMinor uint32
	data                 []byte
}

func buildTestInitramfs(t *testing.T, guest, config []byte, configMode uint32) []byte {
	t.Helper()
	entries := []testNewcEntry{
		{"dev", 0o040755, 2, 0, 0, nil}, {"dev/console", 0o020600, 1, 5, 1, nil}, {"init", 0o100555, 1, 0, 0, guest},
		{"proc", 0o040555, 2, 0, 0, nil}, {"sys", 0o040555, 2, 0, 0, nil}, {"run", 0o040755, 2, 0, 0, nil},
		{"tmp", 0o041777, 2, 0, 0, nil}, {"opt", 0o040555, 2, 0, 0, nil}, {"workspace", 0o040755, 2, 0, 0, nil},
		{"home", 0o040755, 2, 0, 0, nil}, {"config.json", configMode, 1, 0, 0, config},
	}
	var out bytes.Buffer
	for index, entry := range entries {
		writeTestNewc(t, &out, uint32(index+1), entry)
	}
	writeTestNewc(t, &out, uint32(len(entries)+1), testNewcEntry{name: "TRAILER!!!", nlink: 1})
	for out.Len()%512 != 0 {
		out.WriteByte(0)
	}
	return out.Bytes()
}

func writeTestNewc(t *testing.T, out *bytes.Buffer, inode uint32, entry testNewcEntry) {
	t.Helper()
	header := fmt.Sprintf("070701%08x%08x%08x%08x%08x%08x%08x%08x%08x%08x%08x%08x%08x", inode, entry.mode, 0, 0, entry.nlink, 0, len(entry.data), 0, 0, entry.rdevMajor, entry.rdevMinor, len(entry.name)+1, 0)
	if len(header) != 110 {
		t.Fatalf("newc header length %d", len(header))
	}
	out.WriteString(header)
	out.WriteString(entry.name)
	out.WriteByte(0)
	for out.Len()%4 != 0 {
		out.WriteByte(0)
	}
	out.Write(entry.data)
	for out.Len()%4 != 0 {
		out.WriteByte(0)
	}
}

func rebindInitramfs(t *testing.T, f *fixture, data []byte) {
	t.Helper()
	path := filepath.Join(f.opts.evidence, "result.json")
	var result map[string]any
	mustJSON(t, mustRead(t, path), &result)
	record := result["artifacts"].(map[string]any)["initramfs"].(map[string]any)
	record["size"] = len(data)
	record["sha256"] = hashBytes(data)
	boot := result["sealed_boot_inputs"].([]any)
	sealed := boot[1].(map[string]any)["artifact"].(map[string]any)
	sealed["size"] = len(data)
	sealed["sha256"] = hashBytes(data)
	mustWrite(t, path, append(mustMarshal(t, result), '\n'), 0o600)
	// Rebind the corresponding event and then the event artifact in result.
	mutateEvent(t, f, 1, func(x map[string]any) {
		init := x["details"].(map[string]any)["initramfs"].(map[string]any)["artifact"].(map[string]any)
		init["size"] = len(data)
		init["sha256"] = hashBytes(data)
	})
	refreshRetainedArtifact(t, f, "events", "events.jsonl")
}

func refreshRetainedArtifact(t *testing.T, f *fixture, key, name string) {
	t.Helper()
	resultPath := filepath.Join(f.opts.evidence, "result.json")
	var result map[string]any
	mustJSON(t, mustRead(t, resultPath), &result)
	data := mustRead(t, filepath.Join(f.opts.evidence, name))
	record := result["artifacts"].(map[string]any)[key].(map[string]any)
	record["size"] = len(data)
	record["sha256"] = hashBytes(data)
	mustWrite(t, resultPath, append(mustMarshal(t, result), '\n'), 0o600)
}

func mutateEvent(t *testing.T, f *fixture, index int, mutate func(map[string]any)) {
	t.Helper()
	path := filepath.Join(f.opts.evidence, "events.jsonl")
	lines := bytes.Split(bytes.TrimSuffix(mustRead(t, path), []byte{'\n'}), []byte{'\n'})
	var object map[string]any
	mustJSON(t, lines[index], &object)
	mutate(object)
	lines[index] = mustMarshal(t, object)
	mustWrite(t, path, append(bytes.Join(lines, []byte{'\n'}), '\n'), 0o600)
	refreshRetainedArtifact(t, f, "events", "events.jsonl")
}

func mutateJSONLRecord(t *testing.T, path string, index int, mutate func(map[string]any)) {
	t.Helper()
	lines := bytes.Split(bytes.TrimSuffix(mustRead(t, path), []byte{'\n'}), []byte{'\n'})
	if index < 0 || index >= len(lines) {
		t.Fatal("mutation index out of bounds")
	}
	var object map[string]any
	mustJSON(t, lines[index], &object)
	mutate(object)
	lines[index] = mustMarshal(t, object)
	mustWrite(t, path, append(bytes.Join(lines, []byte{'\n'}), '\n'), 0o600)
}

func mutateObject(t *testing.T, path string, mutate func(map[string]any)) {
	t.Helper()
	var object map[string]any
	mustJSON(t, mustRead(t, path), &object)
	mutate(object)
	mustWrite(t, path, append(mustMarshal(t, object), '\n'), 0o600)
}
func mustRead(t *testing.T, path string) []byte {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return data
}
func mustWrite(t *testing.T, path string, data []byte, mode os.FileMode) {
	t.Helper()
	if err := os.WriteFile(path, data, mode); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, mode); err != nil {
		t.Fatal(err)
	}
}

func mustRewriteExecutable(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.Chmod(path, 0o700); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, path, data, 0o500)
}
func mustMarshal(t *testing.T, value any) []byte {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return data
}
func mustJSON(t *testing.T, data []byte, target any) {
	t.Helper()
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	if err := decoder.Decode(target); err != nil {
		t.Fatal(err)
	}
}
