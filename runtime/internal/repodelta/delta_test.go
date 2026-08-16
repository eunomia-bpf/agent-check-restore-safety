package repodelta

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"io"
	"reflect"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repobundle"
)

func TestComputeEncodeDecodeApplyCompleteRepositoryDelta(t *testing.T) {
	base := testBaseBundle(t)
	final := testFinalBundle(t)
	limits := DefaultLimits()

	delta, err := Compute(base, final, limits)
	if err != nil {
		t.Fatal(err)
	}
	wantOperations := []string{
		"add:added.bin",
		"modify:bin/tool",
		"modify:data.bin",
		"delete:delete.txt",
		"add:docs/guide",
		"modify:docs/readme",
		"modify:kind",
		"modify:link",
	}
	if got := operationProjection(delta.Operations); !reflect.DeepEqual(got, wantOperations) {
		t.Fatalf("operations = %#v, want %#v", got, wantOperations)
	}
	if delta.BaseRoot != base.TreeRoot || delta.FinalRoot != final.TreeRoot {
		t.Fatalf("delta roots = %s -> %s, want %s -> %s", delta.BaseRoot, delta.FinalRoot, base.TreeRoot, final.TreeRoot)
	}

	byPath := make(map[string]Operation, len(delta.Operations))
	for _, operation := range delta.Operations {
		byPath[operation.Path] = operation
	}
	if got := byPath["added.bin"].Final.Data; !bytes.Equal(got, []byte{0, 1, 2, 0xff}) {
		t.Fatalf("added binary bytes = %v", got)
	}
	if got := byPath["bin/tool"].Final.Mode; got != 0o755 {
		t.Fatalf("executable mode = %04o", got)
	}
	if operation := byPath["kind"]; operation.Final.Type != repobundle.EntrySymlink || string(operation.Final.Data) != "docs/readme" {
		t.Fatalf("type-change final entry = %+v", operation.Final)
	}
	if got := string(byPath["link"].Final.Data); got != "docs/guide" {
		t.Fatalf("symlink target = %q", got)
	}
	if !zeroEntry(byPath["delete.txt"].Final) {
		t.Fatalf("delete carries final entry: %+v", byPath["delete.txt"].Final)
	}

	var first, second bytes.Buffer
	if err := Encode(&first, delta, limits); err != nil {
		t.Fatal(err)
	}
	if err := Encode(&second, delta, limits); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(first.Bytes(), second.Bytes()) {
		t.Fatal("same delta did not produce byte-identical encodings")
	}
	decoded, err := Decode(bytes.NewReader(first.Bytes()), limits)
	if err != nil {
		t.Fatal(err)
	}
	var reencoded bytes.Buffer
	if err := Encode(&reencoded, decoded, limits); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(first.Bytes(), reencoded.Bytes()) {
		t.Fatal("decoded delta did not re-encode identically")
	}
	applied, err := Apply(base, decoded, limits)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(applied, final) {
		t.Fatalf("applied bundle differs from final:\n got  %+v\n want %+v", applied, final)
	}
}

