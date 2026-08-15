package history

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestAppendCloseAndReopen(t *testing.T) {
	path := filepath.Join(t.TempDir(), "execution.history")
	h, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}

	first, err := h.Append("service.deploy", map[string]any{"version": 7, "ready": true})
	if err != nil {
		t.Fatal(err)
	}
	second, err := h.AppendJSON("vm.restore", json.RawMessage(` { "snapshot": "safe-3" } `))
	if err != nil {
		t.Fatal(err)
	}
	if first.Sequence != 1 || first.PreviousHash != zeroHash {
		t.Fatalf("unexpected first event: %+v", first)
	}
	if second.Sequence != 2 || second.PreviousHash != first.Hash {
		t.Fatalf("unexpected second event: %+v", second)
	}
	if got := h.Head(); got != (Head{Sequence: 2, Hash: second.Hash}) {
		t.Fatalf("Head() = %+v", got)
	}

	copyOfEvents := h.Events()
	copyOfEvents[0].Data[0] = 'x'
	if bytes.Equal(copyOfEvents[0].Data, h.Events()[0].Data) {
		t.Fatal("Events returned mutable internal data")
	}
	if err := h.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if got := reopened.Head(); got != (Head{Sequence: 2, Hash: second.Hash}) {
		t.Fatalf("reopened Head() = %+v", got)
	}
	events := reopened.Events()
	if len(events) != 2 {
		t.Fatalf("reopened event count = %d", len(events))
	}
	if string(events[1].Data) != `{"snapshot":"safe-3"}` {
		t.Fatalf("compacted data = %s", events[1].Data)
	}
	if _, err := reopened.Append("service.ready", nil); err != nil {
		t.Fatal(err)
	}
}

func TestEmptyHeadAndClosedHistory(t *testing.T) {
	h, err := Open(filepath.Join(t.TempDir(), "empty.history"))
	if err != nil {
		t.Fatal(err)
	}
	if got := h.Head(); got != (Head{Hash: zeroHash}) {
		t.Fatalf("empty Head() = %+v", got)
	}
	if err := h.Close(); err != nil {
		t.Fatal(err)
	}
	if err := h.Close(); err != nil {
		t.Fatalf("second Close() = %v", err)
	}
	if _, err := h.Append("after.close", nil); !errors.Is(err, ErrClosed) {
		t.Fatalf("Append after Close error = %v", err)
	}
}

func TestOpenRejectsTamperedCompleteEvent(t *testing.T) {
	path := filepath.Join(t.TempDir(), "tampered.history")
	h, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := h.Append("alpha", map[string]string{"value": "alpha"}); err != nil {
		t.Fatal(err)
	}
	if err := h.Close(); err != nil {
		t.Fatal(err)
	}

	contents, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	tampered := bytes.Replace(contents, []byte(`"value":"alpha"`), []byte(`"value":"omega"`), 1)
	if bytes.Equal(contents, tampered) {
		t.Fatal("test did not find event data to tamper")
	}
	if err := os.WriteFile(path, tampered, 0o600); err != nil {
		t.Fatal(err)
	}

	before, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	_, err = Open(path)
	if !errors.Is(err, ErrCorrupt) {
		t.Fatalf("Open tampered History error = %v", err)
	}
	after, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if before.Size() != after.Size() {
		t.Fatalf("corrupt complete frame was truncated: %d -> %d", before.Size(), after.Size())
	}
}

func TestOpenRecoversTornFinalFrame(t *testing.T) {
	tests := []struct {
		name string
		tail func() []byte
	}{
		{
			name: "partial marker",
			tail: func() []byte { return append([]byte(nil), frameMagic[:2]...) },
		},
		{
			name: "partial length",
			tail: func() []byte {
				return append(append([]byte(nil), frameMagic[:]...), 0, 0, 0)
			},
		},
		{
			name: "partial payload",
			tail: func() []byte {
				var header [headerSize]byte
				copy(header[:4], frameMagic[:])
				binary.BigEndian.PutUint64(header[4:], 100)
				return append(header[:], []byte(`{"version":1}`)...)
			},
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "torn.history")
			h, err := Open(path)
			if err != nil {
				t.Fatal(err)
			}
			event, err := h.Append("durable", map[string]int{"value": 1})
			if err != nil {
				t.Fatal(err)
			}
			if err := h.Close(); err != nil {
				t.Fatal(err)
			}
			clean, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			file, err := os.OpenFile(path, os.O_WRONLY|os.O_APPEND, 0)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := file.Write(test.tail()); err != nil {
				t.Fatal(err)
			}
			if err := file.Close(); err != nil {
				t.Fatal(err)
			}

			recovered, err := Open(path)
			if err != nil {
				t.Fatal(err)
			}
			defer recovered.Close()
			if got := recovered.Head(); got != (Head{Sequence: 1, Hash: event.Hash}) {
				t.Fatalf("recovered Head() = %+v", got)
			}
			after, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(after, clean) {
				t.Fatalf("recovered bytes differ: got %d bytes, want %d", len(after), len(clean))
			}
		})
	}
}

func TestOpenFailsClosedOnInvalidPartialHeader(t *testing.T) {
	path := filepath.Join(t.TempDir(), "invalid-tail.history")
	if err := os.WriteFile(path, []byte("XX"), 0o600); err != nil {
		t.Fatal(err)
	}
	_, err := Open(path)
	if !errors.Is(err, ErrCorrupt) {
		t.Fatalf("Open invalid partial header error = %v", err)
	}
	contents, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatal(readErr)
	}
	if string(contents) != "XX" {
		t.Fatalf("invalid tail was changed: %q", contents)
	}
}

