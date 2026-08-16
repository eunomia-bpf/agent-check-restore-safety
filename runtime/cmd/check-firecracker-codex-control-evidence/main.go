// Command check-firecracker-codex-control-evidence independently joins one
// successful Firecracker/Codex run to its durable control History and the
// external service's commit record. It intentionally imports no producer,
// control, gateway, History, or payment implementation package.
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"syscall"
)

const (
	verdictSchema        = 1
	historyFormat        = 1
	historyHeaderBytes   = 12
	maxHistoryFrame      = 16 << 20
	maxEvidenceFile      = 64 << 20
	privateFileMode      = 0o600
	privateDirectoryMode = 0o700
	emptyHistoryHash     = "0000000000000000000000000000000000000000000000000000000000000000"
	sandboxID            = "firecracker-codex"
	sandboxDomain        = "firecracker-codex-vm"
	operationKind        = "protected_commit"
	resultName           = "callback-committed"
	capacityName         = "external-write"
	responseClassifier   = "operation-receipt-v1"
	queryClassifier      = "operation-observation-v1"
)

var historyMagic = [4]byte{'H', 'S', 'T', '1'}

type options struct {
	runtimeEvidence  string
	adapterResult    string
	history          string
	headAnchor       string
	paymentHistory   string
	workloadContract string
}

type workloadContract struct {
	Schema                  int      `json:"schema"`
	Name                    string   `json:"name"`
	PatchSHA256             string   `json:"patch_sha256"`
	FilePath                string   `json:"file_path"`
	RequiredSubstrings      []string `json:"required_substrings"`
	ForbiddenSubstrings     []string `json:"forbidden_substrings"`
	DeltaOperationCount     int      `json:"delta_operation_count"`
	ValidationCommand       string   `json:"validation_command"`
	ValidationCommandSHA256 string   `json:"validation_command_sha256"`
	EsbuildSHA256           string   `json:"esbuild_sha256"`
	ShellSHA256             string   `json:"shell_sha256"`
}

type verdict struct {
	Schema          int    `json:"schema"`
	Valid           bool   `json:"valid"`
	Error           string `json:"error,omitempty"`
	HistorySequence uint64 `json:"history_sequence,omitempty"`
	OperationID     string `json:"operation_id,omitempty"`
	ExternalCommits int    `json:"external_commits,omitempty"`
	RepositoryEdit  bool   `json:"repository_edit"`
}

type artifact struct {
	Name   string `json:"name"`
	Size   int64  `json:"size"`
	Mode   uint32 `json:"mode"`
	SHA256 string `json:"sha256"`
}

type repositoryChange struct {
	BaseRoot       string `json:"base_root"`
	FinalRoot      string `json:"final_root"`
	OperationCount int    `json:"operation_count"`
}

type checkpointEvidence struct {
	Schema             int             `json:"schema"`
	SessionID          string          `json:"session_id"`
	SourceInstanceID   string          `json:"source_instance_id"`
	RestoredInstanceID string          `json:"restored_instance_id"`
	CodexSHA256        string          `json:"codex_sha256"`
	ArgumentsSHA256    string          `json:"arguments_sha256"`
	RepositoryTreeRoot string          `json:"repository_tree_root"`
	RepositoryBundle   artifact        `json:"repository_bundle"`
	SnapshotState      artifact        `json:"snapshot_state"`
	SnapshotMemory     artifact        `json:"snapshot_memory"`
	StreamCheckpoint   json.RawMessage `json:"stream_checkpoint"`
}

type runtimeResult struct {
	Schema                  int                 `json:"schema"`
	Success                 bool                `json:"success"`
	SessionID               string              `json:"session_id"`
	RunnerSHA256            string              `json:"runner_sha256"`
	CodexSHA256             string              `json:"codex_sha256"`
	ArgumentsSHA256         string              `json:"arguments_sha256"`
	ArgumentsEncoding       string              `json:"arguments_encoding"`
	ArgumentsCount          int                 `json:"arguments_count"`
	WorkspaceMapping        json.RawMessage     `json:"workspace_mapping"`
	Artifacts               map[string]artifact `json:"artifacts"`
	SealedBootInputs        json.RawMessage     `json:"sealed_boot_inputs"`
	SealedLoadInputs        json.RawMessage     `json:"sealed_load_inputs"`
	Checkpoint              json.RawMessage     `json:"checkpoint"`
	RepositoryChange        repositoryChange    `json:"repository_change"`
	Processes               json.RawMessage     `json:"processes"`
	G1SIGKILLConfirmed      bool                `json:"g1_sigkill_confirmed"`
	SnapshotLoadedPaused    bool                `json:"snapshot_loaded_paused"`
	RelayArmedBeforeResume  bool                `json:"relay_armed_before_resume"`
	ToolReleasedAfterAttach bool                `json:"tool_released_after_g3_attach"`
	CompletedTimeNS         int64               `json:"completed_time_ns"`
}

type historyPoint struct {
	Sequence uint64 `json:"sequence"`
	Hash     string `json:"hash"`
}

type sandboxBinding struct {
	SandboxID      string   `json:"sandbox_id"`
	Generation     uint64   `json:"generation"`
	HostInstanceID string   `json:"host_instance_id"`
	Domain         string   `json:"domain"`
	AllowedKinds   []string `json:"allowed_kinds"`
	RepositoryRoot string   `json:"repository_root,omitempty"`
}

type repositoryRecord struct {
	SandboxID         string `json:"sandbox_id"`
	SourceGeneration  uint64 `json:"source_generation"`
	SourceHostID      string `json:"source_host_instance_id"`
	CheckpointSHA256  string `json:"checkpoint_sha256"`
	BaseRoot          string `json:"base_root"`
	FinalRoot         string `json:"final_root"`
	FinalBundleSHA256 string `json:"final_bundle_sha256"`
	FinalBundleSize   uint64 `json:"final_bundle_size"`
	DeltaSHA256       string `json:"delta_sha256"`
	DeltaSize         uint64 `json:"delta_size"`
}

type operationSummary struct {
	CallID           string `json:"call_id,omitempty"`
	EffectID         string `json:"effect_id,omitempty"`
	OperationID      string `json:"operation_id"`
	Phase            string `json:"phase"`
	ResultHash       string `json:"result_hash"`
	Reused           bool   `json:"reused"`
	RecoveredByQuery bool   `json:"recovered_by_query,omitempty"`
	UnknownObserved  bool   `json:"unknown_observed,omitempty"`
}

type controlSummary struct {
	Operation          operationSummary   `json:"operation"`
	Operations         []operationSummary `json:"operations,omitempty"`
	CertificateHistory historyPoint       `json:"certificate_history"`
	CommittedHistory   historyPoint       `json:"committed_history"`
	SourceBinding      sandboxBinding     `json:"source_binding"`
	TargetBinding      sandboxBinding     `json:"target_binding"`
	Repository         repositoryRecord   `json:"repository"`
}

type protectedCallSummary struct {
	RequestID json.RawMessage `json:"request_id"`
	CallID    string          `json:"call_id"`
	EffectID  string          `json:"effect_id"`
}

type fileSummary struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
}

type adapterRuntime struct {
	EvidenceDirectory string      `json:"evidence_directory"`
	Result            fileSummary `json:"result"`
	SessionID         string      `json:"session_id"`
}

type preflightSummary struct {
	OK                             bool                   `json:"ok"`
	SeedThreadID                   string                 `json:"seed_thread_id"`
	SeedTurnID                     string                 `json:"seed_turn_id"`
	ForkThreadID                   string                 `json:"fork_thread_id"`
	ProtectedTurnID                string                 `json:"protected_turn_id"`
	CallID                         string                 `json:"call_id"`
	EffectID                       string                 `json:"effect_id"`
	SeedArchived                   bool                   `json:"seed_archived"`
	ResponsesRequestCount          int                    `json:"responses_request_count"`
	ModelsRequestCount             int                    `json:"models_request_count"`
	RawRecordCount                 int                    `json:"raw_record_count"`
	WorkspaceEditCallID            string                 `json:"workspace_edit_call_id,omitempty"`
	WorkspacePatchSHA256           string                 `json:"workspace_patch_sha256,omitempty"`
	WorkspaceValidationCallID      string                 `json:"workspace_validation_call_id,omitempty"`
	WorkspaceValidationCommandHash string                 `json:"workspace_validation_command_sha256,omitempty"`
	ProtectedCalls                 []protectedCallSummary `json:"protected_calls,omitempty"`
}