func TestComputeUnchangedTreeProducesBoundEmptyDelta(t *testing.T) {
	base := testBaseBundle(t)
	delta, err := Compute(base, base, DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	if len(delta.Operations) != 0 || delta.BaseRoot != base.TreeRoot || delta.FinalRoot != base.TreeRoot {
		t.Fatalf("unchanged delta = %+v", delta)
	}
	var encoded bytes.Buffer
	if err := Encode(&encoded, delta, DefaultLimits()); err != nil {
		t.Fatal(err)
	}
	decoded, err := Decode(bytes.NewReader(encoded.Bytes()), DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Apply(base, decoded, DefaultLimits()); err != nil {
		t.Fatal(err)
	}
	tampered := bytes.Clone(encoded.Bytes())
	tampered[72] ^= 1
	if _, err := Decode(bytes.NewReader(tampered), DefaultLimits()); err == nil || !strings.Contains(err.Error(), "identical") {
		t.Fatalf("empty delta with distinct roots error = %v", err)
	}
}

func TestDecodeRejectsMutationTruncationAndNoncanonicalOperations(t *testing.T) {
	delta := mustCompute(t, testBaseBundle(t), testFinalBundle(t))
	valid := encodeDelta(t, delta)
	offsets := operationOffsets(t, valid)
	first := offsets[0]
	pathLength := int(binary.BigEndian.Uint32(valid[first+8 : first+12]))
	pathPadding := int(paddingFor(uint64(pathLength)))
	dataOffset := first + operationHeaderSize + pathLength + pathPadding

	mutations := map[string]func([]byte) []byte{
		"truncated": func(data []byte) []byte { return data[:len(data)-1] },
		"trailing":  func(data []byte) []byte { return append(data, 0) },
		"magic": func(data []byte) []byte {
			data[0] ^= 1
			return data
		},
		"schema": func(data []byte) []byte {
			binary.BigEndian.PutUint32(data[8:12], Schema+1)
			return data
		},
		"header reserved": func(data []byte) []byte {
			data[headerSize-1] = 1
			return data
		},
		"operation count": func(data []byte) []byte {
			binary.BigEndian.PutUint64(data[16:24], binary.BigEndian.Uint64(data[16:24])+1)
			return data
		},
		"content bytes": func(data []byte) []byte {
			binary.BigEndian.PutUint64(data[24:32], binary.BigEndian.Uint64(data[24:32])+1)
			return data
		},
		"declared total": func(data []byte) []byte {
			binary.BigEndian.PutUint64(data[32:40], uint64(len(data)-1))
			return data
		},
		"body hash": func(data []byte) []byte {
			data[104] ^= 1
			return data
		},
		"operation reserved": func(data []byte) []byte {
			data[first+2] = 1
			rewriteBodyHash(data)
			return data
		},
		"record size": func(data []byte) []byte {
			data[first+63] ^= 1
			rewriteBodyHash(data)
			return data
		},
		"path padding": func(data []byte) []byte {
			if pathPadding == 0 {
				t.Fatal("fixture unexpectedly has no path padding")
			}
			data[first+operationHeaderSize+pathLength] = 1
			rewriteBodyHash(data)
			return data
		},
		"content without body hash": func(data []byte) []byte {
			data[dataOffset] ^= 1
			return data
		},
		"content with body hash": func(data []byte) []byte {
			data[dataOffset] ^= 1
			rewriteBodyHash(data)
			return data
		},
		"entry content digest": func(data []byte) []byte {
			data[first+24] ^= 1
			rewriteBodyHash(data)
			return data
		},
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			candidate := mutate(bytes.Clone(valid))
			if _, err := Decode(bytes.NewReader(candidate), DefaultLimits()); err == nil {
				t.Fatal("mutated delta was accepted")
			}
		})
	}

	canonicalOrder := mustCompute(t,
		testBundle(t),
		testBundle(t, fileEntry("aa", 0o644, []byte("a")), fileEntry("bb", 0o644, []byte("b"))),
	)
	orderedBytes := encodeDelta(t, canonicalOrder)
	orderedOffsets := operationOffsets(t, orderedBytes)
	if len(orderedOffsets) != 2 {
		t.Fatalf("ordered fixture has %d operations", len(orderedOffsets))
	}
	for name, replacement := range map[string]string{"duplicate": "aa", "out of order": "a0"} {
		t.Run(name, func(t *testing.T) {
			candidate := bytes.Clone(orderedBytes)
			secondPath := orderedOffsets[1] + operationHeaderSize
			copy(candidate[secondPath:secondPath+2], replacement)
			rewriteBodyHash(candidate)
			if _, err := Decode(bytes.NewReader(candidate), DefaultLimits()); err == nil {
				t.Fatal("noncanonical operation order was accepted")
			}
		})
	}

	unsafeDelta := mustCompute(t, testBundle(t), testBundle(t, fileEntry("aaa", 0o644, []byte("x"))))
	unsafeBytes := encodeDelta(t, unsafeDelta)
	unsafeOffset := operationOffsets(t, unsafeBytes)[0] + operationHeaderSize
	copy(unsafeBytes[unsafeOffset:unsafeOffset+3], "../")
	rewriteBodyHash(unsafeBytes)
	if _, err := Decode(bytes.NewReader(unsafeBytes), DefaultLimits()); err == nil {
		t.Fatal("unsafe operation path was accepted")
	}
}

