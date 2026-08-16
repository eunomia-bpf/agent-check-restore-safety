// Package repobundle defines the canonical, self-checking repository image
// exchanged between a host and an untrusted execution sandbox.
package repobundle

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"path"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"
)

const (
	Schema               uint32 = 2
	headerSize                  = 128
	entryHeaderSize             = 96
	encodedAlignment            = 8
	blockDeviceAlignment        = 512

	EntryDirectory EntryType = 1
	EntryFile      EntryType = 2
	EntrySymlink   EntryType = 3
)

var (
	bundleMagic = [8]byte{'S', 'C', 'R', 'B', 'N', 'D', 'L', '2'}
	treeDomain  = []byte("safe-change-repository-tree-v1\x00")
)

// Limits bounds all allocations made while scanning or decoding a bundle.
type Limits struct {
	MaxEntries      uint64
	MaxPathBytes    uint32
	MaxFileBytes    uint64
	MaxContentBytes uint64
	MaxBundleBytes  uint64
}

func DefaultLimits() Limits {
	return Limits{
		MaxEntries:      100_000,
		MaxPathBytes:    4 << 10,
		MaxFileBytes:    256 << 20,
		MaxContentBytes: 1 << 30,
		MaxBundleBytes:  2 << 30,
	}
}

type EntryType uint8
type Digest [sha256.Size]byte

func (digest Digest) String() string { return hex.EncodeToString(digest[:]) }

// Entry is one canonical object below the repository root. Data contains file
// bytes or the UTF-8, slash-separated target of a symbolic link. Directories
// have no data. Mode is normalized to 0755 for directories, 0644 or 0755 for
// files, and 0777 for symbolic links.
type Entry struct {
	Path   string
	Type   EntryType
	Mode   uint32
	Data   []byte
	SHA256 Digest
}

type Bundle struct {
	Schema       uint32
	Entries      []Entry
	TreeRoot     Digest
	ContentBytes uint64
}

// FromEntries validates and clones a complete path-sorted repository tree.
func FromEntries(entries []Entry, limits Limits) (Bundle, error) {
	return bundleFromEntries(entries, limits, true)
}

func bundleFromOwnedEntries(entries []Entry, limits Limits) (Bundle, error) {
	return bundleFromEntries(entries, limits, false)
}

func bundleFromEntries(entries []Entry, limits Limits, clone bool) (Bundle, error) {
	if err := validateLimits(limits); err != nil {
		return Bundle{}, err
	}
	if uint64(len(entries)) > limits.MaxEntries {
		return Bundle{}, fmt.Errorf("repository has %d entries, limit is %d", len(entries), limits.MaxEntries)
	}
	canonical := entries
	if clone {
		canonical = make([]Entry, len(entries))
	}
	var contentBytes uint64
	for index, entry := range entries {
		canonical[index] = entry
		if clone {
			canonical[index].Data = bytes.Clone(entry.Data)
		}
		if entry.Type == EntryFile || entry.Type == EntrySymlink {
			if uint64(len(entry.Data)) > limits.MaxFileBytes {
				return Bundle{}, fmt.Errorf("repository entry %q has %d content bytes, per-entry limit is %d", entry.Path, len(entry.Data), limits.MaxFileBytes)
			}
			if uint64(len(entry.Data)) > limits.MaxContentBytes-contentBytes {
				return Bundle{}, fmt.Errorf("repository content exceeds %d bytes", limits.MaxContentBytes)
			}
			contentBytes += uint64(len(entry.Data))
			canonical[index].SHA256 = Digest(sha256.Sum256(entry.Data))
		} else {
			canonical[index].SHA256 = Digest{}
		}
	}
	if err := validateEntries(canonical, limits.MaxPathBytes); err != nil {
		return Bundle{}, err
	}
	root := treeRoot(canonical)
	return Bundle{Schema: Schema, Entries: canonical, TreeRoot: root, ContentBytes: contentBytes}, nil
}

