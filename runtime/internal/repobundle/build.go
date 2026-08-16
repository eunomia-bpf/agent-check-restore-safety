package repobundle

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"

	"golang.org/x/sys/unix"
)

type BuildResult struct {
	Path         string
	SHA256       Digest
	Size         int64
	Bundle       Bundle
	FileCount    uint64
	DirCount     uint64
	SymlinkCount uint64
}

// Build scans source without following symbolic links, normalizes its modes,
// and writes a canonical bundle. Source must be an absolute direct directory.
func Build(source string, writer io.Writer, limits Limits) (Bundle, error) {
	if writer == nil {
		return Bundle{}, errors.New("repository bundle writer is nil")
	}
	validatedSource, err := validateSource(source)
	if err != nil {
		return Bundle{}, err
	}
	entries, err := scanSource(validatedSource, limits)
	if err != nil {
		return Bundle{}, err
	}
	recheck, err := scanSource(validatedSource, limits)
	if err != nil {
		return Bundle{}, fmt.Errorf("recheck repository source: %w", err)
	}
	if !sameEntries(entries, recheck) {
		return Bundle{}, errors.New("repository source changed while the bundle was built")
	}
	// The first scan owns entries. Avoid cloning the complete repository again
	// after the independent recheck has established equality.
	recheck = nil
	bundle, err := bundleFromOwnedEntries(entries, limits)
	if err != nil {
		return Bundle{}, err
	}
	if err := encodeCanonical(writer, bundle, limits); err != nil {
		return Bundle{}, err
	}
	return bundle, nil
}

// BuildFile publishes a complete bundle without overwriting output. The
// anonymous inode is synced and hard-linked into place on the output
// filesystem, so a failed build never publishes a partial named bundle. The
// caller must keep the output parent free from concurrent mutation by another
// process with the same credentials during publication.
func BuildFile(source, output string, limits Limits) (BuildResult, error) {
	validatedSource, err := validateSource(source)
	if err != nil {
		return BuildResult{}, err
	}
	validatedOutput, err := validateNewOutput(validatedSource, output)
	if err != nil {
		return BuildResult{}, err
	}
	parent, err := openDirectDirectory(filepath.Dir(validatedOutput))
	if err != nil {
		return BuildResult{}, fmt.Errorf("open repository bundle output parent: %w", err)
	}
	defer unix.Close(parent)
	var parentIdentity unix.Stat_t
	if err := unix.Fstat(parent, &parentIdentity); err != nil {
		return BuildResult{}, fmt.Errorf("stat repository bundle output parent: %w", err)
	}
	if parentIdentity.Mode&unix.S_IFMT != unix.S_IFDIR || parentIdentity.Mode&0o7777 != 0o700 || parentIdentity.Uid != uint32(os.Geteuid()) {
		return BuildResult{}, errors.New("repository bundle output parent must be a current-user directory with mode 0700")
	}
	descriptor, err := createAnonymousFileAt(parent)
	if err != nil {
		return BuildResult{}, fmt.Errorf("create anonymous repository bundle staging file: %w", err)
	}
	file := os.NewFile(uintptr(descriptor), "repository-bundle")
	if file == nil {
		_ = unix.Close(descriptor)
		return BuildResult{}, errors.New("wrap repository bundle staging descriptor")
	}
	hash := sha256.New()
	counter := &countingWriter{writer: io.MultiWriter(file, hash)}
	bundle, buildErr := Build(validatedSource, counter, limits)
	syncErr := file.Sync()
	if err := errors.Join(buildErr, syncErr); err != nil {
		return BuildResult{}, fmt.Errorf("build repository bundle: %w", errors.Join(err, file.Close()))
	}
	var digest Digest
	copy(digest[:], hash.Sum(nil))
	outputName := filepath.Base(validatedOutput)
	if err := linkAnonymousFileAt(descriptor, parent, outputName); err != nil {
		closeErr := file.Close()
		var outputStat unix.Stat_t
		if inspectErr := unix.Fstatat(parent, outputName, &outputStat, unix.AT_SYMLINK_NOFOLLOW); inspectErr == nil {
			return BuildResult{}, fmt.Errorf("repository bundle output already exists: %q", validatedOutput)
		}
		return BuildResult{}, fmt.Errorf("publish repository bundle %q: %w", validatedOutput, errors.Join(err, closeErr))
	}
	linkedIdentityErr := verifyLinkedFileIdentity(parent, outputName, descriptor)
	directorySyncErr := unix.Fsync(parent)
	closeErr := file.Close()
	identityErr := verifyDirectoryIdentity(filepath.Dir(validatedOutput), parentIdentity)
	if err := errors.Join(linkedIdentityErr, directorySyncErr, closeErr, identityErr); err != nil {
		// The named output is complete, but publication durability or its named
		// parent identity was not established. Report partial success explicitly.
		return BuildResult{}, fmt.Errorf("repository bundle %q was published but publication verification failed: %w", validatedOutput, err)
	}
	result := BuildResult{Path: validatedOutput, SHA256: digest, Size: counter.written, Bundle: bundle}
	for _, entry := range bundle.Entries {
		switch entry.Type {
		case EntryDirectory:
			result.DirCount++
		case EntryFile:
			result.FileCount++
		case EntrySymlink:
			result.SymlinkCount++
		}
	}
	return result, nil
}