type adapterEvidenceSummary struct {
	EvidenceDirectory string      `json:"evidence_directory"`
	AppServerJSONL    fileSummary `json:"app_server_jsonl"`
}

type appServerRecord struct {
	Direction string          `json:"direction"`
	Payload   json.RawMessage `json:"payload"`
	Sequence  uint64          `json:"sequence"`
	TimeNS    int64           `json:"time_ns"`
}

type adapterResult struct {
	Schema                   int                    `json:"schema"`
	OK                       bool                   `json:"ok"`
	ResultPath               string                 `json:"result_path"`
	Artifacts                json.RawMessage        `json:"artifacts"`
	Workspace                json.RawMessage        `json:"workspace"`
	Runtime                  adapterRuntime         `json:"runtime"`
	Adapter                  adapterEvidenceSummary `json:"adapter"`
	Preflight                preflightSummary       `json:"preflight"`
	IndependentEvidenceCheck string                 `json:"independent_evidence_check"`
	Control                  controlSummary         `json:"control"`
}

type kindSpec struct {
	Costs              map[string]uint32 `json:"costs"`
	Produces           map[string]uint32 `json:"produces"`
	RetrySafe          bool              `json:"retry_safe"`
	Queryable          bool              `json:"queryable"`
	Target             string            `json:"target,omitempty"`
	Method             string            `json:"method,omitempty"`
	ResponseClassifier string            `json:"response_classifier,omitempty"`
	QueryTarget        string            `json:"query_target,omitempty"`
	QueryMethod        string            `json:"query_method,omitempty"`
	QueryClassifier    string            `json:"query_classifier,omitempty"`
}

type requirement struct {
	ID         string              `json:"id"`
	Results    map[string]uint32   `json:"results"`
	Capacities map[string]uint32   `json:"capacities"`
	Kinds      map[string]kindSpec `json:"kinds"`
}

type rule struct {
	Version         uint64   `json:"version"`
	RequirementHash string   `json:"requirement_hash"`
	Allow           []string `json:"allow"`
}

type witness struct {
	OpenSucceeded []string `json:"open_succeeded,omitempty"`
	Reason        string   `json:"reason"`
}

type certificate struct {
	Schema      int          `json:"schema"`
	Decision    string       `json:"decision"`
	History     historyPoint `json:"history"`
	FromRule    uint64       `json:"from_rule"`
	Requirement requirement  `json:"requirement"`
	Rule        *rule        `json:"rule,omitempty"`
	Witness     *witness     `json:"witness,omitempty"`
	Digest      string       `json:"digest"`
}

type cutoverData struct {
	SemanticVersion int                `json:"semantic_version"`
	Certificate     certificate        `json:"certificate"`
	Bindings        []sandboxBinding   `json:"bindings"`
	Repositories    []repositoryRecord `json:"repositories,omitempty"`
}

type operation struct {
	ID                 string            `json:"id"`
	Domain             string            `json:"domain"`
	SandboxID          string            `json:"sandbox_id,omitempty"`
	Kind               string            `json:"kind"`
	RequestHash        string            `json:"request_hash"`
	RuleVersion        uint64            `json:"rule_version"`
	Costs              map[string]uint32 `json:"costs"`
	Produces           map[string]uint32 `json:"produces"`
	RetrySafe          bool              `json:"retry_safe"`
	Queryable          bool              `json:"queryable"`
	Target             string            `json:"target,omitempty"`
	Method             string            `json:"method,omitempty"`
	ResponseClassifier string            `json:"response_classifier,omitempty"`
	QueryTarget        string            `json:"query_target,omitempty"`
	QueryMethod        string            `json:"query_method,omitempty"`
	QueryClassifier    string            `json:"query_classifier,omitempty"`
	RequestStored      bool              `json:"request_stored,omitempty"`
	RequestHeaders     map[string]string `json:"request_headers,omitempty"`
	RequestBody        []byte            `json:"request_body,omitempty"`
	Phase              string            `json:"phase"`
	ResultHash         string            `json:"result_hash,omitempty"`
	StatusCode         int               `json:"status_code,omitempty"`
	ResultBody         []byte            `json:"result_body,omitempty"`
	RemoteReference    string            `json:"remote_reference,omitempty"`
	DispatchOwner      string            `json:"dispatch_owner,omitempty"`
	DispatchGeneration uint64            `json:"dispatch_generation,omitempty"`
	Settlement         string            `json:"settlement,omitempty"`
}

type operationUpdate struct {
	Phase              string `json:"phase"`
	ResultHash         string `json:"result_hash,omitempty"`
	StatusCode         int    `json:"status_code,omitempty"`
	ResultBody         []byte `json:"result_body,omitempty"`
	RemoteReference    string `json:"remote_reference,omitempty"`
	DispatchOwner      string `json:"dispatch_owner,omitempty"`
	DispatchGeneration uint64 `json:"dispatch_generation,omitempty"`
	Settlement         string `json:"settlement,omitempty"`
}

type prepareData struct {
	SemanticVersion int       `json:"semantic_version"`
	Operation       operation `json:"operation"`
}

type phaseData struct {
	SemanticVersion int             `json:"semantic_version"`
	ID              string          `json:"id"`
	Update          operationUpdate `json:"update"`
}

type storedEvent struct {
	Version      int             `json:"version"`
	Sequence     uint64          `json:"sequence"`
	Operation    string          `json:"operation"`
	Data         json.RawMessage `json:"data"`
	PreviousHash string          `json:"previous_hash"`
	Hash         string          `json:"hash"`
}

type anchorRecord struct {
	Version  int    `json:"version"`
	Sequence uint64 `json:"sequence"`
	Hash     string `json:"hash"`
	Checksum string `json:"checksum"`
}

type paymentRecord struct {
	OperationID     string `json:"operation_id"`
	RequestHash     string `json:"request_hash"`
	ResultHash      string `json:"result_hash"`
	RemoteReference string `json:"remote_reference"`
	Path            string `json:"path"`
}

type receipt struct {
	OperationID     string `json:"operation_id"`
	Outcome         string `json:"outcome"`
	RemoteReference string `json:"remote_reference"`
	ResultHash      string `json:"result_hash"`
	Schema          int    `json:"schema"`
}

type observation struct {
	Schema          int    `json:"schema"`
	OperationID     string `json:"operation_id"`
	RequestHash     string `json:"request_hash"`
	Outcome         string `json:"outcome"`
	FactHash        string `json:"fact_hash"`
	RemoteReference string `json:"remote_reference"`
}

func main() {
	var arguments options
	flag.StringVar(&arguments.runtimeEvidence, "runtime-evidence", "", "retained Firecracker runtime evidence directory")
	flag.StringVar(&arguments.adapterResult, "adapter-result", "", "retained adapter result.json")
	flag.StringVar(&arguments.history, "history", "", "retained durable control History")
	flag.StringVar(&arguments.headAnchor, "head-anchor", "", "retained external History head anchor")
	flag.StringVar(&arguments.paymentHistory, "payment-history", "", "retained external commit history")
	flag.StringVar(&arguments.workloadContract, "workload-contract", "", "optional canonical absolute workload contract JSON")
	flag.Parse()
	result, err := verify(arguments)
	if err != nil {
		_ = json.NewEncoder(os.Stdout).Encode(verdict{Schema: verdictSchema, Valid: false, Error: err.Error()})
		os.Exit(1)
	}
	_ = json.NewEncoder(os.Stdout).Encode(result)
}

