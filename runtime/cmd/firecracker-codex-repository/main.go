// Command firecracker-codex-repository builds canonical repository bytes for a
// Firecracker Codex guest drive.
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"unicode"
	"unicode/utf8"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repobundle"
	"golang.org/x/sys/unix"
)

type options struct{ source, output, result string }

type repositoryRecord struct {
	Schema           int    `json:"schema"`
	RepositoryPath   string `json:"repository_path"`
	RepositorySHA256 string `json:"repository_sha256"`
	RepositorySize   int64  `json:"repository_size"`
	TreeRoot         string `json:"tree_root"`
	EntryCount       uint64 `json:"entry_count"`
	FileCount        uint64 `json:"file_count"`
	DirectoryCount   uint64 `json:"directory_count"`
	SymlinkCount     uint64 `json:"symlink_count"`
	ContentBytes     uint64 `json:"content_bytes"`
}

type summary struct {
	repositoryRecord
	ResultPath string `json:"result_path"`
}

func main() {
	var config options
	flag.StringVar(&config.source, "source", "", "absolute repository source directory")
	flag.StringVar(&config.output, "output", "", "new absolute canonical repository bundle path")
	flag.StringVar(&config.result, "result", "", "new absolute JSON identity path")
	flag.Parse()
	if flag.NArg() != 0 {
		log.Printf("Codex repository build failed: unexpected positional arguments")
		os.Exit(2)
	}
	if err := run(config, os.Stdout); err != nil {
		log.Printf("Codex repository build failed: %v", err)
		os.Exit(1)
	}
}

func run(config options, stdout io.Writer) error {
	if stdout == nil {
		return errors.New("repository summary writer is nil")
	}
	if err := validatePrivateNewPaths(config); err != nil {
		return err
	}
	limits := repobundle.DefaultLimits()
	built, err := repobundle.BuildFile(config.source, config.output, limits)
	if err != nil {
		return err
	}
	published, err := os.Open(built.Path)
	if err != nil {
		return fmt.Errorf("repository bundle %q was published but could not be reopened: %w", built.Path, err)
	}
	decoded, decodeErr := repobundle.Decode(published, limits)
	closeErr := published.Close()
	if err := errors.Join(decodeErr, closeErr); err != nil {
		return fmt.Errorf("repository bundle %q was published but verification failed: %w", built.Path, err)
	}
	if decoded.TreeRoot != built.Bundle.TreeRoot || decoded.ContentBytes != built.Bundle.ContentBytes || len(decoded.Entries) != len(built.Bundle.Entries) {
		return fmt.Errorf("repository bundle %q was published but differs from the scanned source", built.Path)
	}
	record := repositoryRecord{
		Schema: 1, RepositoryPath: built.Path, RepositorySHA256: built.SHA256.String(), RepositorySize: built.Size,
		TreeRoot: decoded.TreeRoot.String(), EntryCount: uint64(len(decoded.Entries)), FileCount: built.FileCount,
		DirectoryCount: built.DirCount, SymlinkCount: built.SymlinkCount, ContentBytes: decoded.ContentBytes,
	}
	if err := writeExclusiveJSON(config.result, record); err != nil {
		return fmt.Errorf("repository bundle %q was built but identity publication failed: %w", built.Path, err)
	}
	if err := writeJSONLine(stdout, summary{repositoryRecord: record, ResultPath: config.result}); err != nil {
		return fmt.Errorf("repository bundle %q and identity %q were published but summary output failed: %w", built.Path, config.result, err)
	}
	return nil
}

func validatePrivateNewPaths(config options) error {
	for label, value := range map[string]string{"repository bundle output": config.output, "repository identity result": config.result} {
		if err := validateCanonicalNewPath(value, label); err != nil {
			return err
		}
		if err := validatePrivateDirectory(filepath.Dir(value), label+" parent"); err != nil {
			return err
		}
	}
	if config.source == "" || !filepath.IsAbs(config.source) || filepath.Clean(config.source) != config.source {
		return errors.New("repository source must be an absolute canonical path")
	}
	if config.output == config.result {
		return errors.New("repository bundle and identity paths must differ")
	}
	if pathWithin(config.source, config.output) || pathWithin(config.source, config.result) {
		return errors.New("repository outputs must be outside the source directory")
	}
	return nil
}

func validateCanonicalNewPath(value, label string) error {
	if value == "" || !utf8.ValidString(value) || strings.IndexByte(value, 0) >= 0 || strings.IndexFunc(value, unicode.IsControl) >= 0 || !filepath.IsAbs(value) || filepath.Clean(value) != value {
		return fmt.Errorf("%s must be an absolute canonical UTF-8 path without control characters", label)
	}
	if _, err := os.Lstat(value); err == nil {
		return fmt.Errorf("%s already exists", label)
	} else if !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("inspect %s: %w", label, err)
	}
	return nil
}

