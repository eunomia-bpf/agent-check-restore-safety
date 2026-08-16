package firecracker

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"unicode/utf8"

	"golang.org/x/sys/unix"
)

const (
	payloadManifestSchema     = 1
	maxPayloadToolStderrBytes = 64 << 10
)

// PayloadEntryType is the filesystem object represented by a manifest entry.
type PayloadEntryType string

const (
	PayloadEntryDirectory PayloadEntryType = "directory"
	PayloadEntryFile      PayloadEntryType = "file"
	PayloadEntrySymlink   PayloadEntryType = "symlink"
)

// PayloadManifestEntry describes one object below a payload source directory.
// Paths always use slash separators and are relative to the source. The source
// directory itself is represented by ".". SHA256 is populated only for regular
// files, and LinkTarget is populated only for symbolic links.
type PayloadManifestEntry struct {
	Path       string           `json:"path"`
	Type       PayloadEntryType `json:"type"`
	Mode       uint32           `json:"mode"`
	Size       int64            `json:"size"`
	SHA256     string           `json:"sha256"`
	LinkTarget string           `json:"link_target"`
}

// PayloadManifest is the canonical, path-sorted description of a payload.
// Its digest is SHA-256 over the compact JSON encoding of this structure.
type PayloadManifest struct {
	Schema  int                    `json:"schema"`
	Entries []PayloadManifestEntry `json:"entries"`
}

// PayloadBuildConfig identifies one source tree, one new output image, and the
// host mksquashfs implementation. MksquashfsPath defaults to the executable
// found as "mksquashfs" in PATH; an explicitly supplied path must be absolute.
type PayloadBuildConfig struct {
	SourceDir      string
	OutputPath     string
	MksquashfsPath string
}

// PayloadBuildResult binds the published image to the manifest used to build
// it. ImagePath is the cleaned absolute output path.
type PayloadBuildResult struct {
	ImagePath      string          `json:"image_path"`
	ImageSHA256    string          `json:"image_sha256"`
	ImageSize      int64           `json:"image_size"`
	Manifest       PayloadManifest `json:"manifest"`
	ManifestSHA256 string          `json:"manifest_sha256"`
}

// BuildSquashFSPayload validates and inventories a single source directory,
// invokes mksquashfs with deterministic options, and atomically publishes a
// new read-only SquashFS image without overwriting an existing path.
func BuildSquashFSPayload(ctx context.Context, config PayloadBuildConfig) (PayloadBuildResult, error) {
	if ctx == nil {
		return PayloadBuildResult{}, errors.New("build SquashFS payload requires a context")
	}
	source, output, tool, err := validatePayloadBuildConfig(config)
	if err != nil {
		return PayloadBuildResult{}, err
	}
	manifest, manifestDigest, err := scanPayloadManifest(source)
	if err != nil {
		return PayloadBuildResult{}, err
	}

	temporaryDirectory, err := os.MkdirTemp(filepath.Dir(output), ".payload-squashfs-")
	if err != nil {
		return PayloadBuildResult{}, fmt.Errorf("create temporary payload build directory: %w", err)
	}
	defer os.RemoveAll(temporaryDirectory)
	temporaryImage := filepath.Join(temporaryDirectory, "payload.squashfs")

	arguments := payloadMksquashfsArguments(source, temporaryImage)
	command := exec.CommandContext(ctx, tool, arguments...)
	command.Dir = temporaryDirectory
	command.Env = payloadToolEnvironment()
	command.Stdout = io.Discard
	var stderr payloadDiagnosticBuffer
	command.Stderr = &stderr
	if err := command.Run(); err != nil {
		diagnostic := stderr.String()
		if diagnostic == "" {
			return PayloadBuildResult{}, fmt.Errorf("run mksquashfs: %w", err)
		}
		return PayloadBuildResult{}, fmt.Errorf("run mksquashfs: %w; stderr: %s", err, diagnostic)
	}

	// A second inventory detects ordinary source changes during the external
	// build and prevents publishing an image with an already-stale manifest.
	postBuildManifest, postBuildDigest, err := scanPayloadManifest(source)
	if err != nil {
		return PayloadBuildResult{}, fmt.Errorf("revalidate payload source after mksquashfs: %w", err)
	}
	if postBuildDigest != manifestDigest {
		return PayloadBuildResult{}, fmt.Errorf("payload source changed during mksquashfs: manifest SHA-256 was %s, now %s", manifestDigest, postBuildDigest)
	}
	manifest = postBuildManifest

	imageDigest, imageSize, err := inspectPayloadImage(temporaryImage)
	if err != nil {
		return PayloadBuildResult{}, err
	}
	// The temporary image is on the output filesystem. link(2) therefore
	// publishes the complete inode atomically and fails if output now exists.
	if err := os.Link(temporaryImage, output); err != nil {
		if _, inspectErr := os.Lstat(output); inspectErr == nil {
			return PayloadBuildResult{}, fmt.Errorf("publish SquashFS payload: output path already exists: %q", output)
		}
		return PayloadBuildResult{}, fmt.Errorf("publish SquashFS payload %q: %w", output, err)
	}

	return PayloadBuildResult{
		ImagePath: output, ImageSHA256: imageDigest, ImageSize: imageSize,
		Manifest: manifest, ManifestSHA256: manifestDigest,
	}, nil
}