func verify(arguments options) (verdict, error) {
	runtimeDirectory, err := validatePrivateDirectory(arguments.runtimeEvidence, "runtime evidence")
	if err != nil {
		return verdict{}, err
	}
	adapterPath, err := canonicalPath(arguments.adapterResult, "adapter result")
	if err != nil {
		return verdict{}, err
	}
	historyPath, err := canonicalPath(arguments.history, "History")
	if err != nil {
		return verdict{}, err
	}
	anchorPath, err := canonicalPath(arguments.headAnchor, "head anchor")
	if err != nil {
		return verdict{}, err
	}
	paymentPath, err := canonicalPath(arguments.paymentHistory, "payment history")
	if err != nil {
		return verdict{}, err
	}
	contract, err := readWorkloadContract(arguments.workloadContract)
	if err != nil {
		return verdict{}, err
	}
	paths := []string{runtimeDirectory, adapterPath, historyPath, anchorPath, paymentPath}
	for left := range paths {
		for right := left + 1; right < len(paths); right++ {
			if overlaps(paths[left], paths[right]) {
				return verdict{}, fmt.Errorf("evidence inputs overlap: %q and %q", paths[left], paths[right])
			}
		}
	}

	adapterBytes, _, err := readPrivateFile(adapterPath, maxEvidenceFile, "adapter result")
	if err != nil {
		return verdict{}, err
	}
	var adapter adapterResult
	if err := decodeStrict(adapterBytes, &adapter); err != nil {
		return verdict{}, fmt.Errorf("adapter result: %w", err)
	}
	if adapter.Schema != 1 || !adapter.OK || adapter.ResultPath != adapterPath ||
		adapter.IndependentEvidenceCheck != "required" || adapter.Runtime.EvidenceDirectory != runtimeDirectory ||
		adapter.Preflight.OK != true || !adapter.Preflight.SeedArchived || adapter.Preflight.CallID == "" ||
		adapter.Preflight.EffectID == "" || adapter.Preflight.SeedThreadID == "" ||
		adapter.Preflight.SeedTurnID == "" || adapter.Preflight.ForkThreadID == "" ||
		adapter.Preflight.ProtectedTurnID == "" || adapter.Preflight.RawRecordCount <= 0 ||
		adapter.Preflight.ResponsesRequestCount <= 0 {
		return verdict{}, errors.New("adapter result does not describe one successful protected preflight")
	}
	protectedCalls := adapter.Preflight.ProtectedCalls
	if len(protectedCalls) == 0 {
		protectedCalls = []protectedCallSummary{{
			CallID: adapter.Preflight.CallID, EffectID: adapter.Preflight.EffectID,
		}}
	}
	if len(protectedCalls) > 8 || protectedCalls[0].CallID != adapter.Preflight.CallID ||
		protectedCalls[0].EffectID != adapter.Preflight.EffectID {
		return verdict{}, errors.New("adapter protected callback summary is inconsistent")
	}
	operations := adapter.Control.Operations
	if len(operations) == 0 {
		operations = []operationSummary{adapter.Control.Operation}
	}
	if len(operations) != len(protectedCalls) || !reflect.DeepEqual(adapter.Control.Operation, operations[0]) {
		return verdict{}, errors.New("adapter Operation summaries do not match protected callbacks")
	}
	seenCalls := make(map[string]bool, len(protectedCalls))
	seenEffects := make(map[string]bool, len(protectedCalls))
	for index, call := range protectedCalls {
		expectedCallID := fmt.Sprintf("preflight-call-%d", index+1)
		if call.CallID != expectedCallID || call.EffectID == "" || seenCalls[call.CallID] || seenEffects[call.EffectID] ||
			(len(adapter.Preflight.ProtectedCalls) > 0 && len(call.RequestID) == 0) {
			return verdict{}, errors.New("adapter protected callbacks are not unique and ordered")
		}
		seenCalls[call.CallID], seenEffects[call.EffectID] = true, true
		summary := operations[index]
		if (summary.CallID != "" && summary.CallID != call.CallID) ||
			(summary.EffectID != "" && summary.EffectID != call.EffectID) {
			return verdict{}, errors.New("adapter Operation identity differs from its protected callback")
		}
	}
	hasEditCall := adapter.Preflight.WorkspaceEditCallID != ""
	hasPatchDigest := adapter.Preflight.WorkspacePatchSHA256 != ""
	if hasEditCall != hasPatchDigest || (hasPatchDigest && !validDigest(adapter.Preflight.WorkspacePatchSHA256)) {
		return verdict{}, errors.New("adapter workspace edit identity is incomplete or invalid")
	}
	if contract != nil && (!hasEditCall || adapter.Preflight.WorkspacePatchSHA256 != contract.PatchSHA256) {
		return verdict{}, errors.New("adapter patch identity differs from the workload contract")
	}
	hasValidationCall := adapter.Preflight.WorkspaceValidationCallID != ""
	hasValidationDigest := adapter.Preflight.WorkspaceValidationCommandHash != ""
	if hasValidationCall != hasValidationDigest || hasValidationCall && !hasEditCall ||
		(hasValidationDigest && !validDigest(adapter.Preflight.WorkspaceValidationCommandHash)) {
		return verdict{}, errors.New("adapter workspace validation identity is incomplete or invalid")
	}
	if contract != nil && (!hasValidationCall ||
		adapter.Preflight.WorkspaceValidationCommandHash != contract.ValidationCommandSHA256) {
		return verdict{}, errors.New("adapter validation identity differs from the workload contract")
	}
	expectedResponseCount := 2 + len(protectedCalls) + boolInt(hasEditCall) + boolInt(hasValidationCall)
	if adapter.Preflight.ResponsesRequestCount != expectedResponseCount {
		return verdict{}, fmt.Errorf(
			"preflight made %d model requests, want exactly %d", adapter.Preflight.ResponsesRequestCount, expectedResponseCount,
		)
	}
	adapterDirectory, err := validatePrivateDirectory(adapter.Adapter.EvidenceDirectory, "adapter evidence")
	if err != nil {
		return verdict{}, err
	}
	if adapterDirectory != filepath.Dir(adapterPath) ||
		adapter.Adapter.AppServerJSONL.Path != filepath.Join(adapterDirectory, "app-server.jsonl") {
		return verdict{}, errors.New("adapter result points outside its retained App Server evidence")
	}
	appServerBytes, appServerInfo, err := readPrivateFile(
		adapter.Adapter.AppServerJSONL.Path, maxEvidenceFile, "App Server JSONL",
	)
	if err != nil {
		return verdict{}, err
	}
	if err := matchFileSummary(adapter.Adapter.AppServerJSONL, appServerInfo, appServerBytes); err != nil {
		return verdict{}, fmt.Errorf("App Server JSONL fingerprint: %w", err)
	}
	if err := checkAppServerRecords(appServerBytes, adapter.Preflight); err != nil {
		return verdict{}, err
	}

	runtimePath := filepath.Join(runtimeDirectory, "result.json")
	if adapter.Runtime.Result.Path != runtimePath {
		return verdict{}, errors.New("adapter result points to a different runtime result")
	}
	runtimeBytes, runtimeInfo, err := readPrivateFile(runtimePath, maxEvidenceFile, "runtime result")
	if err != nil {
		return verdict{}, err
	}
	if err := matchFileSummary(adapter.Runtime.Result, runtimeInfo, runtimeBytes); err != nil {
		return verdict{}, fmt.Errorf("runtime result fingerprint: %w", err)
	}
	var runtime runtimeResult
	if err := decodeStrict(runtimeBytes, &runtime); err != nil {
		return verdict{}, fmt.Errorf("runtime result: %w", err)
	}
	if runtime.Schema != 1 || !runtime.Success || runtime.SessionID == "" ||
		runtime.SessionID != adapter.Runtime.SessionID || !validDigest(runtime.RunnerSHA256) ||
		!validDigest(runtime.CodexSHA256) || !validDigest(runtime.ArgumentsSHA256) ||
		runtime.ArgumentsEncoding != "compact-json-array" || runtime.ArgumentsCount <= 0 ||
		!runtime.G1SIGKILLConfirmed || !runtime.SnapshotLoadedPaused ||
		!runtime.RelayArmedBeforeResume || !runtime.ToolReleasedAfterAttach || runtime.CompletedTimeNS <= 0 {
		return verdict{}, errors.New("runtime result does not describe a completed Firecracker restore")
	}
	if hasEditCall && (runtime.RepositoryChange.BaseRoot == runtime.RepositoryChange.FinalRoot ||
		runtime.RepositoryChange.OperationCount < 1) {
		return verdict{}, errors.New("completed native Codex edit has no nonempty repository delta")
	}
	if contract != nil && runtime.RepositoryChange.OperationCount != contract.DeltaOperationCount {
		return verdict{}, errors.New("runtime delta operation count differs from the workload contract")
	}
	for key, name := range map[string]string{
		"checkpoint": "checkpoint.json", "repository": "repository.bundle",
		"repository_final": "repository-final.bundle", "repository_delta": "repository.delta",
	} {
		record, ok := runtime.Artifacts[key]
		if !ok || record.Name != name || record.Mode != privateFileMode {
			return verdict{}, fmt.Errorf("runtime artifact %q has an invalid record", key)
		}
		contents, info, err := readPrivateFile(filepath.Join(runtimeDirectory, name), maxEvidenceFile, key)
		if err != nil {
			return verdict{}, err
		}
		if int64(record.Size) != info.Size() || record.SHA256 != hashBytes(contents) {
			return verdict{}, fmt.Errorf("runtime artifact %q fingerprint does not match", key)
		}
	}
	checkpointBytes, _, err := readPrivateFile(
		filepath.Join(runtimeDirectory, "checkpoint.json"), maxEvidenceFile, "checkpoint",
	)
	if err != nil {
		return verdict{}, err
	}
	if err := checkCheckpoint(checkpointBytes, runtime); err != nil {
		return verdict{}, err
	}

	events, err := readHistory(historyPath)
	if err != nil {
		return verdict{}, err
	}
	expectedHistoryEvents := 2
	for _, summary := range operations {
		expectedHistoryEvents += 3 + boolInt(summary.UnknownObserved)
	}
	if len(events) != expectedHistoryEvents {
		return verdict{}, fmt.Errorf(
			"History has %d events, want the exact %d-event join", len(events), expectedHistoryEvents,
		)
	}
	anchor, err := readAnchor(anchorPath)
	if err != nil {
		return verdict{}, err
	}
	last := events[len(events)-1]
	if anchor.Sequence != last.Sequence || anchor.Hash != last.Hash ||
		adapter.Control.CommittedHistory != (historyPoint{Sequence: last.Sequence, Hash: last.Hash}) {
		return verdict{}, errors.New("History, external head anchor, and adapter result disagree")
	}

	initial, err := decodeEventData[cutoverData](events[0])
	if err != nil {
		return verdict{}, err
	}
	final, err := decodeEventData[cutoverData](events[len(events)-1])
	if err != nil {
		return verdict{}, err
	}
	if events[0].Operation != "rule.bindings.cutover" || events[len(events)-1].Operation != "rule.bindings.cutover" {
		return verdict{}, errors.New("History does not begin and end with the required Cutovers")
	}

	queryable := false
	for _, summary := range operations {
		queryable = queryable || summary.UnknownObserved || summary.RecoveredByQuery
	}
	if err := checkInitialCutover(initial, adapter.Control.SourceBinding, len(operations), queryable); err != nil {
		return verdict{}, err
	}
	payment, err := readPayments(paymentPath, len(operations))
	if err != nil {
		return verdict{}, err
	}
	cursor := 1
	expectedIDs := make([]string, 0, len(operations))
	for index, summary := range operations {
		if events[cursor].Operation != "operation.prepared" || events[cursor+1].Operation != "operation.phase" {
			return verdict{}, fmt.Errorf("Operation %d lacks its prepare/dispatch History events", index+1)
		}
		prepared, decodeErr := decodeEventData[prepareData](events[cursor])
		if decodeErr != nil {
			return verdict{}, decodeErr
		}
		dispatched, decodeErr := decodeEventData[phaseData](events[cursor+1])
		if decodeErr != nil {
			return verdict{}, decodeErr
		}
		cursor += 2
		var unknown *phaseData
		if summary.UnknownObserved {
			if events[cursor].Operation != "operation.phase" {
				return verdict{}, fmt.Errorf("Operation %d lacks its unknown History event", index+1)
			}
			value, decodeErr := decodeEventData[phaseData](events[cursor])
			if decodeErr != nil {
				return verdict{}, decodeErr
			}
			unknown = &value
			cursor++
		}
		if events[cursor].Operation != "operation.phase" {
			return verdict{}, fmt.Errorf("Operation %d lacks its success History event", index+1)
		}
		succeeded, decodeErr := decodeEventData[phaseData](events[cursor])
		if decodeErr != nil {
			return verdict{}, decodeErr
		}
		cursor++
		requestBody, marshalErr := json.Marshal(map[string]string{"effect_id": protectedCalls[index].EffectID})
		if marshalErr != nil {
			return verdict{}, marshalErr
		}
		expectedID := deriveSandboxOperationID(sandboxDomain, sandboxID, protectedCalls[index].CallID)
		expectedIDs = append(expectedIDs, expectedID)
		if err := checkPrepared(prepared, initial, expectedID, requestBody); err != nil {
			return verdict{}, err
		}
		if err := checkProgress(dispatched, unknown, succeeded, prepared.Operation); err != nil {
			return verdict{}, err
		}
		expectedSummary := operationSummary{
			CallID: protectedCalls[index].CallID, EffectID: protectedCalls[index].EffectID,
			OperationID: expectedID, Phase: "succeeded", ResultHash: succeeded.Update.ResultHash,
			RecoveredByQuery: unknown != nil, UnknownObserved: unknown != nil,
		}
		if summary.CallID == "" {
			expectedSummary.CallID, expectedSummary.EffectID = "", ""
		}
		if !reflect.DeepEqual(summary, expectedSummary) {
			return verdict{}, fmt.Errorf("adapter Operation summary %d does not match History", index+1)
		}
		if err := checkExternalCommit(payment[index], prepared.Operation, succeeded.Update, requestBody); err != nil {
			return verdict{}, err
		}
	}
	if cursor != len(events)-1 {
		return verdict{}, errors.New("History contains unclaimed Operation events")
	}
	prior := events[len(events)-2]
	if adapter.Control.CertificateHistory != (historyPoint{Sequence: prior.Sequence, Hash: prior.Hash}) {
		return verdict{}, errors.New("post-execution Certificate was not compiled at the final succeeded Operation head")
	}
	if err := checkFinalCutover(final, initial, adapter.Control, runtime, prior); err != nil {
		return verdict{}, err
	}
	return verdict{
		Schema: verdictSchema, Valid: true, HistorySequence: last.Sequence,
		OperationID: expectedIDs[0], ExternalCommits: len(payment),
		RepositoryEdit: runtime.RepositoryChange.BaseRoot != runtime.RepositoryChange.FinalRoot,
	}, nil
}

