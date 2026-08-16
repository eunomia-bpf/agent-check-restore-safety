// Package repodelta defines a canonical, bounded change set between two
// canonical repobundle repository trees.
package repodelta

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"path"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repobundle"
)

const (
	// Schema is the only delta encoding schema accepted by this package.
	Schema uint32 = 1

	headerSize          = 160
	operationHeaderSize = 96
	encodedAlignment    = 8
	// Every operation has a nonempty path, so even the shortest record has
	// one full alignment unit after its fixed header.
	minimumOperationSize = operationHeaderSize + encodedAlignment
)

var deltaMagic = [8]byte{'S', 'C', 'R', 'D', 'L', 'T', 'A', '1'}

// Limits bounds every allocation made while encoding, decoding, computing,
// or applying a delta.
type Limits struct {
	MaxOperations   uint64
	MaxTreeEntries  uint64
	MaxPathBytes    uint32
	MaxEntryBytes   uint64
	MaxContentBytes uint64
	MaxDeltaBytes   uint64
}

// DefaultLimits returns conservative limits suitable for repository deltas.
func DefaultLimits() Limits {
	return Limits{
		MaxOperations:   100_000,
		MaxTreeEntries:  100_000,
		MaxPathBytes:    4 << 10,
		MaxEntryBytes:   256 << 20,
		MaxContentBytes: 1 << 30,
		MaxDeltaBytes:   2 << 30,
	}
}

// OpKind identifies how an operation changes the entry at Path.
type OpKind uint8

const (
	OpAdd    OpKind = 1
	OpDelete OpKind = 2
	OpModify OpKind = 3
)

// Operation changes one repository path. Add and Modify carry the complete
// final canonical entry, including file bytes or a symbolic-link target.
// Delete requires Final to be the zero value.
type Operation struct {
	Kind  OpKind
	Path  string
	Final repobundle.Entry
}

// Delta binds a strictly path-sorted operation sequence to its exact base and
// final repository tree roots.
type Delta struct {
	Schema     uint32
	BaseRoot   repobundle.Digest
	FinalRoot  repobundle.Digest
	Operations []Operation
}

// Compute returns the sole path-sorted delta between two canonical bundles.
func Compute(base, final repobundle.Bundle, limits Limits) (Delta, error) {
	if err := validateLimits(limits); err != nil {
		return Delta{}, err
	}
	canonicalBase, err := requireCanonicalBundle(base, limits, "base")
	if err != nil {
		return Delta{}, err
	}
	canonicalFinal, err := requireCanonicalBundle(final, limits, "final")
	if err != nil {
		return Delta{}, err
	}

	operations := make([]Operation, 0)
	baseIndex, finalIndex := 0, 0
	for baseIndex < len(canonicalBase.Entries) || finalIndex < len(canonicalFinal.Entries) {
		switch {
		case baseIndex == len(canonicalBase.Entries):
			entry := cloneEntry(canonicalFinal.Entries[finalIndex])
			operations = append(operations, Operation{Kind: OpAdd, Path: entry.Path, Final: entry})
			finalIndex++
		case finalIndex == len(canonicalFinal.Entries):
			operations = append(operations, Operation{Kind: OpDelete, Path: canonicalBase.Entries[baseIndex].Path})
			baseIndex++
		default:
			baseEntry := canonicalBase.Entries[baseIndex]
			finalEntry := canonicalFinal.Entries[finalIndex]
			switch {
			case baseEntry.Path < finalEntry.Path:
				operations = append(operations, Operation{Kind: OpDelete, Path: baseEntry.Path})
				baseIndex++
			case finalEntry.Path < baseEntry.Path:
				entry := cloneEntry(finalEntry)
				operations = append(operations, Operation{Kind: OpAdd, Path: entry.Path, Final: entry})
				finalIndex++
			default:
				if !entriesEqual(baseEntry, finalEntry) {
					entry := cloneEntry(finalEntry)
					operations = append(operations, Operation{Kind: OpModify, Path: entry.Path, Final: entry})
				}
				baseIndex++
				finalIndex++
			}
		}
		if uint64(len(operations)) > limits.MaxOperations {
			return Delta{}, fmt.Errorf("repository delta has more than %d operations", limits.MaxOperations)
		}
	}

	delta := Delta{
		Schema:     Schema,
		BaseRoot:   canonicalBase.TreeRoot,
		FinalRoot:  canonicalFinal.TreeRoot,
		Operations: operations,
	}
	if err := checkDelta(delta, limits); err != nil {
		return Delta{}, err
	}
	return delta, nil
}

