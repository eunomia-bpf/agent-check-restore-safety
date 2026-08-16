package repobundle

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/sys/unix"
)

// Materialize writes a validated bundle into an existing empty direct
// directory. Symbolic links are created only after all directories and files,
// so no earlier write can traverse bundle-controlled link state.
func (bundle Bundle) Materialize(destination string) error {
	return bundle.materialize(destination, nil)
}

// MaterializeOwned is Materialize with every created object, including the
// destination directory and symbolic links, assigned to one numeric identity.
// It is used by a privileged sandbox supervisor before dropping privileges to
// the agent process.
func (bundle Bundle) MaterializeOwned(destination string, uid, gid int) error {
	if uid < 0 || gid < 0 {
		return errors.New("repository materialization owner must be nonnegative")
	}
	owner := [2]int{uid, gid}
	return bundle.materialize(destination, &owner)
}

func (bundle Bundle) materialize(destination string, owner *[2]int) error {
	canonical, err := FromEntries(bundle.Entries, limitsForBundle(bundle))
	if err != nil {
		return fmt.Errorf("validate repository before materialization: %w", err)
	}
	if bundle.Schema != Schema || bundle.TreeRoot != canonical.TreeRoot || bundle.ContentBytes != canonical.ContentBytes {
		return errors.New("repository bundle metadata does not match its entries")
	}
	bundle = canonical
	if !filepath.IsAbs(destination) || filepath.Clean(destination) != destination {
		return errors.New("repository destination must be an absolute canonical path")
	}
	info, err := os.Lstat(destination)
	if err != nil {
		return fmt.Errorf("inspect repository destination: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return errors.New("repository destination must be a direct directory")
	}
	resolved, err := filepath.EvalSymlinks(destination)
	if err != nil || filepath.Clean(resolved) != destination {
		return errors.New("repository destination path must not traverse a symbolic link")
	}
	rootDescriptor, err := openDirectDirectory(destination)
	if err != nil {
		return fmt.Errorf("open repository destination: %w", err)
	}
	root := os.NewFile(uintptr(rootDescriptor), destination)
	if root == nil {
		_ = unix.Close(rootDescriptor)
		return errors.New("wrap repository destination descriptor")
	}
	defer root.Close()
	current, err := root.Stat()
	if err != nil || !current.IsDir() || !os.SameFile(info, current) {
		return errors.New("repository destination changed while it was opened")
	}
	names, readErr := root.Readdirnames(1)
	if len(names) != 0 || readErr == nil {
		return errors.New("repository destination must be empty")
	}
	if !errors.Is(readErr, io.EOF) {
		return fmt.Errorf("read repository destination: %w", readErr)
	}
	if owner != nil {
		if err := unix.Fchown(rootDescriptor, owner[0], owner[1]); err != nil {
			return fmt.Errorf("assign repository destination owner: %w", err)
		}
	}

	for _, entry := range bundle.Entries {
		if entry.Type != EntryDirectory {
			continue
		}
		parent, name, err := openParentAt(rootDescriptor, entry.Path)
		if err != nil {
			return fmt.Errorf("open parent of repository directory %q: %w", entry.Path, err)
		}
		createErr := unix.Mkdirat(parent, name, 0o700)
		var ownerErr error
		if createErr == nil && owner != nil {
			ownerErr = unix.Fchownat(parent, name, owner[0], owner[1], unix.AT_SYMLINK_NOFOLLOW)
		}
		closeErr := unix.Close(parent)
		if err := errors.Join(createErr, ownerErr, closeErr); err != nil {
			return fmt.Errorf("create repository directory %q: %w", entry.Path, err)
		}
	}
	for _, entry := range bundle.Entries {
		if entry.Type != EntryFile {
			continue
		}
		parent, name, err := openParentAt(rootDescriptor, entry.Path)
		if err != nil {
			return fmt.Errorf("open parent of repository file %q: %w", entry.Path, err)
		}
		descriptor, openErr := unix.Openat(parent, name, unix.O_WRONLY|unix.O_CREAT|unix.O_EXCL|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0o600)
		parentCloseErr := unix.Close(parent)
		if err := errors.Join(openErr, parentCloseErr); err != nil {
			return fmt.Errorf("create repository file %q: %w", entry.Path, err)
		}
		file := os.NewFile(uintptr(descriptor), entry.Path)
		if file == nil {
			_ = unix.Close(descriptor)
			return fmt.Errorf("wrap repository file %q descriptor", entry.Path)
		}
		writeErr := writeFull(file, entry.Data)
		var ownerErr error
		if owner != nil {
			ownerErr = unix.Fchown(descriptor, owner[0], owner[1])
		}
		modeErr := unix.Fchmod(descriptor, entry.Mode)
		syncErr := file.Sync()
		closeErr := file.Close()
		if err := errors.Join(writeErr, ownerErr, modeErr, syncErr, closeErr); err != nil {
			return fmt.Errorf("write repository file %q: %w", entry.Path, err)
		}
	}
	for _, entry := range bundle.Entries {
		if entry.Type != EntrySymlink {
			continue
		}
		parent, name, err := openParentAt(rootDescriptor, entry.Path)
		if err != nil {
			return fmt.Errorf("open parent of repository symbolic link %q: %w", entry.Path, err)
		}
		linkErr := unix.Symlinkat(string(entry.Data), parent, name)
		var ownerErr error
		if linkErr == nil && owner != nil {
			ownerErr = unix.Fchownat(parent, name, owner[0], owner[1], unix.AT_SYMLINK_NOFOLLOW)
		}
		closeErr := unix.Close(parent)
		if err := errors.Join(linkErr, ownerErr, closeErr); err != nil {
			return fmt.Errorf("create repository symbolic link %q: %w", entry.Path, err)
		}
	}
	// Apply directory modes last so a restrictive umask cannot change the
	// canonical result and future format revisions may safely add stricter modes.
	for index := len(bundle.Entries) - 1; index >= 0; index-- {
		entry := bundle.Entries[index]
		if entry.Type != EntryDirectory {
			continue
		}
		descriptor, err := openDirectoryAt(rootDescriptor, entry.Path)
		if err != nil {
			return fmt.Errorf("open repository directory %q for mode: %w", entry.Path, err)
		}
		modeErr := unix.Fchmod(descriptor, entry.Mode)
		closeErr := unix.Close(descriptor)
		if err := errors.Join(modeErr, closeErr); err != nil {
			return fmt.Errorf("set repository directory %q mode: %w", entry.Path, err)
		}
	}
	return nil
}

func openParentAt(root int, relative string) (int, string, error) {
	components := strings.Split(relative, "/")
	if len(components) == 0 || components[len(components)-1] == "" {
		return -1, "", errors.New("repository path has no final component")
	}
	parent := "."
	if len(components) > 1 {
		parent = strings.Join(components[:len(components)-1], "/")
	}
	descriptor, err := openDirectoryAt(root, parent)
	if err != nil {
		return -1, "", err
	}
	return descriptor, components[len(components)-1], nil
}

func openDirectoryAt(root int, relative string) (int, error) {
	const flags = unix.O_RDONLY | unix.O_DIRECTORY | unix.O_NOFOLLOW | unix.O_CLOEXEC
	current, err := unix.Openat(root, ".", flags, 0)
	if err != nil {
		return -1, err
	}
	if relative == "." {
		return current, nil
	}
	for _, component := range strings.Split(relative, "/") {
		next, openErr := unix.Openat(current, component, flags, 0)
		closeErr := unix.Close(current)
		if openErr != nil {
			return -1, errors.Join(openErr, closeErr)
		}
		if closeErr != nil {
			_ = unix.Close(next)
			return -1, closeErr
		}
		current = next
	}
	return current, nil
}

func limitsForBundle(bundle Bundle) Limits {
	limits := Limits{MaxEntries: uint64(len(bundle.Entries)) + 1, MaxPathBytes: 1, MaxFileBytes: 1, MaxContentBytes: 1, MaxBundleBytes: headerSize}
	for _, entry := range bundle.Entries {
		if uint32(len(entry.Path)) > limits.MaxPathBytes {
			limits.MaxPathBytes = uint32(len(entry.Path))
		}
		if entry.Type == EntrySymlink && uint32(len(entry.Data)) > limits.MaxPathBytes {
			limits.MaxPathBytes = uint32(len(entry.Data))
		}
		if uint64(len(entry.Data)) > limits.MaxFileBytes {
			limits.MaxFileBytes = uint64(len(entry.Data))
		}
		if uint64(len(entry.Data)) > ^uint64(0)-limits.MaxContentBytes {
			limits.MaxContentBytes = ^uint64(0)
		} else {
			limits.MaxContentBytes += uint64(len(entry.Data))
		}
	}
	bodySize, err := encodedBodySize(bundle.Entries)
	if err == nil && bodySize <= ^uint64(0)-headerSize {
		total := uint64(headerSize) + bodySize
		padding := paddingForAlignment(total, blockDeviceAlignment)
		if padding <= ^uint64(0)-total {
			limits.MaxBundleBytes = total + padding
		}
	} else {
		limits.MaxBundleBytes = ^uint64(0)
	}
	return limits
}
