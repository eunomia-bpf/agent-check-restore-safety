// Command check-firecracker-codex-evidence independently verifies the
// retained evidence from one firecracker-codex-shim snapshot/restore run.
// It intentionally imports no shim lifecycle implementation. The repository
// wire-format package is shared so the producer and checker agree on the one
// canonical byte representation while all hashes and bindings are recomputed.
package main

import (
	"bufio"
	"bytes"
	"crypto/sha256"
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
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repobundle"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repodelta"
)

const (
	verdictSchema      = 1
	resultSchema       = 1
	eventSchema        = 1
	payloadSchema      = 1
	manifestSchema     = 1
	streamPort         = uint32(7000)
	firstGeneration    = uint64(1)
	restoredGeneration = uint64(3)
	guestWorkspace     = "/workspace"
	payloadDrive       = "/dev/vda"
	repositoryDrive    = "/dev/vdb"
	fdKernel           = "/proc/self/fd/4"
	fdInitramfs        = "/proc/self/fd/5"
	fdPayload          = "/proc/self/fd/6"
	fdRepository       = "/proc/self/fd/7"
	maxJSONBytes       = int64(128 << 20)
	maxJSONLLines      = 1 << 20
	immutableSeals     = 15
)

type options struct {
	evidence, adapterJSONL, payload, payloadResult, runner string
}

type verdict struct {
	Schema int    `json:"schema"`
	Valid  bool   `json:"valid"`
	Error  string `json:"error,omitempty"`
}

type artifact struct {
	Name   string `json:"name"`
	Size   int64  `json:"size"`
	Mode   uint32 `json:"mode"`
	SHA256 string `json:"sha256"`
}

type sealedArtifact struct {
	Artifact   artifact `json:"artifact"`
	ChildFD    int      `json:"child_fd"`
	LinuxSeals int      `json:"linux_seals"`
}

type socketRecord struct {
	Path   string `json:"path"`
	Device uint64 `json:"device"`
	Inode  uint64 `json:"inode"`
	Mode   uint32 `json:"mode"`
	UID    uint32 `json:"uid"`
}

type processRecord struct {
	Generation       uint64       `json:"generation"`
	ID               string       `json:"id"`
	PID              int          `json:"pid"`
	Executable       string       `json:"executable"`
	ExecutableSHA256 string       `json:"executable_sha256"`
	Device           uint64       `json:"device"`
	Inode            uint64       `json:"inode"`
	StartTimeTicks   uint64       `json:"start_time_ticks"`
	VMMVersion       string       `json:"vmm_version"`
	StartedTimeNS    int64        `json:"started_time_ns"`
	StoppedTimeNS    int64        `json:"stopped_time_ns"`
	Termination      string       `json:"termination"`
	APISocket        socketRecord `json:"api_socket"`
	VsockBackend     socketRecord `json:"vsock_backend"`
}

type workspaceMapping struct {
	Host  string `json:"host"`
	Guest string `json:"guest"`
}

type position struct {
	Offset uint64 `json:"offset"`
	Bytes  uint64 `json:"bytes"`
	Hash   string `json:"hash"`
}

type transcriptState struct {
	HostToGuest position `json:"host_to_guest"`
	GuestToHost position `json:"guest_to_host"`
}

type barrier struct {
	SessionID  string          `json:"session_id"`
	Generation uint64          `json:"generation"`
	State      transcriptState `json:"state"`
}

type checkpoint struct {
	HostBarrier  barrier `json:"HostBarrier"`
	GuestBarrier barrier `json:"GuestBarrier"`
}

type resultRecord struct {
	Schema                  int                 `json:"schema"`
	Success                 bool                `json:"success"`
	SessionID               string              `json:"session_id"`
	CodexSHA256             string              `json:"codex_sha256"`
	RunnerSHA256            string              `json:"runner_sha256"`
	ArgumentsSHA256         string              `json:"arguments_sha256"`
	ArgumentsEncoding       string              `json:"arguments_encoding"`
	ArgumentsCount          int                 `json:"arguments_count"`
	WorkspaceMapping        workspaceMapping    `json:"workspace_mapping"`
	Artifacts               map[string]artifact `json:"artifacts"`
	SealedBootInputs        []sealedArtifact    `json:"sealed_boot_inputs"`
	SealedLoadInputs        []sealedArtifact    `json:"sealed_load_inputs"`
	Checkpoint              checkpoint          `json:"checkpoint"`
	Processes               []processRecord     `json:"processes"`
	G1SIGKILLConfirmed      bool                `json:"g1_sigkill_confirmed"`
	SnapshotLoadedPaused    bool                `json:"snapshot_loaded_paused"`
	RelayArmedBeforeResume  bool                `json:"relay_armed_before_resume"`
	ToolReleasedAfterAttach bool                `json:"tool_released_after_g3_attach"`
	CompletedTimeNS         int64               `json:"completed_time_ns"`
}

type guestConfig struct {
	Schema             int      `json:"schema"`
	SessionID          string   `json:"session_id"`
	CodexSHA256        string   `json:"codex_sha256"`
	Arguments          []string `json:"arguments"`
	StreamPort         uint32   `json:"stream_port"`
	ModelPort          uint32   `json:"model_port"`
	PayloadDrive       string   `json:"payload_drive"`
	RepositoryDrive    string   `json:"repository_drive"`
	RepositorySize     uint64   `json:"repository_size"`
	RepositorySHA256   string   `json:"repository_sha256"`
	RepositoryTreeRoot string   `json:"repository_tree_root"`
}

type manifestEntry struct {
	Path       string `json:"path"`
	Type       string `json:"type"`
	Mode       uint32 `json:"mode"`
	Size       int64  `json:"size"`
	SHA256     string `json:"sha256"`
	LinkTarget string `json:"link_target"`
}

type manifest struct {
	Schema  int             `json:"schema"`
	Entries []manifestEntry `json:"entries"`
}

type payloadBuild struct {
	ImagePath      string   `json:"image_path"`
	ImageSHA256    string   `json:"image_sha256"`
	ImageSize      int64    `json:"image_size"`
	Manifest       manifest `json:"manifest"`
	ManifestSHA256 string   `json:"manifest_sha256"`
}

type payloadRecord struct {
	Schema  int           `json:"schema"`
	Payload payloadBuild  `json:"payload"`
	Codex   manifestEntry `json:"codex"`
}

type eventRecord struct {
	Schema     int             `json:"schema"`
	Sequence   uint64          `json:"sequence"`
	Event      string          `json:"event"`
	TimeNS     int64           `json:"time_ns"`
	Generation uint64          `json:"generation"`
	InstanceID string          `json:"instance_id"`
	PID        int             `json:"pid"`
	Details    json.RawMessage `json:"details"`
}

type apiTrace struct {
	Sequence uint64          `json:"sequence"`
	TimeNS   int64           `json:"time_ns"`
	Method   string          `json:"method"`
	Path     string          `json:"path"`
	Request  json.RawMessage `json:"request"`
	Status   int             `json:"status"`
	Response json.RawMessage `json:"response"`
}

type relayRecord struct {
	Event         string    `json:"event"`
	Time          time.Time `json:"time"`
	Generation    uint64    `json:"generation"`
	Port          uint32    `json:"port"`
	PID           int       `json:"pid"`
	SandboxPID    int       `json:"sandbox_peer_pid"`
	SandboxDevice uint64    `json:"sandbox_device"`
	SandboxInode  uint64    `json:"sandbox_inode"`
	GuestToHost   int64     `json:"guest_to_host_bytes"`
	HostToGuest   int64     `json:"host_to_guest_bytes"`
}

type proxyRecord struct {
	Event          string    `json:"event"`
	Time           time.Time `json:"time"`
	Target         string    `json:"target"`
	PID            int       `json:"pid"`
	UID            uint32    `json:"uid"`
	GID            uint32    `json:"gid"`
	SocketDevice   uint64    `json:"socket_device"`
	SocketInode    uint64    `json:"socket_inode"`
	ClientToTarget int64     `json:"client_to_target_bytes"`
	TargetToClient int64     `json:"target_to_client_bytes"`
}

type rawAdapterRecord struct {
	Sequence  uint64          `json:"sequence"`
	TimeNS    int64           `json:"time_ns"`
	Direction string          `json:"direction"`
	Payload   json.RawMessage `json:"payload"`
}

type bridgeIORecord struct {
	Schema    int    `json:"schema"`
	Sequence  uint64 `json:"sequence"`
	Phase     string `json:"phase"`
	Direction string `json:"direction"`
	TimeNS    int64  `json:"time_ns"`
	Size      int    `json:"canonical_size"`
	SHA256    string `json:"canonical_sha256"`
}

type bridgeMessageProof struct {
	First  bridgeIORecord
	Second *bridgeIORecord
}

type verifier struct {
	opts                                          options
	result                                        resultRecord
	guest                                         guestConfig
	payloadResult                                 payloadRecord
	events                                        []eventRecord
	g1, g3                                        processRecord
	modelTarget, proxySocket, argumentModelTarget string
	baseRepository, finalRepository               repobundle.Bundle
	repositoryDelta                               repodelta.Delta
}

func main() {
	var opts options
	flag.StringVar(&opts.evidence, "evidence", "", "canonical absolute runtime evidence directory")
	flag.StringVar(&opts.adapterJSONL, "adapter-jsonl", "", "canonical absolute App Server raw JSONL file")
	flag.StringVar(&opts.payload, "payload", "", "canonical absolute SquashFS payload file")
	flag.StringVar(&opts.payloadResult, "payload-result", "", "canonical absolute payload result JSON file")
	flag.StringVar(&opts.runner, "runner", "", "canonical absolute firecracker-codex-shim executable used for the run")
	flag.Parse()
	var err error
	if flag.NArg() != 0 {
		err = errors.New("positional arguments are forbidden")
	} else {
		err = verify(opts)
	}
	answer := verdict{Schema: verdictSchema, Valid: err == nil}
	if err != nil {
		answer.Error = err.Error()
	}
	encoded, marshalErr := json.Marshal(answer)
	if marshalErr == nil {
		_, marshalErr = fmt.Fprintln(os.Stdout, string(encoded))
	}
	if err != nil || marshalErr != nil {
		os.Exit(1)
	}
}

func verify(opts options) error {
	v := &verifier{opts: opts}
	if err := v.validateInputs(); err != nil {
		return err
	}
	if err := v.verifyPayload(); err != nil {
		return fmt.Errorf("payload: %w", err)
	}
	if err := v.verifyResultAndArtifacts(); err != nil {
		return fmt.Errorf("result/artifacts: %w", err)
	}
	if err := v.verifyGuestAndInitramfs(); err != nil {
		return fmt.Errorf("guest/initramfs: %w", err)
	}
	if err := v.verifyProcesses(); err != nil {
		return fmt.Errorf("processes: %w", err)
	}
	if err := v.verifyEvents(); err != nil {
		return fmt.Errorf("events: %w", err)
	}
	if err := v.verifyAPITraces(); err != nil {
		return fmt.Errorf("Firecracker API: %w", err)
	}
	if err := v.verifyRelaysAndProxy(); err != nil {
		return fmt.Errorf("relay/proxy: %w", err)
	}
	if err := v.verifyAdapter(); err != nil {
		return fmt.Errorf("App Server capture: %w", err)
	}
	return nil
}

func (v *verifier) validateInputs() error {
	if err := requireCanonicalDirect(v.opts.evidence, true); err != nil {
		return fmt.Errorf("-evidence: %w", err)
	}
	info, err := os.Lstat(v.opts.evidence)
	if err != nil {
		return err
	}
	if info.Mode().Perm() != 0o700 {
		return errors.New("-evidence directory must have mode 0700")
	}
	for label, path := range map[string]string{"-adapter-jsonl": v.opts.adapterJSONL, "-payload": v.opts.payload, "-payload-result": v.opts.payloadResult, "-runner": v.opts.runner} {
		if err := requireCanonicalDirect(path, false); err != nil {
			return fmt.Errorf("%s: %w", label, err)
		}
	}
	if _, _, _, err := inspectExecutable(v.opts.runner); err != nil {
		return fmt.Errorf("-runner: %w", err)
	}
	return nil
}

func requireCanonicalDirect(path string, directory bool) error {
	if path == "" || strings.IndexByte(path, 0) >= 0 || !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return errors.New("path must be nonempty, canonical, absolute, and NUL-free")
	}
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return errors.New("path must not be a symlink")
	}
	if directory != info.IsDir() {
		if directory {
			return errors.New("path is not a directory")
		}
		return errors.New("path is not a regular file")
	}
	if !directory && (!info.Mode().IsRegular() || info.Size() <= 0) {
		return errors.New("path is not a nonempty regular file")
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil || resolved != path {
		return errors.New("path must not traverse symlinks")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != uint32(os.Geteuid()) {
		return errors.New("path must be owned by the current user")
	}
	return nil
}

func evidencePath(v *verifier, name string) string { return filepath.Join(v.opts.evidence, name) }

func readBounded(path string, limit int64) ([]byte, error) {
	file, initial, err := openBoundFile(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(data)) == 0 || int64(len(data)) > limit {
		return nil, fmt.Errorf("file size is outside 1..%d", limit)
	}
	if err := requireSameBoundFile(path, initial); err != nil {
		return nil, err
	}
	return data, nil
}

func openBoundFile(path string) (*os.File, os.FileInfo, error) {
	initial, err := os.Lstat(path)
	if err != nil {
		return nil, nil, err
	}
	if initial.Mode()&os.ModeSymlink != 0 || !initial.Mode().IsRegular() {
		return nil, nil, errors.New("file is not a direct regular file")
	}
	descriptor, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return nil, nil, err
	}
	file := os.NewFile(uintptr(descriptor), path)
	if file == nil {
		_ = syscall.Close(descriptor)
		return nil, nil, errors.New("could not wrap file descriptor")
	}
	opened, err := file.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(initial, opened) {
		_ = file.Close()
		if err != nil {
			return nil, nil, err
		}
		return nil, nil, errors.New("file changed while it was opened")
	}
	return file, initial, nil
}