// Validate checks a complete canonical bundle without cloning its content.
// Callers must not mutate bundle concurrently with validation.
func Validate(bundle Bundle, limits Limits) error {
	if err := validateLimits(limits); err != nil {
		return err
	}
	if bundle.Schema != Schema {
		return fmt.Errorf("repository bundle schema is %d, require %d", bundle.Schema, Schema)
	}
	if uint64(len(bundle.Entries)) > limits.MaxEntries {
		return fmt.Errorf("repository has %d entries, limit is %d", len(bundle.Entries), limits.MaxEntries)
	}
	var contentBytes uint64
	for _, entry := range bundle.Entries {
		if entry.Type != EntryFile && entry.Type != EntrySymlink {
			continue
		}
		if uint64(len(entry.Data)) > limits.MaxFileBytes {
			return fmt.Errorf("repository entry %q has %d content bytes, per-entry limit is %d", entry.Path, len(entry.Data), limits.MaxFileBytes)
		}
		if uint64(len(entry.Data)) > limits.MaxContentBytes-contentBytes {
			return fmt.Errorf("repository content exceeds %d bytes", limits.MaxContentBytes)
		}
		contentBytes += uint64(len(entry.Data))
	}
	if err := validateEntries(bundle.Entries, limits.MaxPathBytes); err != nil {
		return err
	}
	if bundle.ContentBytes != contentBytes {
		return errors.New("repository bundle supplied content size does not match its entries")
	}
	if bundle.TreeRoot != treeRoot(bundle.Entries) {
		return errors.New("repository bundle supplied tree root does not match its entries")
	}
	return nil
}

// Encode writes the sole canonical representation of bundle.
func Encode(writer io.Writer, bundle Bundle, limits Limits) error {
	if writer == nil {
		return errors.New("repository bundle writer is nil")
	}
	canonical, err := FromEntries(bundle.Entries, limits)
	if err != nil {
		return err
	}
	if bundle.Schema != 0 && bundle.Schema != Schema {
		return fmt.Errorf("repository bundle schema is %d, require %d", bundle.Schema, Schema)
	}
	if bundle.TreeRoot != (Digest{}) && bundle.TreeRoot != canonical.TreeRoot {
		return errors.New("repository bundle supplied tree root does not match its entries")
	}
	if bundle.ContentBytes != 0 && bundle.ContentBytes != canonical.ContentBytes {
		return errors.New("repository bundle supplied content size does not match its entries")
	}
	return encodeCanonical(writer, canonical, limits)
}

func encodeCanonical(writer io.Writer, canonical Bundle, limits Limits) error {
	entriesSize, err := encodedBodySize(canonical.Entries)
	if err != nil {
		return err
	}
	devicePadding := paddingForAlignment(uint64(headerSize)+entriesSize, blockDeviceAlignment)
	bodySize := entriesSize + devicePadding
	totalSize := uint64(headerSize) + bodySize
	if totalSize > limits.MaxBundleBytes {
		return fmt.Errorf("encoded repository bundle is %d bytes, limit is %d", totalSize, limits.MaxBundleBytes)
	}
	bodyDigest := sha256.New()
	if err := encodeEntries(bodyDigest, canonical.Entries); err != nil {
		return fmt.Errorf("hash repository bundle body: %w", err)
	}
	if err := writeZeros(bodyDigest, devicePadding); err != nil {
		return fmt.Errorf("hash repository bundle block padding: %w", err)
	}

	header := make([]byte, headerSize)
	copy(header[0:8], bundleMagic[:])
	binary.BigEndian.PutUint32(header[8:12], Schema)
	binary.BigEndian.PutUint32(header[12:16], headerSize)
	binary.BigEndian.PutUint64(header[16:24], uint64(len(canonical.Entries)))
	binary.BigEndian.PutUint64(header[24:32], canonical.ContentBytes)
	binary.BigEndian.PutUint64(header[32:40], totalSize)
	copy(header[40:72], canonical.TreeRoot[:])
	copy(header[72:104], bodyDigest.Sum(nil))
	if err := writeFull(writer, header); err != nil {
		return fmt.Errorf("write repository bundle header: %w", err)
	}
	if err := encodeEntries(writer, canonical.Entries); err != nil {
		return fmt.Errorf("write repository bundle body: %w", err)
	}
	if err := writeZeros(writer, devicePadding); err != nil {
		return fmt.Errorf("write repository bundle block padding: %w", err)
	}
	return nil
}