func scanSource(source string, limits Limits) ([]Entry, error) {
	if err := validateLimits(limits); err != nil {
		return nil, err
	}
	descriptor, err := openDirectDirectory(source)
	if err != nil {
		return nil, fmt.Errorf("open repository source: %w", err)
	}
	defer unix.Close(descriptor)
	var rootStat unix.Stat_t
	if err := unix.Fstat(descriptor, &rootStat); err != nil {
		return nil, fmt.Errorf("stat opened repository source: %w", err)
	}
	if rootStat.Mode&unix.S_IFMT != unix.S_IFDIR || hasSpecialMode(rootStat.Mode) {
		return nil, errors.New("repository source root is not a plain directory mode")
	}
	scanner := sourceScanner{limits: limits, entries: make([]Entry, 0)}
	if err := scanner.scanDirectory(descriptor, ""); err != nil {
		return nil, fmt.Errorf("scan repository source: %w", err)
	}
	sort.Slice(scanner.entries, func(left, right int) bool { return scanner.entries[left].Path < scanner.entries[right].Path })
	return scanner.entries, nil
}

type sourceScanner struct {
	limits       Limits
	entries      []Entry
	contentBytes uint64
}

func (scanner *sourceScanner) scanDirectory(descriptor int, parent string) error {
	var before unix.Stat_t
	if err := unix.Fstat(descriptor, &before); err != nil {
		return err
	}
	remainingEntries := scanner.limits.MaxEntries - uint64(len(scanner.entries))
	names, err := readDirectoryNames(descriptor, remainingEntries)
	if err != nil {
		return err
	}
	for _, name := range names {
		relative := name
		if parent != "" {
			relative = path.Join(parent, name)
		}
		if err := validateRepositoryPath(relative, scanner.limits.MaxPathBytes); err != nil {
			return err
		}
		if uint64(len(scanner.entries)) >= scanner.limits.MaxEntries {
			return fmt.Errorf("repository contains more than %d entries", scanner.limits.MaxEntries)
		}
		var initial unix.Stat_t
		if err := unix.Fstatat(descriptor, name, &initial, unix.AT_SYMLINK_NOFOLLOW); err != nil {
			return fmt.Errorf("stat repository entry %q: %w", relative, err)
		}
		if hasSpecialMode(initial.Mode) {
			return fmt.Errorf("repository entry %q has a forbidden setuid, setgid, or sticky mode", relative)
		}
		switch initial.Mode & unix.S_IFMT {
		case unix.S_IFDIR:
			scanner.entries = append(scanner.entries, Entry{Path: relative, Type: EntryDirectory, Mode: 0o755})
			child, err := unix.Openat(descriptor, name, unix.O_RDONLY|unix.O_DIRECTORY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
			if err != nil {
				return fmt.Errorf("open repository directory %q: %w", relative, err)
			}
			var opened unix.Stat_t
			statErr := unix.Fstat(child, &opened)
			if statErr == nil && !sameStat(initial, opened) {
				statErr = errors.New("directory changed before it was opened")
			}
			if statErr == nil {
				statErr = scanner.scanDirectory(child, relative)
			}
			closeErr := unix.Close(child)
			if err := errors.Join(statErr, closeErr); err != nil {
				return fmt.Errorf("scan repository directory %q: %w", relative, err)
			}
		case unix.S_IFREG:
			entry, err := scanner.readRegularFile(descriptor, name, relative, initial)
			if err != nil {
				return err
			}
			scanner.entries = append(scanner.entries, entry)
		case unix.S_IFLNK:
			entry, err := scanner.readSymlink(descriptor, name, relative, initial)
			if err != nil {
				return err
			}
			scanner.entries = append(scanner.entries, entry)
		default:
			return fmt.Errorf("repository entry %q has unsupported special mode %#o", relative, initial.Mode)
		}
	}
	var after unix.Stat_t
	if err := unix.Fstat(descriptor, &after); err != nil {
		return err
	}
	if !sameStat(before, after) {
		return errors.New("repository directory changed while it was scanned")
	}
	return nil
}

func (scanner *sourceScanner) readRegularFile(parent int, name, relative string, initial unix.Stat_t) (Entry, error) {
	if initial.Size < 0 || uint64(initial.Size) > scanner.limits.MaxFileBytes {
		return Entry{}, fmt.Errorf("repository file %q size %d exceeds %d", relative, initial.Size, scanner.limits.MaxFileBytes)
	}
	descriptor, err := unix.Openat(parent, name, unix.O_RDONLY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
	if err != nil {
		return Entry{}, fmt.Errorf("open repository file %q: %w", relative, err)
	}
	file := os.NewFile(uintptr(descriptor), relative)
	if file == nil {
		_ = unix.Close(descriptor)
		return Entry{}, fmt.Errorf("wrap repository file %q descriptor", relative)
	}
	var opened unix.Stat_t
	if err := unix.Fstat(descriptor, &opened); err != nil || !sameStat(initial, opened) || opened.Mode&unix.S_IFMT != unix.S_IFREG {
		_ = file.Close()
		return Entry{}, fmt.Errorf("repository file %q changed before it was opened", relative)
	}
	data, readErr := io.ReadAll(io.LimitReader(file, int64(scanner.limits.MaxFileBytes)+1))
	var after unix.Stat_t
	statErr := unix.Fstat(descriptor, &after)
	closeErr := file.Close()
	if err := errors.Join(readErr, statErr, closeErr); err != nil {
		return Entry{}, fmt.Errorf("read repository file %q: %w", relative, err)
	}
	if uint64(len(data)) > scanner.limits.MaxFileBytes || !sameStat(opened, after) || after.Size != int64(len(data)) {
		return Entry{}, fmt.Errorf("repository file %q changed while it was read", relative)
	}
	if uint64(len(data)) > scanner.limits.MaxContentBytes-scanner.contentBytes {
		return Entry{}, fmt.Errorf("repository content exceeds %d bytes", scanner.limits.MaxContentBytes)
	}
	scanner.contentBytes += uint64(len(data))
	mode := uint32(0o644)
	if opened.Mode&0o111 != 0 {
		mode = 0o755
	}
	return Entry{Path: relative, Type: EntryFile, Mode: mode, Data: data, SHA256: Digest(sha256.Sum256(data))}, nil
}

func (scanner *sourceScanner) readSymlink(parent int, name, relative string, initial unix.Stat_t) (Entry, error) {
	buffer := make([]byte, int(scanner.limits.MaxPathBytes)+1)
	length, err := unix.Readlinkat(parent, name, buffer)
	if err != nil {
		return Entry{}, fmt.Errorf("read repository symbolic link %q: %w", relative, err)
	}
	if length > int(scanner.limits.MaxPathBytes) {
		return Entry{}, fmt.Errorf("repository symbolic link %q target exceeds %d bytes", relative, scanner.limits.MaxPathBytes)
	}
	var after unix.Stat_t
	if err := unix.Fstatat(parent, name, &after, unix.AT_SYMLINK_NOFOLLOW); err != nil || !sameStat(initial, after) {
		return Entry{}, fmt.Errorf("repository symbolic link %q changed while it was read", relative)
	}
	target := string(buffer[:length])
	if err := validateSymlinkTarget(relative, target, scanner.limits.MaxPathBytes); err != nil {
		return Entry{}, err
	}
	if uint64(length) > scanner.limits.MaxContentBytes-scanner.contentBytes {
		return Entry{}, fmt.Errorf("repository content exceeds %d bytes", scanner.limits.MaxContentBytes)
	}
	scanner.contentBytes += uint64(length)
	data := []byte(target)
	return Entry{Path: relative, Type: EntrySymlink, Mode: 0o777, Data: data, SHA256: Digest(sha256.Sum256(data))}, nil
}

func readDirectoryNames(descriptor int, maximum uint64) ([]string, error) {
	duplicate, err := unix.Openat(descriptor, ".", unix.O_RDONLY|unix.O_DIRECTORY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	directory := os.NewFile(uintptr(duplicate), "repository-directory")
	if directory == nil {
		_ = unix.Close(duplicate)
		return nil, errors.New("wrap repository directory descriptor")
	}
	const batchSize = 256
	capacity := maximum
	if capacity > batchSize {
		capacity = batchSize
	}
	names := make([]string, 0, int(capacity))
	var readErr error
	for {
		entries, err := directory.ReadDir(batchSize)
		for _, entry := range entries {
			if uint64(len(names)) >= maximum {
				readErr = fmt.Errorf("repository directory contains more than %d remaining entries", maximum)
				break
			}
			names = append(names, entry.Name())
		}
		if readErr != nil {
			break
		}
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			readErr = err
			break
		}
	}
	closeErr := directory.Close()
	if err := errors.Join(readErr, closeErr); err != nil {
		return nil, err
	}
	sort.Strings(names)
	return names, nil
}

func hasSpecialMode(mode uint32) bool {
	return mode&(unix.S_ISUID|unix.S_ISGID|unix.S_ISVTX) != 0
}

func sameStat(left, right unix.Stat_t) bool {
	return left.Dev == right.Dev && left.Ino == right.Ino && left.Mode == right.Mode && left.Size == right.Size &&
		left.Mtim == right.Mtim && left.Ctim == right.Ctim
}

func validateSource(source string) (string, error) {
	if err := validateHostPathString(source, "repository source"); err != nil {
		return "", err
	}
	if !filepath.IsAbs(source) || filepath.Clean(source) != source {
		return "", errors.New("repository source must be an absolute canonical path")
	}
	for _, component := range strings.Split(filepath.ToSlash(source), "/") {
		if strings.EqualFold(component, ".git") {
			return "", errors.New("repository source path must not be inside .git state")
		}
	}
	info, err := os.Lstat(source)
	if err != nil {
		return "", fmt.Errorf("inspect repository source: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return "", errors.New("repository source must be a direct directory")
	}
	resolved, err := filepath.EvalSymlinks(source)
	if err != nil || filepath.Clean(resolved) != source {
		return "", errors.New("repository source path must not traverse a symbolic link")
	}
	return source, nil
}

func validateNewOutput(source, output string) (string, error) {
	if err := validateHostPathString(output, "repository bundle output"); err != nil {
		return "", err
	}
	if !filepath.IsAbs(output) || filepath.Clean(output) != output {
		return "", errors.New("repository bundle output must be an absolute canonical path")
	}
	if pathWithin(source, output) {
		return "", errors.New("repository bundle output must be outside the source directory")
	}
	parent := filepath.Dir(output)
	info, err := os.Lstat(parent)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return "", errors.New("repository bundle output parent must be a direct directory")
	}
	resolved, err := filepath.EvalSymlinks(parent)
	if err != nil || filepath.Clean(resolved) != parent {
		return "", errors.New("repository bundle output parent path must not traverse a symbolic link")
	}
	if _, err := os.Lstat(output); err == nil {
		return "", fmt.Errorf("repository bundle output already exists: %q", output)
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", fmt.Errorf("inspect repository bundle output: %w", err)
	}
	return output, nil
}

func validateHostPathString(value, label string) error {
	if value == "" || !utf8.ValidString(value) || strings.IndexByte(value, 0) >= 0 || strings.IndexFunc(value, unicode.IsControl) >= 0 {
		return fmt.Errorf("%s must be nonempty valid UTF-8 without control characters", label)
	}
	return nil
}

func pathWithin(root, candidate string) bool {
	relative, err := filepath.Rel(root, candidate)
	return err == nil && !filepath.IsAbs(relative) && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator))
}