func readWorkloadContract(path string) (*workloadContract, error) {
	if path == "" {
		return nil, nil
	}
	contents, _, err := readOwnedFile(path, 1<<20, "workload contract")
	if err != nil {
		return nil, err
	}
	var value workloadContract
	if err := decodeStrict(contents, &value); err != nil {
		return nil, fmt.Errorf("workload contract: %w", err)
	}
	if value.Schema != 1 || value.Name == "" || !validDigest(value.PatchSHA256) ||
		value.FilePath == "" || len(value.RequiredSubstrings) == 0 ||
		len(value.ForbiddenSubstrings) == 0 || value.DeltaOperationCount < 1 ||
		value.ValidationCommand == "" || strings.IndexByte(value.ValidationCommand, 0) >= 0 ||
		hashBytes([]byte(value.ValidationCommand)) != value.ValidationCommandSHA256 ||
		!validDigest(value.ValidationCommandSHA256) || !validDigest(value.EsbuildSHA256) ||
		!validDigest(value.ShellSHA256) {
		return nil, errors.New("workload contract is malformed")
	}
	return &value, nil
}

func checkAppServerRecords(contents []byte, preflight preflightSummary) error {
	lines := bytes.Split(contents, []byte{'\n'})
	if len(lines) == 0 || len(lines[len(lines)-1]) != 0 {
		return errors.New("App Server JSONL must end with one newline")
	}
	lines = lines[:len(lines)-1]
	if len(lines) != preflight.RawRecordCount {
		return errors.New("App Server JSONL record count differs from the preflight summary")
	}
	structuredCallbacks := len(preflight.ProtectedCalls) > 0
	protectedCalls := preflight.ProtectedCalls
	if len(protectedCalls) == 0 {
		protectedCalls = []protectedCallSummary{{CallID: preflight.CallID, EffectID: preflight.EffectID}}
	}
	var editSequence, validationSequence uint64
	var editOccurrences, validationOccurrences int
	callbackSequences := make([]uint64, 0, len(protectedCalls))
	callbackResponses := make(map[string]int, len(protectedCalls))
	seenExternalBoundary := false
	for index, line := range lines {
		if len(line) == 0 {
			return errors.New("App Server JSONL contains an empty record")
		}
		var record appServerRecord
		if err := decodeStrict(line, &record); err != nil {
			return fmt.Errorf("App Server JSONL record %d: %w", index+1, err)
		}
		if record.Sequence != uint64(index+1) || record.Direction == "" || record.TimeNS <= 0 {
			return fmt.Errorf("App Server JSONL record %d has invalid metadata", index+1)
		}
		payload, err := decodeJSONObject(record.Payload)
		if err != nil {
			return fmt.Errorf("App Server JSONL payload %d: %w", index+1, err)
		}
		method, _ := payload["method"].(string)
		params, _ := payload["params"].(map[string]any)
		if record.Direction == "client_to_server" && method == "turn/start" && params != nil &&
			stringValue(params, "threadId") == preflight.ForkThreadID &&
			stringValue(params, "approvalPolicy") == "never" {
			policy, _ := params["sandboxPolicy"].(map[string]any)
			seenExternalBoundary = policy != nil && stringValue(policy, "type") == "externalSandbox" &&
				stringValue(policy, "networkAccess") == "restricted"
		}
		if record.Direction == "server_to_client" && method == "item/completed" && params != nil &&
			stringValue(params, "threadId") == preflight.ForkThreadID &&
			stringValue(params, "turnId") == preflight.ProtectedTurnID {
			item, _ := params["item"].(map[string]any)
			changes, _ := item["changes"].([]any)
			if item != nil && preflight.WorkspaceEditCallID != "" &&
				stringValue(item, "id") == preflight.WorkspaceEditCallID {
				editOccurrences++
				if stringValue(item, "type") == "fileChange" &&
					stringValue(item, "status") == "completed" && len(changes) > 0 {
					editSequence = record.Sequence
				}
			}
			if item != nil && preflight.WorkspaceValidationCallID != "" &&
				stringValue(item, "id") == preflight.WorkspaceValidationCallID {
				validationOccurrences++
				actions, _ := item["commandActions"].([]any)
				var validationCommand string
				if len(actions) == 1 {
					action, _ := actions[0].(map[string]any)
					validationCommand = stringValue(action, "command")
				}
				if stringValue(item, "type") == "commandExecution" &&
					stringValue(item, "status") == "completed" && jsonNumberIsZero(item["exitCode"]) &&
					strings.HasPrefix(stringValue(item, "command"), "/opt/codex/bin/sh -c ") &&
					hashBytes([]byte(validationCommand)) == preflight.WorkspaceValidationCommandHash {
					validationSequence = record.Sequence
				}
			}
		}
		if record.Direction == "server_to_client" && method == "item/tool/call" && params != nil &&
			stringValue(params, "threadId") == preflight.ForkThreadID &&
			stringValue(params, "turnId") == preflight.ProtectedTurnID &&
			stringValue(params, "tool") == operationKind {
			position := len(callbackSequences)
			if position >= len(protectedCalls) {
				return errors.New("App Server JSONL contains an extra protected callback")
			}
			expected := protectedCalls[position]
			arguments, _ := params["arguments"].(map[string]any)
			if stringValue(params, "callId") != expected.CallID ||
				(structuredCallbacks && (arguments == nil || stringValue(arguments, "effect_id") != expected.EffectID)) ||
				(len(expected.RequestID) > 0 && !rawJSONMatchesValue(expected.RequestID, payload["id"])) {
				return errors.New("App Server JSONL protected callbacks differ from their ordered summary")
			}
			callbackSequences = append(callbackSequences, record.Sequence)
		}
		if record.Direction == "client_to_server" && method == "" && payload["result"] != nil {
			for _, expected := range protectedCalls {
				if len(expected.RequestID) > 0 && rawJSONMatchesValue(expected.RequestID, payload["id"]) {
					callbackResponses[expected.CallID]++
				}
			}
		}
	}
	if len(callbackSequences) != len(protectedCalls) {
		return errors.New("App Server JSONL does not contain every ordered protected callback")
	}
	for _, expected := range protectedCalls {
		if len(expected.RequestID) > 0 && callbackResponses[expected.CallID] != 1 {
			return errors.New("App Server JSONL does not contain exactly one response per protected callback")
		}
	}
	firstCallbackSequence := callbackSequences[0]
	if preflight.WorkspaceEditCallID != "" &&
		(!seenExternalBoundary || editSequence == 0 || editOccurrences != 1 || editSequence >= firstCallbackSequence) {
		return errors.New("App Server JSONL does not place a completed native edit before the protected callback")
	}
	if preflight.WorkspaceValidationCallID != "" &&
		(validationSequence == 0 || validationOccurrences != 1 || editSequence == 0 || editSequence >= validationSequence ||
			validationSequence >= firstCallbackSequence) {
		return errors.New("App Server JSONL does not place a successful workspace validation between edit and protected callback")
	}
	return nil
}

