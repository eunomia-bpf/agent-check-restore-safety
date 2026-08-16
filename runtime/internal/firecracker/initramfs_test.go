package firecracker

import (
	"bytes"
	"debug/elf"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"
)

func TestBuildInitramfsIsDeterministicAndAcceptedByCPIO(t *testing.T) {
	initBinary := buildStaticGuest(t)
	request := []byte(`{"call_id":"fc-call-1","kind":"audit","body":"e30="}`)
	var first bytes.Buffer
	if err := BuildInitramfs(&first, initBinary, request); err != nil {
		t.Fatal(err)
	}
	var second bytes.Buffer
	if err := BuildInitramfs(&second, initBinary, request); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(first.Bytes(), second.Bytes()) {
		t.Fatal("identical inputs produced different initramfs bytes")
	}
	if first.Len()%archiveBlock != 0 {
		t.Fatalf("archive length %d is not %d-byte aligned", first.Len(), archiveBlock)
	}

	command := exec.Command("cpio", "-it", "--quiet")
	command.Stdin = bytes.NewReader(first.Bytes())
	listing, err := command.Output()
	if err != nil {
		t.Fatalf("GNU cpio rejected generated newc: %v", err)
	}
	wantListing := []string{"dev", "dev/console", "init", "proc", "request.json", "run", "sys", "tmp"}
	gotListing := strings.Fields(string(listing))
	if strings.Join(gotListing, "\n") != strings.Join(wantListing, "\n") {
		t.Fatalf("cpio listing = %q, want %q", gotListing, wantListing)
	}

	entries := parseNewc(t, first.Bytes())
	if len(entries) != len(wantListing) {
		t.Fatalf("archive entries = %d, want %d", len(entries), len(wantListing))
	}
	for index, name := range wantListing {
		if entries[index].name != name {
			t.Fatalf("entry %d = %q, want %q", index, entries[index].name, name)
		}
		if entries[index].uid != 0 || entries[index].gid != 0 || entries[index].mtime != 0 {
			t.Fatalf("entry %q has nondeterministic metadata: %+v", name, entries[index])
		}
	}
	if entries[1].mode != modeCharacter|0o600 || entries[1].rdevMajor != 5 || entries[1].rdevMinor != 1 {
		t.Fatalf("console entry = %+v", entries[1])
	}
	if entries[2].mode != modeRegular|0o555 || !bytes.Equal(entries[2].data, initBinary) {
		t.Fatal("/init does not contain the static guest with mode 0555")
	}
	if entries[4].mode != modeRegular|0o444 || !bytes.Equal(entries[4].data, request) {
		t.Fatal("/request.json is not the exact immutable request with mode 0444")
	}
}

func TestBuildInitramfsRejectsNonStaticInitAndNonThreeFieldRequest(t *testing.T) {
	dynamic, err := os.ReadFile("/bin/sh")
	if err != nil {
		t.Fatal(err)
	}
	request := []byte(`{"call_id":"fc-call-1","kind":"audit","body":"e30="}`)
	if err := BuildInitramfs(&bytes.Buffer{}, dynamic, request); err == nil || !strings.Contains(err.Error(), "dynamically linked") {
		t.Fatalf("dynamic init rejection = %v", err)
	}

	invalid := []string{
		`{"call_id":"fc-call-1","kind":"audit"}`,
		`{"call_id":"fc-call-1","kind":"audit","body":"e30=","url":"https://forbidden"}`,
		`{"call_id":"first","call_id":"second","kind":"audit","body":"e30="}`,
		`{"call_id":"fc-call-1","kind":"audit","body":"e30="} {}`,
	}
	for _, candidate := range invalid {
		if err := validateThreeFieldRequest([]byte(candidate)); err == nil {
			t.Errorf("accepted invalid request %s", candidate)
		}
	}
}

func buildStaticGuest(t *testing.T) []byte {
	t.Helper()
	_, source, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	runtimeRoot := filepath.Clean(filepath.Join(filepath.Dir(source), "../.."))
	output := filepath.Join(t.TempDir(), "init")
	command := exec.Command("go", "build", "-trimpath", "-o", output, "./cmd/firecracker-guest")
	command.Dir = runtimeRoot
	command.Env = buildEnvironment("linux", runtime.GOARCH)
	if combined, err := command.CombinedOutput(); err != nil {
		t.Fatalf("build static guest: %v\n%s", err, combined)
	}
	data, err := os.ReadFile(output)
	if err != nil {
		t.Fatal(err)
	}
	executable, err := elf.NewFile(bytes.NewReader(data))
	if err != nil {
		t.Fatal(err)
	}
	defer executable.Close()
	for _, program := range executable.Progs {
		if program.Type == elf.PT_INTERP {
			t.Fatal("CGO_ENABLED=0 guest unexpectedly contains PT_INTERP")
		}
	}
	return data
}

func buildEnvironment(goos, goarch string) []string {
	environment := make([]string, 0, len(os.Environ())+3)
	for _, variable := range os.Environ() {
		name := variable
		if separator := strings.IndexByte(variable, '='); separator >= 0 {
			name = variable[:separator]
		}
		if name != "CGO_ENABLED" && name != "GOOS" && name != "GOARCH" {
			environment = append(environment, variable)
		}
	}
	return append(environment, "CGO_ENABLED=0", "GOOS="+goos, "GOARCH="+goarch)
}

type parsedEntry struct {
	name                  string
	mode, uid, gid, mtime uint32
	rdevMajor, rdevMinor  uint32
	data                  []byte
}

func parseNewc(t *testing.T, archive []byte) []parsedEntry {
	t.Helper()
	var entries []parsedEntry
	offset := 0
	for {
		if offset+newcHeaderBytes > len(archive) {
			t.Fatalf("truncated newc header at %d", offset)
		}
		header := archive[offset : offset+newcHeaderBytes]
		if string(header[:6]) != newcMagic {
			t.Fatalf("newc magic at %d = %q", offset, header[:6])
		}
		field := func(start int) uint32 {
			value, err := strconv.ParseUint(string(header[start:start+8]), 16, 32)
			if err != nil {
				t.Fatalf("parse newc field at %d: %v", offset+start, err)
			}
			return uint32(value)
		}
		entry := parsedEntry{
			mode: field(14), uid: field(22), gid: field(30), mtime: field(46),
			rdevMajor: field(78), rdevMinor: field(86),
		}
		fileSize, nameSize := int(field(54)), int(field(94))
		offset += newcHeaderBytes
		if nameSize < 1 || offset+nameSize > len(archive) || archive[offset+nameSize-1] != 0 {
			t.Fatalf("invalid newc name at %d", offset)
		}
		entry.name = string(archive[offset : offset+nameSize-1])
		offset = align(offset+nameSize, 4)
		if offset+fileSize > len(archive) {
			t.Fatalf("truncated newc data for %q", entry.name)
		}
		entry.data = append([]byte(nil), archive[offset:offset+fileSize]...)
		offset = align(offset+fileSize, 4)
		if entry.name == "TRAILER!!!" {
			for index, value := range archive[offset:] {
				if value != 0 {
					t.Fatalf("nonzero archive padding at %d: %#x", offset+index, value)
				}
			}
			return entries
		}
		entries = append(entries, entry)
	}
}

func align(value, alignment int) int {
	if alignment <= 0 {
		panic(fmt.Sprintf("invalid alignment %d", alignment))
	}
	return (value + alignment - 1) / alignment * alignment
}
