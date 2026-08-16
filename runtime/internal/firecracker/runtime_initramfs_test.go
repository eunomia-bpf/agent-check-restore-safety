package firecracker

import (
	"bytes"
	"errors"
	"io"
	"os"
	"strconv"
	"strings"
	"testing"
)

func TestBuildRuntimeInitramfsIsByteDeterministicAndExact(t *testing.T) {
	initBinary := buildStaticGuest(t)
	config := []byte("{\n  \"command\": [\"codex\", \"exec\"],\n  \"workspace\": \"/workspace\"\n}\n")
	var first bytes.Buffer
	if err := BuildRuntimeInitramfs(&first, initBinary, config); err != nil {
		t.Fatal(err)
	}
	var second bytes.Buffer
	if err := BuildRuntimeInitramfs(&second, initBinary, config); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(first.Bytes(), second.Bytes()) {
		t.Fatal("identical runtime inputs produced different initramfs bytes")
	}
	if first.Len()%archiveBlock != 0 {
		t.Fatalf("archive length %d is not %d-byte aligned", first.Len(), archiveBlock)
	}
	if !bytes.HasPrefix(first.Bytes(), []byte(newcMagic)) || bytes.HasPrefix(first.Bytes(), []byte{0x1f, 0x8b}) {
		t.Fatal("runtime initramfs is not an uncompressed newc archive")
	}

	expected := []runtimeArchiveExpectation{
		{name: "dev", mode: modeDirectory | 0o755, directory: true},
		{name: "dev/console", mode: modeCharacter | 0o600, rdevMajor: 5, rdevMinor: 1},
		{name: "init", mode: modeRegular | 0o555, data: initBinary},
		{name: "proc", mode: modeDirectory | 0o555, directory: true},
		{name: "sys", mode: modeDirectory | 0o555, directory: true},
		{name: "run", mode: modeDirectory | 0o755, directory: true},
		{name: "tmp", mode: modeDirectory | 0o1777, directory: true},
		{name: "opt", mode: modeDirectory | 0o555, directory: true},
		{name: "workspace", mode: modeDirectory | 0o755, directory: true},
		{name: "home", mode: modeDirectory | 0o755, directory: true},
		{name: "config.json", mode: modeRegular | 0o400, data: config},
	}
	entries := parseRuntimeNewc(t, first.Bytes())
	if len(entries) != len(expected) {
		t.Fatalf("archive entries = %d, want %d", len(entries), len(expected))
	}
	for index, want := range expected {
		got := entries[index]
		if got.name != want.name || got.mode != want.mode || !bytes.Equal(got.data, want.data) {
			t.Fatalf("entry %d = %+v, want name=%q mode=%#o data-bytes=%d", index, got, want.name, want.mode, len(want.data))
		}
		if got.inode != uint32(index+1) || got.uid != 0 || got.gid != 0 || got.mtime != 0 || got.devMajor != 0 || got.devMinor != 0 || got.checksum != 0 {
			t.Fatalf("entry %q has non-fixed metadata: %+v", got.name, got)
		}
		wantLinks := uint32(1)
		if want.directory {
			wantLinks = 2
		}
		if got.nlink != wantLinks || got.rdevMajor != want.rdevMajor || got.rdevMinor != want.rdevMinor {
			t.Fatalf("entry %q link/device metadata = %+v", got.name, got)
		}
	}
}

func TestBuildRuntimeInitramfsRejectsNonStaticAndOutOfRangeInit(t *testing.T) {
	config := []byte(`{"command":["agent"]}`)
	dynamic, err := os.ReadFile("/bin/sh")
	if err != nil {
		t.Fatal(err)
	}
	if err := BuildRuntimeInitramfs(&bytes.Buffer{}, dynamic, config); err == nil || !strings.Contains(err.Error(), "dynamically linked") {
		t.Fatalf("dynamic runtime init rejection = %v", err)
	}
	for name, initBinary := range map[string][]byte{
		"empty":    nil,
		"oversize": make([]byte, maxInitBytes+1),
	} {
		t.Run(name, func(t *testing.T) {
			if err := BuildRuntimeInitramfs(&bytes.Buffer{}, initBinary, config); err == nil {
				t.Fatalf("accepted %s runtime init", name)
			}
		})
	}
}