func TestApplyRejectsMalformedSemanticHashAndRootTampering(t *testing.T) {
	base := testBaseBundle(t)
	final := testFinalBundle(t)
	valid := mustCompute(t, base, final)

	cases := map[string]func(Delta) Delta{
		"duplicate": func(delta Delta) Delta {
			delta.Operations = append(delta.Operations[:1], append([]Operation{cloneOperation(delta.Operations[0])}, delta.Operations[1:]...)...)
			return delta
		},
		"out of order": func(delta Delta) Delta {
			delta.Operations[0], delta.Operations[1] = delta.Operations[1], delta.Operations[0]
			return delta
		},
		"unsafe path": func(delta Delta) Delta {
			delta.Operations[0].Path = "../outside"
			delta.Operations[0].Final.Path = "../outside"
			return delta
		},
		"content hash": func(delta Delta) Delta {
			delta.Operations[0].Final.SHA256[0] ^= 1
			return delta
		},
		"base root": func(delta Delta) Delta {
			delta.BaseRoot[0] ^= 1
			return delta
		},
		"final root": func(delta Delta) Delta {
			delta.FinalRoot[0] ^= 1
			return delta
		},
		"delete payload": func(delta Delta) Delta {
			for index := range delta.Operations {
				if delta.Operations[index].Kind == OpDelete {
					delta.Operations[index].Final = fileEntry(delta.Operations[index].Path, 0o644, []byte("bad"))
					break
				}
			}
			return delta
		},
		"unknown kind": func(delta Delta) Delta {
			delta.Operations[0].Kind = 99
			return delta
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			candidate := mutate(cloneDelta(valid))
			if _, err := Apply(base, candidate, DefaultLimits()); err == nil {
				t.Fatal("malformed delta was applied")
			}
		})
	}

	baseEntry := cloneEntry(base.Entries[0])
	semanticCases := map[string]Delta{
		"add existing": {
			Schema: Schema, BaseRoot: base.TreeRoot, FinalRoot: final.TreeRoot,
			Operations: []Operation{{Kind: OpAdd, Path: baseEntry.Path, Final: baseEntry}},
		},
		"delete missing": {
			Schema: Schema, BaseRoot: base.TreeRoot, FinalRoot: final.TreeRoot,
			Operations: []Operation{{Kind: OpDelete, Path: "missing"}},
		},
		"modify missing": {
			Schema: Schema, BaseRoot: base.TreeRoot, FinalRoot: final.TreeRoot,
			Operations: []Operation{{Kind: OpModify, Path: "missing", Final: fileEntry("missing", 0o644, []byte("new"))}},
		},
		"no-op modify": {
			Schema: Schema, BaseRoot: base.TreeRoot, FinalRoot: base.TreeRoot,
			Operations: []Operation{{Kind: OpModify, Path: baseEntry.Path, Final: baseEntry}},
		},
	}
	for name, candidate := range semanticCases {
		t.Run(name, func(t *testing.T) {
			if _, err := Apply(base, candidate, DefaultLimits()); err == nil {
				t.Fatal("semantically invalid delta was applied")
			}
		})
	}
}