// Apply verifies delta against base, applies every operation, and returns the
// exact canonical final bundle committed by delta.FinalRoot.
func Apply(base repobundle.Bundle, delta Delta, limits Limits) (repobundle.Bundle, error) {
	if err := validateLimits(limits); err != nil {
		return repobundle.Bundle{}, err
	}
	canonicalBase, err := requireCanonicalBundle(base, limits, "base")
	if err != nil {
		return repobundle.Bundle{}, err
	}
	if err := checkDelta(delta, limits); err != nil {
		return repobundle.Bundle{}, err
	}
	if canonicalBase.TreeRoot != delta.BaseRoot {
		return repobundle.Bundle{}, fmt.Errorf("repository delta base root %s does not match bundle root %s", delta.BaseRoot, canonicalBase.TreeRoot)
	}

	entries := make(map[string]repobundle.Entry, len(canonicalBase.Entries))
	for _, entry := range canonicalBase.Entries {
		entries[entry.Path] = entry
	}
	for index, operation := range delta.Operations {
		_, exists := entries[operation.Path]
		switch operation.Kind {
		case OpAdd:
			if exists {
				return repobundle.Bundle{}, fmt.Errorf("repository delta operation %d adds existing path %q", index, operation.Path)
			}
			entries[operation.Path] = operation.Final
		case OpDelete:
			if !exists {
				return repobundle.Bundle{}, fmt.Errorf("repository delta operation %d deletes missing path %q", index, operation.Path)
			}
			delete(entries, operation.Path)
		case OpModify:
			if !exists {
				return repobundle.Bundle{}, fmt.Errorf("repository delta operation %d modifies missing path %q", index, operation.Path)
			}
			if entriesEqual(entries[operation.Path], operation.Final) {
				return repobundle.Bundle{}, fmt.Errorf("repository delta operation %d is a no-op modification of %q", index, operation.Path)
			}
			entries[operation.Path] = operation.Final
		default:
			return repobundle.Bundle{}, fmt.Errorf("repository delta operation %d has unknown kind %d", index, operation.Kind)
		}
	}

	paths := make([]string, 0, len(entries))
	for entryPath := range entries {
		paths = append(paths, entryPath)
	}
	sort.Strings(paths)
	finalEntries := make([]repobundle.Entry, 0, len(paths))
	for _, entryPath := range paths {
		finalEntries = append(finalEntries, entries[entryPath])
	}
	final, err := repobundle.FromEntries(finalEntries, repositoryLimits(limits))
	if err != nil {
		return repobundle.Bundle{}, fmt.Errorf("apply repository delta: final tree is invalid: %w", err)
	}
	if final.TreeRoot != delta.FinalRoot {
		return repobundle.Bundle{}, fmt.Errorf("applied repository tree root %s does not match delta final root %s", final.TreeRoot, delta.FinalRoot)
	}
	return final, nil
}

// Encode writes the sole canonical binary representation of delta.
func Encode(writer io.Writer, delta Delta, limits Limits) error {
	if writer == nil {
		return errors.New("repository delta writer is nil")
	}
	if err := validateLimits(limits); err != nil {
		return err
	}
	canonical := cloneDeltaValue(delta)
	if err := checkDelta(canonical, limits); err != nil {
		return err
	}
	bodySize, err := encodedBodySize(canonical.Operations)
	if err != nil {
		return err
	}
	if bodySize > ^uint64(0)-headerSize {
		return errors.New("repository delta encoded size overflows uint64")
	}
	totalSize := uint64(headerSize) + bodySize
	if totalSize > limits.MaxDeltaBytes {
		return fmt.Errorf("encoded repository delta is %d bytes, limit is %d", totalSize, limits.MaxDeltaBytes)
	}
	contentBytes, err := operationContentBytes(canonical.Operations, limits.MaxContentBytes)
	if err != nil {
		return err
	}
	bodyDigest := sha256.New()
	if err := encodeOperations(bodyDigest, canonical.Operations); err != nil {
		return fmt.Errorf("hash repository delta body: %w", err)
	}

	header := make([]byte, headerSize)
	copy(header[0:8], deltaMagic[:])
	binary.BigEndian.PutUint32(header[8:12], Schema)
	binary.BigEndian.PutUint32(header[12:16], headerSize)
	binary.BigEndian.PutUint64(header[16:24], uint64(len(canonical.Operations)))
	binary.BigEndian.PutUint64(header[24:32], contentBytes)
	binary.BigEndian.PutUint64(header[32:40], totalSize)
	copy(header[40:72], canonical.BaseRoot[:])
	copy(header[72:104], canonical.FinalRoot[:])
	copy(header[104:136], bodyDigest.Sum(nil))
	if err := writeFull(writer, header); err != nil {
		return fmt.Errorf("write repository delta header: %w", err)
	}
	if err := encodeOperations(writer, canonical.Operations); err != nil {
		return fmt.Errorf("write repository delta body: %w", err)
	}
	return nil
}