func requireSameBoundFile(path string, initial os.FileInfo) error {
	current, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if initial == nil || current.Mode()&os.ModeSymlink != 0 || !current.Mode().IsRegular() || !os.SameFile(initial, current) {
		return errors.New("file path identity changed while it was read")
	}
	return nil
}

func decodeExact(data []byte, fields []string, target any) error {
	if len(data) == 0 {
		return errors.New("empty JSON")
	}
	if err := rejectDuplicateFields(data); err != nil {
		return err
	}
	var object map[string]json.RawMessage
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	if err := decoder.Decode(&object); err != nil {
		return fmt.Errorf("decode JSON object: %w", err)
	}
	if object == nil {
		return errors.New("JSON value is not an object")
	}
	if err := requireJSONEOF(decoder); err != nil {
		return err
	}
	want := append([]string(nil), fields...)
	got := make([]string, 0, len(object))
	for key := range object {
		got = append(got, key)
	}
	sort.Strings(want)
	sort.Strings(got)
	if !reflect.DeepEqual(got, want) {
		return fmt.Errorf("object fields are %v, require %v", got, want)
	}
	decoder = json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return fmt.Errorf("decode strict object: %w", err)
	}
	return requireJSONEOF(decoder)
}

func decodeAllowed(data []byte, allowed, required []string, target any) error {
	if err := rejectDuplicateFields(data); err != nil {
		return err
	}
	var object map[string]json.RawMessage
	decoder := json.NewDecoder(bytes.NewReader(data))
	if err := decoder.Decode(&object); err != nil || object == nil {
		if err == nil {
			err = errors.New("not an object")
		}
		return fmt.Errorf("decode JSON object: %w", err)
	}
	if err := requireJSONEOF(decoder); err != nil {
		return err
	}
	allow := make(map[string]bool, len(allowed))
	for _, key := range allowed {
		allow[key] = true
	}
	for key := range object {
		if !allow[key] {
			return fmt.Errorf("unknown field %q", key)
		}
	}
	for _, key := range required {
		if _, ok := object[key]; !ok {
			return fmt.Errorf("missing field %q", key)
		}
	}
	decoder = json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	return requireJSONEOF(decoder)
}

func requireJSONEOF(decoder *json.Decoder) error {
	var extra any
	err := decoder.Decode(&extra)
	if errors.Is(err, io.EOF) {
		return nil
	}
	if err == nil {
		return errors.New("JSON contains multiple values")
	}
	return fmt.Errorf("JSON has trailing data: %w", err)
}

func rejectDuplicateFields(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	if err := scanJSONValue(decoder); err != nil {
		return err
	}
	if token, err := decoder.Token(); !errors.Is(err, io.EOF) {
		if err == nil {
			return fmt.Errorf("JSON has trailing token %v", token)
		}
		return fmt.Errorf("JSON trailing data: %w", err)
	}
	return nil
}

func scanJSONValue(decoder *json.Decoder) error {
	token, err := decoder.Token()
	if err != nil {
		return fmt.Errorf("decode JSON token: %w", err)
	}
	delimiter, compound := token.(json.Delim)
	if !compound {
		return nil
	}
	switch delimiter {
	case '{':
		seen := make(map[string]bool)
		for decoder.More() {
			keyToken, err := decoder.Token()
			if err != nil {
				return err
			}
			key, ok := keyToken.(string)
			if !ok {
				return errors.New("object key is not a string")
			}
			if seen[key] {
				return fmt.Errorf("duplicate JSON field %q", key)
			}
			seen[key] = true
			if err := scanJSONValue(decoder); err != nil {
				return err
			}
		}
		end, err := decoder.Token()
		if err != nil || end != json.Delim('}') {
			return errors.New("JSON object is not closed")
		}
	case '[':
		for decoder.More() {
			if err := scanJSONValue(decoder); err != nil {
				return err
			}
		}
		end, err := decoder.Token()
		if err != nil || end != json.Delim(']') {
			return errors.New("JSON array is not closed")
		}
	default:
		return fmt.Errorf("unexpected JSON delimiter %q", delimiter)
	}
	return nil
}

func readStrictJSON(path string, fields []string, target any) ([]byte, error) {
	data, err := readBounded(path, maxJSONBytes)
	if err != nil {
		return nil, err
	}
	if err := decodeExact(data, fields, target); err != nil {
		return nil, err
	}
	return data, nil
}

func readJSONL(path string, decode func([]byte) error) error {
	file, initial, err := openBoundFile(path)
	if err != nil {
		return err
	}
	defer file.Close()
	reader := bufio.NewReaderSize(file, 64<<10)
	count := 0
	for {
		line, readErr := reader.ReadBytes('\n')
		if len(line) != 0 {
			if line[len(line)-1] != '\n' {
				return errors.New("JSONL final record lacks newline")
			}
			line = line[:len(line)-1]
			if len(line) == 0 {
				return errors.New("JSONL contains a blank record")
			}
			if int64(len(line)) > maxJSONBytes {
				return errors.New("JSONL record is too large")
			}
			count++
			if count > maxJSONLLines {
				return errors.New("JSONL has too many records")
			}
			if err := decode(line); err != nil {
				return fmt.Errorf("record %d: %w", count, err)
			}
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return readErr
		}
	}
	if count == 0 {
		return errors.New("JSONL is empty")
	}
	return requireSameBoundFile(path, initial)
}

