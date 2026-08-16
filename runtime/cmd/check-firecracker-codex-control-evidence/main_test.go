package main

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type testFixture struct {
	options options
	adapter adapterResult
	events  []storedEvent
	payment paymentRecord
}

func TestVerifyJoinsVMHistoryAndExternalCommit(t *testing.T) {
	fixture := newTestFixture(t)
	got, err := verify(fixture.options)
	if err != nil {
		t.Fatal(err)
	}
	if !got.Valid || got.HistorySequence != 5 || got.OperationID != fixture.payment.OperationID ||
		got.ExternalCommits != 1 || !got.RepositoryEdit {
		t.Fatalf("verdict=%+v", got)
	}
}

func TestVerifyBindsDeclaredWorkloadPatch(t *testing.T) {
	fixture := newTestFixture(t)
	contractPath := filepath.Join(filepath.Dir(fixture.options.adapterResult), "workload.json")
	contract := workloadContract{
		Schema: 1, Name: "test/workload",
		PatchSHA256: fixture.adapter.Preflight.WorkspacePatchSHA256,
		FilePath:    "file", RequiredSubstrings: []string{"new"},
		ForbiddenSubstrings: []string{"old"}, DeltaOperationCount: 1,
		ValidationCommand:       "compile",
		ValidationCommandSHA256: fixture.adapter.Preflight.WorkspaceValidationCommandHash,
		EsbuildSHA256:           hashBytes([]byte("esbuild")), ShellSHA256: hashBytes([]byte("shell")),
	}
	writePrivate(t, contractPath, append(mustMarshal(t, contract), '\n'))
	fixture.options.workloadContract = contractPath
	if _, err := verify(fixture.options); err != nil {
		t.Fatalf("valid workload contract rejected: %v", err)
	}
	contract.PatchSHA256 = hashBytes([]byte("different patch"))
	writePrivate(t, contractPath, append(mustMarshal(t, contract), '\n'))
	if _, err := verify(fixture.options); err == nil {
		t.Fatal("mismatched workload patch identity was accepted")
	}
}

func TestVerifyRejectsIndependentEvidenceMutations(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*testing.T, *testFixture)
	}{
		{
			name: "duplicate external commit",
			mutate: func(t *testing.T, fixture *testFixture) {
				line := mustMarshal(t, fixture.payment)
				writePrivate(t, fixture.options.paymentHistory, append(append(line, '\n'), append(line, '\n')...))
			},
		},
		{
			name: "adapter operation identity",
			mutate: func(t *testing.T, fixture *testFixture) {
				fixture.adapter.Control.Operation.OperationID = "op-" + strings.Repeat("f", 64)
				writePrivate(t, fixture.options.adapterResult, append(mustMarshal(t, fixture.adapter), '\n'))
			},
		},
		{
			name: "repository artifact bytes",
			mutate: func(t *testing.T, fixture *testFixture) {
				writePrivate(t, filepath.Join(fixture.options.runtimeEvidence, "repository.delta"), []byte("changed"))
			},
		},
		{
			name: "History hash chain",
			mutate: func(t *testing.T, fixture *testFixture) {
				contents, err := os.ReadFile(fixture.options.history)
				if err != nil {
					t.Fatal(err)
				}
				index := bytes.Index(contents, []byte("operation.prepared"))
				if index < 0 {
					t.Fatal("prepared event not found")
				}
				contents[index] = 'O'
				writePrivate(t, fixture.options.history, contents)
			},
		},
		{
			name: "head anchor checksum",
			mutate: func(t *testing.T, fixture *testFixture) {
				anchor := anchorRecord{
					Version: 1, Sequence: 5, Hash: fixture.events[4].Hash,
					Checksum: strings.Repeat("0", 64),
				}
				writePrivate(t, fixture.options.headAnchor, append(mustMarshal(t, anchor), '\n'))
			},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			fixture := newTestFixture(t)
			test.mutate(t, fixture)
			if _, err := verify(fixture.options); err == nil {
				t.Fatal("mutated evidence was accepted")
			}
		})
	}
}