// Decode reads one complete canonical bundle and rejects trailing bytes.
func Decode(reader io.Reader, limits Limits) (Bundle, error) {
	if reader == nil {
		return Bundle{}, errors.New("repository bundle reader is nil")
	}
	if err := validateLimits(limits); err != nil {
		return Bundle{}, err
	}
	header := make([]byte, headerSize)
	if _, err := io.ReadFull(reader, header); err != nil {
		return Bundle{}, fmt.Errorf("read repository bundle header: %w", err)
	}
	if !bytes.Equal(header[0:8], bundleMagic[:]) || binary.BigEndian.Uint32(header[8:12]) != Schema || binary.BigEndian.Uint32(header[12:16]) != headerSize {
		return Bundle{}, errors.New("repository bundle has an invalid magic, schema, or header size")
	}
	if !allZero(header[104:]) {
		return Bundle{}, errors.New("repository bundle header reserved bytes are nonzero")
	}
	entryCount := binary.BigEndian.Uint64(header[16:24])
	contentBytes := binary.BigEndian.Uint64(header[24:32])
	totalSize := binary.BigEndian.Uint64(header[32:40])
	if entryCount > limits.MaxEntries {
		return Bundle{}, fmt.Errorf("repository bundle declares %d entries, limit is %d", entryCount, limits.MaxEntries)
	}
	if contentBytes > limits.MaxContentBytes {
		return Bundle{}, fmt.Errorf("repository bundle declares %d content bytes, limit is %d", contentBytes, limits.MaxContentBytes)
	}
	if totalSize < headerSize || totalSize > limits.MaxBundleBytes {
		return Bundle{}, fmt.Errorf("repository bundle declares invalid total size %d", totalSize)
	}
	if totalSize%blockDeviceAlignment != 0 {
		return Bundle{}, fmt.Errorf("repository bundle size %d is not aligned for a block device", totalSize)
	}
	bodySize := totalSize - headerSize
	const minimumEntrySize = entryHeaderSize + encodedAlignment
	if entryCount > bodySize/minimumEntrySize {
		return Bundle{}, fmt.Errorf("repository bundle body is too small for %d entries", entryCount)
	}
	var expectedRoot, expectedBody Digest
	copy(expectedRoot[:], header[40:72])
	copy(expectedBody[:], header[72:104])

	body := &io.LimitedReader{R: reader, N: int64(totalSize - headerSize)}
	bodyHash := sha256.New()
	teed := io.TeeReader(body, bodyHash)
	entries := make([]Entry, 0)
	var decodedContent uint64
	for index := uint64(0); index < entryCount; index++ {
		remainingContent := contentBytes - decodedContent
		entry, err := decodeEntry(teed, body, limits, remainingContent)
		if err != nil {
			return Bundle{}, fmt.Errorf("decode repository entry %d: %w", index, err)
		}
		if entry.Type == EntryFile || entry.Type == EntrySymlink {
			if uint64(len(entry.Data)) > limits.MaxContentBytes-decodedContent {
				return Bundle{}, fmt.Errorf("repository content exceeds %d bytes", limits.MaxContentBytes)
			}
			decodedContent += uint64(len(entry.Data))
		}
		entries = append(entries, entry)
	}
	if body.N >= blockDeviceAlignment {
		return Bundle{}, fmt.Errorf("repository bundle body contains %d undeclared bytes", body.N)
	}
	if err := readZeroPadding(teed, uint64(body.N)); err != nil {
		return Bundle{}, fmt.Errorf("read repository bundle block padding: %w", err)
	}
	var actualBody Digest
	copy(actualBody[:], bodyHash.Sum(nil))
	if actualBody != expectedBody {
		return Bundle{}, errors.New("repository bundle body SHA-256 does not match its header")
	}
	if decodedContent != contentBytes {
		return Bundle{}, fmt.Errorf("repository bundle decoded %d content bytes, header declares %d", decodedContent, contentBytes)
	}
	if err := requireEOF(reader); err != nil {
		return Bundle{}, err
	}
	if err := validateEntries(entries, limits.MaxPathBytes); err != nil {
		return Bundle{}, err
	}
	actualRoot := treeRoot(entries)
	if actualRoot != expectedRoot {
		return Bundle{}, errors.New("repository bundle tree root does not match its entries")
	}
	return Bundle{Schema: Schema, Entries: entries, TreeRoot: actualRoot, ContentBytes: decodedContent}, nil
}