// Decode reads one complete canonical delta and rejects trailing bytes.
func Decode(reader io.Reader, limits Limits) (Delta, error) {
	if reader == nil {
		return Delta{}, errors.New("repository delta reader is nil")
	}
	if err := validateLimits(limits); err != nil {
		return Delta{}, err
	}
	header := make([]byte, headerSize)
	if _, err := io.ReadFull(reader, header); err != nil {
		return Delta{}, fmt.Errorf("read repository delta header: %w", err)
	}
	if !bytes.Equal(header[0:8], deltaMagic[:]) || binary.BigEndian.Uint32(header[8:12]) != Schema || binary.BigEndian.Uint32(header[12:16]) != headerSize {
		return Delta{}, errors.New("repository delta has an invalid magic, schema, or header size")
	}
	if !allZero(header[136:]) {
		return Delta{}, errors.New("repository delta header reserved bytes are nonzero")
	}
	operationCount := binary.BigEndian.Uint64(header[16:24])
	contentBytes := binary.BigEndian.Uint64(header[24:32])
	totalSize := binary.BigEndian.Uint64(header[32:40])
	if operationCount > limits.MaxOperations {
		return Delta{}, fmt.Errorf("repository delta declares %d operations, limit is %d", operationCount, limits.MaxOperations)
	}
	if contentBytes > limits.MaxContentBytes {
		return Delta{}, fmt.Errorf("repository delta declares %d content bytes, limit is %d", contentBytes, limits.MaxContentBytes)
	}
	if totalSize < headerSize || totalSize > limits.MaxDeltaBytes {
		return Delta{}, fmt.Errorf("repository delta declares invalid total size %d", totalSize)
	}
	bodySize := totalSize - headerSize
	if operationCount > bodySize/minimumOperationSize {
		return Delta{}, fmt.Errorf("repository delta declares %d operations in a %d-byte body", operationCount, bodySize)
	}
	if contentBytes > bodySize {
		return Delta{}, fmt.Errorf("repository delta declares %d content bytes in a %d-byte body", contentBytes, bodySize)
	}
	var baseRoot, finalRoot, expectedBody repobundle.Digest
	copy(baseRoot[:], header[40:72])
	copy(finalRoot[:], header[72:104])
	copy(expectedBody[:], header[104:136])

	body := &io.LimitedReader{R: reader, N: int64(bodySize)}
	bodyHash := sha256.New()
	teed := io.TeeReader(body, bodyHash)
	// Do not preallocate from an attacker-controlled declaration. Appending
	// only after a complete record is read keeps a short input short-lived.
	var operations []Operation
	var decodedContent uint64
	for index := uint64(0); index < operationCount; index++ {
		operation, err := decodeOperation(teed, limits, uint64(body.N), contentBytes-decodedContent)
		if err != nil {
			return Delta{}, fmt.Errorf("decode repository delta operation %d: %w", index, err)
		}
		if uint64(len(operation.Final.Data)) > limits.MaxContentBytes-decodedContent {
			return Delta{}, fmt.Errorf("repository delta content exceeds %d bytes", limits.MaxContentBytes)
		}
		decodedContent += uint64(len(operation.Final.Data))
		operations = append(operations, operation)
	}
	if body.N != 0 {
		return Delta{}, fmt.Errorf("repository delta body contains %d undeclared bytes", body.N)
	}
	var actualBody repobundle.Digest
	copy(actualBody[:], bodyHash.Sum(nil))
	if actualBody != expectedBody {
		return Delta{}, errors.New("repository delta body SHA-256 does not match its header")
	}
	if decodedContent != contentBytes {
		return Delta{}, fmt.Errorf("repository delta decoded %d content bytes, header declares %d", decodedContent, contentBytes)
	}
	if err := requireEOF(reader); err != nil {
		return Delta{}, err
	}
	delta := Delta{Schema: Schema, BaseRoot: baseRoot, FinalRoot: finalRoot, Operations: operations}
	if err := checkDelta(delta, limits); err != nil {
		return Delta{}, err
	}
	return delta, nil
}