func TestApplyRejectsTamperedCanonicalBaseAndInvalidFinalTree(t *testing.T) {
	base := testBaseBundle(t)
	final := testFinalBundle(t)
	delta := mustCompute(t, base, final)

	tampered := base
	tampered.Entries = append([]repobundle.Entry(nil), base.Entries...)
	tampered.Entries[0] = cloneEntry(tampered.Entries[0])
	tampered.Entries[0].Data = append(tampered.Entries[0].Data, 'x')
	if _, err := Apply(tampered, delta, DefaultLimits()); err == nil {
		t.Fatal("tampered base bundle was accepted")
	}

	nestedBase := testBundle(t,
		directoryEntry("dir"),
		fileEntry("dir/file", 0o644, []byte("x")),
	)
	invalidTreeDelta := Delta{
		Schema:     Schema,
		BaseRoot:   nestedBase.TreeRoot,
		FinalRoot:  final.TreeRoot,
		Operations: []Operation{{Kind: OpDelete, Path: "dir"}},
	}
	if _, err := Apply(nestedBase, invalidTreeDelta, DefaultLimits()); err == nil || !strings.Contains(err.Error(), "final tree") {
		t.Fatalf("invalid final tree error = %v", err)
	}
}

func TestDecodeRootTamperingIsRejectedByApply(t *testing.T) {
	base := testBaseBundle(t)
	final := testFinalBundle(t)
	valid := encodeDelta(t, mustCompute(t, base, final))
	for name, offset := range map[string]int{"base": 40, "final": 72} {
		t.Run(name, func(t *testing.T) {
			candidate := bytes.Clone(valid)
			candidate[offset] ^= 1
			decoded, err := Decode(bytes.NewReader(candidate), DefaultLimits())
			if err != nil {
				t.Fatalf("root-only tamper should remain structurally decodable: %v", err)
			}
			if _, err := Apply(base, decoded, DefaultLimits()); err == nil {
				t.Fatal("root-tampered delta was applied")
			}
		})
	}
}

func TestBoundsAreEnforcedBeforeAllocationOrEmission(t *testing.T) {
	base := testBaseBundle(t)
	final := testFinalBundle(t)
	delta := mustCompute(t, base, final)
	encoded := encodeDelta(t, delta)

	limits := DefaultLimits()
	limits.MaxOperations = uint64(len(delta.Operations) - 1)
	if _, err := Compute(base, final, limits); err == nil {
		t.Fatal("Compute ignored operation bound")
	}
	if _, err := Decode(bytes.NewReader(encoded), limits); err == nil {
		t.Fatal("Decode ignored declared operation bound")
	}

	limits = DefaultLimits()
	limits.MaxDeltaBytes = uint64(len(encoded) - 1)
	if _, err := Decode(bytes.NewReader(encoded), limits); err == nil {
		t.Fatal("Decode ignored declared byte bound")
	}
	var output bytes.Buffer
	if err := Encode(&output, delta, limits); err == nil {
		t.Fatal("Encode ignored encoded byte bound")
	}

	limits = DefaultLimits()
	limits.MaxEntryBytes = uint64(^uint(0) >> 1)
	if _, err := Decode(bytes.NewReader(encoded), limits); err == nil {
		t.Fatal("Decode accepted MaxEntryBytes equal to MaxInt")
	}

	limits = DefaultLimits()
	limits.MaxDeltaBytes = uint64(^uint64(0)>>1) + 1
	if _, err := Decode(bytes.NewReader(encoded), limits); err == nil {
		t.Fatal("Decode accepted MaxDeltaBytes above MaxInt64")
	}
}