func rawJSONMatchesValue(raw json.RawMessage, value any) bool {
	encoded, err := json.Marshal(value)
	return err == nil && bytes.Equal(raw, encoded)
}

func jsonNumberIsZero(value any) bool {
	number, ok := value.(json.Number)
	return ok && number.String() == "0"
}

func decodeJSONObject(contents []byte) (map[string]any, error) {
	if err := rejectDuplicateKeys(contents); err != nil {
		return nil, err
	}
	decoder := json.NewDecoder(bytes.NewReader(contents))
	decoder.UseNumber()
	var value map[string]any
	if err := decoder.Decode(&value); err != nil {
		return nil, err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return nil, errors.New("multiple JSON values")
		}
		return nil, err
	}
	if value == nil {
		return nil, errors.New("JSON value is not an object")
	}
	return value, nil
}

func stringValue(value map[string]any, key string) string {
	result, _ := value[key].(string)
	return result
}

func checkCheckpoint(contents []byte, runtime runtimeResult) error {
	var value checkpointEvidence
	if err := decodeStrict(contents, &value); err != nil {
		return fmt.Errorf("checkpoint: %w", err)
	}
	canonical, err := json.Marshal(value)
	if err != nil || !bytes.Equal(canonical, bytes.TrimSuffix(contents, []byte{'\n'})) {
		return errors.New("checkpoint is not canonical JSON")
	}
	if value.Schema != 1 || value.SessionID != runtime.SessionID ||
		!validLowerHex(value.SourceInstanceID, 16) || !validLowerHex(value.RestoredInstanceID, 16) ||
		value.SourceInstanceID == value.RestoredInstanceID || value.CodexSHA256 != runtime.CodexSHA256 ||
		value.ArgumentsSHA256 != runtime.ArgumentsSHA256 ||
		value.RepositoryTreeRoot != runtime.RepositoryChange.BaseRoot || len(value.StreamCheckpoint) == 0 ||
		value.RepositoryBundle != runtime.Artifacts["repository"] ||
		value.SnapshotState != runtime.Artifacts["snapshot_state"] ||
		value.SnapshotMemory != runtime.Artifacts["snapshot_memory"] {
		return errors.New("checkpoint does not bind the exact source/restored VMs and runtime inputs")
	}
	return nil
}

func checkInitialCutover(value cutoverData, summary sandboxBinding, operationCount int, queryable bool) error {
	if value.SemanticVersion != 1 || len(value.Bindings) != 1 || len(value.Repositories) != 0 ||
		!reflect.DeepEqual(value.Bindings[0], summary) || !validBinding(summary, 1) {
		return errors.New("initial Cutover does not bind exactly one source Firecracker instance")
	}
	certificate := value.Certificate
	if certificate.Schema != 1 || certificate.Decision != "activate" ||
		certificate.History != (historyPoint{Hash: emptyHistoryHash}) || certificate.FromRule != 0 ||
		certificate.Rule == nil || certificate.Rule.Version != 1 ||
		!reflect.DeepEqual(certificate.Rule.Allow, []string{operationKind}) || certificate.Witness != nil ||
		certificate.Requirement.ID != "firecracker-codex-before" {
		return errors.New("initial Certificate has the wrong rule or History point")
	}
	if err := checkRequirement(certificate.Requirement, operationCount, queryable); err != nil {
		return fmt.Errorf("initial Certificate: %w", err)
	}
	return checkCertificateDigests(certificate)
}