func validatePayloadBuildConfig(config PayloadBuildConfig) (string, string, string, error) {
	if strings.IndexByte(config.SourceDir, 0) >= 0 || strings.IndexByte(config.OutputPath, 0) >= 0 || strings.IndexByte(config.MksquashfsPath, 0) >= 0 {
		return "", "", "", errors.New("payload build configuration contains NUL")
	}
	if !utf8.ValidString(config.SourceDir) || !utf8.ValidString(config.OutputPath) || !utf8.ValidString(config.MksquashfsPath) {
		return "", "", "", errors.New("payload build paths must be valid UTF-8")
	}
	if !filepath.IsAbs(config.SourceDir) {
		return "", "", "", errors.New("payload source directory must be absolute")
	}
	if !filepath.IsAbs(config.OutputPath) {
		return "", "", "", errors.New("payload output path must be absolute")
	}
	source := filepath.Clean(config.SourceDir)
	output := filepath.Clean(config.OutputPath)

	sourceInfo, err := os.Lstat(source)
	if err != nil {
		return "", "", "", fmt.Errorf("inspect payload source directory: %w", err)
	}
	if sourceInfo.Mode()&os.ModeSymlink != 0 || !sourceInfo.IsDir() {
		return "", "", "", errors.New("payload source must be a real directory, not a symlink")
	}
	resolvedSource, err := filepath.EvalSymlinks(source)
	if err != nil {
		return "", "", "", fmt.Errorf("resolve payload source directory: %w", err)
	}
	if filepath.Clean(resolvedSource) != source {
		return "", "", "", errors.New("payload source directory path must not traverse a symlink")
	}

	parent := filepath.Dir(output)
	parentInfo, err := os.Lstat(parent)
	if err != nil {
		return "", "", "", fmt.Errorf("inspect payload output parent: %w", err)
	}
	if parentInfo.Mode()&os.ModeSymlink != 0 || !parentInfo.IsDir() {
		return "", "", "", errors.New("payload output parent must be a real directory, not a symlink")
	}
	resolvedParent, err := filepath.EvalSymlinks(parent)
	if err != nil {
		return "", "", "", fmt.Errorf("resolve payload output parent: %w", err)
	}
	if filepath.Clean(resolvedParent) != parent {
		return "", "", "", errors.New("payload output parent path must not traverse a symlink")
	}
	if payloadPathWithin(source, output) {
		return "", "", "", errors.New("payload output must be outside the source directory")
	}
	if _, err := os.Lstat(output); err == nil {
		return "", "", "", fmt.Errorf("payload output path already exists: %q", output)
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", "", "", fmt.Errorf("inspect payload output path: %w", err)
	}

	tool := config.MksquashfsPath
	if tool == "" {
		tool, err = exec.LookPath("mksquashfs")
		if err != nil {
			return "", "", "", fmt.Errorf("locate host mksquashfs: %w", err)
		}
		if !filepath.IsAbs(tool) {
			tool, err = filepath.Abs(tool)
			if err != nil {
				return "", "", "", fmt.Errorf("make mksquashfs path absolute: %w", err)
			}
		}
	} else if !filepath.IsAbs(tool) {
		return "", "", "", errors.New("mksquashfs path must be absolute")
	}
	return source, output, filepath.Clean(tool), nil
}