func sameEntries(left, right []Entry) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index].Path != right[index].Path || left[index].Type != right[index].Type || left[index].Mode != right[index].Mode || left[index].SHA256 != right[index].SHA256 || !bytes.Equal(left[index].Data, right[index].Data) {
			return false
		}
	}
	return true
}

type countingWriter struct {
	writer  io.Writer
	written int64
}

func (writer *countingWriter) Write(data []byte) (int, error) {
	written, err := writer.writer.Write(data)
	writer.written += int64(written)
	return written, err
}

func createAnonymousFileAt(parent int) (int, error) {
	descriptor, err := unix.Openat(parent, ".", unix.O_WRONLY|unix.O_CLOEXEC|unix.O_TMPFILE, 0o600)
	if err != nil {
		return -1, err
	}
	if err := unix.Fchmod(descriptor, 0o600); err != nil {
		_ = unix.Close(descriptor)
		return -1, err
	}
	return descriptor, nil
}

func linkAnonymousFileAt(descriptor, parent int, name string) error {
	if err := unix.Linkat(descriptor, "", parent, name, unix.AT_EMPTY_PATH); err == nil {
		return nil
	}
	// AT_EMPTY_PATH can require CAP_DAC_READ_SEARCH. Linux documents this
	// procfs form for publishing an O_TMPFILE inode without that capability.
	return unix.Linkat(unix.AT_FDCWD, fmt.Sprintf("/proc/self/fd/%d", descriptor), parent, name, unix.AT_SYMLINK_FOLLOW)
}