func validDigest(value string) bool {
	if len(value) != 64 || strings.ToLower(value) != value {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func hashFile(path string) (string, int64, error) {
	file, initial, err := openBoundFile(path)
	if err != nil {
		return "", 0, err
	}
	defer file.Close()
	digest := sha256.New()
	size, err := io.Copy(digest, file)
	if err != nil {
		return "", 0, err
	}
	if err := requireSameBoundFile(path, initial); err != nil {
		return "", 0, err
	}
	return hex.EncodeToString(digest.Sum(nil)), size, nil
}

func inspectExecutable(path string) (string, int64, uint32, error) {
	if err := requireCanonicalDirect(path, false); err != nil {
		return "", 0, 0, err
	}
	file, initial, err := openBoundFile(path)
	if err != nil {
		return "", 0, 0, err
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil {
		return "", 0, 0, err
	}
	stat, ok := opened.Sys().(*syscall.Stat_t)
	mode := opened.Mode()
	if !ok || stat.Uid != uint32(os.Geteuid()) || !mode.IsRegular() || opened.Size() <= 0 || mode.Perm()&0o111 == 0 || mode&(os.ModeSetuid|os.ModeSetgid|os.ModeSticky) != 0 {
		return "", 0, 0, errors.New("runner must be a nonempty, current-user-owned regular executable without special mode bits")
	}
	digest := sha256.New()
	size, err := io.Copy(digest, file)
	if err != nil {
		return "", 0, 0, err
	}
	if size != opened.Size() {
		return "", 0, 0, errors.New("runner size changed while hashing")
	}
	if err := requireSameBoundFile(path, initial); err != nil {
		return "", 0, 0, err
	}
	return hex.EncodeToString(digest.Sum(nil)), size, uint32(mode.Perm()), nil
}

func hashBytes(data []byte) string { sum := sha256.Sum256(data); return hex.EncodeToString(sum[:]) }

func (v *verifier) verifyPayload() error {
	fields := []string{"schema", "payload", "codex"}
	data, err := readBounded(v.opts.payloadResult, maxJSONBytes)
	if err != nil {
		return err
	}
	if err := decodeExact(data, fields, &v.payloadResult); err != nil {
		return err
	}
	if v.payloadResult.Schema != payloadSchema {
		return fmt.Errorf("result schema is %d", v.payloadResult.Schema)
	}
	// Reparse every nested object with exact schemas; DisallowUnknownFields on
	// the outer decode rejects unknown nested fields, while this requires their
	// complete field sets as well.
	var root map[string]json.RawMessage
	_ = json.Unmarshal(data, &root)
	if err := decodeExact(root["payload"], []string{"image_path", "image_sha256", "image_size", "manifest", "manifest_sha256"}, &v.payloadResult.Payload); err != nil {
		return fmt.Errorf("payload build: %w", err)
	}
	if err := decodeExact(root["codex"], []string{"path", "type", "mode", "size", "sha256", "link_target"}, &v.payloadResult.Codex); err != nil {
		return fmt.Errorf("Codex entry: %w", err)
	}
	var build map[string]json.RawMessage
	_ = json.Unmarshal(root["payload"], &build)
	if err := decodeExact(build["manifest"], []string{"schema", "entries"}, &v.payloadResult.Payload.Manifest); err != nil {
		return fmt.Errorf("manifest: %w", err)
	}
	var manifestObject map[string]json.RawMessage
	_ = json.Unmarshal(build["manifest"], &manifestObject)
	var entries []json.RawMessage
	if err := json.Unmarshal(manifestObject["entries"], &entries); err != nil || len(entries) == 0 {
		return errors.New("manifest entries are missing")
	}
	for index, raw := range entries {
		if err := decodeExact(raw, []string{"path", "type", "mode", "size", "sha256", "link_target"}, &v.payloadResult.Payload.Manifest.Entries[index]); err != nil {
			return fmt.Errorf("manifest entry %d: %w", index, err)
		}
	}
	buildResult := v.payloadResult.Payload
	if buildResult.ImagePath != v.opts.payload {
		return errors.New("payload result image_path does not equal -payload")
	}
	if buildResult.ImageSize <= 0 || !validDigest(buildResult.ImageSHA256) || !validDigest(buildResult.ManifestSHA256) {
		return errors.New("payload result has invalid sizes or digests")
	}
	actualHash, actualSize, err := hashFile(v.opts.payload)
	if err != nil {
		return err
	}
	if actualHash != buildResult.ImageSHA256 || actualSize != buildResult.ImageSize {
		return errors.New("supplied payload bytes do not match payload result")
	}
	if buildResult.Manifest.Schema != manifestSchema {
		return errors.New("payload manifest schema is not 1")
	}
	previous := ""
	var codexMatches int
	for index, entry := range buildResult.Manifest.Entries {
		if entry.Path == "" || (index > 0 && entry.Path <= previous) {
			return errors.New("payload manifest paths are not strictly sorted and unique")
		}
		previous = entry.Path
		switch entry.Type {
		case "directory":
			if entry.Size != 0 || entry.SHA256 != "" || entry.LinkTarget != "" {
				return fmt.Errorf("directory %q has file data", entry.Path)
			}
		case "file":
			if entry.Size < 0 || !validDigest(entry.SHA256) || entry.LinkTarget != "" {
				return fmt.Errorf("file %q is malformed", entry.Path)
			}
		case "symlink":
			if entry.Size != 0 || entry.SHA256 != "" || entry.LinkTarget == "" {
				return fmt.Errorf("symlink %q is malformed", entry.Path)
			}
		default:
			return fmt.Errorf("entry %q has unknown type", entry.Path)
		}
		if entry.Path == "bin/codex" {
			codexMatches++
			if entry != v.payloadResult.Codex {
				return errors.New("Codex record differs from manifest entry")
			}
		}
	}
	if codexMatches != 1 || v.payloadResult.Codex.Type != "file" || v.payloadResult.Codex.Size <= 0 || v.payloadResult.Codex.Mode&0o111 == 0 {
		return errors.New("manifest lacks one executable bin/codex")
	}
	manifestJSON, err := json.Marshal(buildResult.Manifest)
	if err != nil {
		return err
	}
	if hashBytes(manifestJSON) != buildResult.ManifestSHA256 {
		return errors.New("manifest SHA-256 is not over canonical compact manifest JSON")
	}
	return nil
}

func (v *verifier) verifyResultAndArtifacts() error {
	path := evidencePath(v, "result.json")
	if err := requirePrivateFile(path); err != nil {
		return err
	}
	fields := []string{"schema", "success", "session_id", "codex_sha256", "runner_sha256", "arguments_sha256", "arguments_encoding", "arguments_count", "workspace_mapping", "artifacts", "sealed_boot_inputs", "sealed_load_inputs", "checkpoint", "processes", "g1_sigkill_confirmed", "snapshot_loaded_paused", "relay_armed_before_resume", "tool_released_after_g3_attach", "completed_time_ns"}
	data, err := readStrictJSON(path, fields, &v.result)
	if err != nil {
		return err
	}
	if v.result.Schema != resultSchema || !v.result.Success || v.result.CompletedTimeNS <= 0 {
		return errors.New("result is not one successful schema-1 run")
	}
	if !validSession(v.result.SessionID) || !validDigest(v.result.CodexSHA256) || !validDigest(v.result.RunnerSHA256) || !validDigest(v.result.ArgumentsSHA256) {
		return errors.New("result identities are malformed")
	}
	if v.result.ArgumentsEncoding != "compact-json-array" || v.result.ArgumentsCount < 2 {
		return errors.New("result argument metadata is malformed")
	}
	if v.result.WorkspaceMapping.Guest != guestWorkspace {
		return errors.New("result guest workspace is not /workspace")
	}
	if err := requireCanonicalDirect(v.result.WorkspaceMapping.Host, true); err != nil {
		return fmt.Errorf("host workspace: %w", err)
	}
	workspace, err := os.Open(v.result.WorkspaceMapping.Host)
	if err != nil {
		return err
	}
	_, readErr := workspace.Readdirnames(1)
	_ = workspace.Close()
	if !errors.Is(readErr, io.EOF) {
		return errors.New("host workspace is no longer empty")
	}
	if !(v.result.G1SIGKILLConfirmed && v.result.SnapshotLoadedPaused && v.result.RelayArmedBeforeResume && v.result.ToolReleasedAfterAttach) {
		return errors.New("result safety booleans are not all true")
	}

	var root map[string]json.RawMessage
	_ = json.Unmarshal(data, &root)
	if err := decodeExact(root["workspace_mapping"], []string{"host", "guest"}, &v.result.WorkspaceMapping); err != nil {
		return err
	}
	if err := decodeCheckpoint(root["checkpoint"], &v.result.Checkpoint); err != nil {
		return err
	}
	for _, field := range []struct {
		name   string
		values []sealedArtifact
	}{{"sealed_boot_inputs", v.result.SealedBootInputs}, {"sealed_load_inputs", v.result.SealedLoadInputs}} {
		var raws []json.RawMessage
		if err := json.Unmarshal(root[field.name], &raws); err != nil || len(raws) != len(field.values) {
			return fmt.Errorf("%s is malformed", field.name)
		}
		for index, raw := range raws {
			if err := decodeSealedArtifact(raw, &field.values[index]); err != nil {
				return fmt.Errorf("%s[%d]: %w", field.name, index, err)
			}
		}
	}
	var processRaws []json.RawMessage
	if err := json.Unmarshal(root["processes"], &processRaws); err != nil || len(processRaws) != len(v.result.Processes) {
		return errors.New("process records are malformed")
	}
	for index, raw := range processRaws {
		if err := decodeProcess(raw, &v.result.Processes[index]); err != nil {
			return fmt.Errorf("processes[%d]: %w", index, err)
		}
	}

	wantKeys := []string{
		"bridge_io", "events", "firecracker", "firecracker_api_g1", "firecracker_api_g3",
		"firecracker_relay_g1", "firecracker_relay_g3", "guest", "guest_config", "initramfs",
		"kernel", "model_proxy", "payload", "repository", "repository_delta", "repository_final", "runner", "snapshot_memory", "snapshot_state",
	}
	gotKeys := make([]string, 0, len(v.result.Artifacts))
	for key := range v.result.Artifacts {
		gotKeys = append(gotKeys, key)
	}
	sort.Strings(gotKeys)
	if !reflect.DeepEqual(gotKeys, wantKeys) {
		return fmt.Errorf("artifact keys are %v, require %v", gotKeys, wantKeys)
	}
	var artifactRaws map[string]json.RawMessage
	if err := json.Unmarshal(root["artifacts"], &artifactRaws); err != nil {
		return err
	}
	for key, raw := range artifactRaws {
		item := v.result.Artifacts[key]
		if err := decodeExact(raw, []string{"name", "size", "mode", "sha256"}, &item); err != nil {
			return fmt.Errorf("artifact %s: %w", key, err)
		}
		if err := validateArtifact(item); err != nil {
			return fmt.Errorf("artifact %s: %w", key, err)
		}
	}

	retained := map[string]string{
		"bridge_io":            "bridge-io.jsonl",
		"events":               "events.jsonl",
		"firecracker_api_g1":   "firecracker-api-g1.jsonl",
		"firecracker_api_g3":   "firecracker-api-g3.jsonl",
		"firecracker_relay_g1": "firecracker-relay-g1.jsonl",
		"firecracker_relay_g3": "firecracker-relay-g3.jsonl",
		"guest_config":         "guest-config.json",
		"initramfs":            "guest-initramfs.cpio",
		"model_proxy":          "model-proxy.jsonl",
		"repository":           "repository.bundle",
		"repository_delta":     "repository.delta",
		"repository_final":     "repository-final.bundle",
		"runner":               "runner",
		"snapshot_memory":      "snapshot.memory",
		"snapshot_state":       "snapshot.state",
	}
	for key, name := range retained {
		filePath := evidencePath(v, name)
		if err := requirePrivateFile(filePath); err != nil {
			return err
		}
		hash, size, err := hashFile(filePath)
		if err != nil {
			return err
		}
		record := v.result.Artifacts[key]
		if record.Name != name || record.Mode != 0o600 || record.SHA256 != hash || record.Size != size {
			return fmt.Errorf("retained %s does not match result artifact", name)
		}
	}
	payloadArtifact := v.result.Artifacts["payload"]
	if payloadArtifact.Name != "payload" || payloadArtifact.Mode != 0o400 || payloadArtifact.SHA256 != v.payloadResult.Payload.ImageSHA256 || payloadArtifact.Size != v.payloadResult.Payload.ImageSize {
		return errors.New("result payload artifact is not the supplied payload")
	}
	if v.result.CodexSHA256 != v.payloadResult.Codex.SHA256 {
		return errors.New("result Codex hash differs from payload manifest")
	}
	runnerHash, runnerSize, _, err := inspectExecutable(v.opts.runner)
	if err != nil {
		return fmt.Errorf("runner: %w", err)
	}
	runnerArtifact := v.result.Artifacts["runner"]
	if v.result.RunnerSHA256 != runnerHash || runnerArtifact.Name != "runner" || runnerArtifact.Size != runnerSize || runnerArtifact.Mode != 0o600 || runnerArtifact.SHA256 != runnerHash {
		return errors.New("result runner identity/artifact does not match -runner")
	}
	if err := v.verifySealedInputs(); err != nil {
		return err
	}
	return nil
}

func decodeSealedArtifact(raw []byte, target *sealedArtifact) error {
	if err := decodeExact(raw, []string{"artifact", "child_fd", "linux_seals"}, target); err != nil {
		return err
	}
	var root map[string]json.RawMessage
	_ = json.Unmarshal(raw, &root)
	return decodeExact(root["artifact"], []string{"name", "size", "mode", "sha256"}, &target.Artifact)
}

func decodeProcess(raw []byte, target *processRecord) error {
	fields := []string{"generation", "id", "pid", "executable", "executable_sha256", "device", "inode", "start_time_ticks", "vmm_version", "started_time_ns", "stopped_time_ns", "termination", "api_socket", "vsock_backend"}
	if err := decodeExact(raw, fields, target); err != nil {
		return err
	}
	var root map[string]json.RawMessage
	_ = json.Unmarshal(raw, &root)
	for name, socket := range map[string]*socketRecord{"api_socket": &target.APISocket, "vsock_backend": &target.VsockBackend} {
		if err := decodeExact(root[name], []string{"path", "device", "inode", "mode", "uid"}, socket); err != nil {
			return fmt.Errorf("%s: %w", name, err)
		}
	}
	return nil
}

func requirePrivateFile(path string) error {
	if err := requireCanonicalDirect(path, false); err != nil {
		return fmt.Errorf("%s: %w", filepath.Base(path), err)
	}
	info, _ := os.Lstat(path)
	if info.Mode().Perm() != 0o600 {
		return fmt.Errorf("%s must have mode 0600", filepath.Base(path))
	}
	return nil
}

func validateArtifact(item artifact) error {
	if item.Name == "" || item.Size <= 0 || !validDigest(item.SHA256) || item.Mode > 0o7777 {
		return errors.New("invalid name, size, mode, or SHA-256")
	}
	return nil
}

func (v *verifier) verifySealedInputs() error {
	if len(v.result.SealedBootInputs) != 4 || len(v.result.SealedLoadInputs) != 4 {
		return errors.New("sealed input sets must each contain exactly four records")
	}
	wantBoot := []struct {
		name        string
		fd          int
		artifactKey string
	}{{"kernel", 4, "kernel"}, {"runtime-initramfs", 5, "initramfs"}, {"payload", 6, "payload"}, {"repository", 7, "repository"}}
	for index, want := range wantBoot {
		got := v.result.SealedBootInputs[index]
		if got.Artifact.Name != want.name || got.ChildFD != want.fd || got.LinuxSeals != immutableSeals {
			return fmt.Errorf("sealed boot input %d is malformed", index)
		}
		base := v.result.Artifacts[want.artifactKey]
		if got.Artifact.Size != base.Size || got.Artifact.SHA256 != base.SHA256 || got.Artifact.Mode != 0o400 {
			return fmt.Errorf("sealed boot input %d is not linked to artifact", index)
		}
	}
	wantLoad := []struct {
		name        string
		fd          int
		artifactKey string
	}{{"snapshot-state", 4, "snapshot_state"}, {"snapshot-memory", 5, "snapshot_memory"}, {"payload", 6, "payload"}, {"repository", 7, "repository"}}
	for index, want := range wantLoad {
		got := v.result.SealedLoadInputs[index]
		if got.Artifact.Name != want.name || got.ChildFD != want.fd || got.LinuxSeals != immutableSeals {
			return fmt.Errorf("sealed load input %d is malformed", index)
		}
		base := v.result.Artifacts[want.artifactKey]
		if got.Artifact.Size != base.Size || got.Artifact.SHA256 != base.SHA256 || got.Artifact.Mode != 0o400 {
			return fmt.Errorf("sealed load input %d is not linked to artifact", index)
		}
	}
	return nil
}

func decodeCheckpoint(data []byte, target *checkpoint) error {
	if err := decodeExact(data, []string{"HostBarrier", "GuestBarrier"}, target); err != nil {
		return fmt.Errorf("checkpoint: %w", err)
	}
	var root map[string]json.RawMessage
	_ = json.Unmarshal(data, &root)
	for name, raw := range root {
		var value barrier
		if err := decodeBarrier(raw, &value); err != nil {
			return fmt.Errorf("checkpoint %s: %w", name, err)
		}
	}
	return nil
}

func decodeBarrier(data []byte, target *barrier) error {
	if err := decodeExact(data, []string{"session_id", "generation", "state"}, target); err != nil {
		return err
	}
	var root map[string]json.RawMessage
	_ = json.Unmarshal(data, &root)
	var state transcriptState
	if err := decodeExact(root["state"], []string{"host_to_guest", "guest_to_host"}, &state); err != nil {
		return err
	}
	var stateRoot map[string]json.RawMessage
	_ = json.Unmarshal(root["state"], &stateRoot)
	for name, raw := range stateRoot {
		var value position
		if err := decodeExact(raw, []string{"offset", "bytes", "hash"}, &value); err != nil {
			return fmt.Errorf("%s: %w", name, err)
		}
		emptyDigest := hashBytes(nil)
		if !validDigest(value.Hash) || (value.Offset == 0) != (value.Bytes == 0) ||
			(value.Offset == 0 && value.Hash != emptyDigest) || (value.Offset > 0 && value.Bytes < value.Offset) ||
			value.Offset > 65536 || value.Bytes > 64<<20 {
			return fmt.Errorf("%s has invalid transcript position", name)
		}
	}
	return nil
}

func validSession(value string) bool {
	if len(value) != 32 || strings.ToLower(value) != value {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func validatePinnedGuestArguments(arguments []string, modelPort uint32) (string, error) {
	if len(arguments) < 4 || len(arguments) > 256 || arguments[0] != "app-server" || arguments[1] != "--stdio" {
		return "", errors.New("guest arguments are not a bounded app-server --stdio command")
	}
	total := 0
	for index, argument := range arguments {
		if argument == "" || len(argument) > 64<<10 || strings.IndexFunc(argument, func(r rune) bool { return r < 0x20 || r == 0x7f }) >= 0 {
			return "", fmt.Errorf("guest argument %d is empty, oversized, or contains controls", index)
		}
		total += len(argument)
		if total > 1<<20 {
			return "", errors.New("guest arguments exceed the aggregate limit")
		}
	}
	var baseURLs []string
	for index := 2; index < len(arguments); index += 2 {
		if index+1 >= len(arguments) || arguments[index] != "-c" {
			return "", errors.New("guest arguments after --stdio must be separate -c overrides")
		}
		found, err := scanBaseURLs(arguments[index+1])
		if err != nil {
			return "", fmt.Errorf("parse guest override %d: %w", index+1, err)
		}
		baseURLs = append(baseURLs, found...)
	}
	if len(baseURLs) != 1 {
		return "", fmt.Errorf("guest arguments contain %d base_url assignments, require one", len(baseURLs))
	}
	parsed, err := url.Parse(baseURLs[0])
	if err != nil || parsed.Scheme != "http" || parsed.User != nil || parsed.Hostname() != "127.0.0.1" || parsed.Port() == "" || parsed.Path != "/v1" || parsed.RawQuery != "" || parsed.Fragment != "" {
		return "", errors.New("model base_url is not canonical unauthenticated numeric-loopback HTTP /v1")
	}
	port, err := strconv.ParseUint(parsed.Port(), 10, 16)
	if err != nil || port == 0 || uint32(port) != modelPort || parsed.Host != "127.0.0.1:"+strconv.FormatUint(port, 10) {
		return "", errors.New("model base_url port differs from the immutable guest model port")
	}
	if !reflect.DeepEqual(arguments, pinnedArguments(baseURLs[0])) {
		return "", errors.New("guest arguments contain unpinned options, auth, providers, or feature overrides")
	}
	return parsed.Host, nil
}

func pinnedArguments(baseURL string) []string {
	provider := `model_providers.authority_continuity_mock={name="Authority Continuity deterministic fixture",base_url=` + strconv.Quote(baseURL) + `,wire_api="responses",request_max_retries=0,stream_max_retries=0,requires_openai_auth=false,supports_websockets=false}`
	overrides := []string{
		`model="gpt-5.6-sol"`, `model_provider="authority_continuity_mock"`, provider,
		"analytics.enabled=false", "features.responses_websockets=false", "features.remote_models=false",
		"features.apps=false", "features.enable_mcp_apps=false", "features.plugins=false", "mcp_servers={}",
	}
	arguments := []string{"app-server", "--stdio"}
	for _, override := range overrides {
		arguments = append(arguments, "-c", override)
	}
	return arguments
}

func scanBaseURLs(override string) ([]string, error) {
	var result []string
	var stack []byte
	topAssignments := 0
	for index := 0; index < len(override); {
		value := override[index]
		switch {
		case value == ' ':
			index++
		case value == '#':
			index = len(override)
		case value == '"':
			_, next, err := scanBasicString(override, index)
			if err != nil {
				return nil, err
			}
			index = next
		case value == '\'':
			next := strings.IndexByte(override[index+1:], '\'')
			if next < 0 {
				return nil, errors.New("unterminated TOML literal string")
			}
			index += next + 2
		case value == '{' || value == '[':
			stack = append(stack, value)
			index++
		case value == '}' || value == ']':
			if len(stack) == 0 || (value == '}' && stack[len(stack)-1] != '{') || (value == ']' && stack[len(stack)-1] != '[') {
				return nil, errors.New("mismatched TOML delimiter")
			}
			stack = stack[:len(stack)-1]
			index++
		case isBareKey(value):
			start := index
			for index < len(override) && isBareKey(override[index]) {
				index++
			}
			if override[start:index] != "base_url" {
				continue
			}
			assignment := skipSpaces(override, index)
			if assignment >= len(override) || override[assignment] != '=' {
				return nil, errors.New("base_url is not an assignment")
			}
			assignment = skipSpaces(override, assignment+1)
			if assignment >= len(override) || override[assignment] != '"' {
				return nil, errors.New("base_url is not a TOML basic string")
			}
			decoded, next, err := scanBasicString(override, assignment)
			if err != nil {
				return nil, err
			}
			result = append(result, decoded)
			index = next
		case value == '=':
			if len(stack) == 0 {
				topAssignments++
			}
			index++
		case strings.ContainsRune(".,+:-", rune(value)):
			index++
		default:
			return nil, fmt.Errorf("invalid TOML byte %q", value)
		}
	}
	if len(stack) != 0 {
		return nil, errors.New("unclosed TOML delimiter")
	}
	if topAssignments != 1 {
		return nil, fmt.Errorf("override has %d top-level assignments, require one", topAssignments)
	}
	return result, nil
}

func scanBasicString(value string, start int) (string, int, error) {
	for index := start + 1; index < len(value); index++ {
		if value[index] == '\\' {
			index++
			if index >= len(value) {
				return "", 0, errors.New("unterminated TOML escape")
			}
			continue
		}
		if value[index] == '"' {
			decoded, err := strconv.Unquote(value[start : index+1])
			if err != nil {
				return "", 0, err
			}
			return decoded, index + 1, nil
		}
	}
	return "", 0, errors.New("unterminated TOML basic string")
}
func skipSpaces(value string, index int) int {
	for index < len(value) && value[index] == ' ' {
		index++
	}
	return index
}
func isBareKey(value byte) bool {
	return value >= 'a' && value <= 'z' || value >= 'A' && value <= 'Z' || value >= '0' && value <= '9' || value == '_' || value == '-'
}

func (v *verifier) verifyGuestAndInitramfs() error {
	configPath := evidencePath(v, "guest-config.json")
	configBytes, err := readBounded(configPath, 1<<20)
	if err != nil {
		return err
	}
	if err := decodeExact(configBytes, []string{"schema", "session_id", "codex_sha256", "arguments", "stream_port", "model_port", "payload_drive", "repository_drive", "repository_size", "repository_sha256", "repository_tree_root"}, &v.guest); err != nil {
		return err
	}
	if v.guest.Schema != 2 || v.guest.SessionID != v.result.SessionID || v.guest.CodexSHA256 != v.result.CodexSHA256 || v.guest.StreamPort != streamPort || v.guest.ModelPort == 0 || v.guest.ModelPort == streamPort || v.guest.PayloadDrive != payloadDrive || v.guest.RepositoryDrive != repositoryDrive {
		return errors.New("guest config is not linked to the successful run")
	}
	repositoryPath := evidencePath(v, "repository.bundle")
	repositoryFile, err := os.Open(repositoryPath)
	if err != nil {
		return err
	}
	repository, decodeErr := repobundle.Decode(repositoryFile, repobundle.DefaultLimits())
	closeErr := repositoryFile.Close()
	if err := errors.Join(decodeErr, closeErr); err != nil {
		return fmt.Errorf("decode retained repository: %w", err)
	}
	repositoryArtifact := v.result.Artifacts["repository"]
	if v.guest.RepositorySize != uint64(repositoryArtifact.Size) || v.guest.RepositorySHA256 != repositoryArtifact.SHA256 || v.guest.RepositoryTreeRoot != repository.TreeRoot.String() {
		return errors.New("guest repository identity differs from the retained canonical bundle")
	}
	finalFile, err := os.Open(evidencePath(v, "repository-final.bundle"))
	if err != nil {
		return err
	}
	finalRepository, finalDecodeErr := repobundle.Decode(finalFile, repobundle.DefaultLimits())
	finalCloseErr := finalFile.Close()
	if err := errors.Join(finalDecodeErr, finalCloseErr); err != nil {
		return fmt.Errorf("decode retained final repository: %w", err)
	}
	deltaFile, err := os.Open(evidencePath(v, "repository.delta"))
	if err != nil {
		return err
	}
	delta, deltaDecodeErr := repodelta.Decode(deltaFile, repodelta.DefaultLimits())
	deltaCloseErr := deltaFile.Close()
	if err := errors.Join(deltaDecodeErr, deltaCloseErr); err != nil {
		return fmt.Errorf("decode retained repository delta: %w", err)
	}
	applied, err := repodelta.Apply(repository, delta, repodelta.DefaultLimits())
	if err != nil || applied.TreeRoot != finalRepository.TreeRoot {
		return errors.Join(errors.New("retained repository delta does not reconstruct the retained final tree"), err)
	}
	v.baseRepository, v.finalRepository, v.repositoryDelta = repository, finalRepository, delta
	if len(v.guest.Arguments) != v.result.ArgumentsCount || len(v.guest.Arguments) < 2 || v.guest.Arguments[0] != "app-server" || v.guest.Arguments[1] != "--stdio" {
		return errors.New("guest arguments are not the fixed App Server entrypoint")
	}
	for _, argument := range v.guest.Arguments {
		if argument == "" || strings.IndexFunc(argument, func(r rune) bool { return r < 0x20 || r == 0x7f }) >= 0 {
			return errors.New("guest argument is empty or contains controls")
		}
	}
	argumentsJSON, err := json.Marshal(v.guest.Arguments)
	if err != nil {
		return err
	}
	if hashBytes(argumentsJSON) != v.result.ArgumentsSHA256 {
		return errors.New("guest arguments digest differs from result")
	}
	v.argumentModelTarget, err = validatePinnedGuestArguments(v.guest.Arguments, v.guest.ModelPort)
	if err != nil {
		return err
	}

	initramfsBytes, err := readBounded(evidencePath(v, "guest-initramfs.cpio"), 80<<20)
	if err != nil {
		return err
	}
	entries, err := parseNewc(initramfsBytes)
	if err != nil {
		return err
	}
	want := []newcExpectation{
		{name: "dev", mode: 0o040755, nlink: 2},
		{name: "dev/console", mode: 0o020600, nlink: 1, rdevMajor: 5, rdevMinor: 1},
		{name: "init", mode: 0o100555, nlink: 1},
		{name: "proc", mode: 0o040555, nlink: 2},
		{name: "sys", mode: 0o040555, nlink: 2},
		{name: "run", mode: 0o040755, nlink: 2},
		{name: "tmp", mode: 0o041777, nlink: 2},
		{name: "opt", mode: 0o040555, nlink: 2},
		{name: "workspace", mode: 0o040755, nlink: 2},
		{name: "home", mode: 0o040755, nlink: 2},
		{name: "config.json", mode: 0o100400, nlink: 1},
	}
	if len(entries) != len(want) {
		return fmt.Errorf("initramfs has %d entries, require %d", len(entries), len(want))
	}
	for index, expected := range want {
		got := entries[index]
		if got.name != expected.name || got.mode != expected.mode || got.nlink != expected.nlink || got.rdevMajor != expected.rdevMajor || got.rdevMinor != expected.rdevMinor {
			return fmt.Errorf("initramfs entry %d metadata differs", index)
		}
		if got.inode != uint32(index+1) || got.uid != 0 || got.gid != 0 || got.mtime != 0 || got.devMajor != 0 || got.devMinor != 0 || got.checksum != 0 {
			return fmt.Errorf("initramfs entry %q has non-fixed metadata", got.name)
		}
		if got.name != "init" && got.name != "config.json" && len(got.data) != 0 {
			return fmt.Errorf("initramfs entry %q unexpectedly has data", got.name)
		}
	}
	initEntry, configEntry := entries[2], entries[10]
	if len(initEntry.data) == 0 || !bytes.Equal(configEntry.data, configBytes) {
		return errors.New("initramfs /init or config.json bytes differ from retained inputs")
	}
	guestArtifact := v.result.Artifacts["guest"]
	if guestArtifact.Name != "guest" || guestArtifact.Mode != 0o400 || guestArtifact.Size != int64(len(initEntry.data)) || guestArtifact.SHA256 != hashBytes(initEntry.data) {
		return errors.New("initramfs /init is not the sealed guest binary")
	}
	if v.result.Artifacts["guest_config"].SHA256 != hashBytes(configEntry.data) {
		return errors.New("initramfs config is not the retained guest config")
	}
	if v.result.Checkpoint.HostBarrier != v.result.Checkpoint.GuestBarrier {
		return errors.New("checkpoint barriers do not prove one identical quiescent state")
	}
	barrier := v.result.Checkpoint.HostBarrier
	if barrier.SessionID != v.result.SessionID || barrier.Generation != firstGeneration {
		return errors.New("checkpoint is not bound to session generation 1")
	}
	return nil
}

type newcEntry struct {
	name                                                                                    string
	inode, mode, uid, gid, nlink, mtime, devMajor, devMinor, rdevMajor, rdevMinor, checksum uint32
	data                                                                                    []byte
}

type newcExpectation struct {
	name                              string
	mode, nlink, rdevMajor, rdevMinor uint32
}

func parseNewc(archive []byte) ([]newcEntry, error) {
	const headerSize = 110
	var entries []newcEntry
	offset := 0
	for {
		if offset+headerSize > len(archive) {
			return nil, fmt.Errorf("truncated newc header at %d", offset)
		}
		header := archive[offset : offset+headerSize]
		if string(header[:6]) != "070701" {
			return nil, fmt.Errorf("newc magic at %d is invalid", offset)
		}
		field := func(start int) (uint32, error) {
			value, err := strconv.ParseUint(string(header[start:start+8]), 16, 32)
			return uint32(value), err
		}
		starts := []int{6, 14, 22, 30, 38, 46, 54, 62, 70, 78, 86, 94, 102}
		values := make([]uint32, len(starts))
		for index, start := range starts {
			value, err := field(start)
			if err != nil {
				return nil, fmt.Errorf("newc field at %d: %w", offset+start, err)
			}
			values[index] = value
		}
		entry := newcEntry{inode: values[0], mode: values[1], uid: values[2], gid: values[3], nlink: values[4], mtime: values[5], devMajor: values[7], devMinor: values[8], rdevMajor: values[9], rdevMinor: values[10], checksum: values[12]}
		fileSize, nameSize := int(values[6]), int(values[11])
		offset += headerSize
		if nameSize < 1 || nameSize > len(archive)-offset || archive[offset+nameSize-1] != 0 {
			return nil, errors.New("invalid newc name")
		}
		entry.name = string(archive[offset : offset+nameSize-1])
		nameEnd := offset + nameSize
		offset = align4(nameEnd)
		if offset > len(archive) || !allZero(archive[nameEnd:offset]) {
			return nil, errors.New("nonzero or truncated newc name padding")
		}
		if fileSize < 0 || fileSize > len(archive)-offset {
			return nil, fmt.Errorf("truncated newc data for %q", entry.name)
		}
		entry.data = append([]byte(nil), archive[offset:offset+fileSize]...)
		dataEnd := offset + fileSize
		offset = align4(dataEnd)
		if offset > len(archive) || !allZero(archive[dataEnd:offset]) {
			return nil, errors.New("nonzero or truncated newc data padding")
		}
		if entry.name == "TRAILER!!!" {
			if entry.inode != uint32(len(entries)+1) || entry.mode != 0 || entry.uid != 0 || entry.gid != 0 || entry.nlink != 1 || entry.mtime != 0 || entry.devMajor != 0 || entry.devMinor != 0 || entry.rdevMajor != 0 || entry.rdevMinor != 0 || entry.checksum != 0 || len(entry.data) != 0 {
				return nil, errors.New("newc trailer metadata is not fixed")
			}
			if !allZero(archive[offset:]) || len(archive)%512 != 0 {
				return nil, errors.New("newc archive has invalid final padding")
			}
			return entries, nil
		}
		if entry.name == "" || strings.HasPrefix(entry.name, "/") || strings.Contains(entry.name, "..") {
			return nil, errors.New("newc entry name is unsafe")
		}
		entries = append(entries, entry)
	}
}

func align4(value int) int { return (value + 3) &^ 3 }
func allZero(data []byte) bool {
	for _, value := range data {
		if value != 0 {
			return false
		}
	}
	return true
}

func (v *verifier) verifyProcesses() error {
	if len(v.result.Processes) != 2 {
		return fmt.Errorf("process count is %d, require 2", len(v.result.Processes))
	}
	v.g1, v.g3 = v.result.Processes[0], v.result.Processes[1]
	if v.g1.Generation != firstGeneration || v.g3.Generation != restoredGeneration {
		return errors.New("process order/generations are not g1 then g3")
	}
	for label, process := range map[string]processRecord{"g1": v.g1, "g3": v.g3} {
		if process.ID == "" || process.PID <= 0 || process.Device == 0 || process.Inode == 0 || process.StartTimeTicks == 0 || process.StartedTimeNS <= 0 || process.StoppedTimeNS <= process.StartedTimeNS || process.VMMVersion == "" || (process.Termination != "supervisor" && process.Termination != "already-exited") {
			return fmt.Errorf("%s process identity/lifecycle is incomplete", label)
		}
		if !filepath.IsAbs(process.Executable) || filepath.Clean(process.Executable) != process.Executable || !validDigest(process.ExecutableSHA256) {
			return fmt.Errorf("%s executable identity is malformed", label)
		}
		if process.ExecutableSHA256 != v.result.Artifacts["firecracker"].SHA256 {
			return fmt.Errorf("%s executable hash differs from captured Firecracker artifact", label)
		}
		if err := v.verifySocketRecord(label+" API", process.APISocket, evidencePath(v, "api-"+label+".sock")); err != nil {
			return err
		}
		if err := v.verifySocketRecord(label+" vsock", process.VsockBackend, evidencePath(v, "vsock-"+label)); err != nil {
			return err
		}
	}
	if v.g1.ID == v.g3.ID || (v.g1.PID == v.g3.PID && v.g1.StartTimeTicks == v.g3.StartTimeTicks) {
		return errors.New("g1 and g3 are not distinct Firecracker identities")
	}
	if v.g1.Termination != "supervisor" {
		return errors.New("g1 process was not terminated by supervisor SIGKILL")
	}
	// StartProcess copies the same verified source into a fresh sealed memfd
	// for every generation. The source path, digest, and reported VMM version
	// must agree; the executed memfd device/inode is intentionally per-process
	// and therefore must not be used as a cross-generation equality key.
	if v.g1.ExecutableSHA256 != v.g3.ExecutableSHA256 || v.g1.Executable != v.g3.Executable || v.g1.VMMVersion != v.g3.VMMVersion {
		return errors.New("g1 and g3 did not execute the same Firecracker source/hash/version")
	}
	if v.g1.StoppedTimeNS >= v.g3.StartedTimeNS {
		return errors.New("g1 was not reaped before g3 started")
	}
	firecrackerArtifact := v.result.Artifacts["firecracker"]
	if firecrackerArtifact.Name != "firecracker" || firecrackerArtifact.SHA256 != v.g1.ExecutableSHA256 || firecrackerArtifact.Mode&0o111 == 0 {
		return errors.New("Firecracker artifact is malformed")
	}
	return nil
}

func (v *verifier) verifySocketRecord(label string, record socketRecord, wantPath string) error {
	if record.Path != wantPath || record.Device == 0 || record.Inode == 0 || record.Mode != 0o600 || record.UID != uint32(os.Geteuid()) {
		return fmt.Errorf("%s socket record is malformed", label)
	}
	return nil
}

type expectedEvent struct {
	name       string
	generation uint64
	details    bool
}

var expectedEvents = []expectedEvent{
	{"run-started", 0, true}, {"artifacts-sealed", 0, true}, {"model-proxy-started", 0, true},
	{"process-started", 1, false}, {"endpoints-armed-before-start", 1, true}, {"bridge-attached", 1, false},
	{"tool-call-observed-checkpoint-quiescent", 1, true}, {"model-path-quiescent", 1, false},
	{"vm-paused", 1, false}, {"snapshot-created-paused", 1, true},
	{"g1-sigkill-confirmed", 1, true}, {"snapshot-load-inputs-sealed", 0, true}, {"bridge-generation-advanced", 0, true},
	{"process-started", 3, false}, {"snapshot-loaded-paused", 3, true}, {"endpoints-armed-while-paused", 3, true},
	{"vm-resumed", 3, false}, {"bridge-attached", 3, false}, {"tool-call-release-authorized", 3, false},
	{"tool-call-delivered-after-attach", 3, false}, {"codex-session-completed", 3, false},
	{"repository-exported", 3, true}, {"run-completed", 0, true},
}

func (v *verifier) verifyEvents() error {
	path := evidencePath(v, "events.jsonl")
	if err := requirePrivateFile(path); err != nil {
		return err
	}
	var raws [][]byte
	if err := readJSONL(path, func(line []byte) error { raws = append(raws, append([]byte(nil), line...)); return nil }); err != nil {
		return err
	}
	if len(raws) != len(expectedEvents) {
		return fmt.Errorf("event count is %d, require %d", len(raws), len(expectedEvents))
	}
	v.events = make([]eventRecord, len(raws))
	previousTime := int64(0)
	for index, raw := range raws {
		want := expectedEvents[index]
		allowed := []string{"schema", "sequence", "event", "time_ns", "generation", "instance_id", "pid", "details"}
		required := []string{"schema", "sequence", "event", "time_ns"}
		if want.generation != 0 {
			required = append(required, "generation", "instance_id", "pid")
		}
		if want.details {
			required = append(required, "details")
		}
		if err := decodeAllowed(raw, allowed, required, &v.events[index]); err != nil {
			return err
		}
		fields := append([]string(nil), required...)
		if err := decodeExact(raw, fields, &v.events[index]); err != nil {
			return err
		}
		event := v.events[index]
		if event.Schema != eventSchema || event.Sequence != uint64(index+1) || event.Event != want.name || event.TimeNS <= previousTime {
			return fmt.Errorf("event %d schema/sequence/name/time is invalid", index+1)
		}
		previousTime = event.TimeNS
		if want.generation == 0 {
			if event.Generation != 0 || event.InstanceID != "" || event.PID != 0 {
				return fmt.Errorf("event %s unexpectedly names a process", event.Event)
			}
		} else {
			process := v.g1
			if want.generation == 3 {
				process = v.g3
			}
			if event.Generation != want.generation || event.InstanceID != process.ID || event.PID != process.PID {
				return fmt.Errorf("event %s is not bound to g%d", event.Event, want.generation)
			}
		}
		if err := v.verifyEventDetails(index, event); err != nil {
			return fmt.Errorf("%s details: %w", event.Event, err)
		}
	}
	if previousTime > v.result.CompletedTimeNS {
		return errors.New("result completion predates event log")
	}
	if !(v.g1.StartedTimeNS < v.events[3].TimeNS && v.events[10].TimeNS >= v.g1.StoppedTimeNS && v.g1.StoppedTimeNS < v.g3.StartedTimeNS && v.g3.StartedTimeNS < v.events[13].TimeNS && v.events[20].TimeNS <= v.g3.StoppedTimeNS) {
		return errors.New("process timestamps contradict ordered lifecycle events")
	}
	return nil
}

func (v *verifier) verifyEventDetails(index int, event eventRecord) error {
	switch index {
	case 0:
		var d struct {
			SessionID, G1ID, G3ID, CodexSHA256, RunnerSHA256, ArgumentsSHA256 string
			WorkspaceMapping                                                  workspaceMapping
		}
		type wire struct {
			SessionID        string           `json:"session_id"`
			G1ID             string           `json:"g1_id"`
			G3ID             string           `json:"g3_id"`
			CodexSHA256      string           `json:"codex_sha256"`
			RunnerSHA256     string           `json:"runner_sha256"`
			ArgumentsSHA256  string           `json:"arguments_sha256"`
			WorkspaceMapping workspaceMapping `json:"workspace_mapping"`
		}
		var w wire
		if err := decodeExact(event.Details, []string{"session_id", "g1_id", "g3_id", "codex_sha256", "runner_sha256", "arguments_sha256", "workspace_mapping"}, &w); err != nil {
			return err
		}
		d = struct {
			SessionID, G1ID, G3ID, CodexSHA256, RunnerSHA256, ArgumentsSHA256 string
			WorkspaceMapping                                                  workspaceMapping
		}{w.SessionID, w.G1ID, w.G3ID, w.CodexSHA256, w.RunnerSHA256, w.ArgumentsSHA256, w.WorkspaceMapping}
		if d.SessionID != v.result.SessionID || d.G1ID != v.g1.ID || d.G3ID != v.g3.ID || d.CodexSHA256 != v.result.CodexSHA256 || d.RunnerSHA256 != v.result.RunnerSHA256 || d.ArgumentsSHA256 != v.result.ArgumentsSHA256 || d.WorkspaceMapping != v.result.WorkspaceMapping {
			return errors.New("run identity differs from result")
		}
		var root map[string]json.RawMessage
		_ = json.Unmarshal(event.Details, &root)
		var mapping workspaceMapping
		if err := decodeExact(root["workspace_mapping"], []string{"host", "guest"}, &mapping); err != nil {
			return err
		}
	case 1:
		var d struct {
			Kernel, Payload, Repository, Guest, Initramfs sealedArtifact `json:"-"`
			RepositoryTreeRoot                            string         `json:"-"`
		}
		type wire struct {
			Kernel             sealedArtifact `json:"kernel"`
			Payload            sealedArtifact `json:"payload"`
			Repository         sealedArtifact `json:"repository"`
			RepositoryTreeRoot string         `json:"repository_tree_root"`
			Guest              sealedArtifact `json:"guest"`
			Initramfs          sealedArtifact `json:"initramfs"`
		}
		var w wire
		if err := decodeExact(event.Details, []string{"kernel", "payload", "repository", "repository_tree_root", "guest", "initramfs"}, &w); err != nil {
			return err
		}
		d.Kernel, d.Payload, d.Repository, d.RepositoryTreeRoot, d.Guest, d.Initramfs = w.Kernel, w.Payload, w.Repository, w.RepositoryTreeRoot, w.Guest, w.Initramfs
		if d.Kernel != v.result.SealedBootInputs[0] || d.Initramfs != v.result.SealedBootInputs[1] || d.Payload != v.result.SealedBootInputs[2] || d.Repository != v.result.SealedBootInputs[3] || d.RepositoryTreeRoot != v.guest.RepositoryTreeRoot {
			return errors.New("sealed boot event differs from result")
		}
		guest := v.result.Artifacts["guest"]
		if d.Guest.ChildFD != 0 || d.Guest.LinuxSeals != immutableSeals || d.Guest.Artifact.Name != "guest" || d.Guest.Artifact.Size != guest.Size || d.Guest.Artifact.SHA256 != guest.SHA256 || d.Guest.Artifact.Mode != 0o400 {
			return errors.New("sealed guest event is malformed")
		}
	case 2:
		var d struct {
			Target string `json:"target"`
			Socket string `json:"socket"`
		}
		if err := decodeExact(event.Details, []string{"target", "socket"}, &d); err != nil {
			return err
		}
		if d.Target != v.argumentModelTarget || d.Socket != evidencePath(v, "model-proxy.sock") {
			return errors.New("model proxy is not fixed to numeric loopback/private socket")
		}
		v.modelTarget, v.proxySocket = d.Target, d.Socket
	case 4, 15:
		var d struct {
			StreamPort uint32 `json:"stream_port"`
			ExportPort uint32 `json:"export_port"`
			ModelPort  uint32 `json:"model_port"`
		}
		if err := decodeExact(event.Details, []string{"stream_port", "export_port", "model_port"}, &d); err != nil {
			return err
		}
		if d.StreamPort != streamPort || d.ExportPort != 7001 || d.ModelPort != v.guest.ModelPort {
			return errors.New("endpoint ports differ from guest config")
		}
	case 6:
		type details struct {
			Host  barrier `json:"host_barrier"`
			Guest barrier `json:"guest_barrier"`
		}
		var d details
		if err := decodeExact(event.Details, []string{"host_barrier", "guest_barrier"}, &d); err != nil {
			return err
		}
		var root map[string]json.RawMessage
		_ = json.Unmarshal(event.Details, &root)
		if err := decodeBarrier(root["host_barrier"], &d.Host); err != nil {
			return err
		}
		if err := decodeBarrier(root["guest_barrier"], &d.Guest); err != nil {
			return err
		}
		if d.Host != v.result.Checkpoint.HostBarrier || d.Guest != v.result.Checkpoint.GuestBarrier {
			return errors.New("event barriers differ from result checkpoint")
		}
	case 9:
		var d struct {
			State  artifact `json:"state"`
			Memory artifact `json:"memory"`
		}
		if err := decodeExact(event.Details, []string{"state", "memory"}, &d); err != nil {
			return err
		}
		if d.State != v.result.Artifacts["snapshot_state"] || d.Memory != v.result.Artifacts["snapshot_memory"] {
			return errors.New("snapshot artifacts differ from result")
		}
	case 10:
		var d struct {
			Disposition string `json:"disposition"`
		}
		if err := decodeExact(event.Details, []string{"disposition"}, &d); err != nil {
			return err
		}
		if d.Disposition != "supervisor" {
			return errors.New("g1 was not supervisor-SIGKILLed")
		}
	case 11:
		var d struct {
			State      sealedArtifact `json:"state"`
			Memory     sealedArtifact `json:"memory"`
			Payload    sealedArtifact `json:"payload"`
			Repository sealedArtifact `json:"repository"`
		}
		if err := decodeExact(event.Details, []string{"state", "memory", "payload", "repository"}, &d); err != nil {
			return err
		}
		if d.State != v.result.SealedLoadInputs[0] || d.Memory != v.result.SealedLoadInputs[1] || d.Payload != v.result.SealedLoadInputs[2] || d.Repository != v.result.SealedLoadInputs[3] {
			return errors.New("sealed snapshot inputs differ from result")
		}
	case 12:
		var d struct {
			Generation uint64 `json:"generation"`
		}
		if err := decodeExact(event.Details, []string{"generation"}, &d); err != nil {
			return err
		}
		if d.Generation != restoredGeneration {
			return errors.New("bridge did not advance to g3")
		}
	case 14:
		var d struct {
			StateSHA256  string `json:"state_sha256"`
			MemorySHA256 string `json:"memory_sha256"`
		}
		if err := decodeExact(event.Details, []string{"state_sha256", "memory_sha256"}, &d); err != nil {
			return err
		}
		if d.StateSHA256 != v.result.Artifacts["snapshot_state"].SHA256 || d.MemorySHA256 != v.result.Artifacts["snapshot_memory"].SHA256 {
			return errors.New("loaded snapshot hashes differ")
		}
	case 21:
		var d struct {
			BaseRoot       string   `json:"base_root"`
			FinalRoot      string   `json:"final_root"`
			OperationCount int      `json:"operation_count"`
			FinalBundle    artifact `json:"final_bundle"`
			Delta          artifact `json:"delta"`
		}
		if err := decodeExact(event.Details, []string{"base_root", "final_root", "operation_count", "final_bundle", "delta"}, &d); err != nil {
			return err
		}
		if d.BaseRoot != v.baseRepository.TreeRoot.String() || d.FinalRoot != v.finalRepository.TreeRoot.String() || d.OperationCount != len(v.repositoryDelta.Operations) || d.FinalBundle != v.result.Artifacts["repository_final"] || d.Delta != v.result.Artifacts["repository_delta"] {
			return errors.New("repository export event differs from retained artifacts")
		}
	case 22:
		var d struct {
			Error string `json:"error"`
		}
		if err := decodeExact(event.Details, []string{"error"}, &d); err != nil {
			return err
		}
		if d.Error != "" {
			return errors.New("run-completed carries an error")
		}
	}
	return nil
}

type apiExpectation struct {
	method, path string
	status       int
	request      bool
	state        string
}

var g1API = []apiExpectation{
	{"GET", "/", 200, false, "Not started"},
	{"PUT", "/machine-config", 204, true, ""},
	{"PUT", "/boot-source", 204, true, ""},
	{"PUT", "/vsock", 204, true, ""},
	{"PUT", "/drives/payload", 204, true, ""},
	{"PUT", "/drives/repository", 204, true, ""},
	{"PUT", "/actions", 204, true, ""},
	{"GET", "/", 200, false, "Running"},
	{"PATCH", "/vm", 204, true, ""},
	{"GET", "/", 200, false, "Paused"},
	{"PUT", "/snapshot/create", 204, true, ""},
}

var g3API = []apiExpectation{
	{"GET", "/", 200, false, "Not started"},
	{"PUT", "/snapshot/load", 204, true, ""},
	{"GET", "/", 200, false, "Paused"},
	{"PATCH", "/vm", 204, true, ""},
	{"GET", "/", 200, false, "Running"},
}

func (v *verifier) verifyAPITraces() error {
	g1, err := v.readAPI("g1", v.g1, g1API)
	if err != nil {
		return err
	}
	g3, err := v.readAPI("g3", v.g3, g3API)
	if err != nil {
		return err
	}
	// Join API call times to the independently ordered lifecycle log.
	if !(g1[0].TimeNS >= v.g1.StartedTimeNS && g1[0].TimeNS <= v.events[3].TimeNS &&
		g1[1].TimeNS > v.events[3].TimeNS && g1[4].TimeNS < v.events[4].TimeNS &&
		g1[5].TimeNS < v.events[4].TimeNS && g1[6].TimeNS > v.events[4].TimeNS && g1[7].TimeNS < v.events[5].TimeNS &&
		g1[8].TimeNS > v.events[7].TimeNS && g1[9].TimeNS < v.events[8].TimeNS &&
		g1[10].TimeNS > v.events[8].TimeNS && g1[10].TimeNS < v.events[9].TimeNS && g1[10].TimeNS < v.g1.StoppedTimeNS) {
		return errors.New("g1 API times contradict checkpoint/pause/snapshot lifecycle")
	}
	if !(g3[0].TimeNS >= v.g3.StartedTimeNS && g3[0].TimeNS <= v.events[13].TimeNS &&
		g3[1].TimeNS > v.events[13].TimeNS && g3[2].TimeNS < v.events[14].TimeNS &&
		g3[3].TimeNS > v.events[15].TimeNS && g3[4].TimeNS < v.events[16].TimeNS && g3[4].TimeNS < v.g3.StoppedTimeNS) {
		return errors.New("g3 API times contradict paused-load/arm/resume lifecycle")
	}
	return nil
}

func (v *verifier) readAPI(label string, process processRecord, wants []apiExpectation) ([]apiTrace, error) {
	path := evidencePath(v, "firecracker-api-"+label+".jsonl")
	if err := requirePrivateFile(path); err != nil {
		return nil, err
	}
	var records []apiTrace
	err := readJSONL(path, func(raw []byte) error {
		index := len(records)
		if index >= len(wants) {
			return errors.New("too many API calls")
		}
		want := wants[index]
		fields := []string{"sequence", "time_ns", "method", "path", "status"}
		if want.request {
			fields = append(fields, "request")
		} else {
			fields = append(fields, "response")
		}
		var record apiTrace
		if err := decodeExact(raw, fields, &record); err != nil {
			return err
		}
		if record.Sequence != uint64(index+1) || record.TimeNS <= 0 || record.Method != want.method || record.Path != want.path || record.Status != want.status {
			return fmt.Errorf("call %d differs from required %s %s", index+1, want.method, want.path)
		}
		if index > 0 && record.TimeNS <= records[index-1].TimeNS {
			return errors.New("API timestamps are not strictly increasing")
		}
		if want.request {
			if len(record.Request) == 0 {
				return errors.New("API request body is absent")
			}
			if err := v.verifyAPIRequest(label, index, record.Request); err != nil {
				return err
			}
		} else {
			if len(record.Response) == 0 {
				return errors.New("API response body is absent")
			}
			if err := verifyStateResponse(record.Response, process, want.state); err != nil {
				return err
			}
		}
		records = append(records, record)
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("%s trace: %w", label, err)
	}
	if len(records) != len(wants) {
		return nil, fmt.Errorf("%s API call count is %d, require %d", label, len(records), len(wants))
	}
	return records, nil
}

func verifyStateResponse(raw []byte, process processRecord, wantState string) error {
	var state struct {
		AppName    string `json:"app_name"`
		ID         string `json:"id"`
		State      string `json:"state"`
		VMMVersion string `json:"vmm_version"`
	}
	if err := decodeExact(raw, []string{"app_name", "id", "state", "vmm_version"}, &state); err != nil {
		return err
	}
	if state.AppName == "" || state.ID != process.ID || state.State != wantState || state.VMMVersion != process.VMMVersion {
		return errors.New("Firecracker state response differs from process/lifecycle")
	}
	return nil
}

func (v *verifier) verifyAPIRequest(label string, index int, raw []byte) error {
	if label == "g1" {
		switch index {
		case 1:
			var x struct {
				VCPUCount       int  `json:"vcpu_count"`
				MemSizeMiB      int  `json:"mem_size_mib"`
				SMT             bool `json:"smt"`
				TrackDirtyPages bool `json:"track_dirty_pages"`
			}
			if err := decodeExact(raw, []string{"vcpu_count", "mem_size_mib", "smt", "track_dirty_pages"}, &x); err != nil {
				return err
			}
			if x.VCPUCount != 1 || x.MemSizeMiB != 1024 || x.SMT || x.TrackDirtyPages {
				return errors.New("machine config is not the fixed 1-vCPU/1024-MiB slice")
			}
		case 2:
			var x struct {
				Kernel   string `json:"kernel_image_path"`
				BootArgs string `json:"boot_args"`
				Initrd   string `json:"initrd_path"`
			}
			if err := decodeExact(raw, []string{"kernel_image_path", "boot_args", "initrd_path"}, &x); err != nil {
				return err
			}
			if x.Kernel != fdKernel || x.Initrd != fdInitramfs || x.BootArgs != "console=ttyS0 reboot=k panic=1 pci=off rdinit=/init" {
				return errors.New("boot source does not use sealed fd4/fd5")
			}
		case 3:
			var x struct {
				GuestCID uint32 `json:"guest_cid"`
				UDS      string `json:"uds_path"`
			}
			if err := decodeExact(raw, []string{"guest_cid", "uds_path"}, &x); err != nil {
				return err
			}
			if x.GuestCID != 3 || x.UDS != v.g1.VsockBackend.Path {
				return errors.New("g1 vsock config differs from process record")
			}
		case 4:
			var x struct {
				DriveID  string `json:"drive_id"`
				Path     string `json:"path_on_host"`
				Root     bool   `json:"is_root_device"`
				ReadOnly bool   `json:"is_read_only"`
			}
			if err := decodeExact(raw, []string{"drive_id", "path_on_host", "is_root_device", "is_read_only"}, &x); err != nil {
				return err
			}
			if x.DriveID != "payload" || x.Path != fdPayload || x.Root || !x.ReadOnly {
				return errors.New("payload is not a read-only non-root fd6 drive")
			}
		case 5:
			var x struct {
				DriveID  string `json:"drive_id"`
				Path     string `json:"path_on_host"`
				Root     bool   `json:"is_root_device"`
				ReadOnly bool   `json:"is_read_only"`
			}
			if err := decodeExact(raw, []string{"drive_id", "path_on_host", "is_root_device", "is_read_only"}, &x); err != nil {
				return err
			}
			if x.DriveID != "repository" || x.Path != fdRepository || x.Root || !x.ReadOnly {
				return errors.New("repository is not a read-only non-root fd7 drive")
			}
		case 6:
			var x struct {
				Action string `json:"action_type"`
			}
			if err := decodeExact(raw, []string{"action_type"}, &x); err != nil {
				return err
			}
			if x.Action != "InstanceStart" {
				return errors.New("g1 action is not InstanceStart")
			}
		case 8:
			return verifyVMStateRequest(raw, "Paused")
		case 10:
			var x struct {
				Type     string `json:"snapshot_type"`
				Snapshot string `json:"snapshot_path"`
				Memory   string `json:"mem_file_path"`
			}
			if err := decodeExact(raw, []string{"snapshot_type", "snapshot_path", "mem_file_path"}, &x); err != nil {
				return err
			}
			if x.Type != "Full" || x.Snapshot != evidencePath(v, "snapshot.state") || x.Memory != evidencePath(v, "snapshot.memory") {
				return errors.New("snapshot create is not a retained full snapshot")
			}
		default:
			return fmt.Errorf("unexpected g1 request index %d", index)
		}
		return nil
	}
	switch index {
	case 1:
		type backend struct {
			Type string `json:"backend_type"`
			Path string `json:"backend_path"`
		}
		type override struct {
			UDS string `json:"uds_path"`
		}
		var x struct {
			Snapshot string   `json:"snapshot_path"`
			Backend  backend  `json:"mem_backend"`
			Resume   bool     `json:"resume_vm"`
			Vsock    override `json:"vsock_override"`
		}
		if err := decodeExact(raw, []string{"snapshot_path", "mem_backend", "resume_vm", "vsock_override"}, &x); err != nil {
			return err
		}
		var root map[string]json.RawMessage
		_ = json.Unmarshal(raw, &root)
		if err := decodeExact(root["mem_backend"], []string{"backend_type", "backend_path"}, &x.Backend); err != nil {
			return err
		}
		if err := decodeExact(root["vsock_override"], []string{"uds_path"}, &x.Vsock); err != nil {
			return err
		}
		if x.Snapshot != fdKernel || x.Backend.Type != "File" || x.Backend.Path != fdInitramfs || x.Resume || x.Vsock.UDS != v.g3.VsockBackend.Path {
			return errors.New("snapshot load is not paused fd4/fd5 with g3 vsock override")
		}
	case 3:
		return verifyVMStateRequest(raw, "Resumed")
	default:
		return fmt.Errorf("unexpected g3 request index %d", index)
	}
	return nil
}

func verifyVMStateRequest(raw []byte, want string) error {
	var x struct {
		State string `json:"state"`
	}
	if err := decodeExact(raw, []string{"state"}, &x); err != nil {
		return err
	}
	if x.State != want {
		return fmt.Errorf("VM state request is %q, require %q", x.State, want)
	}
	return nil
}

func (v *verifier) verifyRelaysAndProxy() error {
	var relayBytes []string
	shimPID := 0
	for _, item := range []struct {
		label   string
		process processRecord
	}{{"g1", v.g1}, {"g3", v.g3}} {
		path := evidencePath(v, "firecracker-relay-"+item.label+".jsonl")
		if err := requirePrivateFile(path); err != nil {
			return err
		}
		accepts, bytesCount := 0, 0
		err := readJSONL(path, func(raw []byte) error {
			var header relayRecord
			if err := decodeAllowed(raw, []string{"event", "time", "generation", "port", "pid", "sandbox_peer_pid", "sandbox_device", "sandbox_inode", "guest_to_host_bytes", "host_to_guest_bytes"}, []string{"event"}, &header); err != nil {
				return err
			}
			var record relayRecord
			switch header.Event {
			case "accept":
				if err := decodeExact(raw, []string{"event", "time", "generation", "port", "pid", "sandbox_device", "sandbox_inode", "guest_to_host_bytes", "host_to_guest_bytes"}, &record); err != nil {
					return err
				}
				accepts++
				if record.PID != item.process.PID || record.SandboxPID != 0 || record.GuestToHost != 0 || record.HostToGuest != 0 {
					return errors.New("relay accept PID/zero counters are malformed")
				}
			case "bytes":
				if err := decodeExact(raw, []string{"event", "time", "generation", "port", "sandbox_peer_pid", "sandbox_device", "sandbox_inode", "guest_to_host_bytes", "host_to_guest_bytes"}, &record); err != nil {
					return err
				}
				bytesCount++
				if bytesCount > accepts || record.PID != 0 || record.SandboxPID <= 0 || record.GuestToHost <= 0 || record.HostToGuest <= 0 {
					return errors.New("relay byte record lacks a preceding accepted connection")
				}
				if shimPID == 0 {
					shimPID = record.SandboxPID
				} else if shimPID != record.SandboxPID {
					return errors.New("relay records name different sandbox peer PIDs")
				}
				relayBytes = append(relayBytes, bytePair(record.GuestToHost, record.HostToGuest))
			default:
				return fmt.Errorf("forbidden relay event %q", header.Event)
			}
			if record.Time.IsZero() || record.Generation != item.process.Generation || record.Port != v.guest.ModelPort || record.SandboxDevice == 0 || record.SandboxInode == 0 {
				return errors.New("relay record identity is incomplete")
			}
			timeNS := record.Time.UnixNano()
			if item.process.Generation == firstGeneration {
				if timeNS <= v.events[5].TimeNS || timeNS >= v.events[7].TimeNS {
					return errors.New("g1 model traffic was not closed before model-path quiescence")
				}
			} else if timeNS <= v.events[19].TimeNS || timeNS >= v.events[20].TimeNS {
				return errors.New("g3 model traffic was not confined after tool release and before session completion")
			}
			return nil
		})
		if err != nil {
			return fmt.Errorf("%s: %w", item.label, err)
		}
		if accepts == 0 || accepts != bytesCount {
			return fmt.Errorf("%s relay has %d accepts and %d byte records", item.label, accepts, bytesCount)
		}
	}
	if shimPID <= 0 {
		return errors.New("relay did not record a sandbox peer PID")
	}

	proxyPath := evidencePath(v, "model-proxy.jsonl")
	if err := requirePrivateFile(proxyPath); err != nil {
		return err
	}
	accepts, bytesCount := 0, 0
	var proxyBytes []string
	device, inode := uint64(0), uint64(0)
	proxyUID, proxyGID := uint32(0), uint32(0)
	haveProxyCredential := false
	err := readJSONL(proxyPath, func(raw []byte) error {
		var header proxyRecord
		if err := decodeAllowed(raw, []string{"event", "time", "target", "pid", "uid", "gid", "socket_device", "socket_inode", "client_to_target_bytes", "target_to_client_bytes"}, []string{"event"}, &header); err != nil {
			return err
		}
		var record proxyRecord
		if err := decodeExact(raw, []string{"event", "time", "target", "pid", "uid", "gid", "socket_device", "socket_inode", "client_to_target_bytes", "target_to_client_bytes"}, &record); err != nil {
			return err
		}
		if record.Time.IsZero() || record.Target != v.modelTarget || record.SocketDevice == 0 || record.SocketInode == 0 {
			return errors.New("proxy record target/socket identity is malformed")
		}
		timeNS := record.Time.UnixNano()
		inG1Window := timeNS > v.events[5].TimeNS && timeNS < v.events[7].TimeNS
		inG3Window := timeNS > v.events[19].TimeNS && timeNS < v.events[20].TimeNS
		if !inG1Window && !inG3Window {
			return errors.New("model proxy traffic overlaps the checkpoint/restore transition")
		}
		if device == 0 {
			device, inode = record.SocketDevice, record.SocketInode
		} else if device != record.SocketDevice || inode != record.SocketInode {
			return errors.New("proxy socket identity changed")
		}
		switch header.Event {
		case "accept":
			accepts++
			if !haveProxyCredential {
				proxyUID, proxyGID = record.UID, record.GID
				haveProxyCredential = true
			}
			if record.PID != shimPID || record.UID != proxyUID || record.GID != proxyGID || record.UID != v.g1.APISocket.UID || record.ClientToTarget != 0 || record.TargetToClient != 0 {
				return errors.New("proxy accept credentials/counters are malformed")
			}
		case "bytes":
			bytesCount++
			if bytesCount > accepts || record.PID != 0 || record.UID != 0 || record.GID != 0 || record.ClientToTarget <= 0 || record.TargetToClient <= 0 {
				return errors.New("proxy byte record lacks a preceding accept")
			}
			proxyBytes = append(proxyBytes, bytePair(record.ClientToTarget, record.TargetToClient))
		default:
			return fmt.Errorf("forbidden proxy event %q", header.Event)
		}
		return nil
	})
	if err != nil {
		return err
	}
	if accepts == 0 || accepts != bytesCount {
		return fmt.Errorf("proxy has %d accepts and %d byte records", accepts, bytesCount)
	}
	sort.Strings(relayBytes)
	sort.Strings(proxyBytes)
	if !reflect.DeepEqual(relayBytes, proxyBytes) {
		return errors.New("relay and loopback-proxy byte records do not describe the same connections")
	}
	// Every relay record must name the one proxy socket identity.
	for _, label := range []string{"g1", "g3"} {
		err := readJSONL(evidencePath(v, "firecracker-relay-"+label+".jsonl"), func(raw []byte) error {
			var record relayRecord
			if err := decodeAllowed(raw, []string{"event", "time", "generation", "port", "pid", "sandbox_peer_pid", "sandbox_device", "sandbox_inode", "guest_to_host_bytes", "host_to_guest_bytes"}, []string{"event", "time", "generation", "port", "sandbox_device", "sandbox_inode", "guest_to_host_bytes", "host_to_guest_bytes"}, &record); err != nil {
				return err
			}
			if record.SandboxDevice != device || record.SandboxInode != inode {
				return errors.New("relay sandbox socket differs from proxy socket")
			}
			return nil
		})
		if err != nil {
			return err
		}
	}
	return nil
}

func bytePair(left, right int64) string { return fmt.Sprintf("%020d/%020d", left, right) }

type adapterToolParams struct {
	Arguments map[string]json.RawMessage `json:"arguments"`
	CallID    string                     `json:"callId"`
	Namespace *string                    `json:"namespace"`
	ThreadID  string                     `json:"threadId"`
	Tool      string                     `json:"tool"`
	TurnID    string                     `json:"turnId"`
}

type adapterCallEvidence struct {
	record rawAdapterRecord
	id     string
	params adapterToolParams
}

type adapterResponseEvidence struct {
	record       rawAdapterRecord
	contentItems json.RawMessage
}

func (v *verifier) verifyAdapter() error {
	var records []rawAdapterRecord
	err := readJSONL(v.opts.adapterJSONL, func(raw []byte) error {
		var record rawAdapterRecord
		if err := decodeExact(raw, []string{"sequence", "time_ns", "direction", "payload"}, &record); err != nil {
			return err
		}
		if record.Sequence != uint64(len(records)+1) || record.TimeNS <= 0 {
			return errors.New("adapter sequence/time is invalid")
		}
		if len(records) > 0 && record.TimeNS < records[len(records)-1].TimeNS {
			return errors.New("adapter timestamps move backwards")
		}
		switch record.Direction {
		case "meta", "client_to_server", "server_to_client", "server_stderr":
		default:
			return fmt.Errorf("forbidden adapter direction %q", record.Direction)
		}
		if err := rejectDuplicateFields(record.Payload); err != nil {
			return fmt.Errorf("payload: %w", err)
		}
		var object map[string]json.RawMessage
		if err := json.Unmarshal(record.Payload, &object); err != nil || object == nil {
			return errors.New("adapter payload is not an object")
		}
		if record.Direction == "server_stdout_invalid" {
			return errors.New("adapter captured invalid server stdout")
		}
		records = append(records, record)
		return nil
	})
	if err != nil {
		return err
	}
	bridgeProofs, err := v.verifyBridgeIO(records)
	if err != nil {
		return fmt.Errorf("bridge I/O commitment: %w", err)
	}
	if err := v.verifyAdapterProcessRecords(records); err != nil {
		return err
	}
	var calls []adapterCallEvidence
	for _, record := range records {
		if record.Direction != "server_to_client" {
			continue
		}
		var object map[string]json.RawMessage
		_ = json.Unmarshal(record.Payload, &object)
		methodRaw, ok := object["method"]
		if !ok {
			continue
		}
		var method string
		if json.Unmarshal(methodRaw, &method) != nil || method != "item/tool/call" {
			continue
		}
		var call struct {
			ID     json.RawMessage   `json:"id"`
			Method string            `json:"method"`
			Params adapterToolParams `json:"params"`
		}
		if err := decodeExact(record.Payload, []string{"id", "method", "params"}, &call); err != nil {
			return err
		}
		var root map[string]json.RawMessage
		_ = json.Unmarshal(record.Payload, &root)
		if err := decodeExact(root["params"], []string{"arguments", "callId", "namespace", "threadId", "tool", "turnId"}, &call.Params); err != nil {
			return err
		}
		id, err := normalizeRPCID(call.ID)
		if err != nil {
			return err
		}
		if call.Method != "item/tool/call" || call.Params.CallID != "preflight-call-1" || call.Params.ThreadID == "" || call.Params.TurnID == "" || call.Params.Tool != "protected_commit" || call.Params.Namespace != nil {
			return errors.New("item/tool/call is not the fixed protected preflight callback")
		}
		if err := requirePreflightArguments(call.Params.Arguments); err != nil {
			return err
		}
		calls = append(calls, adapterCallEvidence{record: record, id: id, params: call.Params})
	}
	if len(calls) != 1 {
		return fmt.Errorf("captured %d item/tool/call messages, require exactly one", len(calls))
	}
	call := calls[0]
	callProof, ok := bridgeProofs[call.record.Sequence]
	if !ok || callProof.First.Phase != "authorized" || callProof.Second == nil || callProof.Second.Phase != "delivered" {
		return errors.New("item/tool/call lacks an authorized/delivered bridge commitment")
	}
	if !(v.events[18].TimeNS < callProof.First.TimeNS && callProof.First.TimeNS < callProof.Second.TimeNS && callProof.Second.TimeNS < v.events[19].TimeNS) {
		return errors.New("item/tool/call bridge commitment is outside its runtime authorization/delivery events")
	}
	if call.record.TimeNS <= callProof.First.TimeNS || call.record.TimeNS >= v.events[20].TimeNS {
		return errors.New("adapter did not capture the protected callback after authorization and before session completion")
	}
	var responses []adapterResponseEvidence
	for _, record := range records {
		if record.Direction != "client_to_server" || record.Sequence <= call.record.Sequence {
			continue
		}
		var object map[string]json.RawMessage
		_ = json.Unmarshal(record.Payload, &object)
		idRaw, hasID := object["id"]
		_, hasResult := object["result"]
		if !hasID || !hasResult {
			continue
		}
		id, err := normalizeRPCID(idRaw)
		if err != nil {
			continue
		}
		if id != call.id {
			continue
		}
		var response struct {
			ID     json.RawMessage `json:"id"`
			Result struct {
				ContentItems []struct {
					Type string `json:"type"`
					Text string `json:"text"`
				} `json:"contentItems"`
				Success bool `json:"success"`
			} `json:"result"`
		}
		if err := decodeExact(record.Payload, []string{"id", "result"}, &response); err != nil {
			return err
		}
		var root map[string]json.RawMessage
		_ = json.Unmarshal(record.Payload, &root)
		if err := decodeExact(root["result"], []string{"contentItems", "success"}, &response.Result); err != nil {
			return err
		}
		if !response.Result.Success || len(response.Result.ContentItems) != 1 {
			return errors.New("tool response is unsuccessful or empty")
		}
		var resultRoot map[string]json.RawMessage
		_ = json.Unmarshal(root["result"], &resultRoot)
		var itemRaws []json.RawMessage
		if err := json.Unmarshal(resultRoot["contentItems"], &itemRaws); err != nil {
			return err
		}
		for index, item := range response.Result.ContentItems {
			if err := decodeExact(itemRaws[index], []string{"type", "text"}, &item); err != nil {
				return err
			}
			if item.Type != "inputText" || item.Text != "receipt:preflight-effect-1" {
				return errors.New("tool response content item is malformed")
			}
		}
		if record.TimeNS < call.record.TimeNS || record.TimeNS >= v.events[20].TimeNS {
			return errors.New("tool response does not follow the g3-exposed call before session completion")
		}
		responses = append(responses, adapterResponseEvidence{record: record, contentItems: append(json.RawMessage(nil), resultRoot["contentItems"]...)})
	}
	if len(responses) != 1 {
		return fmt.Errorf("captured %d matching tool responses, require one", len(responses))
	}
	responseProof, ok := bridgeProofs[responses[0].record.Sequence]
	if !ok || responseProof.First.Phase != "observed" || responseProof.Second != nil || responseProof.First.TimeNS <= callProof.First.TimeNS || responseProof.First.TimeNS >= v.events[20].TimeNS {
		return errors.New("tool response lacks a post-authorization, pre-completion observed bridge commitment")
	}
	if err := v.verifyAdapterToolLifecycle(records, bridgeProofs, call, responses[0]); err != nil {
		return err
	}
	return nil
}

func (v *verifier) verifyBridgeIO(adapterRecords []rawAdapterRecord) (map[uint64]bridgeMessageProof, error) {
	path := evidencePath(v, "bridge-io.jsonl")
	if err := requirePrivateFile(path); err != nil {
		return nil, err
	}
	var records []bridgeIORecord
	err := readJSONL(path, func(raw []byte) error {
		var record bridgeIORecord
		if err := decodeExact(raw, []string{"schema", "sequence", "phase", "direction", "time_ns", "canonical_size", "canonical_sha256"}, &record); err != nil {
			return err
		}
		if record.Schema != eventSchema || record.Sequence != uint64(len(records)+1) || record.TimeNS <= 0 || record.Size <= 1 || !validDigest(record.SHA256) {
			return errors.New("bridge I/O schema/sequence/time/commitment is malformed")
		}
		if len(records) > 0 && record.TimeNS <= records[len(records)-1].TimeNS {
			return errors.New("bridge I/O timestamps are not strictly increasing")
		}
		switch record.Direction {
		case "client_to_server":
			if record.Phase != "observed" {
				return errors.New("client-to-server bridge I/O is not observed exactly once")
			}
		case "server_to_client":
			if record.Phase != "authorized" && record.Phase != "delivered" {
				return errors.New("server-to-client bridge I/O has a forbidden phase")
			}
		default:
			return fmt.Errorf("forbidden bridge I/O direction %q", record.Direction)
		}
		records = append(records, record)
		return nil
	})
	if err != nil {
		return nil, err
	}

	var observed, authorized, delivered []bridgeIORecord
	for _, record := range records {
		switch record.Phase {
		case "observed":
			observed = append(observed, record)
		case "authorized":
			authorized = append(authorized, record)
		case "delivered":
			delivered = append(delivered, record)
		}
	}
	if len(authorized) != len(delivered) {
		return nil, fmt.Errorf("bridge has %d authorizations and %d deliveries", len(authorized), len(delivered))
	}
	for index := range authorized {
		if authorized[index].Sequence >= delivered[index].Sequence || authorized[index].SHA256 != delivered[index].SHA256 || authorized[index].Size != delivered[index].Size {
			return nil, fmt.Errorf("server-to-client bridge message %d authorization differs from delivery", index+1)
		}
		if index+1 < len(authorized) && delivered[index].Sequence >= authorized[index+1].Sequence {
			return nil, fmt.Errorf("server-to-client bridge message %d overlaps the next authorization", index+1)
		}
	}

	var clientAdapter, serverAdapter []rawAdapterRecord
	for _, record := range adapterRecords {
		switch record.Direction {
		case "client_to_server":
			clientAdapter = append(clientAdapter, record)
		case "server_to_client":
			serverAdapter = append(serverAdapter, record)
		}
	}
	if len(clientAdapter) != len(observed) || len(serverAdapter) != len(authorized) {
		return nil, fmt.Errorf("adapter/bridge message counts differ: client %d/%d, server %d/%d", len(clientAdapter), len(observed), len(serverAdapter), len(authorized))
	}
	proofs := make(map[uint64]bridgeMessageProof, len(clientAdapter)+len(serverAdapter))
	match := func(adapter rawAdapterRecord, record bridgeIORecord) error {
		canonical, err := canonicalJSONObject(adapter.Payload)
		if err != nil {
			return err
		}
		if record.Size != len(canonical) || record.SHA256 != hashBytes(canonical) {
			return errors.New("canonical size/digest differs")
		}
		return nil
	}
	for index, adapter := range clientAdapter {
		if err := match(adapter, observed[index]); err != nil {
			return nil, fmt.Errorf("adapter client message %d: %w", index+1, err)
		}
		if adapter.TimeNS >= observed[index].TimeNS {
			return nil, fmt.Errorf("adapter client message %d was not captured before runtime observation", index+1)
		}
		proofs[adapter.Sequence] = bridgeMessageProof{First: observed[index]}
	}
	for index, adapter := range serverAdapter {
		if err := match(adapter, authorized[index]); err != nil {
			return nil, fmt.Errorf("adapter server message %d: %w", index+1, err)
		}
		if authorized[index].TimeNS >= adapter.TimeNS {
			return nil, fmt.Errorf("adapter server message %d was captured before runtime authorization", index+1)
		}
		copyDelivered := delivered[index]
		proofs[adapter.Sequence] = bridgeMessageProof{First: authorized[index], Second: &copyDelivered}
	}
	return proofs, nil
}

func requirePreflightArguments(arguments map[string]json.RawMessage) error {
	if len(arguments) != 1 {
		return errors.New("protected callback arguments must contain exactly effect_id")
	}
	var effectID string
	if err := json.Unmarshal(arguments["effect_id"], &effectID); err != nil || effectID != "preflight-effect-1" {
		return errors.New("protected callback effect_id differs from the preflight fixture")
	}
	return nil
}

func (v *verifier) verifyAdapterProcessRecords(records []rawAdapterRecord) error {
	starts, stops := 0, 0
	for _, record := range records {
		if record.Direction == "server_stderr" {
			var payload struct {
				Line string `json:"line"`
			}
			if err := decodeExact(record.Payload, []string{"line"}, &payload); err != nil || payload.Line == "" {
				return errors.New("server_stderr payload is malformed")
			}
			continue
		}
		if record.Direction != "meta" {
			continue
		}
		var header struct {
			Event string `json:"event"`
		}
		var object map[string]json.RawMessage
		if err := json.Unmarshal(record.Payload, &object); err != nil || object == nil {
			return errors.New("adapter meta payload is not an object")
		}
		if eventRaw, ok := object["event"]; !ok || json.Unmarshal(eventRaw, &header.Event) != nil || header.Event == "" {
			return errors.New("adapter meta payload lacks an event")
		}
		switch header.Event {
		case "process_start":
			var payload struct {
				Event   string   `json:"event"`
				Command []string `json:"command"`
			}
			if err := decodeExact(record.Payload, []string{"event", "command"}, &payload); err != nil {
				return err
			}
			starts++
			if starts != 1 || len(payload.Command) != len(v.guest.Arguments)+1 || filepath.Base(payload.Command[0]) != "codex" || !reflect.DeepEqual(payload.Command[1:], v.guest.Arguments) || record.TimeNS >= v.events[0].TimeNS {
				return errors.New("adapter process_start is not the one shim command preceding the run")
			}
		case "process_stop":
			var payload struct {
				Event      string `json:"event"`
				Returncode int    `json:"returncode"`
			}
			if err := decodeExact(record.Payload, []string{"event", "returncode"}, &payload); err != nil {
				return err
			}
			stops++
			if stops != 1 || payload.Returncode != 0 || record.TimeNS <= v.events[21].TimeNS {
				return errors.New("adapter process_stop is not one clean exit after run completion")
			}
		default:
			return fmt.Errorf("forbidden adapter meta event %q", header.Event)
		}
	}
	if starts != 1 || stops != 1 {
		return fmt.Errorf("adapter capture has %d process_start and %d process_stop records", starts, stops)
	}
	return nil
}

type dynamicToolItem struct {
	Arguments    map[string]json.RawMessage `json:"arguments"`
	ContentItems json.RawMessage            `json:"contentItems"`
	DurationMS   *int64                     `json:"durationMs"`
	ID           string                     `json:"id"`
	Namespace    *string                    `json:"namespace"`
	Status       string                     `json:"status"`
	Success      *bool                      `json:"success"`
	Tool         string                     `json:"tool"`
	Type         string                     `json:"type"`
}

func (v *verifier) verifyAdapterToolLifecycle(records []rawAdapterRecord, bridgeProofs map[uint64]bridgeMessageProof, call adapterCallEvidence, response adapterResponseEvidence) error {
	started, completed, turnCompleted := 0, 0, 0
	var completedSequence uint64
	for _, record := range records {
		if record.Direction != "server_to_client" {
			continue
		}
		var outer map[string]json.RawMessage
		_ = json.Unmarshal(record.Payload, &outer)
		var method string
		if json.Unmarshal(outer["method"], &method) != nil {
			continue
		}
		switch method {
		case "item/started", "item/completed":
			var envelope struct {
				EmittedAtMS *int64          `json:"emittedAtMs"`
				Method      string          `json:"method"`
				Params      json.RawMessage `json:"params"`
			}
			if err := decodeAllowed(record.Payload, []string{"emittedAtMs", "method", "params"}, []string{"method", "params"}, &envelope); err != nil {
				return err
			}
			if err := validateEmittedAt(envelope.EmittedAtMS, record.TimeNS); err != nil {
				return err
			}
			var paramsRoot map[string]json.RawMessage
			if err := json.Unmarshal(envelope.Params, &paramsRoot); err != nil {
				return err
			}
			itemRaw := paramsRoot["item"]
			var itemObject map[string]json.RawMessage
			if err := json.Unmarshal(itemRaw, &itemObject); err != nil || itemObject == nil {
				return errors.New("item lifecycle payload is not an object")
			}
			var itemType string
			if json.Unmarshal(itemObject["type"], &itemType) != nil {
				continue
			}
			if itemType != "dynamicToolCall" {
				continue
			}
			var item dynamicToolItem
			if err := decodeExact(itemRaw, []string{"arguments", "contentItems", "durationMs", "id", "namespace", "status", "success", "tool", "type"}, &item); err != nil {
				return err
			}
			var threadID, turnID string
			if method == "item/started" {
				var params struct {
					Item        json.RawMessage `json:"item"`
					StartedAtMS int64           `json:"startedAtMs"`
					ThreadID    string          `json:"threadId"`
					TurnID      string          `json:"turnId"`
				}
				if err := decodeExact(envelope.Params, []string{"item", "startedAtMs", "threadId", "turnId"}, &params); err != nil || params.StartedAtMS <= 0 {
					return errors.New("dynamic tool item/started envelope is malformed")
				}
				threadID, turnID = params.ThreadID, params.TurnID
				started++
				if started != 1 || record.Sequence >= call.record.Sequence || item.Status != "inProgress" || item.DurationMS != nil || item.Success != nil || string(item.ContentItems) != "null" {
					return errors.New("dynamic tool start does not precede the protected callback")
				}
			} else {
				var params struct {
					CompletedAtMS int64           `json:"completedAtMs"`
					Item          json.RawMessage `json:"item"`
					ThreadID      string          `json:"threadId"`
					TurnID        string          `json:"turnId"`
				}
				if err := decodeExact(envelope.Params, []string{"completedAtMs", "item", "threadId", "turnId"}, &params); err != nil || params.CompletedAtMS <= 0 {
					return errors.New("dynamic tool item/completed envelope is malformed")
				}
				threadID, turnID = params.ThreadID, params.TurnID
				completed++
				if completed != 1 || record.Sequence <= response.record.Sequence || item.Status != "completed" || item.DurationMS == nil || *item.DurationMS < 0 || item.Success == nil || !*item.Success || !sameCanonicalJSON(item.ContentItems, response.contentItems) {
					return errors.New("dynamic tool completion does not follow/match the callback response")
				}
				completedSequence = record.Sequence
			}
			if item.ID != call.params.CallID || item.Tool != call.params.Tool || item.Namespace != nil || threadID != call.params.ThreadID || turnID != call.params.TurnID || !sameArgumentMaps(item.Arguments, call.params.Arguments) {
				return errors.New("dynamic tool lifecycle identity differs from item/tool/call")
			}
		case "turn/completed":
			var envelope struct {
				EmittedAtMS *int64          `json:"emittedAtMs"`
				Method      string          `json:"method"`
				Params      json.RawMessage `json:"params"`
			}
			if err := decodeAllowed(record.Payload, []string{"emittedAtMs", "method", "params"}, []string{"method", "params"}, &envelope); err != nil {
				return err
			}
			if err := validateEmittedAt(envelope.EmittedAtMS, record.TimeNS); err != nil {
				return err
			}
			var params struct {
				ThreadID string          `json:"threadId"`
				Turn     json.RawMessage `json:"turn"`
			}
			if err := decodeExact(envelope.Params, []string{"threadId", "turn"}, &params); err != nil || params.ThreadID != call.params.ThreadID {
				continue
			}
			var turn struct {
				CompletedAt int64           `json:"completedAt"`
				DurationMS  int64           `json:"durationMs"`
				Error       json.RawMessage `json:"error"`
				ID          string          `json:"id"`
				Items       json.RawMessage `json:"items"`
				ItemsView   string          `json:"itemsView"`
				StartedAt   int64           `json:"startedAt"`
				Status      string          `json:"status"`
			}
			if err := decodeExact(params.Turn, []string{"completedAt", "durationMs", "error", "id", "items", "itemsView", "startedAt", "status"}, &turn); err != nil {
				return err
			}
			if turn.ID != call.params.TurnID {
				continue
			}
			turnCompleted++
			turnProof, hasTurnProof := bridgeProofs[record.Sequence]
			responseProof, hasResponseProof := bridgeProofs[response.record.Sequence]
			if turnCompleted != 1 || record.Sequence <= completedSequence || turn.Status != "completed" || string(turn.Error) != "null" || turn.CompletedAt <= 0 || turn.StartedAt <= 0 || turn.DurationMS < 0 || turn.ItemsView != "summary" || record.TimeNS >= v.events[20].TimeNS ||
				!hasTurnProof || turnProof.First.Phase != "authorized" || turnProof.Second == nil || turnProof.Second.Phase != "delivered" || turnProof.Second.TimeNS >= v.events[20].TimeNS ||
				!hasResponseProof || responseProof.First.Phase != "observed" || responseProof.Second != nil || responseProof.First.TimeNS >= turnProof.First.TimeNS {
				return errors.New("protected turn completion is malformed or out of order")
			}
		}
	}
	if started != 1 || completed != 1 || turnCompleted != 1 {
		return fmt.Errorf("protected lifecycle counts are started=%d completed=%d turn=%d", started, completed, turnCompleted)
	}
	return nil
}

func validateEmittedAt(emittedAtMS *int64, capturedTimeNS int64) error {
	if emittedAtMS == nil {
		return nil
	}
	if *emittedAtMS <= 0 || *emittedAtMS > capturedTimeNS/1_000_000+1000 {
		return errors.New("App Server emittedAtMs is invalid or later than its capture")
	}
	return nil
}

func sameArgumentMaps(left, right map[string]json.RawMessage) bool {
	leftJSON, leftErr := json.Marshal(left)
	rightJSON, rightErr := json.Marshal(right)
	return leftErr == nil && rightErr == nil && sameCanonicalJSON(leftJSON, rightJSON)
}

func sameCanonicalJSON(left, right []byte) bool {
	var leftValue, rightValue any
	leftDecoder := json.NewDecoder(bytes.NewReader(left))
	leftDecoder.UseNumber()
	rightDecoder := json.NewDecoder(bytes.NewReader(right))
	rightDecoder.UseNumber()
	if leftDecoder.Decode(&leftValue) != nil || rightDecoder.Decode(&rightValue) != nil {
		return false
	}
	leftCanonical, leftErr := json.Marshal(leftValue)
	rightCanonical, rightErr := json.Marshal(rightValue)
	return leftErr == nil && rightErr == nil && bytes.Equal(leftCanonical, rightCanonical)
}

func canonicalJSONObject(data []byte) ([]byte, error) {
	if err := rejectDuplicateFields(data); err != nil {
		return nil, err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return nil, err
	}
	if _, ok := value.(map[string]any); !ok {
		return nil, errors.New("canonical JSON value is not an object")
	}
	if err := requireJSONEOF(decoder); err != nil {
		return nil, err
	}
	encoded, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	return encoded, nil
}

func normalizeRPCID(raw []byte) (string, error) {
	if len(raw) == 0 {
		return "", errors.New("RPC id is absent")
	}
	var text string
	if json.Unmarshal(raw, &text) == nil {
		if text == "" {
			return "", errors.New("RPC id string is empty")
		}
		return "s:" + text, nil
	}
	var number json.Number
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err := decoder.Decode(&number); err != nil {
		return "", errors.New("RPC id is neither string nor integer")
	}
	value, err := strconv.ParseInt(string(number), 10, 64)
	if err != nil || value < 0 {
		return "", errors.New("RPC id is not a nonnegative integer")
	}
	return "i:" + strconv.FormatInt(value, 10), nil
}