func scanPayloadManifest(source string) (PayloadManifest, string, error) {
	manifest := PayloadManifest{Schema: payloadManifestSchema}
	err := filepath.WalkDir(source, func(path string, _ fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		relative, err := filepath.Rel(source, path)
		if err != nil {
			return fmt.Errorf("make payload path relative: %w", err)
		}
		relative = filepath.ToSlash(relative)
		if !utf8.ValidString(relative) || strings.IndexByte(relative, 0) >= 0 {
			return fmt.Errorf("payload entry path is not valid UTF-8: %q", relative)
		}
		info, err := os.Lstat(path)
		if err != nil {
			return fmt.Errorf("inspect payload entry %q: %w", relative, err)
		}
		entry := PayloadManifestEntry{Path: relative, Mode: payloadMode(info.Mode())}
		switch {
		case info.IsDir():
			entry.Type = PayloadEntryDirectory
		case info.Mode().IsRegular():
			entry.Type = PayloadEntryFile
			digest, size, mode, err := inspectPayloadRegularFile(path, info)
			if err != nil {
				return fmt.Errorf("inspect payload file %q: %w", relative, err)
			}
			entry.Mode, entry.Size, entry.SHA256 = mode, size, digest
		case info.Mode()&os.ModeSymlink != 0:
			entry.Type = PayloadEntrySymlink
			target, err := os.Readlink(path)
			if err != nil {
				return fmt.Errorf("read payload symlink %q: %w", relative, err)
			}
			if strings.IndexByte(target, 0) >= 0 || !utf8.ValidString(target) {
				return fmt.Errorf("payload symlink %q target is not valid UTF-8", relative)
			}
			if filepath.IsAbs(target) {
				return fmt.Errorf("payload symlink %q has an absolute target", relative)
			}
			lexicalTarget := filepath.Clean(filepath.Join(filepath.Dir(path), target))
			if !payloadPathWithin(source, lexicalTarget) {
				return fmt.Errorf("payload symlink %q escapes the source directory", relative)
			}
			resolvedTarget, err := filepath.EvalSymlinks(path)
			if err != nil {
				return fmt.Errorf("resolve payload symlink %q: %w", relative, err)
			}
			if !payloadPathWithin(source, filepath.Clean(resolvedTarget)) {
				return fmt.Errorf("payload symlink %q resolves outside the source directory", relative)
			}
			entry.Size = int64(len(target))
			entry.LinkTarget = target
		default:
			return fmt.Errorf("payload entry %q has unsupported special file type %s", relative, info.Mode().Type())
		}
		manifest.Entries = append(manifest.Entries, entry)
		return nil
	})
	if err != nil {
		return PayloadManifest{}, "", fmt.Errorf("walk payload source: %w", err)
	}
	sort.Slice(manifest.Entries, func(left, right int) bool {
		return manifest.Entries[left].Path < manifest.Entries[right].Path
	})
	encoded, err := json.Marshal(manifest)
	if err != nil {
		return PayloadManifest{}, "", fmt.Errorf("encode payload manifest: %w", err)
	}
	digest := sha256.Sum256(encoded)
	return manifest, hex.EncodeToString(digest[:]), nil
}