func TestDecodeStrictRejectsDuplicateKeys(t *testing.T) {
	var target historyPoint
	if err := decodeStrict([]byte(`{"sequence":1,"sequence":2,"hash":"x"}`), &target); err == nil ||
		!strings.Contains(err.Error(), "duplicate") {
		t.Fatalf("duplicate key error=%v", err)
	}
}

func newTestFixture(t *testing.T) *testFixture {
	t.Helper()
	root := t.TempDir()
	runtimeDirectory := filepath.Join(root, "runtime")
	if err := os.Mkdir(runtimeDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(runtimeDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	adapterPath := filepath.Join(root, "adapter.json")
	historyPath := filepath.Join(root, "runtime.history")
	anchorPath := filepath.Join(root, "runtime.head")
	paymentPath := filepath.Join(root, "payment.history")

	artifactBytes := map[string][]byte{
		"repository.bundle":       []byte("base-repository\n"),
		"repository-final.bundle": []byte("final-repository\n"),
		"repository.delta":        []byte("one-edit\n"),
	}
	artifacts := make(map[string]artifact)
	keys := map[string]string{
		"repository": "repository.bundle", "repository_final": "repository-final.bundle",
		"repository_delta": "repository.delta",
	}
	for key, name := range keys {
		contents := artifactBytes[name]
		writePrivate(t, filepath.Join(runtimeDirectory, name), contents)
		artifacts[key] = artifact{Name: name, Size: int64(len(contents)), Mode: 0o600, SHA256: hashBytes(contents)}
	}
	baseRoot := hashBytes([]byte("base tree"))
	finalRoot := hashBytes([]byte("final tree"))
	artifacts["snapshot_state"] = artifact{
		Name: "snapshot.state", Size: 17, Mode: 0o600, SHA256: hashBytes([]byte("snapshot-state")),
	}
	artifacts["snapshot_memory"] = artifact{
		Name: "snapshot.memory", Size: 19, Mode: 0o600, SHA256: hashBytes([]byte("snapshot-memory")),
	}
	checkpointValue := checkpointEvidence{
		Schema: 1, SessionID: strings.Repeat("1", 32),
		SourceInstanceID: strings.Repeat("d", 32), RestoredInstanceID: strings.Repeat("e", 32),
		CodexSHA256: hashBytes([]byte("codex")), ArgumentsSHA256: hashBytes([]byte("arguments")),
		RepositoryTreeRoot: baseRoot, RepositoryBundle: artifacts["repository"],
		SnapshotState: artifacts["snapshot_state"], SnapshotMemory: artifacts["snapshot_memory"],
		StreamCheckpoint: json.RawMessage(`{}`),
	}
	checkpointBytes := append(mustMarshal(t, checkpointValue), '\n')
	writePrivate(t, filepath.Join(runtimeDirectory, "checkpoint.json"), checkpointBytes)
	artifacts["checkpoint"] = artifact{
		Name: "checkpoint.json", Size: int64(len(checkpointBytes)), Mode: 0o600, SHA256: hashBytes(checkpointBytes),
	}
	target := "http://127.0.0.1:38682/v1/charge"
	source := sandboxBinding{
		SandboxID: sandboxID, Generation: 1, HostInstanceID: "host-" + strings.Repeat("a", 32),
		Domain: sandboxDomain, AllowedKinds: []string{operationKind}, RepositoryRoot: baseRoot,
	}
	replacement := sandboxBinding{
		SandboxID: sandboxID, Generation: 2, HostInstanceID: "host-" + strings.Repeat("b", 32),
		Domain: sandboxDomain, AllowedKinds: []string{operationKind}, RepositoryRoot: finalRoot,
	}
	before := testRequirement("firecracker-codex-before", target)
	firstCertificate := testCertificate(t, historyPoint{Hash: emptyHistoryHash}, 0, before, 1, []string{operationKind})
	events := make([]storedEvent, 0, 5)
	events = appendEvent(t, events, "rule.bindings.cutover", cutoverData{
		SemanticVersion: 1, Certificate: firstCertificate, Bindings: []sandboxBinding{source},
	})
	callID := "preflight-call-1"
	effectID := "preflight-effect-1"
	operationID := deriveSandboxOperationID(sandboxDomain, sandboxID, callID)
	body := mustMarshal(t, map[string]string{"effect_id": effectID})
	requestDigest := operationRequestHash("POST", target, map[string]string{
		"Accept-Encoding": "identity", "Idempotency-Key": operationID,
		"User-Agent": "safe-change-runtime/1", "X-Operation-ID": operationID,
	}, body)
	prepared := operation{
		ID: operationID, Domain: sandboxDomain, SandboxID: sandboxID, Kind: operationKind,
		RequestHash: requestDigest, RuleVersion: 1,
		Costs: map[string]uint32{capacityName: 1}, Produces: map[string]uint32{resultName: 1},
		RetrySafe: true, Target: target, Method: "POST", ResponseClassifier: responseClassifier,
		RequestStored: true, RequestBody: body, Phase: "prepared",
	}
	events = appendEvent(t, events, "operation.prepared", prepareData{SemanticVersion: 1, Operation: prepared})
	events = appendEvent(t, events, "operation.phase", phaseData{
		SemanticVersion: 1, ID: operationID,
		Update: operationUpdate{Phase: "dispatched", DispatchOwner: strings.Repeat("c", 32), DispatchGeneration: 1},
	})
	resultHash := hashBytes([]byte("charged\x00" + operationID))
	remoteReference := "firecracker-codex/" + operationID
	receiptBytes := append(mustMarshal(t, receipt{
		OperationID: operationID, Outcome: "succeeded", RemoteReference: remoteReference,
		ResultHash: resultHash, Schema: 1,
	}), '\n')
	events = appendEvent(t, events, "operation.phase", phaseData{
		SemanticVersion: 1, ID: operationID,
		Update: operationUpdate{
			Phase: "succeeded", ResultHash: resultHash, StatusCode: 200,
			ResultBody: receiptBytes, RemoteReference: remoteReference,
		},
	})
	after := testRequirement("firecracker-codex-after", target)
	finalCertificate := testCertificate(
		t, historyPoint{Sequence: events[3].Sequence, Hash: events[3].Hash}, 1, after, 2, []string{},
	)
	repository := repositoryRecord{
		SandboxID: sandboxID, SourceGeneration: 1, SourceHostID: source.HostInstanceID,
		CheckpointSHA256: artifacts["checkpoint"].SHA256,
		BaseRoot:         baseRoot, FinalRoot: finalRoot,
		FinalBundleSHA256: artifacts["repository_final"].SHA256,
		FinalBundleSize:   uint64(artifacts["repository_final"].Size),
		DeltaSHA256:       artifacts["repository_delta"].SHA256,
		DeltaSize:         uint64(artifacts["repository_delta"].Size),
	}
	events = appendEvent(t, events, "rule.bindings.cutover", cutoverData{
		SemanticVersion: 2, Certificate: finalCertificate,
		Bindings: []sandboxBinding{replacement}, Repositories: []repositoryRecord{repository},
	})
	writeHistory(t, historyPath, events)
	anchor := anchorRecord{
		Version: 1, Sequence: 5, Hash: events[4].Hash,
		Checksum: anchorChecksum(5, events[4].Hash),
	}
	writePrivate(t, anchorPath, append(mustMarshal(t, anchor), '\n'))
	payment := paymentRecord{
		OperationID: operationID, RequestHash: paymentRequestHash("POST", "/v1/charge", body),
		ResultHash: resultHash, RemoteReference: remoteReference, Path: "/v1/charge",
	}
	writePrivate(t, paymentPath, append(mustMarshal(t, payment), '\n'))

	runtime := runtimeResult{
		Schema: 1, Success: true, SessionID: strings.Repeat("1", 32),
		RunnerSHA256: hashBytes([]byte("runner")), CodexSHA256: hashBytes([]byte("codex")),
		ArgumentsSHA256: hashBytes([]byte("arguments")), ArgumentsEncoding: "compact-json-array", ArgumentsCount: 22,
		WorkspaceMapping: json.RawMessage(`{}`), Artifacts: artifacts,
		SealedBootInputs: json.RawMessage(`[]`), SealedLoadInputs: json.RawMessage(`[]`),
		Checkpoint: json.RawMessage(`{}`), RepositoryChange: repositoryChange{BaseRoot: baseRoot, FinalRoot: finalRoot, OperationCount: 1},
		Processes: json.RawMessage(`[]`), G1SIGKILLConfirmed: true, SnapshotLoadedPaused: true,
		RelayArmedBeforeResume: true, ToolReleasedAfterAttach: true, CompletedTimeNS: 99,
	}
	runtimePath := filepath.Join(runtimeDirectory, "result.json")
	runtimeBytes := append(mustMarshal(t, runtime), '\n')
	writePrivate(t, runtimePath, runtimeBytes)
	appServerPath := filepath.Join(root, "app-server.jsonl")
	appServerRecords := []appServerRecord{
		{
			Direction: "client_to_server", Sequence: 1, TimeNS: 1,
			Payload: mustMarshal(t, map[string]any{
				"method": "turn/start",
				"params": map[string]any{
					"threadId": "fork", "approvalPolicy": "never",
					"sandboxPolicy": map[string]any{"type": "externalSandbox", "networkAccess": "restricted"},
				},
			}),
		},
		{
			Direction: "server_to_client", Sequence: 2, TimeNS: 2,
			Payload: mustMarshal(t, map[string]any{
				"method": "item/completed",
				"params": map[string]any{
					"threadId": "fork", "turnId": "protected",
					"item": map[string]any{
						"id": "preflight-edit-1", "type": "fileChange", "status": "completed",
						"changes": []any{map[string]any{"path": "/workspace/file", "diff": "edit"}},
					},
				},
			}),
		},
		{
			Direction: "server_to_client", Sequence: 3, TimeNS: 3,
			Payload: mustMarshal(t, map[string]any{
				"method": "item/completed",
				"params": map[string]any{
					"threadId": "fork", "turnId": "protected",
					"item": map[string]any{
						"id": "preflight-validation-1", "type": "commandExecution", "status": "completed",
						"command": "/opt/codex/bin/sh -c 'compile'", "exitCode": 0,
						"commandActions": []any{map[string]any{"command": "compile", "type": "unknown"}},
					},
				},
			}),
		},
		{
			Direction: "server_to_client", Sequence: 4, TimeNS: 4,
			Payload: mustMarshal(t, map[string]any{
				"method": "item/tool/call",
				"params": map[string]any{
					"threadId": "fork", "turnId": "protected", "tool": operationKind, "callId": callID,
				},
			}),
		},
	}
	var appServerBytes bytes.Buffer
	for _, record := range appServerRecords {
		appServerBytes.Write(mustMarshal(t, record))
		appServerBytes.WriteByte('\n')
	}
	writePrivate(t, appServerPath, appServerBytes.Bytes())
	adapter := adapterResult{
		Schema: 1, OK: true, ResultPath: adapterPath,
		Artifacts: json.RawMessage(`{}`), Workspace: json.RawMessage(`{}`),
		Adapter: adapterEvidenceSummary{
			EvidenceDirectory: root,
			AppServerJSONL: fileSummary{
				Path: appServerPath, SHA256: hashBytes(appServerBytes.Bytes()), Size: int64(appServerBytes.Len()),
			},
		},
		Runtime: adapterRuntime{
			EvidenceDirectory: runtimeDirectory,
			Result:            fileSummary{Path: runtimePath, SHA256: hashBytes(runtimeBytes), Size: int64(len(runtimeBytes))},
			SessionID:         runtime.SessionID,
		},
		Preflight: preflightSummary{
			OK: true, SeedThreadID: "seed", SeedTurnID: "seed-turn", ForkThreadID: "fork",
			ProtectedTurnID: "protected", CallID: callID, EffectID: effectID, SeedArchived: true,
			ResponsesRequestCount: 5, RawRecordCount: len(appServerRecords),
			WorkspaceEditCallID: "preflight-edit-1", WorkspacePatchSHA256: hashBytes([]byte("patch")),
			WorkspaceValidationCallID:      "preflight-validation-1",
			WorkspaceValidationCommandHash: hashBytes([]byte("compile")),
		},
		IndependentEvidenceCheck: "required",
		Control: controlSummary{
			Operation:          operationSummary{OperationID: operationID, Phase: "succeeded", ResultHash: resultHash},
			CertificateHistory: historyPoint{Sequence: events[3].Sequence, Hash: events[3].Hash},
			CommittedHistory:   historyPoint{Sequence: events[4].Sequence, Hash: events[4].Hash},
			SourceBinding:      source, TargetBinding: replacement, Repository: repository,
		},
	}
	writePrivate(t, adapterPath, append(mustMarshal(t, adapter), '\n'))
	return &testFixture{
		options: options{
			runtimeEvidence: runtimeDirectory, adapterResult: adapterPath, history: historyPath,
			headAnchor: anchorPath, paymentHistory: paymentPath,
		},
		adapter: adapter, events: events, payment: payment,
	}
}

func testRequirement(id, target string) requirement {
	return requirement{
		ID: id, Results: map[string]uint32{resultName: 1}, Capacities: map[string]uint32{capacityName: 1},
		Kinds: map[string]kindSpec{
			operationKind: {
				Costs: map[string]uint32{capacityName: 1}, Produces: map[string]uint32{resultName: 1},
				RetrySafe: true, Target: target, Method: "POST", ResponseClassifier: responseClassifier,
			},
		},
	}
}

func testCertificate(
	t *testing.T, point historyPoint, from uint64, requirement requirement, version uint64, allow []string,
) certificate {
	t.Helper()
	requirementBytes := mustMarshal(t, requirement)
	value := certificate{
		Schema: 1, Decision: "activate", History: point, FromRule: from, Requirement: requirement,
		Rule: &rule{Version: version, RequirementHash: hashBytes(requirementBytes), Allow: allow},
	}
	encoded := mustMarshal(t, value)
	value.Digest = hashBytes(encoded)
	return value
}

func appendEvent(t *testing.T, events []storedEvent, operation string, data any) []storedEvent {
	t.Helper()
	previous := emptyHistoryHash
	if len(events) != 0 {
		previous = events[len(events)-1].Hash
	}
	event := storedEvent{
		Version: 1, Sequence: uint64(len(events) + 1), Operation: operation,
		Data: mustMarshal(t, data), PreviousHash: previous,
	}
	event.Hash = hashEvent(event)
	return append(events, event)
}

func writeHistory(t *testing.T, path string, events []storedEvent) {
	t.Helper()
	var output bytes.Buffer
	for _, event := range events {
		payload := mustMarshal(t, event)
		var header [historyHeaderBytes]byte
		copy(header[:4], historyMagic[:])
		binary.BigEndian.PutUint64(header[4:], uint64(len(payload)))
		output.Write(header[:])
		output.Write(payload)
	}
	writePrivate(t, path, output.Bytes())
}

func mustMarshal(t *testing.T, value any) []byte {
	t.Helper()
	encoded, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return encoded
}

func writePrivate(t *testing.T, path string, contents []byte) {
	t.Helper()
	if err := os.WriteFile(path, contents, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}
}