func checkPrepared(value prepareData, initial cutoverData, expectedID string, body []byte) error {
	op := value.Operation
	spec := initial.Certificate.Requirement.Kinds[operationKind]
	target := spec.Target
	requestHash := operationRequestHash("POST", target, map[string]string{
		"Accept-Encoding": "identity",
		"Idempotency-Key": expectedID,
		"User-Agent":      "safe-change-runtime/1",
		"X-Operation-ID":  expectedID,
	}, body)
	if value.SemanticVersion != 1 || op.ID != expectedID || op.Domain != sandboxDomain ||
		op.SandboxID != sandboxID || op.Kind != operationKind || op.RequestHash != requestHash ||
		op.RuleVersion != 1 || !reflect.DeepEqual(op.Costs, spec.Costs) ||
		!reflect.DeepEqual(op.Produces, spec.Produces) || op.RetrySafe != spec.RetrySafe || op.Queryable != spec.Queryable ||
		op.Target != target || op.Method != spec.Method || op.ResponseClassifier != spec.ResponseClassifier ||
		op.QueryTarget != spec.QueryTarget || op.QueryMethod != spec.QueryMethod || op.QueryClassifier != spec.QueryClassifier || !op.RequestStored ||
		len(op.RequestHeaders) != 0 ||
		!bytes.Equal(op.RequestBody, body) || op.Phase != "prepared" || op.ResultHash != "" ||
		op.StatusCode != 0 || len(op.ResultBody) != 0 || op.RemoteReference != "" ||
		op.DispatchOwner != "" || op.DispatchGeneration != 0 || op.Settlement != "" {
		return errors.New("prepared Operation is not the VM-bound protected callback")
	}
	return nil
}

func checkProgress(dispatched phaseData, unknown *phaseData, succeeded phaseData, prepared operation) error {
	if dispatched.SemanticVersion != 1 || dispatched.ID != prepared.ID ||
		dispatched.Update.Phase != "dispatched" || !validLowerHex(dispatched.Update.DispatchOwner, 16) ||
		dispatched.Update.DispatchGeneration != 1 || dispatched.Update.ResultHash != "" ||
		dispatched.Update.StatusCode != 0 || len(dispatched.Update.ResultBody) != 0 ||
		dispatched.Update.RemoteReference != "" || dispatched.Update.Settlement != "" {
		return errors.New("History event is not the Operation's first durable dispatch")
	}
	if unknown != nil && (unknown.SemanticVersion != 1 || unknown.ID != prepared.ID ||
		unknown.Update.Phase != "unknown" || unknown.Update.ResultHash != "" || unknown.Update.StatusCode != 0 ||
		len(unknown.Update.ResultBody) != 0 || unknown.Update.RemoteReference != "" ||
		unknown.Update.DispatchOwner != "" || unknown.Update.DispatchGeneration != 0 || unknown.Update.Settlement != "") {
		return errors.New("History event is not the definitive unknown outcome")
	}
	expectedSettlement := ""
	if unknown != nil {
		expectedSettlement = "query"
	}
	if succeeded.SemanticVersion != 1 || succeeded.ID != prepared.ID ||
		succeeded.Update.Phase != "succeeded" || !validDigest(succeeded.Update.ResultHash) ||
		succeeded.Update.StatusCode != 200 || len(succeeded.Update.ResultBody) == 0 ||
		succeeded.Update.RemoteReference == "" || succeeded.Update.DispatchOwner != "" ||
		succeeded.Update.DispatchGeneration != 0 || succeeded.Update.Settlement != expectedSettlement {
		return errors.New("History event is not one definitive success with the expected settlement source")
	}
	return nil
}

func checkExternalCommit(payment paymentRecord, prepared operation, update operationUpdate, body []byte) error {
	expectedRequestHash := paymentRequestHash("POST", "/v1/charge", body)
	expectedResultHash := hashBytes([]byte("charged\x00" + prepared.ID))
	expectedReference := "firecracker-codex/" + prepared.ID
	if payment.OperationID != prepared.ID || payment.Path != "/v1/charge" ||
		payment.RequestHash != expectedRequestHash || payment.ResultHash != expectedResultHash ||
		payment.RemoteReference != expectedReference || update.ResultHash != payment.ResultHash ||
		update.RemoteReference != payment.RemoteReference {
		return errors.New("external durable commit does not match the succeeded Operation")
	}
	if update.Settlement == "query" {
		var response observation
		if err := decodeStrict(update.ResultBody, &response); err != nil {
			return fmt.Errorf("Operation observation: %w", err)
		}
		if response.Schema != 1 || response.OperationID != prepared.ID || response.RequestHash != prepared.RequestHash ||
			response.Outcome != "succeeded" || response.FactHash != payment.ResultHash ||
			response.RemoteReference != payment.RemoteReference {
			return errors.New("stored Operation observation does not match the external commit")
		}
	} else {
		var response receipt
		if err := decodeStrict(update.ResultBody, &response); err != nil {
			return fmt.Errorf("Operation receipt: %w", err)
		}
		if response.Schema != 1 || response.OperationID != prepared.ID || response.Outcome != "succeeded" ||
			response.ResultHash != payment.ResultHash || response.RemoteReference != payment.RemoteReference {
			return errors.New("stored Operation receipt does not match the external commit")
		}
	}
	return nil
}

func checkFinalCutover(value cutoverData, initial cutoverData, summary controlSummary, runtime runtimeResult, prior storedEvent) error {
	if value.SemanticVersion != 2 || len(value.Bindings) != 1 || len(value.Repositories) != 1 ||
		!reflect.DeepEqual(value.Bindings[0], summary.TargetBinding) || !validBinding(summary.TargetBinding, 2) ||
		summary.TargetBinding.HostInstanceID == summary.SourceBinding.HostInstanceID {
		return errors.New("final Cutover does not replace the Firecracker binding")
	}
	certificate := value.Certificate
	expectedRequirement := initial.Certificate.Requirement
	expectedRequirement.ID = "firecracker-codex-after"
	if certificate.Schema != 1 || certificate.Decision != "activate" || certificate.FromRule != 1 ||
		certificate.History != (historyPoint{Sequence: prior.Sequence, Hash: prior.Hash}) ||
		!reflect.DeepEqual(certificate.Requirement, expectedRequirement) || certificate.Rule == nil ||
		certificate.Rule.Version != 2 || certificate.Rule.Allow == nil || len(certificate.Rule.Allow) != 0 ||
		certificate.Witness != nil {
		return errors.New("final Certificate is not bound to the succeeded Operation head")
	}
	if err := checkCertificateDigests(certificate); err != nil {
		return err
	}
	repository := value.Repositories[0]
	if repository != summary.Repository || repository.SandboxID != sandboxID ||
		repository.SourceGeneration != summary.SourceBinding.Generation ||
		repository.SourceHostID != summary.SourceBinding.HostInstanceID ||
		repository.BaseRoot != summary.SourceBinding.RepositoryRoot ||
		repository.FinalRoot != summary.TargetBinding.RepositoryRoot ||
		repository.BaseRoot != runtime.RepositoryChange.BaseRoot ||
		repository.FinalRoot != runtime.RepositoryChange.FinalRoot || runtime.RepositoryChange.OperationCount < 0 {
		return errors.New("repository Cutover record does not join the source and replacement bindings")
	}
	for _, digest := range []string{
		repository.CheckpointSHA256, repository.BaseRoot, repository.FinalRoot,
		repository.FinalBundleSHA256, repository.DeltaSHA256,
	} {
		if !validDigest(digest) {
			return errors.New("repository Cutover contains an invalid digest")
		}
	}
	checkpoint := runtime.Artifacts["checkpoint"]
	finalBundle := runtime.Artifacts["repository_final"]
	delta := runtime.Artifacts["repository_delta"]
	if repository.CheckpointSHA256 != checkpoint.SHA256 ||
		repository.FinalBundleSHA256 != finalBundle.SHA256 || repository.FinalBundleSize != uint64(finalBundle.Size) ||
		repository.DeltaSHA256 != delta.SHA256 || repository.DeltaSize != uint64(delta.Size) {
		return errors.New("final History event does not bind the retained repository artifacts")
	}
	return nil
}