func requireCanonicalBundle(bundle repobundle.Bundle, limits Limits, label string) (repobundle.Bundle, error) {
	if err := repobundle.Validate(bundle, repositoryLimits(limits)); err != nil {
		return repobundle.Bundle{}, fmt.Errorf("repository delta %s bundle is invalid: %w", label, err)
	}
	return bundle, nil
}

func checkDelta(delta Delta, limits Limits) error {
	if delta.Schema != Schema {
		return fmt.Errorf("repository delta schema is %d, require %d", delta.Schema, Schema)
	}
	if delta.BaseRoot == (repobundle.Digest{}) || delta.FinalRoot == (repobundle.Digest{}) {
		return errors.New("repository delta roots must be nonzero")
	}
	if uint64(len(delta.Operations)) > limits.MaxOperations {
		return fmt.Errorf("repository delta has %d operations, limit is %d", len(delta.Operations), limits.MaxOperations)
	}
	if len(delta.Operations) == 0 && delta.BaseRoot != delta.FinalRoot {
		return errors.New("empty repository delta must have identical base and final roots")
	}
	var contentBytes uint64
	for index, operation := range delta.Operations {
		if err := validateRepositoryPath(operation.Path, limits.MaxPathBytes); err != nil {
			return fmt.Errorf("invalid repository delta operation %d: %w", index, err)
		}
		if index > 0 && delta.Operations[index-1].Path >= operation.Path {
			return fmt.Errorf("repository delta operations are not strictly path-sorted at %q", operation.Path)
		}
		switch operation.Kind {
		case OpDelete:
			if !zeroEntry(operation.Final) {
				return fmt.Errorf("repository delta delete %q carries a final entry", operation.Path)
			}
		case OpAdd, OpModify:
			if operation.Final.Path != operation.Path {
				return fmt.Errorf("repository delta operation %q final entry path is %q", operation.Path, operation.Final.Path)
			}
			if err := validateFinalEntry(operation.Final, limits); err != nil {
				return fmt.Errorf("repository delta operation %q has invalid final entry: %w", operation.Path, err)
			}
			if uint64(len(operation.Final.Data)) > limits.MaxContentBytes-contentBytes {
				return fmt.Errorf("repository delta content exceeds %d bytes", limits.MaxContentBytes)
			}
			contentBytes += uint64(len(operation.Final.Data))
		default:
			return fmt.Errorf("repository delta operation %q has unknown kind %d", operation.Path, operation.Kind)
		}
	}
	return nil
}

func validateFinalEntry(entry repobundle.Entry, limits Limits) error {
	if err := validateRepositoryPath(entry.Path, limits.MaxPathBytes); err != nil {
		return err
	}
	if uint64(len(entry.Data)) > limits.MaxEntryBytes {
		return fmt.Errorf("entry %q has %d bytes, limit is %d", entry.Path, len(entry.Data), limits.MaxEntryBytes)
	}
	switch entry.Type {
	case repobundle.EntryDirectory:
		if entry.Mode != 0o755 || len(entry.Data) != 0 || entry.SHA256 != (repobundle.Digest{}) {
			return fmt.Errorf("directory %q must have mode 0755 and no content", entry.Path)
		}
	case repobundle.EntryFile:
		if entry.Mode != 0o644 && entry.Mode != 0o755 {
			return fmt.Errorf("file %q mode is %04o, require 0644 or 0755", entry.Path, entry.Mode)
		}
		if repobundle.Digest(sha256.Sum256(entry.Data)) != entry.SHA256 {
			return fmt.Errorf("file %q content digest is incorrect", entry.Path)
		}
	case repobundle.EntrySymlink:
		if entry.Mode != 0o777 {
			return fmt.Errorf("symbolic link %q mode is %04o, require 0777", entry.Path, entry.Mode)
		}
		if repobundle.Digest(sha256.Sum256(entry.Data)) != entry.SHA256 {
			return fmt.Errorf("symbolic link %q target digest is incorrect", entry.Path)
		}
		if err := validateSymlinkTarget(entry.Path, string(entry.Data), limits.MaxPathBytes); err != nil {
			return err
		}
	default:
		return fmt.Errorf("entry %q has unknown type %d", entry.Path, entry.Type)
	}
	return nil
}

