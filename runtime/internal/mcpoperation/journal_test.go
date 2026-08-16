package mcpoperation

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func testDigest(value string) string {
	digest := sha256.Sum256([]byte(value))
	return hex.EncodeToString(digest[:])
}

func privateTestDirectory(t *testing.T) string {
	t.Helper()
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	return directory
}

func TestJournalPersistsPreparedIdentityAndCompletedResponse(t *testing.T) {
	directory := privateTestDirectory(t)
	path := filepath.Join(directory, "calls.jsonl")
	journal, err := OpenJournal(path, "execution-journal")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := OpenJournal(path, "execution-journal"); err == nil {
		t.Fatal("a second process acquired the locked journal")
	}
	call, err := journal.Prepare("1", testDigest("request-one"))
	if err != nil {
		t.Fatal(err)
	}
	if call.CallID != "mcp-call-v1:17:execution-journal:1" || call.Sequence != 1 {
		t.Fatalf("prepared call = %+v", call)
	}
	response := []byte(`{"jsonrpc":"2.0","id":1,"result":{"ok":true}}`)
	if err := journal.Complete(call, response, false); err != nil {
		t.Fatal(err)
	}
	if err := journal.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := OpenJournal(path, "execution-journal")
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	recorded, exists, err := reopened.Lookup("1", testDigest("request-one"))
	if err != nil || !exists || !recorded.Completed || string(recorded.Response) != string(response) {
		t.Fatalf("replayed call=%+v exists=%t error=%v", recorded, exists, err)
	}
	second, err := reopened.Prepare("2", testDigest("request-two"))
	if err != nil {
		t.Fatal(err)
	}
	if second.Sequence != 2 || second.CallID != "mcp-call-v1:17:execution-journal:2" {
		t.Fatalf("second call = %+v", second)
	}
}

func TestJournalResumesPreparedCallAndRejectsDifferentWork(t *testing.T) {
	path := filepath.Join(privateTestDirectory(t), "calls.jsonl")
	journal, err := OpenJournal(path, "crash-scope")
	if err != nil {
		t.Fatal(err)
	}
	prepared, err := journal.Prepare(`"rpc-7"`, testDigest("original"))
	if err != nil {
		t.Fatal(err)
	}
	if err := journal.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := OpenJournal(path, "crash-scope")
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	replayed, exists, err := reopened.Lookup(`"rpc-7"`, testDigest("original"))
	if err != nil || !exists || replayed.Completed || replayed.CallID != prepared.CallID {
		t.Fatalf("pending replay=%+v exists=%t error=%v", replayed, exists, err)
	}
	if _, _, err := reopened.Lookup(`"rpc-7"`, testDigest("different")); err == nil {
		t.Fatal("pending JSON-RPC identity accepted different work")
	}
	if _, err := reopened.Prepare(`"rpc-8"`, testDigest("later")); err == nil {
		t.Fatal("new work passed a pending prepared call")
	}
	if err := reopened.Complete(replayed, []byte(`{"jsonrpc":"2.0","id":"rpc-7","result":{}}`), false); err != nil {
		t.Fatal(err)
	}
	later, err := reopened.Prepare(`"rpc-8"`, testDigest("later"))
	if err != nil || later.Sequence != 2 {
		t.Fatalf("later call=%+v error=%v", later, err)
	}
}

func TestJournalPersistsExecutionFence(t *testing.T) {
	path := filepath.Join(privateTestDirectory(t), "calls.jsonl")
	journal, err := OpenJournal(path, "fenced-scope")
	if err != nil {
		t.Fatal(err)
	}
	call, err := journal.Prepare("1", testDigest("uncertain"))
	if err != nil {
		t.Fatal(err)
	}
	if err := journal.Complete(call, []byte(`{"jsonrpc":"2.0","id":1,"result":{"isError":true}}`), true); err != nil {
		t.Fatal(err)
	}
	if err := journal.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := OpenJournal(path, "fenced-scope")
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	fenced, pending, err := reopened.Fenced()
	if err != nil || !fenced || pending {
		t.Fatalf("fenced=%t pending=%t error=%v", fenced, pending, err)
	}
	if _, err := reopened.Prepare("2", testDigest("must-not-run")); err == nil {
		t.Fatal("new work passed a durable execution fence")
	}
}

func TestJournalRejectsWrongExecutionMutationAndUnsafePaths(t *testing.T) {
	directory := privateTestDirectory(t)
	path := filepath.Join(directory, "calls.jsonl")
	journal, err := OpenJournal(path, "bound-scope")
	if err != nil {
		t.Fatal(err)
	}
	call, err := journal.Prepare("1", testDigest("work"))
	if err != nil {
		t.Fatal(err)
	}
	if err := journal.Complete(call, []byte(`{"jsonrpc":"2.0","id":1,"result":{}}`), false); err != nil {
		t.Fatal(err)
	}
	if err := journal.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenJournal(path, "other-scope"); err == nil {
		t.Fatal("journal opened under another execution identity")
	}
	contents, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	mutated := strings.Replace(string(contents), `"event":"prepared"`, `"event":"tampered"`, 1)
	if err := os.WriteFile(path, []byte(mutated), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenJournal(path, "bound-scope"); err == nil {
		t.Fatal("mutated journal hash chain was accepted")
	}

	public := filepath.Join(t.TempDir(), "public")
	if err := os.Mkdir(public, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(public, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenJournal(filepath.Join(public, "calls.jsonl"), "scope"); err == nil {
		t.Fatal("journal in a world-searchable directory was accepted")
	}
	if _, err := OpenJournal("relative.jsonl", "scope"); err == nil {
		t.Fatal("relative journal path was accepted")
	}
}
