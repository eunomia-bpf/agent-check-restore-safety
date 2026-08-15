package headanchor

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCreateAdvanceAndReopen(t *testing.T) {
	path := filepath.Join(t.TempDir(), "outside-restore", "history-head.json")
	if err := os.Mkdir(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	initial := Head{Hash: zeroHash}
	anchor, err := Create(path, initial)
	if err != nil {
		t.Fatal(err)
	}
	if got, err := anchor.Current(); err != nil || got != initial {
		t.Fatalf("Current() = %+v, %v", got, err)
	}

	next := testHead(1, 'a')
	if err := anchor.Advance(next); err != nil {
		t.Fatal(err)
	}
	if err := anchor.Advance(next); err != nil {
		t.Fatalf("idempotent Advance: %v", err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != privateMode {
		t.Fatalf("anchor mode = %#o", info.Mode().Perm())
	}
	if err := anchor.Close(); err != nil {
		t.Fatal(err)
	}

	reopened, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if got, err := reopened.Current(); err != nil || got != next {
		t.Fatalf("reopened Current() = %+v, %v", got, err)
	}
	final := testHead(9, 'b')
	if err := reopened.Advance(final); err != nil {
		t.Fatalf("Advance across a sequence gap: %v", err)
	}
	if err := reopened.Close(); err != nil {
		t.Fatal(err)
	}

	again, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer again.Close()
	if got, err := again.Current(); err != nil || got != final {
		t.Fatalf("final Current() = %+v, %v", got, err)
	}
}

func TestWriterLock(t *testing.T) {
	path := filepath.Join(t.TempDir(), "head.json")
	first, err := Create(path, Head{Hash: zeroHash})
	if err != nil {
		t.Fatal(err)
	}
	// Advance replaces the anchor inode. The separate, stable lock file must
	// still exclude another writer after that replacement.
	if err := first.Advance(testHead(1, 'a')); err != nil {
		t.Fatal(err)
	}
	if second, err := Open(path); !errors.Is(err, ErrLocked) {
		if second != nil {
			_ = second.Close()
		}
		t.Fatalf("second writer error = %v", err)
	}
	if err := first.Close(); err != nil {
		t.Fatal(err)
	}
	second, err := Open(path)
	if err != nil {
		t.Fatalf("Open after Close: %v", err)
	}
	if err := second.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := Create(path, Head{Hash: zeroHash}); !errors.Is(err, ErrExists) {
		t.Fatalf("Create existing anchor error = %v", err)
	}
}

func TestAdvanceRefusesRollbackAndConflict(t *testing.T) {
	path := filepath.Join(t.TempDir(), "head.json")
	current := testHead(5, 'a')
	anchor, err := Create(path, current)
	if err != nil {
		t.Fatal(err)
	}
	defer anchor.Close()

	tests := []struct {
		name string
		head Head
		want error
	}{
		{name: "older sequence", head: testHead(4, 'b'), want: ErrRollback},
		{name: "same sequence different hash", head: testHead(5, 'b'), want: ErrConflict},
		{name: "later sequence same hash", head: Head{Sequence: 6, Hash: current.Hash}, want: ErrConflict},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			before, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			if err := anchor.Advance(test.head); !errors.Is(err, test.want) {
				t.Fatalf("Advance error = %v, want %v", err, test.want)
			}
			got, err := anchor.Current()
			if err != nil {
				t.Fatal(err)
			}
			if got != current {
				t.Fatalf("Current() changed to %+v", got)
			}
			after, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(after, before) {
				t.Fatal("refused Advance changed the anchor file")
			}
		})
	}
}

func TestOpenRejectsTampering(t *testing.T) {
	path := filepath.Join(t.TempDir(), "head.json")
	head := testHead(3, 'a')
	anchor, err := Create(path, head)
	if err != nil {
		t.Fatal(err)
	}
	if err := anchor.Close(); err != nil {
		t.Fatal(err)
	}
	contents, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	tampered := bytes.Replace(contents, []byte(head.Hash), []byte(strings.Repeat("b", 64)), 1)
	if bytes.Equal(contents, tampered) {
		t.Fatal("test did not change the anchored hash")
	}
	if err := os.WriteFile(path, tampered, privateMode); err != nil {
		t.Fatal(err)
	}
	if _, err := Open(path); !errors.Is(err, ErrCorrupt) {
		t.Fatalf("Open tampered anchor error = %v", err)
	}
}

func TestOpenRejectsFormatErrors(t *testing.T) {
	tests := []struct {
		name     string
		contents string
	}{
		{name: "malformed JSON", contents: "{\n"},
		{name: "wrong version", contents: `{"version":2,"sequence":0,"hash":"` + zeroHash + `","checksum":"` + strings.Repeat("0", 64) + `"}` + "\n"},
		{name: "unknown field", contents: `{"version":1,"sequence":0,"hash":"` + zeroHash + `","checksum":"` + checksum(Head{Hash: zeroHash}) + `","extra":true}` + "\n"},
		{name: "noncanonical whitespace", contents: ` {"version":1,"sequence":0,"hash":"` + zeroHash + `","checksum":"` + checksum(Head{Hash: zeroHash}) + `"}` + "\n"},
		{name: "multiple values", contents: "{}\n{}\n"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "head.json")
			if err := os.WriteFile(path, []byte(test.contents), privateMode); err != nil {
				t.Fatal(err)
			}
			if _, err := Open(path); !errors.Is(err, ErrCorrupt) {
				t.Fatalf("Open format error = %v", err)
			}
		})
	}
}

func TestOpenRequiresPrivateRegularFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "head.json")
	anchor, err := Create(path, Head{Hash: zeroHash})
	if err != nil {
		t.Fatal(err)
	}
	if err := anchor.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := Open(path); !errors.Is(err, ErrPrivate) {
		t.Fatalf("Open public anchor error = %v", err)
	}
}

func TestClosedAnchor(t *testing.T) {
	anchor, err := Create(filepath.Join(t.TempDir(), "head.json"), Head{Hash: zeroHash})
	if err != nil {
		t.Fatal(err)
	}
	if err := anchor.Close(); err != nil {
		t.Fatal(err)
	}
	if err := anchor.Close(); err != nil {
		t.Fatalf("second Close: %v", err)
	}
	if _, err := anchor.Current(); !errors.Is(err, ErrClosed) {
		t.Fatalf("Current after Close error = %v", err)
	}
	if err := anchor.Advance(testHead(1, 'a')); !errors.Is(err, ErrClosed) {
		t.Fatalf("Advance after Close error = %v", err)
	}
}

func testHead(sequence uint64, digit byte) Head {
	return Head{Sequence: sequence, Hash: strings.Repeat(string(digit), 64)}
}