func validateRepositoryPath(value string, maxBytes uint32) error {
	if value == "" || uint64(len(value)) > uint64(maxBytes) || !utf8.ValidString(value) || strings.IndexByte(value, 0) >= 0 || strings.Contains(value, "\\") || strings.IndexFunc(value, unicode.IsControl) >= 0 {
		return fmt.Errorf("repository path %q is empty, too long, invalid UTF-8, or contains a forbidden character", value)
	}
	if path.IsAbs(value) || path.Clean(value) != value || value == "." {
		return fmt.Errorf("repository path %q is not canonical and relative", value)
	}
	for _, component := range strings.Split(value, "/") {
		if component == "" || component == "." || component == ".." || strings.EqualFold(component, ".git") || len(component) > 255 {
			return fmt.Errorf("repository path %q contains a forbidden component", value)
		}
	}
	return nil
}

func validateSymlinkTarget(linkPath, target string, maxBytes uint32) error {
	if target == "" || uint64(len(target)) > uint64(maxBytes) || !utf8.ValidString(target) || strings.IndexByte(target, 0) >= 0 || strings.Contains(target, "\\") || strings.IndexFunc(target, unicode.IsControl) >= 0 || path.IsAbs(target) || path.Clean(target) != target {
		return fmt.Errorf("symbolic link %q has an invalid target", linkPath)
	}
	for _, component := range strings.Split(target, "/") {
		if component == "" || len(component) > 255 {
			return fmt.Errorf("symbolic link %q target contains a forbidden component", linkPath)
		}
	}
	resolved := path.Clean(path.Join(path.Dir(linkPath), target))
	if resolved == ".." || strings.HasPrefix(resolved, "../") || path.IsAbs(resolved) {
		return fmt.Errorf("symbolic link %q escapes the repository", linkPath)
	}
	if resolved != "." {
		for _, component := range strings.Split(resolved, "/") {
			if strings.EqualFold(component, ".git") {
				return fmt.Errorf("symbolic link %q targets forbidden .git state", linkPath)
			}
		}
	}
	return nil
}

func encodeOperations(writer io.Writer, operations []Operation) error {
	for _, operation := range operations {
		pathPadding := paddingFor(uint64(len(operation.Path)))
		dataPadding := paddingFor(uint64(len(operation.Final.Data)))
		recordSize := uint64(operationHeaderSize) + uint64(len(operation.Path)) + pathPadding + uint64(len(operation.Final.Data)) + dataPadding
		header := make([]byte, operationHeaderSize)
		header[0] = byte(operation.Kind)
		if operation.Kind != OpDelete {
			header[1] = byte(operation.Final.Type)
			binary.BigEndian.PutUint32(header[4:8], operation.Final.Mode)
			copy(header[24:56], operation.Final.SHA256[:])
		}
		binary.BigEndian.PutUint32(header[8:12], uint32(len(operation.Path)))
		binary.BigEndian.PutUint64(header[16:24], uint64(len(operation.Final.Data)))
		binary.BigEndian.PutUint64(header[56:64], recordSize)
		if err := writeFull(writer, header); err != nil {
			return err
		}
		if err := writeFull(writer, []byte(operation.Path)); err != nil {
			return err
		}
		if err := writeZeros(writer, pathPadding); err != nil {
			return err
		}
		if err := writeFull(writer, operation.Final.Data); err != nil {
			return err
		}
		if err := writeZeros(writer, dataPadding); err != nil {
			return err
		}
	}
	return nil
}