func encodeEntries(writer io.Writer, entries []Entry) error {
	for _, entry := range entries {
		pathPadding := paddingFor(uint64(len(entry.Path)))
		dataPadding := paddingFor(uint64(len(entry.Data)))
		recordSize := uint64(entryHeaderSize) + uint64(len(entry.Path)) + pathPadding + uint64(len(entry.Data)) + dataPadding
		header := make([]byte, entryHeaderSize)
		header[0] = byte(entry.Type)
		binary.BigEndian.PutUint32(header[4:8], entry.Mode)
		binary.BigEndian.PutUint32(header[8:12], uint32(len(entry.Path)))
		binary.BigEndian.PutUint64(header[16:24], uint64(len(entry.Data)))
		copy(header[24:56], entry.SHA256[:])
		binary.BigEndian.PutUint64(header[56:64], recordSize)
		if err := writeFull(writer, header); err != nil {
			return err
		}
		if err := writeFull(writer, []byte(entry.Path)); err != nil {
			return err
		}
		if err := writeZeros(writer, pathPadding); err != nil {
			return err
		}
		if err := writeFull(writer, entry.Data); err != nil {
			return err
		}
		if err := writeZeros(writer, dataPadding); err != nil {
			return err
		}
	}
	return nil
}

func decodeEntry(reader io.Reader, remaining *io.LimitedReader, limits Limits, remainingContent uint64) (Entry, error) {
	header := make([]byte, entryHeaderSize)
	if _, err := io.ReadFull(reader, header); err != nil {
		return Entry{}, err
	}
	if !allZero(header[1:4]) || !allZero(header[12:16]) || !allZero(header[64:]) {
		return Entry{}, errors.New("entry reserved bytes are nonzero")
	}
	entryType := EntryType(header[0])
	mode := binary.BigEndian.Uint32(header[4:8])
	pathLength := binary.BigEndian.Uint32(header[8:12])
	dataLength := binary.BigEndian.Uint64(header[16:24])
	recordSize := binary.BigEndian.Uint64(header[56:64])
	if pathLength == 0 || pathLength > limits.MaxPathBytes {
		return Entry{}, fmt.Errorf("entry path length %d is outside the allowed range", pathLength)
	}
	if dataLength > limits.MaxFileBytes {
		return Entry{}, fmt.Errorf("entry data length %d exceeds %d", dataLength, limits.MaxFileBytes)
	}
	var digest Digest
	copy(digest[:], header[24:56])
	switch entryType {
	case EntryDirectory:
		if mode != 0o755 || dataLength != 0 || digest != (Digest{}) {
			return Entry{}, errors.New("directory entry has invalid mode, data length, or digest")
		}
	case EntryFile:
		if mode != 0o644 && mode != 0o755 {
			return Entry{}, errors.New("file entry has an invalid mode")
		}
		if dataLength > remainingContent {
			return Entry{}, errors.New("file entry exceeds the remaining declared content")
		}
	case EntrySymlink:
		if mode != 0o777 || dataLength == 0 || dataLength > uint64(limits.MaxPathBytes) {
			return Entry{}, errors.New("symbolic-link entry has an invalid mode or target length")
		}
		if dataLength > remainingContent {
			return Entry{}, errors.New("symbolic-link entry exceeds the remaining declared content")
		}
	default:
		return Entry{}, fmt.Errorf("entry has unknown type %d", entryType)
	}
	expectedSize := uint64(entryHeaderSize) + uint64(pathLength) + paddingFor(uint64(pathLength)) + dataLength + paddingFor(dataLength)
	if recordSize != expectedSize {
		return Entry{}, fmt.Errorf("entry record size is %d, require %d", recordSize, expectedSize)
	}
	if recordSize < entryHeaderSize || recordSize-entryHeaderSize > uint64(remaining.N) {
		return Entry{}, errors.New("entry record exceeds the remaining bundle body")
	}
	pathBytes := make([]byte, int(pathLength))
	if _, err := io.ReadFull(reader, pathBytes); err != nil {
		return Entry{}, err
	}
	if err := readZeroPadding(reader, paddingFor(uint64(pathLength))); err != nil {
		return Entry{}, err
	}
	data, err := readDeclaredBytes(reader, dataLength)
	if err != nil {
		return Entry{}, err
	}
	if err := readZeroPadding(reader, paddingFor(dataLength)); err != nil {
		return Entry{}, err
	}
	entry := Entry{Path: string(pathBytes), Type: entryType, Mode: mode, Data: data, SHA256: digest}
	if entryType == EntryFile || entryType == EntrySymlink {
		if Digest(sha256.Sum256(data)) != digest {
			return Entry{}, errors.New("entry content SHA-256 does not match its header")
		}
	}
	return entry, nil
}