func checkRequirement(value requirement, operationCount int, queryable bool) error {
	count := uint32(operationCount)
	if !reflect.DeepEqual(value.Results, map[string]uint32{resultName: count}) ||
		!reflect.DeepEqual(value.Capacities, map[string]uint32{capacityName: count}) || len(value.Kinds) != 1 {
		return errors.New("Requirement has the wrong result or capacity")
	}
	spec, ok := value.Kinds[operationKind]
	if !ok || !reflect.DeepEqual(spec.Costs, map[string]uint32{capacityName: 1}) ||
		!reflect.DeepEqual(spec.Produces, map[string]uint32{resultName: 1}) || spec.RetrySafe == queryable ||
		spec.Queryable != queryable || spec.Method != "POST" || spec.ResponseClassifier != responseClassifier {
		return errors.New("Requirement has the wrong Operation contract")
	}
	parsed, err := url.Parse(spec.Target)
	if err != nil || parsed.Scheme != "http" || parsed.Hostname() != "127.0.0.1" ||
		parsed.Port() == "" || parsed.Path != "/v1/charge" || parsed.RawQuery != "" || parsed.Fragment != "" ||
		parsed.User != nil {
		return errors.New("Requirement target is not one credential-free loopback payment endpoint")
	}
	if queryable {
		query, err := url.Parse(spec.QueryTarget)
		if err != nil || query.Scheme != parsed.Scheme || query.Host != parsed.Host || query.Path != "/v1/query" ||
			query.RawQuery != "" || query.Fragment != "" || query.User != nil || spec.QueryMethod != "POST" ||
			spec.QueryClassifier != queryClassifier {
			return errors.New("Requirement query contract is not the matching loopback observer")
		}
	} else if spec.QueryTarget != "" || spec.QueryMethod != "" || spec.QueryClassifier != "" {
		return errors.New("non-queryable Requirement carries a query contract")
	}
	return nil
}

func checkCertificateDigests(value certificate) error {
	if value.Rule == nil {
		return errors.New("activate Certificate has no Rule")
	}
	requirementBytes, err := json.Marshal(value.Requirement)
	if err != nil {
		return err
	}
	if value.Rule.RequirementHash != hashBytes(requirementBytes) {
		return errors.New("Rule does not bind its Requirement")
	}
	want := value.Digest
	value.Digest = ""
	certificateBytes, err := json.Marshal(value)
	if err != nil {
		return err
	}
	if !validDigest(want) || want != hashBytes(certificateBytes) {
		return errors.New("Certificate digest does not match its complete contents")
	}
	return nil
}

func validBinding(value sandboxBinding, generation uint64) bool {
	return value.SandboxID == sandboxID && value.Generation == generation &&
		validHostID(value.HostInstanceID) && value.Domain == sandboxDomain &&
		reflect.DeepEqual(value.AllowedKinds, []string{operationKind}) && validDigest(value.RepositoryRoot)
}

func validHostID(value string) bool {
	return strings.HasPrefix(value, "host-") && validLowerHex(strings.TrimPrefix(value, "host-"), 16)
}

func readHistory(path string) ([]storedEvent, error) {
	contents, _, err := readPrivateFile(path, maxEvidenceFile, "History")
	if err != nil {
		return nil, err
	}
	var events []storedEvent
	previous := emptyHistoryHash
	for offset := 0; offset < len(contents); {
		if len(contents)-offset < historyHeaderBytes {
			return nil, errors.New("History ends with a partial frame header")
		}
		header := contents[offset : offset+historyHeaderBytes]
		offset += historyHeaderBytes
		if !bytes.Equal(header[:4], historyMagic[:]) {
			return nil, errors.New("History frame marker is invalid")
		}
		length := binary.BigEndian.Uint64(header[4:])
		if length == 0 || length > maxHistoryFrame || uint64(len(contents)-offset) < length {
			return nil, errors.New("History frame length is invalid or incomplete")
		}
		payload := contents[offset : offset+int(length)]
		offset += int(length)
		var event storedEvent
		if err := decodeStrict(payload, &event); err != nil {
			return nil, fmt.Errorf("History event %d: %w", len(events)+1, err)
		}
		canonical, err := json.Marshal(event)
		if err != nil || !bytes.Equal(canonical, payload) {
			return nil, fmt.Errorf("History event %d is not canonical JSON", len(events)+1)
		}
		if event.Version != historyFormat || event.Sequence != uint64(len(events)+1) || event.Operation == "" ||
			event.PreviousHash != previous || !validDigest(event.Hash) || event.Hash != hashEvent(event) {
			return nil, fmt.Errorf("History event %d fails its sequence or hash chain", len(events)+1)
		}
		previous = event.Hash
		events = append(events, event)
	}
	if len(events) == 0 {
		return nil, errors.New("History is empty")
	}
	return events, nil
}

func readAnchor(path string) (anchorRecord, error) {
	contents, _, err := readPrivateFile(path, 4096, "head anchor")
	if err != nil {
		return anchorRecord{}, err
	}
	var record anchorRecord
	if err := decodeStrict(contents, &record); err != nil {
		return anchorRecord{}, fmt.Errorf("head anchor: %w", err)
	}
	canonical, err := json.Marshal(record)
	if err != nil {
		return anchorRecord{}, err
	}
	canonical = append(canonical, '\n')
	if !bytes.Equal(canonical, contents) || record.Version != 1 || record.Sequence == 0 ||
		!validDigest(record.Hash) || record.Checksum != anchorChecksum(record.Sequence, record.Hash) {
		return anchorRecord{}, errors.New("head anchor is not canonical or its checksum is invalid")
	}
	return record, nil
}

func readPayments(path string, expected int) ([]paymentRecord, error) {
	contents, _, err := readPrivateFile(path, maxEvidenceFile, "payment history")
	if err != nil {
		return nil, err
	}
	lines := bytes.Split(contents, []byte{'\n'})
	if expected < 1 || len(lines) != expected+1 || len(lines[len(lines)-1]) != 0 {
		return nil, fmt.Errorf("payment history must contain exactly %d durable commits", expected)
	}
	records := make([]paymentRecord, 0, expected)
	for index, line := range lines[:len(lines)-1] {
		if len(line) == 0 {
			return nil, errors.New("payment history contains an empty record")
		}
		var record paymentRecord
		if err := decodeStrict(line, &record); err != nil {
			return nil, fmt.Errorf("payment history record %d: %w", index+1, err)
		}
		canonical, err := json.Marshal(record)
		if err != nil || !bytes.Equal(canonical, line) {
			return nil, fmt.Errorf("payment history record %d is not canonical JSON", index+1)
		}
		records = append(records, record)
	}
	return records, nil
}

func boolInt(value bool) int {
	if value {
		return 1
	}
	return 0
}

func decodeEventData[T any](event storedEvent) (T, error) {
	var value T
	if err := decodeStrict(event.Data, &value); err != nil {
		return value, fmt.Errorf("History event %d data: %w", event.Sequence, err)
	}
	canonical, err := json.Marshal(value)
	if err != nil || !bytes.Equal(canonical, event.Data) {
		return value, fmt.Errorf("History event %d data is not canonical", event.Sequence)
	}
	return value, nil
}

func hashEvent(event storedEvent) string {
	digest := sha256.New()
	_, _ = digest.Write([]byte("history-event-v1\x00"))
	var sequence [8]byte
	binary.BigEndian.PutUint64(sequence[:], event.Sequence)
	_, _ = digest.Write(sequence[:])
	writeHashPart(digest, []byte(event.PreviousHash))
	writeHashPart(digest, []byte(event.Operation))
	writeHashPart(digest, event.Data)
	return hex.EncodeToString(digest.Sum(nil))
}

func writeHashPart(writer io.Writer, value []byte) {
	var length [8]byte
	binary.BigEndian.PutUint64(length[:], uint64(len(value)))
	_, _ = writer.Write(length[:])
	_, _ = writer.Write(value)
}