func decodeOperation(reader io.Reader, limits Limits, remainingBody, remainingContent uint64) (Operation, error) {
	header := make([]byte, operationHeaderSize)
	if _, err := io.ReadFull(reader, header); err != nil {
		return Operation{}, err
	}
	if !allZero(header[2:4]) || !allZero(header[12:16]) || !allZero(header[64:]) {
		return Operation{}, errors.New("operation reserved bytes are nonzero")
	}
	kind := OpKind(header[0])
	entryType := repobundle.EntryType(header[1])
	mode := binary.BigEndian.Uint32(header[4:8])
	pathLength := binary.BigEndian.Uint32(header[8:12])
	dataLength := binary.BigEndian.Uint64(header[16:24])
	recordSize := binary.BigEndian.Uint64(header[56:64])
	if pathLength == 0 || pathLength > limits.MaxPathBytes {
		return Operation{}, fmt.Errorf("operation path length %d is outside the allowed range", pathLength)
	}
	if dataLength > limits.MaxEntryBytes {
		return Operation{}, fmt.Errorf("operation data length %d exceeds %d", dataLength, limits.MaxEntryBytes)
	}
	if dataLength > remainingContent {
		return Operation{}, fmt.Errorf("operation data length %d exceeds %d declared remaining content bytes", dataLength, remainingContent)
	}
	expectedSize := uint64(operationHeaderSize) + uint64(pathLength) + paddingFor(uint64(pathLength)) + dataLength + paddingFor(dataLength)
	if recordSize != expectedSize {
		return Operation{}, fmt.Errorf("operation record size is %d, require %d", recordSize, expectedSize)
	}
	if recordSize > remainingBody {
		return Operation{}, fmt.Errorf("operation record size %d exceeds %d remaining body bytes", recordSize, remainingBody)
	}
	var digest repobundle.Digest
	copy(digest[:], header[24:56])
	switch kind {
	case OpDelete:
		if entryType != 0 || mode != 0 || dataLength != 0 || digest != (repobundle.Digest{}) {
			return Operation{}, errors.New("delete operation carries final entry metadata")
		}
	case OpAdd, OpModify:
		switch entryType {
		case repobundle.EntryDirectory:
			if mode != 0o755 || dataLength != 0 || digest != (repobundle.Digest{}) {
				return Operation{}, errors.New("directory operation has invalid mode, content length, or digest")
			}
		case repobundle.EntryFile:
			if mode != 0o644 && mode != 0o755 {
				return Operation{}, fmt.Errorf("file operation has invalid mode %04o", mode)
			}
		case repobundle.EntrySymlink:
			if mode != 0o777 {
				return Operation{}, fmt.Errorf("symbolic-link operation has invalid mode %04o", mode)
			}
			if dataLength == 0 || dataLength > uint64(limits.MaxPathBytes) {
				return Operation{}, fmt.Errorf("symbolic-link target length %d is outside the allowed range", dataLength)
			}
		default:
			return Operation{}, fmt.Errorf("operation has unknown final entry type %d", entryType)
		}
	default:
		return Operation{}, fmt.Errorf("operation has unknown kind %d", kind)
	}
	pathBytes := make([]byte, int(pathLength))
	if _, err := io.ReadFull(reader, pathBytes); err != nil {
		return Operation{}, err
	}
	if err := readZeroPadding(reader, paddingFor(uint64(pathLength))); err != nil {
		return Operation{}, err
	}
	data, err := readDeclaredBytes(reader, dataLength)
	if err != nil {
		return Operation{}, err
	}
	if err := readZeroPadding(reader, paddingFor(dataLength)); err != nil {
		return Operation{}, err
	}
	operation := Operation{Kind: kind, Path: string(pathBytes)}
	if kind == OpDelete {
		return operation, nil
	}
	operation.Final = repobundle.Entry{Path: operation.Path, Type: entryType, Mode: mode, Data: data, SHA256: digest}
	return operation, nil
}

func encodedBodySize(operations []Operation) (uint64, error) {
	var total uint64
	for _, operation := range operations {
		size := uint64(operationHeaderSize) + uint64(len(operation.Path)) + paddingFor(uint64(len(operation.Path))) + uint64(len(operation.Final.Data)) + paddingFor(uint64(len(operation.Final.Data)))
		if size > ^uint64(0)-total {
			return 0, errors.New("repository delta encoded size overflows uint64")
		}
		total += size
	}
	return total, nil
}

func operationContentBytes(operations []Operation, maximum uint64) (uint64, error) {
	var total uint64
	for _, operation := range operations {
		length := uint64(len(operation.Final.Data))
		if length > maximum-total {
			return 0, fmt.Errorf("repository delta content exceeds %d bytes", maximum)
		}
		total += length
	}
	return total, nil
}