func validateEntries(entries []Entry, maxPathBytes uint32) error {
	byPath := make(map[string]EntryType, len(entries))
	for index, entry := range entries {
		if err := validateEntry(entry, maxPathBytes); err != nil {
			return fmt.Errorf("invalid repository entry %d: %w", index, err)
		}
		if index > 0 && entries[index-1].Path >= entry.Path {
			return fmt.Errorf("repository paths are not strictly sorted at %q", entry.Path)
		}
		parent := path.Dir(entry.Path)
		if parent != "." {
			parentType, found := byPath[parent]
			if !found || parentType != EntryDirectory {
				return fmt.Errorf("repository entry %q has missing or non-directory parent %q", entry.Path, parent)
			}
		}
		byPath[entry.Path] = entry.Type
	}
	return nil
}

func validateEntry(entry Entry, maxPathBytes uint32) error {
	if err := validateRepositoryPath(entry.Path, maxPathBytes); err != nil {
		return err
	}
	switch entry.Type {
	case EntryDirectory:
		if entry.Mode != 0o755 || len(entry.Data) != 0 || entry.SHA256 != (Digest{}) {
			return fmt.Errorf("directory %q must have mode 0755 and no content", entry.Path)
		}
	case EntryFile:
		if entry.Mode != 0o644 && entry.Mode != 0o755 {
			return fmt.Errorf("file %q mode is %04o, require 0644 or 0755", entry.Path, entry.Mode)
		}
		if Digest(sha256.Sum256(entry.Data)) != entry.SHA256 {
			return fmt.Errorf("file %q content digest is incorrect", entry.Path)
		}
	case EntrySymlink:
		if entry.Mode != 0o777 {
			return fmt.Errorf("symbolic link %q mode is %04o, require 0777", entry.Path, entry.Mode)
		}
		if Digest(sha256.Sum256(entry.Data)) != entry.SHA256 {
			return fmt.Errorf("symbolic link %q target digest is incorrect", entry.Path)
		}
		if err := validateSymlinkTarget(entry.Path, string(entry.Data), maxPathBytes); err != nil {
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
	if target == "" || uint64(len(target)) > uint64(maxBytes) || !utf8.ValidString(target) || strings.IndexByte(target, 0) >= 0 || strings.Contains(target, "\\") || strings.IndexFunc(target, unicode.IsControl) >= 0 || path.IsAbs(target) {
		return fmt.Errorf("symbolic link %q has an invalid target", linkPath)
	}
	for _, component := range strings.Split(target, "/") {
		if component == "" || len(component) > 255 {
			return fmt.Errorf("symbolic link %q target has a forbidden component", linkPath)
		}
	}
	// Linux resolves each component before applying a later "..". Requiring
	// the target itself to be canonical prevents a safe-looking lexical clean
	// from hiding traversal through another symbolic link followed by "..".
	if path.Clean(target) != target {
		return fmt.Errorf("symbolic link %q target is not canonical", linkPath)
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

func treeRoot(entries []Entry) Digest {
	hash := sha256.New()
	_, _ = hash.Write(treeDomain)
	var number [8]byte
	binary.BigEndian.PutUint64(number[:], uint64(len(entries)))
	_, _ = hash.Write(number[:])
	for _, entry := range entries {
		binary.BigEndian.PutUint64(number[:], uint64(len(entry.Path)))
		_, _ = hash.Write(number[:])
		_, _ = hash.Write([]byte(entry.Path))
		_, _ = hash.Write([]byte{byte(entry.Type)})
		binary.BigEndian.PutUint64(number[:], uint64(entry.Mode))
		_, _ = hash.Write(number[:])
		binary.BigEndian.PutUint64(number[:], uint64(len(entry.Data)))
		_, _ = hash.Write(number[:])
		_, _ = hash.Write(entry.SHA256[:])
	}
	var result Digest
	copy(result[:], hash.Sum(nil))
	return result
}

func encodedBodySize(entries []Entry) (uint64, error) {
	var total uint64
	for _, entry := range entries {
		size := uint64(entryHeaderSize) + uint64(len(entry.Path)) + paddingFor(uint64(len(entry.Path))) + uint64(len(entry.Data)) + paddingFor(uint64(len(entry.Data)))
		if size > ^uint64(0)-total {
			return 0, errors.New("repository bundle encoded size overflows uint64")
		}
		total += size
	}
	return total, nil
}

func validateLimits(limits Limits) error {
	if limits.MaxEntries == 0 || limits.MaxPathBytes == 0 || limits.MaxFileBytes == 0 || limits.MaxContentBytes == 0 || limits.MaxBundleBytes < headerSize {
		return errors.New("repository bundle limits must all be positive and permit one header")
	}
	maxInt := uint64(^uint(0) >> 1)
	if uint64(limits.MaxPathBytes) > maxInt || limits.MaxFileBytes >= maxInt || limits.MaxEntries > maxInt || limits.MaxBundleBytes > uint64(^uint64(0)>>1) {
		return errors.New("repository bundle allocation limit exceeds this platform's int range")
	}
	return nil
}

func paddingFor(length uint64) uint64 {
	return paddingForAlignment(length, encodedAlignment)
}

func paddingForAlignment(length, alignment uint64) uint64 {
	return (alignment - length%alignment) % alignment
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
		return errors.New("repository bundle padding is nonzero")
	}
	return nil
}

// readDeclaredBytes grows with bytes actually observed. A truncated, untrusted
// bundle therefore cannot force one allocation equal to an attacker-declared
// content length before supplying those bytes.
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
		return errors.New("repository bundle contains trailing bytes")
	}
	if !errors.Is(err, io.EOF) {
		return fmt.Errorf("check repository bundle end: %w", err)
	}
	return nil
}

// SortedEntries returns a path-sorted deep copy. It is useful at explicit
// conversion boundaries; callers still need FromEntries for validation.
func SortedEntries(entries []Entry) []Entry {
	result := make([]Entry, len(entries))
	for index, entry := range entries {
		result[index] = entry
		result[index].Data = bytes.Clone(entry.Data)
	}
	sort.Slice(result, func(left, right int) bool { return result[left].Path < result[right].Path })
	return result
}