func TestOpenFailsClosedOnCompleteCorruption(t *testing.T) {
	path := filepath.Join(t.TempDir(), "complete-corruption.history")
	payload := []byte(`{"not":"a stored event"}`)
	var header [headerSize]byte
	copy(header[:4], frameMagic[:])
	binary.BigEndian.PutUint64(header[4:], uint64(len(payload)))
	contents := append(header[:], payload...)
	if err := os.WriteFile(path, contents, 0o600); err != nil {
		t.Fatal(err)
	}
	_, err := Open(path)
	if !errors.Is(err, ErrCorrupt) {
		t.Fatalf("Open complete corruption error = %v", err)
	}
	after, readErr := os.ReadFile(path)
	if readErr != nil {
		t.Fatal(readErr)
	}
	if !bytes.Equal(after, contents) {
		t.Fatal("complete corrupt frame was changed")
	}
}

func TestWriterLockContention(t *testing.T) {
	path := filepath.Join(t.TempDir(), "locked.history")
	first, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	second, err := Open(path)
	if !errors.Is(err, ErrLocked) {
		if second != nil {
			_ = second.Close()
		}
		t.Fatalf("second Open error = %v", err)
	}
	if err := first.Close(); err != nil {
		t.Fatal(err)
	}
	third, err := Open(path)
	if err != nil {
		t.Fatalf("Open after lock release: %v", err)
	}
	if err := third.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestAppendRejectsInvalidInputWithoutChangingHistory(t *testing.T) {
	h, err := Open(filepath.Join(t.TempDir(), "invalid-input.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer h.Close()
	if _, err := h.AppendJSON("", json.RawMessage(`null`)); err == nil {
		t.Fatal("empty operation was accepted")
	}
	if _, err := h.AppendJSON("operation", json.RawMessage(`{`)); err == nil {
		t.Fatal("invalid JSON was accepted")
	}
	if got := h.Head(); got != (Head{Hash: zeroHash}) {
		t.Fatalf("Head after invalid input = %+v", got)
	}
	if len(h.Events()) != 0 {
		t.Fatal("invalid input added an event")
	}
}

func TestRollbackFailureRequiresReopen(t *testing.T) {
	tests := []struct {
		name        string
		truncateErr error
		seekErr     error
		syncErr     error
	}{
		{name: "truncate", truncateErr: errors.New("injected truncate failure")},
		{name: "seek", seekErr: errors.New("injected seek failure")},
		{name: "sync", syncErr: errors.New("injected sync failure")},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "failed-recovery.history")
			h, err := Open(path)
			if err != nil {
				t.Fatal(err)
			}
			before, err := os.Stat(path)
			if err != nil {
				t.Fatal(err)
			}

			injected := &recoveryFileStub{
				truncateErr: test.truncateErr,
				seekErr:     test.seekErr,
				syncErr:     test.syncErr,
			}
			h.mu.Lock()
			recoveryErr := h.rollbackOn(injected, 0, errors.New("injected Append failure"))
			h.mu.Unlock()
			if !errors.Is(recoveryErr, ErrNeedsReopen) {
				t.Fatalf("rollbackOn error = %v", recoveryErr)
			}
			if got := injected.calls; got != "truncate,seek,sync" {
				t.Fatalf("recovery calls = %q", got)
			}

			if _, err := h.Append("must.not.write", nil); !errors.Is(err, ErrNeedsReopen) {
				t.Fatalf("Append after failed recovery error = %v", err)
			}
			after, err := os.Stat(path)
			if err != nil {
				t.Fatal(err)
			}
			if after.Size() != before.Size() {
				t.Fatalf("blocked Append changed file size: %d -> %d", before.Size(), after.Size())
			}
			if err := h.Close(); err != nil {
				t.Fatal(err)
			}

			reopened, err := Open(path)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := reopened.Append("safe.after.replay", nil); err != nil {
				t.Fatalf("Append after reopen: %v", err)
			}
			if err := reopened.Close(); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestSuccessfulRollbackDoesNotRequireReopen(t *testing.T) {
	h, err := Open(filepath.Join(t.TempDir(), "successful-recovery.history"))
	if err != nil {
		t.Fatal(err)
	}
	defer h.Close()

	injectedCause := errors.New("injected Append failure")
	injected := &recoveryFileStub{}
	h.mu.Lock()
	recoveryErr := h.rollbackOn(injected, 0, injectedCause)
	h.mu.Unlock()
	if !errors.Is(recoveryErr, injectedCause) || errors.Is(recoveryErr, ErrNeedsReopen) {
		t.Fatalf("rollbackOn error = %v", recoveryErr)
	}
	if _, err := h.Append("safe.after.recovery", nil); err != nil {
		t.Fatalf("Append after successful recovery: %v", err)
	}
}

type recoveryFileStub struct {
	truncateErr error
	seekErr     error
	syncErr     error
	calls       string
}

func (file *recoveryFileStub) Truncate(int64) error {
	file.recordCall("truncate")
	return file.truncateErr
}

func (file *recoveryFileStub) Seek(int64, int) (int64, error) {
	file.recordCall("seek")
	return 0, file.seekErr
}

func (file *recoveryFileStub) Sync() error {
	file.recordCall("sync")
	return file.syncErr
}

func (file *recoveryFileStub) recordCall(call string) {
	if file.calls != "" {
		file.calls += ","
	}
	file.calls += call
}
