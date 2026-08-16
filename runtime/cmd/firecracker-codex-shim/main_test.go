package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/agentguest"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/codexvm"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repobundle"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repodelta"
	"golang.org/x/sys/unix"
)

func TestGenerateRunIDsUsesLowercaseDistinctSixteenByteValues(t *testing.T) {
	entropy := make([]byte, 48)
	for index := range entropy {
		entropy[index] = byte(index)
	}
	session, first, restored, err := generateRunIDs(bytes.NewReader(entropy))
	if err != nil {
		t.Fatal(err)
	}
	for label, value := range map[string]string{"session": session, "first": first, "restored": restored} {
		if len(value) != 32 || strings.ToLower(value) != value {
			t.Fatalf("%s ID = %q, require 32 lowercase hex characters", label, value)
		}
		if _, err := hex.DecodeString(value); err != nil {
			t.Fatalf("decode %s ID: %v", label, err)
		}
	}
	if first == restored {
		t.Fatal("VM IDs are not distinct")
	}
}

func TestGenerateRunIDsRejectsShortEntropyAndRepeatedVMID(t *testing.T) {
	if _, _, _, err := generateRunIDs(bytes.NewReader(make([]byte, 47))); err == nil {
		t.Fatal("short entropy was accepted")
	}
	if _, _, _, err := generateRunIDs(bytes.NewReader(make([]byte, 16+16+8*16))); err == nil {
		t.Fatal("repeated VM IDs were accepted")
	}
}

func TestArgumentsDigestBindsExactJSONArgumentArray(t *testing.T) {
	left, err := argumentsDigest([]string{"ab", "c"})
	if err != nil {
		t.Fatal(err)
	}
	right, err := argumentsDigest([]string{"a", "bc"})
	if err != nil {
		t.Fatal(err)
	}
	if left == right {
		t.Fatal("distinct argv arrays have the same digest")
	}
	encoded, _ := json.Marshal([]string{"ab", "c"})
	want := sha256.Sum256(encoded)
	if left != hex.EncodeToString(want[:]) {
		t.Fatalf("arguments digest = %s, want %x", left, want)
	}
}