func inspectPayloadRegularFile(path string, walkedInfo os.FileInfo) (string, int64, uint32, error) {
	descriptor, err := unix.Open(path, unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return "", 0, 0, err
	}
	file := os.NewFile(uintptr(descriptor), path)
	if file == nil {
		_ = unix.Close(descriptor)
		return "", 0, 0, errors.New("wrap payload file descriptor")
	}
	defer file.Close()
	openedInfo, err := file.Stat()
	if err != nil {
		return "", 0, 0, err
	}
	if !openedInfo.Mode().IsRegular() || !os.SameFile(walkedInfo, openedInfo) {
		return "", 0, 0, errors.New("payload file changed while it was opened")
	}
	digest := sha256.New()
	written, err := io.Copy(digest, file)
	if err != nil {
		return "", 0, 0, err
	}
	postReadInfo, err := file.Stat()
	if err != nil {
		return "", 0, 0, err
	}
	if written != openedInfo.Size() || postReadInfo.Size() != openedInfo.Size() || postReadInfo.Mode() != openedInfo.Mode() {
		return "", 0, 0, errors.New("payload file changed while it was hashed")
	}
	return hex.EncodeToString(digest.Sum(nil)), openedInfo.Size(), payloadMode(openedInfo.Mode()), nil
}

func inspectPayloadImage(path string) (string, int64, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return "", 0, fmt.Errorf("inspect mksquashfs output: %w", err)
	}
	if !info.Mode().IsRegular() || info.Size() <= 0 {
		return "", 0, errors.New("mksquashfs did not produce a non-empty regular image")
	}
	digest, size, _, err := inspectPayloadRegularFile(path, info)
	if err != nil {
		return "", 0, fmt.Errorf("hash mksquashfs output: %w", err)
	}
	return digest, size, nil
}

func payloadMksquashfsArguments(source, output string) []string {
	return []string{
		source, output,
		"-noappend",
		"-all-root",
		"-no-xattrs",
		"-no-progress",
		"-mkfs-time", "0",
		"-all-time", "0",
		"-processors", "1",
		"-comp", "zstd",
	}
}

func payloadToolEnvironment() []string {
	environment := make([]string, 0, len(os.Environ())+3)
	for _, item := range os.Environ() {
		name, _, _ := strings.Cut(item, "=")
		switch name {
		case "SOURCE_DATE_EPOCH", "TZ", "LC_ALL", "LANG":
			continue
		}
		environment = append(environment, item)
	}
	// mksquashfs 4.6 rejects SOURCE_DATE_EPOCH when -mkfs-time/-all-time
	// are supplied too. The explicit flags already fix both timestamps, so
	// remove any inherited epoch instead of setting a competing value.
	return append(environment, "TZ=UTC", "LC_ALL=C", "LANG=C")
}

func payloadPathWithin(root, candidate string) bool {
	relative, err := filepath.Rel(root, candidate)
	if err != nil || filepath.IsAbs(relative) || relative == ".." {
		return false
	}
	return !strings.HasPrefix(relative, ".."+string(filepath.Separator))
}

func payloadMode(mode os.FileMode) uint32 {
	value := uint32(mode.Perm())
	if mode&os.ModeSetuid != 0 {
		value |= 0o4000
	}
	if mode&os.ModeSetgid != 0 {
		value |= 0o2000
	}
	if mode&os.ModeSticky != 0 {
		value |= 0o1000
	}
	return value
}

type payloadDiagnosticBuffer struct {
	data      []byte
	truncated bool
}

func (buffer *payloadDiagnosticBuffer) Write(data []byte) (int, error) {
	written := len(data)
	remaining := maxPayloadToolStderrBytes - len(buffer.data)
	if remaining > 0 {
		if len(data) > remaining {
			buffer.data = append(buffer.data, data[:remaining]...)
			buffer.truncated = true
		} else {
			buffer.data = append(buffer.data, data...)
		}
	} else if len(data) > 0 {
		buffer.truncated = true
	}
	return written, nil
}

func (buffer *payloadDiagnosticBuffer) String() string {
	diagnostic := strings.TrimSpace(string(buffer.data))
	if buffer.truncated {
		if diagnostic != "" {
			diagnostic += "\n"
		}
		diagnostic += "[stderr truncated]"
	}
	return diagnostic
}