func validateLimits(limits Limits) error {
	if limits.MaxOperations == 0 || limits.MaxTreeEntries == 0 || limits.MaxPathBytes == 0 || limits.MaxEntryBytes == 0 || limits.MaxContentBytes == 0 || limits.MaxDeltaBytes < headerSize {
		return errors.New("repository delta limits must all be positive and permit one header")
	}
	maxInt := uint64(^uint(0) >> 1)
	if limits.MaxOperations > maxInt || limits.MaxTreeEntries > maxInt || uint64(limits.MaxPathBytes) > maxInt || limits.MaxEntryBytes >= maxInt {
		return errors.New("repository delta allocation limit exceeds this platform's int range")
	}
	if limits.MaxDeltaBytes > uint64(^uint64(0)>>1) {
		return errors.New("repository delta byte limit exceeds int64 range")
	}
	return nil
}

func repositoryLimits(limits Limits) repobundle.Limits {
	return repobundle.Limits{
		MaxEntries:      limits.MaxTreeEntries,
		MaxPathBytes:    limits.MaxPathBytes,
		MaxFileBytes:    limits.MaxEntryBytes,
		MaxContentBytes: limits.MaxContentBytes,
		MaxBundleBytes:  limits.MaxDeltaBytes,
	}
}

func entriesEqual(left, right repobundle.Entry) bool {
	return left.Path == right.Path && left.Type == right.Type && left.Mode == right.Mode && left.SHA256 == right.SHA256 && bytes.Equal(left.Data, right.Data)
}

func cloneEntry(entry repobundle.Entry) repobundle.Entry {
	entry.Data = bytes.Clone(entry.Data)
	return entry
}

func cloneOperation(operation Operation) Operation {
	operation.Final = cloneEntry(operation.Final)
	return operation
}

func cloneDeltaValue(delta Delta) Delta {
	result := Delta{Schema: delta.Schema, BaseRoot: delta.BaseRoot, FinalRoot: delta.FinalRoot, Operations: make([]Operation, len(delta.Operations))}
	for index, operation := range delta.Operations {
		result.Operations[index] = cloneOperation(operation)
	}
	return result
}

func zeroEntry(entry repobundle.Entry) bool {
	return entry.Path == "" && entry.Type == 0 && entry.Mode == 0 && len(entry.Data) == 0 && entry.SHA256 == (repobundle.Digest{})
}

func paddingFor(length uint64) uint64 {
	return (encodedAlignment - length%encodedAlignment) % encodedAlignment
}

func writeFull(writer io.Writer, data []byte) error {
	for len(data) > 0 {
		written, err := writer.Write(data)
		if err != nil {
			return err
		}
		if written <= 0 || written > len(data) {
			return io.ErrShortWrite
		}
		data = data[written:]
	}
	return nil
}

func writeZeros(writer io.Writer, count uint64) error {
	if count == 0 {
		return nil
	}
	return writeFull(writer, make([]byte, int(count)))
}

func readZeroPadding(reader io.Reader, count uint64) error {
	if count == 0 {
		return nil
	}
	padding := make([]byte, int(count))
	if _, err := io.ReadFull(reader, padding); err != nil {
		return err
	}
	if !allZero(padding) {
		return errors.New("repository delta padding is nonzero")
	}
	return nil
}

// readDeclaredBytes grows with bytes actually observed instead of allocating
// an attacker-declared length before a truncated input has supplied it.
func readDeclaredBytes(reader io.Reader, length uint64) ([]byte, error) {
	if length == 0 {
		return nil, nil
	}
	const chunkSize = 32 << 10
	initial := length
	if initial > chunkSize {
		initial = chunkSize
	}
	data := make([]byte, 0, int(initial))
	buffer := make([]byte, int(initial))
	remaining := length
	for remaining > 0 {
		want := uint64(len(buffer))
		if want > remaining {
			want = remaining
		}
		n, err := io.ReadFull(reader, buffer[:int(want)])
		if n > 0 {
			data = append(data, buffer[:n]...)
			remaining -= uint64(n)
		}
		if err != nil {
			return nil, err
		}
	}
	return data, nil
}

func allZero(data []byte) bool {
	for _, value := range data {
		if value != 0 {
			return false
		}
	}
	return true
}

func requireEOF(reader io.Reader) error {
	var extra [1]byte
	n, err := reader.Read(extra[:])
	if n != 0 || err == nil {
		return errors.New("repository delta contains trailing bytes")
	}
	if !errors.Is(err, io.EOF) {
		return fmt.Errorf("check repository delta end: %w", err)
	}
	return nil
}