func verifyLinkedFileIdentity(parent int, name string, descriptor int) error {
	var source, linked unix.Stat_t
	if err := unix.Fstat(descriptor, &source); err != nil {
		return fmt.Errorf("stat anonymous repository bundle: %w", err)
	}
	if err := unix.Fstatat(parent, name, &linked, unix.AT_SYMLINK_NOFOLLOW); err != nil {
		return fmt.Errorf("stat linked repository bundle: %w", err)
	}
	if source.Dev != linked.Dev || source.Ino != linked.Ino || linked.Mode&unix.S_IFMT != unix.S_IFREG || linked.Mode&0o7777 != 0o600 {
		return errors.New("linked repository bundle identity differs from the built inode")
	}
	return nil
}

func verifyDirectoryIdentity(path string, expected unix.Stat_t) error {
	descriptor, err := openDirectDirectory(path)
	if err != nil {
		return fmt.Errorf("reopen published repository bundle parent: %w", err)
	}
	defer unix.Close(descriptor)
	var actual unix.Stat_t
	if err := unix.Fstat(descriptor, &actual); err != nil {
		return fmt.Errorf("stat reopened repository bundle parent: %w", err)
	}
	if actual.Dev != expected.Dev || actual.Ino != expected.Ino {
		return errors.New("repository bundle output parent changed during publication")
	}
	return nil
}