func TestBuildRuntimeInitramfsValidatesOneBoundedJSONObject(t *testing.T) {
	initBinary := buildStaticGuest(t)
	invalid := []struct {
		name   string
		config []byte
	}{
		{name: "empty"},
		{name: "whitespace", config: []byte(" \n\t")},
		{name: "null", config: []byte("null")},
		{name: "array", config: []byte("[]")},
		{name: "string", config: []byte(`"config"`)},
		{name: "number", config: []byte("1")},
		{name: "boolean", config: []byte("true")},
		{name: "unclosed", config: []byte(`{"command":"agent"`)},
		{name: "trailing object", config: []byte(`{} {}`)},
		{name: "trailing scalar", config: []byte(`{} 1`)},
		{name: "trailing garbage", config: []byte(`{} x`)},
		{name: "oversize", config: bytes.Repeat([]byte{' '}, maxRuntimeConfigBytes+1)},
	}
	for _, test := range invalid {
		t.Run(test.name, func(t *testing.T) {
			if err := BuildRuntimeInitramfs(&bytes.Buffer{}, initBinary, test.config); err == nil {
				t.Fatalf("accepted invalid config %q", test.config)
			}
		})
	}

	boundary := append([]byte(`{"value":"`), bytes.Repeat([]byte{'a'}, maxRuntimeConfigBytes-len(`{"value":"`)-len(`"}`))...)
	boundary = append(boundary, []byte(`"}`)...)
	if len(boundary) != maxRuntimeConfigBytes {
		t.Fatalf("boundary config length = %d, want %d", len(boundary), maxRuntimeConfigBytes)
	}
	if err := BuildRuntimeInitramfs(io.Discard, initBinary, boundary); err != nil {
		t.Fatalf("exact-limit config rejected: %v", err)
	}
	if err := BuildRuntimeInitramfs(io.Discard, initBinary, []byte(" \n{}\t")); err != nil {
		t.Fatalf("single object with surrounding whitespace rejected: %v", err)
	}
}

type runtimeShortWriter struct{}

func (runtimeShortWriter) Write(data []byte) (int, error) {
	if len(data) == 0 {
		return 0, nil
	}
	return len(data) - 1, nil
}

func TestBuildRuntimeInitramfsRejectsNilAndShortWriter(t *testing.T) {
	initBinary := buildStaticGuest(t)
	config := []byte(`{"command":["agent"]}`)
	if err := BuildRuntimeInitramfs(nil, initBinary, config); err == nil {
		t.Fatal("nil runtime initramfs writer was accepted")
	}
	if err := BuildRuntimeInitramfs(runtimeShortWriter{}, initBinary, config); !errors.Is(err, io.ErrShortWrite) {
		t.Fatalf("short writer error = %v, want io.ErrShortWrite", err)
	}
}

type runtimeArchiveExpectation struct {
	name                 string
	mode                 uint32
	rdevMajor, rdevMinor uint32
	data                 []byte
	directory            bool
}

type runtimeParsedEntry struct {
	name                                                                          string
	inode, mode, uid, gid, nlink, mtime, devMajor, devMinor, rdevMajor, rdevMinor uint32
	checksum                                                                      uint32
	data                                                                          []byte
}

func parseRuntimeNewc(t *testing.T, archive []byte) []runtimeParsedEntry {
	t.Helper()
	var entries []runtimeParsedEntry
	offset := 0
	for {
		if offset+newcHeaderBytes > len(archive) {
			t.Fatalf("truncated runtime newc header at %d", offset)
		}
		headerOffset := offset
		header := archive[offset : offset+newcHeaderBytes]
		if string(header[:6]) != newcMagic {
			t.Fatalf("runtime newc magic at %d = %q", offset, header[:6])
		}
		field := func(start int) uint32 {
			value, err := strconv.ParseUint(string(header[start:start+8]), 16, 32)
			if err != nil {
				t.Fatalf("parse runtime newc field at %d: %v", headerOffset+start, err)
			}
			return uint32(value)
		}
		entry := runtimeParsedEntry{
			inode: field(6), mode: field(14), uid: field(22), gid: field(30),
			nlink: field(38), mtime: field(46), devMajor: field(62), devMinor: field(70),
			rdevMajor: field(78), rdevMinor: field(86), checksum: field(102),
		}
		fileSize, nameSize := int(field(54)), int(field(94))
		offset += newcHeaderBytes
		if nameSize < 1 || offset+nameSize > len(archive) || archive[offset+nameSize-1] != 0 {
			t.Fatalf("invalid runtime newc name at %d", offset)
		}
		entry.name = string(archive[offset : offset+nameSize-1])
		nameEnd := offset + nameSize
		offset = align(nameEnd, 4)
		assertZeroRuntimePadding(t, archive[nameEnd:offset], nameEnd)
		if offset+fileSize > len(archive) {
			t.Fatalf("truncated runtime newc data for %q", entry.name)
		}
		entry.data = append([]byte(nil), archive[offset:offset+fileSize]...)
		dataEnd := offset + fileSize
		offset = align(dataEnd, 4)
		assertZeroRuntimePadding(t, archive[dataEnd:offset], dataEnd)
		if entry.name == "TRAILER!!!" {
			if entry.inode != uint32(len(entries)+1) || entry.mode != 0 || entry.uid != 0 || entry.gid != 0 || entry.mtime != 0 || len(entry.data) != 0 {
				t.Fatalf("runtime newc trailer has non-fixed metadata: %+v", entry)
			}
			assertZeroRuntimePadding(t, archive[offset:], offset)
			return entries
		}
		entries = append(entries, entry)
	}
}

func assertZeroRuntimePadding(t *testing.T, data []byte, offset int) {
	t.Helper()
	for index, value := range data {
		if value != 0 {
			t.Fatalf("nonzero runtime archive padding at %d: %#x", offset+index, value)
		}
	}
}