func TestBuildGuestConfigCopiesArgumentsAndUsesFixedContract(t *testing.T) {
	host := codexvm.Config{
		CodexSHA256:    strings.Repeat("a", 64),
		Arguments:      []string{"app-server", "--stdio", "-c", "model_provider=x"},
		GuestModelPort: 8080,
	}
	repositoryFile, err := os.CreateTemp(t.TempDir(), "repository-")
	if err != nil {
		t.Fatal(err)
	}
	defer repositoryFile.Close()
	tree, err := repobundle.FromEntries(nil, repobundle.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	repository := &sealedArtifact{file: repositoryFile, record: sealedArtifactRecord{Artifact: artifactRecord{
		Name: "repository", Size: 512, SHA256: strings.Repeat("b", 64),
	}}}
	guest, err := buildGuestConfig(host, strings.Repeat("1", 32), repository, tree)
	if err != nil {
		t.Fatal(err)
	}
	if guest.Schema != agentguest.ConfigSchema || guest.StreamPort != agentguest.DefaultStreamPort ||
		guest.ModelPort != 8080 || guest.PayloadDrive != "/dev/vda" || guest.RepositoryDrive != "/dev/vdb" || guest.RepositorySize != 512 || guest.RepositoryTreeRoot != tree.TreeRoot.String() || guest.CodexSHA256 != host.CodexSHA256 {
		t.Fatalf("unexpected guest config: %+v", guest)
	}
	host.Arguments[0] = "changed"
	if guest.Arguments[0] != "app-server" {
		t.Fatal("guest arguments alias host arguments")
	}
	host.GuestModelPort = agentguest.DefaultStreamPort
	if _, err := buildGuestConfig(host, strings.Repeat("1", 32), repository, tree); err == nil {
		t.Fatal("colliding model and stream ports were accepted")
	}
}

func TestSealPathVerifiesHashAndAppliesCompleteImmutableSeals(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "artifact")
	content := []byte("immutable artifact bytes")
	if err := os.WriteFile(path, content, 0o600); err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(content)
	sealed, err := sealPath("artifact", path, hex.EncodeToString(digest[:]), 6, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer sealed.file.Close()
	if sealed.record.Artifact.Size != int64(len(content)) || sealed.record.Artifact.SHA256 != hex.EncodeToString(digest[:]) || sealed.record.ChildFD != 6 {
		t.Fatalf("unexpected sealed record: %+v", sealed.record)
	}
	seals, err := unix.FcntlInt(sealed.file.Fd(), unix.F_GET_SEALS, 0)
	if err != nil {
		t.Fatal(err)
	}
	if seals != immutableSeals || sealed.record.LinuxSeals != immutableSeals {
		t.Fatalf("seals = %d/%d, want %d", seals, sealed.record.LinuxSeals, immutableSeals)
	}
	if _, err := sealed.file.WriteAt([]byte("x"), 0); err == nil {
		t.Fatal("write to immutable memfd succeeded")
	}
	data, err := readSealedArtifact(sealed, int64(len(content)))
	if err != nil || !bytes.Equal(data, content) {
		t.Fatalf("read sealed artifact = %q, %v", data, err)
	}
}

func TestSealPathRejectsWrongHashSymlinkEmptyAndLimit(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "artifact")
	if err := os.WriteFile(path, []byte("content"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := sealPath("artifact", path, strings.Repeat("0", 64), 4, 0); err == nil {
		t.Fatal("wrong expected hash was accepted")
	}
	if _, err := sealPath("artifact", path, "", 4, 3); err == nil {
		t.Fatal("oversize source was accepted")
	}
	symlink := filepath.Join(directory, "symlink")
	if err := os.Symlink(path, symlink); err != nil {
		t.Fatal(err)
	}
	if _, err := sealPath("artifact", symlink, "", 4, 0); err == nil {
		t.Fatal("symlink source was accepted")
	}
	empty := filepath.Join(directory, "empty")
	if err := os.WriteFile(empty, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := sealPath("empty", empty, "", 4, 0); err == nil {
		t.Fatal("empty source was accepted")
	}
}

func TestFinalizeMemfdRejectsEmptyArtifact(t *testing.T) {
	file, err := newMemfd("empty-test")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := finalizeMemfd("empty-test", file, 4); err == nil {
		t.Fatal("empty memfd was accepted")
	}
}

func TestPersistArtifactsAreExclusivePrivateDurableRehashes(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "guest-config.json")
	data := []byte(`{"schema":1}`)
	record, err := persistBytesArtifact("guest-config.json", path, data)
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Lstat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 || record.Mode != 0o600 || record.Size != int64(len(data)) {
		t.Fatalf("retained artifact mode/size = %04o/%04o/%d", info.Mode().Perm(), record.Mode, record.Size)
	}
	if _, err := persistBytesArtifact("guest-config.json", path, data); err == nil {
		t.Fatal("retained artifact was overwritten")
	}

	source, err := newMemfd("retained-source")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := source.Write([]byte("initramfs bytes")); err != nil {
		t.Fatal(err)
	}
	sealed, err := finalizeMemfd("source", source, 5)
	if err != nil {
		t.Fatal(err)
	}
	defer sealed.file.Close()
	retained, err := persistOpenArtifact("guest-initramfs.cpio", filepath.Join(directory, "guest-initramfs.cpio"), sealed.file, sealed.record.Artifact)
	if err != nil {
		t.Fatal(err)
	}
	if retained.SHA256 != sealed.record.Artifact.SHA256 || retained.Size != sealed.record.Artifact.Size {
		t.Fatalf("retained = %+v, sealed = %+v", retained, sealed.record.Artifact)
	}
}

func TestPersistReaderRejectsShortSource(t *testing.T) {
	directory := t.TempDir()
	expected := bytesArtifact("short", []byte("longer"), 0o600)
	if _, err := persistReaderArtifact("short", filepath.Join(directory, "short"), bytes.NewReader([]byte("x")), expected); err == nil {
		t.Fatal("short retained source was accepted")
	}
}

func TestReceiveRepositoryBundlePersistsExactlyWhatGuestExported(t *testing.T) {
	bundle, err := repobundle.FromEntries([]repobundle.Entry{{
		Path: "result.txt", Type: repobundle.EntryFile, Mode: 0o644, Data: []byte("complete\n"),
	}}, repobundle.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	var encoded bytes.Buffer
	if err := repobundle.Encode(&encoded, bundle, repobundle.DefaultLimits()); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "repository-final.bundle")
	decoded, artifact, err := receiveRepositoryBundle(bytes.NewReader(encoded.Bytes()), path)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(encoded.Bytes())
	if decoded.TreeRoot != bundle.TreeRoot || artifact.Name != "repository-final.bundle" || artifact.Size != int64(encoded.Len()) || artifact.SHA256 != hex.EncodeToString(digest[:]) {
		t.Fatalf("received repository/artifact = %+v / %+v", decoded, artifact)
	}
	if _, _, err := receiveRepositoryBundle(bytes.NewReader(encoded.Bytes()), path); err == nil {
		t.Fatal("existing final repository evidence was overwritten")
	}
}

func TestPersistRepositoryDeltaReconstructsExportedTree(t *testing.T) {
	base, err := repobundle.FromEntries([]repobundle.Entry{{
		Path: "old.txt", Type: repobundle.EntryFile, Mode: 0o644, Data: []byte("old\n"),
	}}, repobundle.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	final, err := repobundle.FromEntries([]repobundle.Entry{{
		Path: "new.txt", Type: repobundle.EntryFile, Mode: 0o644, Data: []byte("new\n"),
	}}, repobundle.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	delta, err := repodelta.Compute(base, final, repodelta.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "repository.delta")
	artifact, err := persistRepositoryDelta(path, base, final, delta)
	if err != nil {
		t.Fatal(err)
	}
	if artifact.Name != "repository.delta" || artifact.Size <= 0 {
		t.Fatalf("persisted delta artifact = %+v", artifact)
	}
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	decoded, decodeErr := repodelta.Decode(file, repodelta.DefaultLimits())
	closeErr := file.Close()
	if err := errors.Join(decodeErr, closeErr); err != nil {
		t.Fatal(err)
	}
	applied, err := repodelta.Apply(base, decoded, repodelta.DefaultLimits())
	if err != nil || applied.TreeRoot != final.TreeRoot {
		t.Fatalf("persisted delta reconstruction = %s, %v", applied.TreeRoot, err)
	}
}

func TestFinalizeSnapshotFileProtectsAndRejectsUnsafeObjects(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "snapshot.state")
	if err := os.WriteFile(path, []byte("snapshot"), 0o666); err != nil {
		t.Fatal(err)
	}
	record, err := finalizeSnapshotFile("snapshot.state", path)
	if err != nil {
		t.Fatal(err)
	}
	if record.Mode != 0o600 {
		t.Fatalf("snapshot mode = %04o, want 0600", record.Mode)
	}
	symlink := filepath.Join(directory, "snapshot-link")
	if err := os.Symlink(path, symlink); err != nil {
		t.Fatal(err)
	}
	if _, err := finalizeSnapshotFile("snapshot-link", symlink); err == nil {
		t.Fatal("snapshot symlink was accepted")
	}
	empty := filepath.Join(directory, "empty")
	if err := os.WriteFile(empty, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := finalizeSnapshotFile("empty", empty); err == nil {
		t.Fatal("empty snapshot was accepted")
	}
}

func TestEvidenceLogIsExclusivePrivateJSONLAndFailsAfterClose(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "events.jsonl")
	file, err := openEvidenceFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := openEvidenceFile(path); err == nil {
		t.Fatal("evidence file was opened twice")
	}
	events := &eventLog{file: file}
	if err := events.Record("first", nil, map[string]any{"value": 1}); err != nil {
		t.Fatal(err)
	}
	if err := events.Record("second", nil, nil); err != nil {
		t.Fatal(err)
	}
	if err := events.Close(); err != nil {
		t.Fatal(err)
	}
	info, err := os.Lstat(path)
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("events file mode/error = %v/%v", info, err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	lines := bytes.Split(bytes.TrimSpace(data), []byte{'\n'})
	if len(lines) != 2 {
		t.Fatalf("event lines = %d, want 2", len(lines))
	}
	for index, line := range lines {
		var event eventRecord
		if err := json.Unmarshal(line, &event); err != nil {
			t.Fatalf("decode event %d: %v", index, err)
		}
		if event.Sequence != uint64(index+1) {
			t.Fatalf("event sequence = %d, want %d", event.Sequence, index+1)
		}
	}
	if _, err := file.Write([]byte("late")); err == nil {
		t.Fatal("write after close succeeded")
	}
	select {
	case <-file.Failed():
	default:
		t.Fatal("evidence failure was not latched")
	}
}

func TestWritePrivateJSONDoesNotOverwrite(t *testing.T) {
	path := filepath.Join(t.TempDir(), "result.json")
	if err := writePrivateJSON(path, map[string]any{"schema": 1}); err != nil {
		t.Fatal(err)
	}
	if err := writePrivateJSON(path, map[string]any{"schema": 2}); err == nil {
		t.Fatal("result evidence was overwritten")
	}
}

func TestRetainSelfExecutableBindsRunningBytes(t *testing.T) {
	running, err := os.Open("/proc/self/exe")
	if err != nil {
		t.Fatal(err)
	}
	source, recordErr := artifactForOpenFile("runner", running)
	closeErr := running.Close()
	if recordErr != nil || closeErr != nil {
		t.Fatal(errors.Join(recordErr, closeErr))
	}
	path := filepath.Join(t.TempDir(), "runner")
	retained, err := retainSelfExecutable(path, source.SHA256)
	if err != nil {
		t.Fatal(err)
	}
	if retained.Name != "runner" || retained.Size != source.Size || retained.SHA256 != source.SHA256 || retained.Mode != 0o600 {
		t.Fatalf("retained self executable = %+v, source = %+v", retained, source)
	}
	if _, err := retainSelfExecutable(filepath.Join(t.TempDir(), "wrong"), strings.Repeat("0", 64)); err == nil || !strings.Contains(err.Error(), "running shim SHA-256") {
		t.Fatalf("wrong running shim digest error = %v", err)
	}
}

func TestArtifactForPathRejectsSymlinkAndWrongMode(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "artifact")
	if err := os.WriteFile(path, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(directory, "link")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	if _, err := artifactForPath("link", link, 0o600); err == nil {
		t.Fatal("artifact symlink was accepted")
	}
	if err := os.Chmod(path, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := artifactForPath("artifact", path, 0o600); err == nil {
		t.Fatal("wrong retained artifact mode was accepted")
	}
}

func TestValidateRuntimePathsRejectsLongUnixSocketPath(t *testing.T) {
	if err := validateRuntimePaths("/"+strings.Repeat("x", unixSocketPathLimit), 8080); err == nil {
		t.Fatal("overlong Unix socket path was accepted")
	}
	if err := validateRuntimePaths("/tmp/evidence", 8080); err != nil {
		t.Fatalf("short runtime paths rejected: %v", err)
	}
}

func TestRandomHexRejectsInvalidReaderAndSize(t *testing.T) {
	if _, err := randomHex(nil, 16); err == nil {
		t.Fatal("nil random reader accepted")
	}
	if _, err := randomHex(bytes.NewReader(nil), 0); err == nil {
		t.Fatal("zero random size accepted")
	}
	if _, err := randomHex(io.LimitReader(bytes.NewReader(make([]byte, 16)), 15), 16); !errors.Is(err, io.EOF) && !errors.Is(err, io.ErrUnexpectedEOF) {
		t.Fatalf("short random reader error = %v", err)
	}
}