func TestSymlinkTargetsMustBeCanonicalAndComponentBounded(t *testing.T) {
	base := testBundle(t)
	root := base.TreeRoot
	cases := map[string][]Operation{
		"noncanonical": {{Kind: OpAdd, Path: "link", Final: symlinkEntry("link", "dir/../target")}},
		"too long":     {{Kind: OpAdd, Path: "link", Final: symlinkEntry("link", strings.Repeat("a", int(DefaultLimits().MaxPathBytes)+1))}},
		"long component": {
			{Kind: OpAdd, Path: "link", Final: symlinkEntry("link", strings.Repeat("a", 256))},
		},
		"composed escape": {
			{Kind: OpAdd, Path: "s", Final: symlinkEntry("s", ".")},
			{Kind: OpAdd, Path: "trigger", Final: symlinkEntry("trigger", "s/../outside")},
		},
	}
	for name, operations := range cases {
		t.Run(name, func(t *testing.T) {
			delta := Delta{Schema: Schema, BaseRoot: root, FinalRoot: root, Operations: operations}
			if _, err := Apply(base, delta, DefaultLimits()); err == nil {
				t.Fatal("unsafe symbolic-link target was accepted")
			}
			if err := Encode(io.Discard, delta, DefaultLimits()); err == nil {
				t.Fatal("unsafe symbolic-link target was encoded")
			}
		})
	}
}

