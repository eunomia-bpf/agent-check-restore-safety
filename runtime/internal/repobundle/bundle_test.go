package repobundle

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"syscall"
	"testing"

	"golang.org/x/sys/unix"
)

func TestBuildDecodeAndMaterializeCanonicalRepository(t *testing.T) {
	source := filepath.Join(t.TempDir(), "source")
	if err := os.MkdirAll(filepath.Join(source, "cmd"), 0o700); err != nil {
		t.Fatal(err)
	}
	writeTestFile(t, filepath.Join(source, "README.md"), []byte("hello\n"), 0o600)
	writeTestFile(t, filepath.Join(source, "cmd", "run"), []byte{'#', '!', 0, '\n'}, 0o711)
	if err := os.Symlink("../README.md", filepath.Join(source, "cmd", "readme")); err != nil {
		t.Fatal(err)
	}

	var first, second bytes.Buffer
	bundle, err := Build(source, &first, DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Build(source, &second, DefaultLimits()); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(first.Bytes(), second.Bytes()) {
		t.Fatal("same repository did not produce byte-identical bundles")
	}
	if first.Len()%blockDeviceAlignment != 0 {
		t.Fatalf("repository bundle size %d is not block aligned", first.Len())
	}
	decoded, err := Decode(bytes.NewReader(first.Bytes()), DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	if decoded.TreeRoot != bundle.TreeRoot || decoded.ContentBytes != uint64(len("hello\n")+4+len("../README.md")) {
		t.Fatalf("decoded metadata = root %s content %d", decoded.TreeRoot, decoded.ContentBytes)
	}
	if got := entryProjection(decoded.Entries); !reflect.DeepEqual(got, []string{
		"README.md:file:0644:6", "cmd:directory:0755:0", "cmd/readme:symlink:0777:12", "cmd/run:file:0755:4",
	}) {
		t.Fatalf("entries = %#v", got)
	}

	destination := filepath.Join(t.TempDir(), "destination")
	if err := os.Mkdir(destination, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := decoded.Materialize(destination); err != nil {
		t.Fatal(err)
	}
	owned := filepath.Join(t.TempDir(), "owned")
	if err := os.Mkdir(owned, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := decoded.MaterializeOwned(owned, os.Geteuid(), os.Getegid()); err != nil {
		t.Fatal(err)
	}
	for _, relative := range []string{".", "README.md", "cmd", "cmd/readme", "cmd/run"} {
		info, err := os.Lstat(filepath.Join(owned, relative))
		if err != nil {
			t.Fatal(err)
		}
		stat := info.Sys().(*syscall.Stat_t)
		if stat.Uid != uint32(os.Geteuid()) || stat.Gid != uint32(os.Getegid()) {
			t.Fatalf("owned entry %s has uid/gid %d/%d", relative, stat.Uid, stat.Gid)
		}
	}
	assertFile(t, filepath.Join(destination, "README.md"), []byte("hello\n"), 0o644)
	assertFile(t, filepath.Join(destination, "cmd", "run"), []byte{'#', '!', 0, '\n'}, 0o755)
	target, err := os.Readlink(filepath.Join(destination, "cmd", "readme"))
	if err != nil || target != "../README.md" {
		t.Fatalf("materialized link target=%q err=%v", target, err)
	}
	if err := decoded.Materialize(destination); err == nil || !strings.Contains(err.Error(), "empty") {
		t.Fatalf("nonempty destination error = %v", err)
	}
	tampered := decoded
	tampered.TreeRoot[0] ^= 1
	empty := filepath.Join(t.TempDir(), "empty")
	if err := os.Mkdir(empty, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := tampered.Materialize(empty); err == nil || !strings.Contains(err.Error(), "metadata") {
		t.Fatalf("tampered metadata error = %v", err)
	}
}

func TestBuildFilePublishesExclusiveVerifiedBytes(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "source")
	if err := os.Mkdir(source, 0o700); err != nil {
		t.Fatal(err)
	}
	writeTestFile(t, filepath.Join(source, "a"), []byte("a"), 0o600)
	output := filepath.Join(root, "repository.bundle")
	result, err := BuildFile(source, output, DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(output)
	if err != nil {
		t.Fatal(err)
	}
	if result.Path != output || result.Size != int64(len(data)) || result.SHA256 == (Digest{}) || result.FileCount != 1 || result.DirCount != 0 {
		t.Fatalf("result = %+v", result)
	}
	if _, err := Decode(bytes.NewReader(data), DefaultLimits()); err != nil {
		t.Fatalf("published bytes do not decode: %v", err)
	}
	if _, err := BuildFile(source, output, DefaultLimits()); err == nil || !strings.Contains(err.Error(), "exists") {
		t.Fatalf("existing output error = %v", err)
	}
	public := filepath.Join(root, "public")
	if err := os.Mkdir(public, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(public, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := BuildFile(source, filepath.Join(public, "repository.bundle"), DefaultLimits()); err == nil || !strings.Contains(err.Error(), "0700") {
		t.Fatalf("public output parent error = %v", err)
	}
}

func TestValidateRejectsBundleMetadataWithoutCloning(t *testing.T) {
	bundle := testBundle(t)
	if err := Validate(bundle, DefaultLimits()); err != nil {
		t.Fatal(err)
	}
	tampered := bundle
	tampered.TreeRoot[0] ^= 1
	if err := Validate(tampered, DefaultLimits()); err == nil || !strings.Contains(err.Error(), "tree root") {
		t.Fatalf("tampered tree root error = %v", err)
	}
}

func TestDecodeRejectsEveryBoundIntegrityAndCanonicalityViolation(t *testing.T) {
	bundle := testBundle(t)
	var encoded bytes.Buffer
	if err := Encode(&encoded, bundle, DefaultLimits()); err != nil {
		t.Fatal(err)
	}
	valid := encoded.Bytes()
	mutations := map[string]func([]byte) []byte{
		"truncated":       func(data []byte) []byte { return data[:len(data)-1] },
		"trailing":        func(data []byte) []byte { return append(data, 0) },
		"magic":           func(data []byte) []byte { data[0] ^= 1; return data },
		"header reserved": func(data []byte) []byte { data[127] = 1; return data },
		"declared total":  func(data []byte) []byte { binary.BigEndian.PutUint64(data[32:40], uint64(len(data)-1)); return data },
		"body hash":       func(data []byte) []byte { data[72] ^= 1; return data },
		"tree root":       func(data []byte) []byte { data[40] ^= 1; return data },
		"block padding":   func(data []byte) []byte { data[len(data)-1] = 1; return data },
		"entry reserved":  func(data []byte) []byte { data[headerSize+1] = 1; return data },
		"record size":     func(data []byte) []byte { data[headerSize+63] ^= 1; return data },
		"path padding": func(data []byte) []byte {
			pathLength := binary.BigEndian.Uint32(data[headerSize+8 : headerSize+12])
			padding := paddingFor(uint64(pathLength))
			if padding == 0 {
				t.Fatal("fixture unexpectedly has no path padding")
			}
			data[headerSize+entryHeaderSize+int(pathLength)] = 1
			return data
		},
		"content": func(data []byte) []byte {
			pathLength := binary.BigEndian.Uint32(data[headerSize+8 : headerSize+12])
			offset := headerSize + entryHeaderSize + int(pathLength+uint32(paddingFor(uint64(pathLength))))
			data[offset] ^= 1
			return data
		},
		"data padding": func(data []byte) []byte {
			pathLength := binary.BigEndian.Uint32(data[headerSize+8 : headerSize+12])
			dataLength := binary.BigEndian.Uint64(data[headerSize+16 : headerSize+24])
			offset := headerSize + entryHeaderSize + int(pathLength) + int(paddingFor(uint64(pathLength))) + int(dataLength)
			if paddingFor(dataLength) == 0 {
				t.Fatal("fixture unexpectedly has no data padding")
			}
			data[offset] = 1
			return data
		},
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			candidate := mutate(bytes.Clone(valid))
			if _, err := Decode(bytes.NewReader(candidate), DefaultLimits()); err == nil {
				t.Fatal("mutated bundle was accepted")
			}
		})
	}
}

func TestDecodeRejectsImpossibleRecordBeforeContentAllocation(t *testing.T) {
	const declaredData = 64 << 20
	header := make([]byte, headerSize)
	copy(header[0:8], bundleMagic[:])
	binary.BigEndian.PutUint32(header[8:12], Schema)
	binary.BigEndian.PutUint32(header[12:16], headerSize)
	binary.BigEndian.PutUint64(header[16:24], 1)
	binary.BigEndian.PutUint64(header[24:32], declaredData)
	binary.BigEndian.PutUint64(header[32:40], blockDeviceAlignment)
	entry := make([]byte, entryHeaderSize+encodedAlignment)
	entry[0] = byte(EntryFile)
	binary.BigEndian.PutUint32(entry[4:8], 0o644)
	binary.BigEndian.PutUint32(entry[8:12], 1)
	binary.BigEndian.PutUint64(entry[16:24], declaredData)
	binary.BigEndian.PutUint64(entry[56:64], entryHeaderSize+encodedAlignment+declaredData)
	entry[entryHeaderSize] = 'a'
	_, err := Decode(bytes.NewReader(append(header, entry...)), DefaultLimits())
	if err == nil || !strings.Contains(err.Error(), "remaining bundle body") {
		t.Fatalf("impossible record error = %v", err)
	}

	const largeDeclaredData = 64 << 20
	largeHeader := make([]byte, headerSize)
	copy(largeHeader[0:8], bundleMagic[:])
	binary.BigEndian.PutUint32(largeHeader[8:12], Schema)
	binary.BigEndian.PutUint32(largeHeader[12:16], headerSize)
	binary.BigEndian.PutUint64(largeHeader[16:24], 1)
	binary.BigEndian.PutUint64(largeHeader[24:32], largeDeclaredData)
	largeRecordSize := uint64(entryHeaderSize+encodedAlignment) + largeDeclaredData
	largeTotal := uint64(headerSize) + largeRecordSize
	largeTotal += paddingForAlignment(largeTotal, blockDeviceAlignment)
	binary.BigEndian.PutUint64(largeHeader[32:40], largeTotal)
	largeEntry := make([]byte, entryHeaderSize+encodedAlignment)
	largeEntry[0] = byte(EntryFile)
	binary.BigEndian.PutUint32(largeEntry[4:8], 0o644)
	binary.BigEndian.PutUint32(largeEntry[8:12], 1)
	binary.BigEndian.PutUint64(largeEntry[16:24], largeDeclaredData)
	binary.BigEndian.PutUint64(largeEntry[56:64], largeRecordSize)
	largeEntry[entryHeaderSize] = 'a'
	tracked := &maximumReadReader{reader: bytes.NewReader(append(largeHeader, largeEntry...))}
	if _, err := Decode(tracked, DefaultLimits()); err == nil {
		t.Fatal("truncated large declared entry was accepted")
	}
	if tracked.maximum > 32<<10 {
		t.Fatalf("decoder requested a %d-byte read for truncated input", tracked.maximum)
	}

	tooMany := make([]byte, headerSize)
	copy(tooMany[0:8], bundleMagic[:])
	binary.BigEndian.PutUint32(tooMany[8:12], Schema)
	binary.BigEndian.PutUint32(tooMany[12:16], headerSize)
	binary.BigEndian.PutUint64(tooMany[16:24], 4)
	binary.BigEndian.PutUint64(tooMany[32:40], blockDeviceAlignment)
	if _, err := Decode(bytes.NewReader(tooMany), DefaultLimits()); err == nil || !strings.Contains(err.Error(), "too small") {
		t.Fatalf("impossible entry count error = %v", err)
	}
}

func TestReadDirectoryNamesEnforcesLimitWhileReading(t *testing.T) {
	root := t.TempDir()
	for index := 0; index < 300; index++ {
		writeTestFile(t, filepath.Join(root, fmt.Sprintf("entry-%03d", index)), nil, 0o600)
	}
	descriptor, err := openDirectDirectory(root)
	if err != nil {
		t.Fatal(err)
	}
	defer unix.Close(descriptor)
	if _, err := readDirectoryNames(descriptor, 2); err == nil || !strings.Contains(err.Error(), "more than 2") {
		t.Fatalf("directory limit error = %v", err)
	}
}

func TestFromEntriesRejectsUnsafeTrees(t *testing.T) {
	file := func(path string, data string) Entry {
		return Entry{Path: path, Type: EntryFile, Mode: 0o644, Data: []byte(data)}
	}
	directory := func(path string) Entry { return Entry{Path: path, Type: EntryDirectory, Mode: 0o755} }
	link := func(path, target string) Entry {
		return Entry{Path: path, Type: EntrySymlink, Mode: 0o777, Data: []byte(target)}
	}
	cases := map[string][]Entry{
		"absolute":       {file("/x", "x")},
		"parent":         {file("../x", "x")},
		"control":        {file("bad\nname", "x")},
		"backslash":      {file(`a\b`, "x")},
		"git":            {directory(".git")},
		"casefold git":   {directory(".GIT")},
		"missing parent": {file("a/b", "x")},
		"file parent":    {file("a", "x"), file("a/b", "x")},
		"duplicate":      {file("a", "x"), file("a", "y")},
		"unsorted":       {file("b", "x"), file("a", "y")},
		"escape link":    {directory("a"), link("a/out", "../../outside")},
		"absolute link":  {link("out", "/outside")},
		"git link":       {link("out", ".git/config")},
		"composed escape": {
			link("s", "."),
			link("trigger", "s/../outside"),
		},
		"bad file mode": {{Path: "a", Type: EntryFile, Mode: 0o666, Data: []byte("x")}},
		"unknown type":  {{Path: "a", Type: 9, Mode: 0o644}},
	}
	for name, entries := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := FromEntries(entries, DefaultLimits()); err == nil {
				t.Fatal("unsafe tree was accepted")
			}
		})
	}
}

func TestBuildRejectsGitSpecialAndEscapingLinks(t *testing.T) {
	for name, makeBad := range map[string]func(string) error{
		"git": func(root string) error { return os.Mkdir(filepath.Join(root, ".git"), 0o700) },
		"fifo": func(root string) error {
			return syscall.Mkfifo(filepath.Join(root, "pipe"), 0o600)
		},
		"link": func(root string) error { return os.Symlink("../outside", filepath.Join(root, "out")) },
	} {
		t.Run(name, func(t *testing.T) {
			root := filepath.Join(t.TempDir(), "source")
			if err := os.Mkdir(root, 0o700); err != nil {
				t.Fatal(err)
			}
			if err := makeBad(root); err != nil {
				t.Fatal(err)
			}
			if _, err := Build(root, io.Discard, DefaultLimits()); err == nil {
				t.Fatal("unsafe source was accepted")
			}
		})
	}
}

func TestBuildRejectsSpecialModesAndGitSourceRoot(t *testing.T) {
	for name, makeBad := range map[string]func(string) error{
		"setuid": func(root string) error {
			path := filepath.Join(root, "program")
			if err := os.WriteFile(path, []byte("x"), 0o600); err != nil {
				return err
			}
			return os.Chmod(path, 0o644|os.ModeSetuid)
		},
		"setgid": func(root string) error {
			path := filepath.Join(root, "program")
			if err := os.WriteFile(path, []byte("x"), 0o600); err != nil {
				return err
			}
			return os.Chmod(path, 0o644|os.ModeSetgid)
		},
		"sticky": func(root string) error {
			path := filepath.Join(root, "directory")
			if err := os.Mkdir(path, 0o700); err != nil {
				return err
			}
			return os.Chmod(path, 0o755|os.ModeSticky)
		},
	} {
		t.Run(name, func(t *testing.T) {
			root := filepath.Join(t.TempDir(), "source")
			if err := os.Mkdir(root, 0o700); err != nil {
				t.Fatal(err)
			}
			if err := makeBad(root); err != nil {
				t.Fatal(err)
			}
			if _, err := Build(root, io.Discard, DefaultLimits()); err == nil || !strings.Contains(err.Error(), "forbidden") {
				t.Fatalf("special-mode error = %v", err)
			}
		})
	}
	gitRoot := filepath.Join(t.TempDir(), ".git")
	if err := os.Mkdir(gitRoot, 0o700); err != nil {
		t.Fatal(err)
	}
	if _, err := Build(gitRoot, io.Discard, DefaultLimits()); err == nil || !strings.Contains(err.Error(), ".git") {
		t.Fatalf(".git source-root error = %v", err)
	}
}

func TestAnchoredDirectoryWalkRejectsSymbolicLinkComponent(t *testing.T) {
	root := filepath.Join(t.TempDir(), "root")
	outside := filepath.Join(t.TempDir(), "outside")
	if err := os.Mkdir(root, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(outside, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(root, "escape")); err != nil {
		t.Fatal(err)
	}
	descriptor, err := openDirectDirectory(root)
	if err != nil {
		t.Fatal(err)
	}
	defer unix.Close(descriptor)
	if opened, err := openDirectoryAt(descriptor, "escape"); err == nil {
		_ = unix.Close(opened)
		t.Fatal("anchored directory walk followed a symbolic link")
	}
}

func testBundle(t *testing.T) Bundle {
	t.Helper()
	bundle, err := FromEntries([]Entry{{Path: "a", Type: EntryFile, Mode: 0o644, Data: []byte("payload")}}, DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	return bundle
}

func writeTestFile(t *testing.T, path string, data []byte, mode os.FileMode) {
	t.Helper()
	if err := os.WriteFile(path, data, mode); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, mode); err != nil {
		t.Fatal(err)
	}
}

func assertFile(t *testing.T, path string, want []byte, mode os.FileMode) {
	t.Helper()
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, want) || info.Mode().Perm() != mode {
		t.Fatalf("%s bytes=%q mode=%04o", path, got, info.Mode().Perm())
	}
}

func entryProjection(entries []Entry) []string {
	result := make([]string, 0, len(entries))
	for _, entry := range entries {
		typeName := map[EntryType]string{EntryDirectory: "directory", EntryFile: "file", EntrySymlink: "symlink"}[entry.Type]
		result = append(result, entry.Path+":"+typeName+":"+formatMode(entry.Mode)+":"+formatLength(len(entry.Data)))
	}
	return result
}

func formatMode(mode uint32) string {
	const digits = "01234567"
	return string([]byte{digits[(mode>>9)&7], digits[(mode>>6)&7], digits[(mode>>3)&7], digits[mode&7]})
}

func formatLength(length int) string {
	return strconv.Itoa(length)
}

type maximumReadReader struct {
	reader  io.Reader
	maximum int
}

func (reader *maximumReadReader) Read(data []byte) (int, error) {
	if len(data) > reader.maximum {
		reader.maximum = len(data)
	}
	return reader.reader.Read(data)
}