func validatePrivateDirectory(value, label string) error {
	info, err := os.Lstat(value)
	if err != nil {
		return fmt.Errorf("inspect %s: %w", label, err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() || info.Mode().Perm() != 0o700 {
		return fmt.Errorf("%s must be a direct private directory with mode 0700", label)
	}
	resolved, err := filepath.EvalSymlinks(value)
	if err != nil || filepath.Clean(resolved) != value {
		return fmt.Errorf("%s path must not traverse a symbolic link", label)
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != uint32(os.Geteuid()) {
		return fmt.Errorf("%s must be owned by the current user", label)
	}
	return nil
}

func writeExclusiveJSON(path string, value any) error {
	encoded, err := json.Marshal(value)
	if err != nil {
		return err
	}
	encoded = append(encoded, '\n')
	parentPath := filepath.Dir(path)
	parent, parentIdentity, err := openPrivateDirectory(parentPath)
	if err != nil {
		return err
	}
	defer unix.Close(parent)
	descriptor, err := unix.Openat(parent, ".", unix.O_WRONLY|unix.O_CLOEXEC|unix.O_TMPFILE, 0o600)
	if err != nil {
		return fmt.Errorf("create anonymous identity staging file: %w", err)
	}
	file := os.NewFile(uintptr(descriptor), "repository-identity")
	if file == nil {
		_ = unix.Close(descriptor)
		return errors.New("wrap repository identity staging descriptor")
	}
	if err := unix.Fchmod(descriptor, 0o600); err != nil {
		return errors.Join(err, file.Close())
	}
	writeErr := writeFull(file, encoded)
	syncErr := file.Sync()
	if err := errors.Join(writeErr, syncErr); err != nil {
		return errors.Join(err, file.Close())
	}
	name := filepath.Base(path)
	linkErr := unix.Linkat(descriptor, "", parent, name, unix.AT_EMPTY_PATH)
	if linkErr != nil {
		linkErr = unix.Linkat(unix.AT_FDCWD, fmt.Sprintf("/proc/self/fd/%d", descriptor), parent, name, unix.AT_SYMLINK_FOLLOW)
	}
	if linkErr != nil {
		closeErr := file.Close()
		var stat unix.Stat_t
		if inspectErr := unix.Fstatat(parent, name, &stat, unix.AT_SYMLINK_NOFOLLOW); inspectErr == nil {
			return fmt.Errorf("repository identity already exists: %q", path)
		}
		return errors.Join(linkErr, closeErr)
	}
	linkedIdentityErr := verifyLinkedIdentity(parent, name, descriptor)
	directorySyncErr := unix.Fsync(parent)
	closeErr := file.Close()
	identityErr := verifyPrivateDirectoryIdentity(parentPath, parentIdentity)
	if err := errors.Join(linkedIdentityErr, directorySyncErr, closeErr, identityErr); err != nil {
		return fmt.Errorf("identity %q was published but publication verification failed: %w", path, err)
	}
	return nil
}

func verifyLinkedIdentity(parent int, name string, descriptor int) error {
	var source, linked unix.Stat_t
	if err := unix.Fstat(descriptor, &source); err != nil {
		return fmt.Errorf("stat anonymous repository identity: %w", err)
	}
	if err := unix.Fstatat(parent, name, &linked, unix.AT_SYMLINK_NOFOLLOW); err != nil {
		return fmt.Errorf("stat linked repository identity: %w", err)
	}
	if source.Dev != linked.Dev || source.Ino != linked.Ino || linked.Mode&unix.S_IFMT != unix.S_IFREG || linked.Mode&0o7777 != 0o600 {
		return errors.New("linked repository identity differs from the written inode")
	}
	return nil
}

func openPrivateDirectory(path string) (int, unix.Stat_t, error) {
	descriptor, err := unix.Openat2(unix.AT_FDCWD, path, &unix.OpenHow{
		Flags:   unix.O_RDONLY | unix.O_DIRECTORY | unix.O_CLOEXEC,
		Resolve: unix.RESOLVE_NO_SYMLINKS | unix.RESOLVE_NO_MAGICLINKS,
	})
	if err != nil {
		return -1, unix.Stat_t{}, fmt.Errorf("open private output directory: %w", err)
	}
	var stat unix.Stat_t
	if err := unix.Fstat(descriptor, &stat); err != nil {
		_ = unix.Close(descriptor)
		return -1, unix.Stat_t{}, fmt.Errorf("stat private output directory: %w", err)
	}
	if stat.Mode&unix.S_IFMT != unix.S_IFDIR || stat.Mode&0o7777 != 0o700 || stat.Uid != uint32(os.Geteuid()) {
		_ = unix.Close(descriptor)
		return -1, unix.Stat_t{}, errors.New("output directory must be a current-user directory with mode 0700")
	}
	return descriptor, stat, nil
}

func verifyPrivateDirectoryIdentity(path string, expected unix.Stat_t) error {
	descriptor, actual, err := openPrivateDirectory(path)
	if err != nil {
		return err
	}
	defer unix.Close(descriptor)
	if actual.Dev != expected.Dev || actual.Ino != expected.Ino {
		return errors.New("repository identity parent changed during publication")
	}
	return nil
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

func writeJSONLine(writer io.Writer, value any) error {
	encoded, err := json.Marshal(value)
	if err != nil {
		return err
	}
	encoded = append(encoded, '\n')
	for len(encoded) > 0 {
		written, err := writer.Write(encoded)
		if err != nil {
			return err
		}
		if written <= 0 || written > len(encoded) {
			return io.ErrShortWrite
		}
		encoded = encoded[written:]
	}
	return nil
}

func pathWithin(root, candidate string) bool {
	relative, err := filepath.Rel(root, candidate)
	return err == nil && !filepath.IsAbs(relative) && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator))
}