func TestCanonicalParentSymlinkTargetRoundTrips(t *testing.T) {
	base := testBundle(t)
	final := testBundle(t,
		directoryEntry("dir"),
		symlinkEntry("dir/link", "../target"),
		fileEntry("target", 0o644, []byte("target\n")),
	)
	delta := mustCompute(t, base, final)
	decoded, err := Decode(bytes.NewReader(encodeDelta(t, delta)), DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	applied, err := Apply(base, decoded, DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	if applied.TreeRoot != final.TreeRoot {
		t.Fatalf("applied root = %s, want %s", applied.TreeRoot, final.TreeRoot)
	}
}

func TestDecodeRejectsLargeDeclarationsBeforePayloadAllocation(t *testing.T) {
	empty := testBundle(t)
	header := bytes.Clone(encodeDelta(t, mustCompute(t, empty, empty))[:headerSize])

	t.Run("count cannot fit body", func(t *testing.T) {
		candidate := bytes.Clone(header)
		binary.BigEndian.PutUint64(candidate[16:24], 1)
		if _, err := Decode(bytes.NewReader(candidate), DefaultLimits()); err == nil {
			t.Fatal("operation count impossible for body was accepted")
		}
	})

	t.Run("record exceeds remaining body", func(t *testing.T) {
		const bodySize = minimumOperationSize
		candidate := declaredDeltaPrefix(header, 1, 1, bodySize)
		operation := make([]byte, operationHeaderSize)
		operation[0] = byte(OpAdd)
		operation[1] = byte(repobundle.EntryFile)
		binary.BigEndian.PutUint32(operation[4:8], 0o644)
		binary.BigEndian.PutUint32(operation[8:12], 1)
		binary.BigEndian.PutUint64(operation[16:24], 1)
		binary.BigEndian.PutUint64(operation[56:64], minimumOperationSize+encodedAlignment)
		candidate = append(candidate, operation...)
		if _, err := Decode(bytes.NewReader(candidate), DefaultLimits()); err == nil {
			t.Fatal("operation larger than remaining body was accepted")
		}
	})

	t.Run("data exceeds declared remaining content", func(t *testing.T) {
		const bodySize = minimumOperationSize + encodedAlignment
		candidate := declaredDeltaPrefix(header, 1, 0, bodySize)
		operation := make([]byte, operationHeaderSize)
		operation[0] = byte(OpAdd)
		operation[1] = byte(repobundle.EntryFile)
		binary.BigEndian.PutUint32(operation[4:8], 0o644)
		binary.BigEndian.PutUint32(operation[8:12], 1)
		binary.BigEndian.PutUint64(operation[16:24], 1)
		binary.BigEndian.PutUint64(operation[56:64], bodySize)
		candidate = append(candidate, operation...)
		if _, err := Decode(bytes.NewReader(candidate), DefaultLimits()); err == nil {
			t.Fatal("operation exceeding declared content was accepted")
		}
	})

	const largeData = 64 << 20
	largeRecord := uint64(operationHeaderSize+encodedAlignment) + largeData
	t.Run("truncated large file declaration", func(t *testing.T) {
		candidate := declaredDeltaPrefix(header, 1, largeData, largeRecord)
		operation := make([]byte, operationHeaderSize)
		operation[0] = byte(OpAdd)
		operation[1] = byte(repobundle.EntryFile)
		binary.BigEndian.PutUint32(operation[4:8], 0o644)
		binary.BigEndian.PutUint32(operation[8:12], 1)
		binary.BigEndian.PutUint64(operation[16:24], largeData)
		binary.BigEndian.PutUint64(operation[56:64], largeRecord)
		candidate = append(candidate, operation...)
		candidate = append(candidate, 'x')
		candidate = append(candidate, make([]byte, encodedAlignment-1)...)
		if _, err := Decode(bytes.NewReader(candidate), DefaultLimits()); err == nil {
			t.Fatal("truncated large content declaration was accepted")
		}
	})

	t.Run("oversized symlink target", func(t *testing.T) {
		length := uint64(DefaultLimits().MaxPathBytes) + 1
		record := uint64(operationHeaderSize+encodedAlignment) + length + paddingFor(length)
		candidate := declaredDeltaPrefix(header, 1, length, record)
		operation := make([]byte, operationHeaderSize)
		operation[0] = byte(OpAdd)
		operation[1] = byte(repobundle.EntrySymlink)
		binary.BigEndian.PutUint32(operation[4:8], 0o777)
		binary.BigEndian.PutUint32(operation[8:12], 1)
		binary.BigEndian.PutUint64(operation[16:24], length)
		binary.BigEndian.PutUint64(operation[56:64], record)
		candidate = append(candidate, operation...)
		if _, err := Decode(bytes.NewReader(candidate), DefaultLimits()); err == nil {
			t.Fatal("oversized symlink target declaration was accepted")
		}
	})

	for name, configure := range map[string]func([]byte){
		"unknown kind": func(operation []byte) {
			operation[0] = 99
		},
		"invalid mode": func(operation []byte) {
			operation[0] = byte(OpAdd)
			operation[1] = byte(repobundle.EntryFile)
			binary.BigEndian.PutUint32(operation[4:8], 0o666)
		},
		"delete with data": func(operation []byte) {
			operation[0] = byte(OpDelete)
		},
	} {
		t.Run(name+" before large allocation", func(t *testing.T) {
			candidate := declaredDeltaPrefix(header, 1, largeData, largeRecord)
			operation := make([]byte, operationHeaderSize)
			configure(operation)
			binary.BigEndian.PutUint32(operation[8:12], 1)
			binary.BigEndian.PutUint64(operation[16:24], largeData)
			binary.BigEndian.PutUint64(operation[56:64], largeRecord)
			candidate = append(candidate, operation...)
			if _, err := Decode(bytes.NewReader(candidate), DefaultLimits()); err == nil {
				t.Fatal("invalid large operation declaration was accepted")
			}
		})
	}
}

func testBaseBundle(t *testing.T) repobundle.Bundle {
	t.Helper()
	return testBundle(t,
		directoryEntry("bin"),
		fileEntry("bin/tool", 0o644, []byte("#!/bin/sh\n")),
		fileEntry("data.bin", 0o644, []byte{0, 1, 0, 2}),
		fileEntry("delete.txt", 0o644, []byte("remove me\n")),
		directoryEntry("docs"),
		fileEntry("docs/readme", 0o644, []byte("old text\n")),
		fileEntry("kind", 0o644, []byte("ordinary file\n")),
		symlinkEntry("link", "docs/readme"),
		fileEntry("unchanged", 0o644, []byte("same\n")),
	)
}

func testFinalBundle(t *testing.T) repobundle.Bundle {
	t.Helper()
	return testBundle(t,
		fileEntry("added.bin", 0o644, []byte{0, 1, 2, 0xff}),
		directoryEntry("bin"),
		fileEntry("bin/tool", 0o755, []byte("#!/bin/sh\n")),
		fileEntry("data.bin", 0o644, []byte{0, 9, 0, 8, 0xff}),
		directoryEntry("docs"),
		fileEntry("docs/guide", 0o644, []byte("new guide\n")),
		fileEntry("docs/readme", 0o644, []byte("new text\n")),
		symlinkEntry("kind", "docs/readme"),
		symlinkEntry("link", "docs/guide"),
		fileEntry("unchanged", 0o644, []byte("same\n")),
	)
}

func testBundle(t *testing.T, entries ...repobundle.Entry) repobundle.Bundle {
	t.Helper()
	bundle, err := repobundle.FromEntries(repobundle.SortedEntries(entries), repobundle.DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	return bundle
}

func directoryEntry(entryPath string) repobundle.Entry {
	return repobundle.Entry{Path: entryPath, Type: repobundle.EntryDirectory, Mode: 0o755}
}

func fileEntry(entryPath string, mode uint32, data []byte) repobundle.Entry {
	digest := sha256.Sum256(data)
	return repobundle.Entry{Path: entryPath, Type: repobundle.EntryFile, Mode: mode, Data: bytes.Clone(data), SHA256: repobundle.Digest(digest)}
}

func symlinkEntry(entryPath, target string) repobundle.Entry {
	digest := sha256.Sum256([]byte(target))
	return repobundle.Entry{Path: entryPath, Type: repobundle.EntrySymlink, Mode: 0o777, Data: []byte(target), SHA256: repobundle.Digest(digest)}
}

func mustCompute(t *testing.T, base, final repobundle.Bundle) Delta {
	t.Helper()
	delta, err := Compute(base, final, DefaultLimits())
	if err != nil {
		t.Fatal(err)
	}
	return delta
}

func encodeDelta(t *testing.T, delta Delta) []byte {
	t.Helper()
	var encoded bytes.Buffer
	if err := Encode(&encoded, delta, DefaultLimits()); err != nil {
		t.Fatal(err)
	}
	return encoded.Bytes()
}

func operationProjection(operations []Operation) []string {
	result := make([]string, 0, len(operations))
	for _, operation := range operations {
		kind := map[OpKind]string{OpAdd: "add", OpDelete: "delete", OpModify: "modify"}[operation.Kind]
		result = append(result, kind+":"+operation.Path)
	}
	return result
}

func operationOffsets(t *testing.T, encoded []byte) []int {
	t.Helper()
	count := binary.BigEndian.Uint64(encoded[16:24])
	offsets := make([]int, 0, int(count))
	offset := headerSize
	for index := uint64(0); index < count; index++ {
		if offset+operationHeaderSize > len(encoded) {
			t.Fatalf("operation %d header exceeds fixture", index)
		}
		offsets = append(offsets, offset)
		recordSize := binary.BigEndian.Uint64(encoded[offset+56 : offset+64])
		offset += int(recordSize)
	}
	if offset != len(encoded) {
		t.Fatalf("operation records end at %d, fixture length is %d", offset, len(encoded))
	}
	return offsets
}

func rewriteBodyHash(encoded []byte) {
	digest := sha256.Sum256(encoded[headerSize:])
	copy(encoded[104:136], digest[:])
}

func declaredDeltaPrefix(header []byte, operations, contentBytes, bodySize uint64) []byte {
	result := bytes.Clone(header)
	binary.BigEndian.PutUint64(result[16:24], operations)
	binary.BigEndian.PutUint64(result[24:32], contentBytes)
	binary.BigEndian.PutUint64(result[32:40], uint64(headerSize)+bodySize)
	return result
}

func cloneDelta(delta Delta) Delta {
	result := Delta{Schema: delta.Schema, BaseRoot: delta.BaseRoot, FinalRoot: delta.FinalRoot, Operations: make([]Operation, len(delta.Operations))}
	for index, operation := range delta.Operations {
		result.Operations[index] = cloneOperation(operation)
	}
	return result
}