func anchorChecksum(sequence uint64, hash string) string {
	digest := sha256.New()
	_, _ = digest.Write([]byte("history-head-anchor-v1\x00"))
	var number [8]byte
	binary.BigEndian.PutUint64(number[:], sequence)
	_, _ = digest.Write(number[:])
	_, _ = digest.Write([]byte(hash))
	return hex.EncodeToString(digest.Sum(nil))
}

func deriveSandboxOperationID(domain, sandbox, callID string) string {
	digest := sha256.New()
	_, _ = digest.Write([]byte("sandbox-operation-id-v2\x00"))
	_, _ = digest.Write([]byte(domain))
	_, _ = digest.Write([]byte{0})
	_, _ = digest.Write([]byte(sandbox))
	_, _ = digest.Write([]byte{0})
	_, _ = digest.Write([]byte(callID))
	return "op-" + hex.EncodeToString(digest.Sum(nil))
}

func operationRequestHash(method, target string, headers map[string]string, body []byte) string {
	type pair struct{ name, value string }
	pairs := make([]pair, 0, len(headers))
	for name, value := range headers {
		pairs = append(pairs, pair{name: strings.ToLower(name), value: value})
	}
	sort.Slice(pairs, func(left, right int) bool {
		if pairs[left].name != pairs[right].name {
			return pairs[left].name < pairs[right].name
		}
		return pairs[left].value < pairs[right].value
	})
	digest := sha256.New()
	_, _ = io.WriteString(digest, method)
	_, _ = digest.Write([]byte{0})
	_, _ = io.WriteString(digest, target)
	_, _ = digest.Write([]byte{0})
	for _, item := range pairs {
		_, _ = io.WriteString(digest, item.name)
		_, _ = digest.Write([]byte{':'})
		_, _ = io.WriteString(digest, item.value)
		_, _ = digest.Write([]byte{0})
	}
	_, _ = digest.Write(body)
	return hex.EncodeToString(digest.Sum(nil))
}

func paymentRequestHash(method, path string, body []byte) string {
	digest := sha256.New()
	_, _ = io.WriteString(digest, method)
	_, _ = digest.Write([]byte{0})
	_, _ = io.WriteString(digest, path)
	_, _ = digest.Write([]byte{0})
	_, _ = digest.Write(body)
	return hex.EncodeToString(digest.Sum(nil))
}

func matchFileSummary(summary fileSummary, info os.FileInfo, contents []byte) error {
	if summary.Size != info.Size() || summary.SHA256 != hashBytes(contents) || !validDigest(summary.SHA256) {
		return errors.New("size or SHA-256 differs")
	}
	return nil
}

func hashBytes(contents []byte) string {
	digest := sha256.Sum256(contents)
	return hex.EncodeToString(digest[:])
}

func validDigest(value string) bool {
	return validLowerHex(value, sha256.Size)
}

func validLowerHex(value string, bytesLength int) bool {
	if len(value) != bytesLength*2 {
		return false
	}
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == bytesLength && hex.EncodeToString(decoded) == value
}

func validatePrivateDirectory(path, label string) (string, error) {
	canonical, err := canonicalPath(path, label)
	if err != nil {
		return "", err
	}
	info, err := os.Lstat(canonical)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 ||
		info.Mode().Perm() != privateDirectoryMode || ownerUID(info) != os.Geteuid() {
		return "", fmt.Errorf("%s must be a current-user directory with mode 0700", label)
	}
	return canonical, nil
}

func canonicalPath(path, label string) (string, error) {
	if path == "" || !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return "", fmt.Errorf("%s path must be absolute and canonical", label)
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil || resolved != path {
		return "", fmt.Errorf("%s path must not traverse symlinks", label)
	}
	return path, nil
}

func readPrivateFile(path string, limit int64, label string) ([]byte, os.FileInfo, error) {
	canonical, err := canonicalPath(path, label)
	if err != nil {
		return nil, nil, err
	}
	descriptor, err := syscall.Open(canonical, syscall.O_RDONLY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return nil, nil, fmt.Errorf("open %s: %w", label, err)
	}
	file := os.NewFile(uintptr(descriptor), canonical)
	if file == nil {
		_ = syscall.Close(descriptor)
		return nil, nil, fmt.Errorf("open %s: create file handle", label)
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm() != privateFileMode ||
		ownerUID(info) != os.Geteuid() || info.Size() <= 0 || info.Size() > limit {
		return nil, nil, fmt.Errorf("%s must be a nonempty current-user file with mode 0600 within %d bytes", label, limit)
	}
	pathInfo, err := os.Lstat(canonical)
	if err != nil || !os.SameFile(info, pathInfo) {
		return nil, nil, fmt.Errorf("%s path changed while opening", label)
	}
	contents, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil || int64(len(contents)) != info.Size() {
		return nil, nil, fmt.Errorf("read stable %s", label)
	}
	return contents, info, nil
}

func readOwnedFile(path string, limit int64, label string) ([]byte, os.FileInfo, error) {
	canonical, err := canonicalPath(path, label)
	if err != nil {
		return nil, nil, err
	}
	descriptor, err := syscall.Open(canonical, syscall.O_RDONLY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return nil, nil, fmt.Errorf("open %s: %w", label, err)
	}
	file := os.NewFile(uintptr(descriptor), canonical)
	if file == nil {
		_ = syscall.Close(descriptor)
		return nil, nil, fmt.Errorf("open %s: create file handle", label)
	}
	defer file.Close()
	info, err := file.Stat()
	mode := infoMode(info)
	if err != nil || info == nil || !mode.IsRegular() ||
		(mode.Perm() != 0o600 && mode.Perm() != 0o644) || ownerUID(info) != os.Geteuid() ||
		info.Size() <= 0 || info.Size() > limit {
		return nil, nil, fmt.Errorf("%s must be a nonempty current-user file with mode 0600 or 0644 within %d bytes", label, limit)
	}
	pathInfo, err := os.Lstat(canonical)
	if err != nil || !os.SameFile(info, pathInfo) {
		return nil, nil, fmt.Errorf("%s path changed while opening", label)
	}
	contents, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil || int64(len(contents)) != info.Size() {
		return nil, nil, fmt.Errorf("read stable %s", label)
	}
	return contents, info, nil
}

func infoMode(info os.FileInfo) os.FileMode {
	if info == nil {
		return 0
	}
	return info.Mode()
}

func ownerUID(info os.FileInfo) int {
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return -1
	}
	return int(stat.Uid)
}

func overlaps(left, right string) bool {
	return left == right || strings.HasPrefix(left, right+string(filepath.Separator)) ||
		strings.HasPrefix(right, left+string(filepath.Separator))
}

func decodeStrict(data []byte, target any) error {
	if err := rejectDuplicateKeys(data); err != nil {
		return err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("multiple JSON values")
		}
		return err
	}
	return nil
}

func rejectDuplicateKeys(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	if err := walkJSON(decoder); err != nil {
		return err
	}
	if _, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("multiple JSON values")
		}
		return err
	}
	return nil
}

func walkJSON(decoder *json.Decoder) error {
	token, err := decoder.Token()
	if err != nil {
		return err
	}
	delimiter, ok := token.(json.Delim)
	if !ok {
		return nil
	}
	switch delimiter {
	case '{':
		seen := make(map[string]struct{})
		for decoder.More() {
			keyToken, err := decoder.Token()
			if err != nil {
				return err
			}
			key, ok := keyToken.(string)
			if !ok {
				return errors.New("JSON object key is not a string")
			}
			if _, exists := seen[key]; exists {
				return fmt.Errorf("duplicate JSON key %q", key)
			}
			seen[key] = struct{}{}
			if err := walkJSON(decoder); err != nil {
				return err
			}
		}
		end, err := decoder.Token()
		if err != nil || end != json.Delim('}') {
			return errors.New("invalid JSON object end")
		}
	case '[':
		for decoder.More() {
			if err := walkJSON(decoder); err != nil {
				return err
			}
		}
		end, err := decoder.Token()
		if err != nil || end != json.Delim(']') {
			return errors.New("invalid JSON array end")
		}
	default:
		return errors.New("invalid JSON delimiter")
	}
	return nil
}
