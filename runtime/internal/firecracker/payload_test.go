package firecracker

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"golang.org/x/sys/unix"
)

func TestBuildSquashFSPayloadManifestAndDeterministicArguments(t *testing.T) {
	workspace := t.TempDir()
	source := filepath.Join(workspace, "source")
	outputDirectory := filepath.Join(workspace, "output")
	if err := os.Mkdir(source, 0o750); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(source, 0o750); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(outputDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "z.txt"), []byte("last by path\n"), 0o640); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(filepath.Join(source, "z.txt"), 0o640); err != nil {
		t.Fatal(err)
	}
	nested := filepath.Join(source, "nested")
	if err := os.Mkdir(nested, 0o711); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(nested, 0o711); err != nil {
		t.Fatal(err)
	}
	nestedContents := []byte("nested payload")
	if err := os.WriteFile(filepath.Join(nested, "data"), nestedContents, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(filepath.Join(nested, "data"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("nested/data", filepath.Join(source, "a-link")); err != nil {
		t.Fatal(err)
	}

	tool, invocation := newFakeMksquashfs(t, `printf 'deterministic squashfs bytes' > "$2"`)
	output := filepath.Join(outputDirectory, "payload.squashfs")
	result, err := BuildSquashFSPayload(context.Background(), PayloadBuildConfig{
		SourceDir: source, OutputPath: output, MksquashfsPath: tool,
	})
	if err != nil {
		t.Fatal(err)
	}

	wantPaths := []string{".", "a-link", "nested", "nested/data", "z.txt"}
	gotPaths := make([]string, len(result.Manifest.Entries))
	entries := make(map[string]PayloadManifestEntry, len(result.Manifest.Entries))
	for index, entry := range result.Manifest.Entries {
		gotPaths[index] = entry.Path
		entries[entry.Path] = entry
	}
	if !reflect.DeepEqual(gotPaths, wantPaths) {
		t.Fatalf("manifest paths = %q, want %q", gotPaths, wantPaths)
	}
	if result.Manifest.Schema != payloadManifestSchema {
		t.Fatalf("manifest schema = %d", result.Manifest.Schema)
	}
	if entry := entries["."]; entry.Type != PayloadEntryDirectory || entry.Mode != 0o750 || entry.Size != 0 || entry.SHA256 != "" || entry.LinkTarget != "" {
		t.Fatalf("root manifest entry = %+v", entry)
	}
	if entry := entries["nested"]; entry.Type != PayloadEntryDirectory || entry.Mode != 0o711 || entry.Size != 0 {
		t.Fatalf("directory manifest entry = %+v", entry)
	}
	wantNestedDigest := sha256.Sum256(nestedContents)
	if entry := entries["nested/data"]; entry.Type != PayloadEntryFile || entry.Mode != 0o600 || entry.Size != int64(len(nestedContents)) || entry.SHA256 != hex.EncodeToString(wantNestedDigest[:]) || entry.LinkTarget != "" {
		t.Fatalf("file manifest entry = %+v", entry)
	}
	if entry := entries["a-link"]; entry.Type != PayloadEntrySymlink || entry.Size != int64(len("nested/data")) || entry.SHA256 != "" || entry.LinkTarget != "nested/data" {
		t.Fatalf("symlink manifest entry = %+v", entry)
	}
	manifestJSON, err := json.Marshal(result.Manifest)
	if err != nil {
		t.Fatal(err)
	}
	wantManifestDigest := sha256.Sum256(manifestJSON)
	if result.ManifestSHA256 != hex.EncodeToString(wantManifestDigest[:]) {
		t.Fatalf("manifest SHA-256 = %q, want %x", result.ManifestSHA256, wantManifestDigest)
	}
	wantImage := []byte("deterministic squashfs bytes")
	wantImageDigest := sha256.Sum256(wantImage)
	if result.ImagePath != output || result.ImageSize != int64(len(wantImage)) || result.ImageSHA256 != hex.EncodeToString(wantImageDigest[:]) {
		t.Fatalf("image result = %+v", result)
	}
	gotImage, err := os.ReadFile(output)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(gotImage, wantImage) {
		t.Fatalf("image = %q", gotImage)
	}

	arguments := readFakeInvocation(t, invocation)
	if len(arguments) < 2 || arguments[0] != source || filepath.Base(arguments[1]) != "payload.squashfs" || filepath.Dir(filepath.Dir(arguments[1])) != outputDirectory || !strings.HasPrefix(filepath.Base(filepath.Dir(arguments[1])), ".payload-squashfs-") {
		t.Fatalf("mksquashfs source/output arguments = %q", arguments)
	}
	wantOptions := []string{
		"-noappend", "-all-root", "-no-xattrs", "-no-progress",
		"-mkfs-time", "0", "-all-time", "0", "-processors", "1", "-comp", "zstd",
	}
	if !reflect.DeepEqual(arguments[2:], wantOptions) {
		t.Fatalf("mksquashfs options = %q, want %q", arguments[2:], wantOptions)
	}

	secondTool, _ := newFakeMksquashfs(t, `printf 'deterministic squashfs bytes' > "$2"`)
	second, err := BuildSquashFSPayload(context.Background(), PayloadBuildConfig{
		SourceDir: source, OutputPath: filepath.Join(outputDirectory, "payload-2.squashfs"), MksquashfsPath: secondTool,
	})
	if err != nil {
		t.Fatal(err)
	}
	if second.ManifestSHA256 != result.ManifestSHA256 || second.ImageSHA256 != result.ImageSHA256 || !reflect.DeepEqual(second.Manifest, result.Manifest) {
		t.Fatalf("repeat build differs: first=%+v second=%+v", result, second)
	}
}

func TestBuildSquashFSPayloadRejectsInvalidSourcesAndEntries(t *testing.T) {
	workspace := t.TempDir()
	outputDirectory := filepath.Join(workspace, "output")
	if err := os.Mkdir(outputDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	tool, _ := newFakeMksquashfs(t, `printf image > "$2"`)

	t.Run("relative source", func(t *testing.T) {
		expectPayloadBuildError(t, PayloadBuildConfig{
			SourceDir: "relative", OutputPath: filepath.Join(outputDirectory, "relative.squashfs"), MksquashfsPath: tool,
		}, "source directory must be absolute")
	})

	t.Run("source symlink", func(t *testing.T) {
		realSource := filepath.Join(workspace, "real-source")
		if err := os.Mkdir(realSource, 0o700); err != nil {
			t.Fatal(err)
		}
		linkSource := filepath.Join(workspace, "source-link")
		if err := os.Symlink(realSource, linkSource); err != nil {
			t.Fatal(err)
		}
		expectPayloadBuildError(t, PayloadBuildConfig{
			SourceDir: linkSource, OutputPath: filepath.Join(outputDirectory, "link.squashfs"), MksquashfsPath: tool,
		}, "real directory")
	})

	t.Run("escaping symlink", func(t *testing.T) {
		source := filepath.Join(workspace, "escaping-source")
		if err := os.Mkdir(source, 0o700); err != nil {
			t.Fatal(err)
		}
		outside := filepath.Join(workspace, "outside")
		if err := os.WriteFile(outside, []byte("outside"), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink("../outside", filepath.Join(source, "escape")); err != nil {
			t.Fatal(err)
		}
		expectPayloadBuildError(t, PayloadBuildConfig{
			SourceDir: source, OutputPath: filepath.Join(outputDirectory, "escape.squashfs"), MksquashfsPath: tool,
		}, "escapes the source directory")
	})

	t.Run("absolute symlink", func(t *testing.T) {
		source := filepath.Join(workspace, "absolute-source")
		if err := os.Mkdir(source, 0o700); err != nil {
			t.Fatal(err)
		}
		target := filepath.Join(source, "target")
		if err := os.WriteFile(target, []byte("target"), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(target, filepath.Join(source, "absolute")); err != nil {
			t.Fatal(err)
		}
		expectPayloadBuildError(t, PayloadBuildConfig{
			SourceDir: source, OutputPath: filepath.Join(outputDirectory, "absolute.squashfs"), MksquashfsPath: tool,
		}, "absolute target")
	})

	t.Run("fifo", func(t *testing.T) {
		source := filepath.Join(workspace, "fifo-source")
		if err := os.Mkdir(source, 0o700); err != nil {
			t.Fatal(err)
		}
		if err := unix.Mkfifo(filepath.Join(source, "pipe"), 0o600); err != nil {
			t.Fatal(err)
		}
		expectPayloadBuildError(t, PayloadBuildConfig{
			SourceDir: source, OutputPath: filepath.Join(outputDirectory, "fifo.squashfs"), MksquashfsPath: tool,
		}, "unsupported special file type")
	})

	t.Run("socket", func(t *testing.T) {
		source := filepath.Join(workspace, "socket-source")
		if err := os.Mkdir(source, 0o700); err != nil {
			t.Fatal(err)
		}
		listener, err := net.Listen("unix", filepath.Join(source, "socket"))
		if err != nil {
			t.Fatal(err)
		}
		defer listener.Close()
		expectPayloadBuildError(t, PayloadBuildConfig{
			SourceDir: source, OutputPath: filepath.Join(outputDirectory, "socket.squashfs"), MksquashfsPath: tool,
		}, "unsupported special file type")
	})

	t.Run("NUL", func(t *testing.T) {
		expectPayloadBuildError(t, PayloadBuildConfig{
			SourceDir: workspace + "\x00source", OutputPath: filepath.Join(outputDirectory, "nul.squashfs"), MksquashfsPath: tool,
		}, "contains NUL")
	})
}

func TestBuildSquashFSPayloadValidatesOutputAndNeverOverwrites(t *testing.T) {
	workspace := t.TempDir()
	source := filepath.Join(workspace, "source")
	outputDirectory := filepath.Join(workspace, "output")
	if err := os.Mkdir(source, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "data"), []byte("payload"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(outputDirectory, 0o700); err != nil {
		t.Fatal(err)
	}

	t.Run("existing target", func(t *testing.T) {
		output := filepath.Join(outputDirectory, "existing.squashfs")
		if err := os.WriteFile(output, []byte("keep me"), 0o600); err != nil {
			t.Fatal(err)
		}
		tool, invocation := newFakeMksquashfs(t, `printf replacement > "$2"`)
		expectPayloadBuildError(t, PayloadBuildConfig{
			SourceDir: source, OutputPath: output, MksquashfsPath: tool,
		}, "already exists")
		contents, err := os.ReadFile(output)
		if err != nil {
			t.Fatal(err)
		}
		if string(contents) != "keep me" {
			t.Fatalf("existing output was overwritten: %q", contents)
		}
		if _, err := os.Stat(invocation); !os.IsNotExist(err) {
			t.Fatalf("mksquashfs ran despite existing output: %v", err)
		}
	})

	t.Run("target created during build", func(t *testing.T) {
		output := filepath.Join(outputDirectory, "raced.squashfs")
		tool, _ := newFakeMksquashfs(t, "printf 'racer wins' > "+shellQuote(output)+"\nprintf image > \"$2\"")
		expectPayloadBuildError(t, PayloadBuildConfig{
			SourceDir: source, OutputPath: output, MksquashfsPath: tool,
		}, "already exists")
		contents, err := os.ReadFile(output)
		if err != nil {
			t.Fatal(err)
		}
		if string(contents) != "racer wins" {
			t.Fatalf("racing output was overwritten: %q", contents)
		}
	})

	t.Run("missing parent", func(t *testing.T) {
		tool, _ := newFakeMksquashfs(t, `printf image > "$2"`)
		expectPayloadBuildError(t, PayloadBuildConfig{
			SourceDir: source, OutputPath: filepath.Join(workspace, "missing", "payload.squashfs"), MksquashfsPath: tool,
		}, "output parent")
	})

	t.Run("relative output", func(t *testing.T) {
		tool, _ := newFakeMksquashfs(t, `printf image > "$2"`)
		expectPayloadBuildError(t, PayloadBuildConfig{
			SourceDir: source, OutputPath: "payload.squashfs", MksquashfsPath: tool,
		}, "output path must be absolute")
	})

	t.Run("output in source", func(t *testing.T) {
		tool, _ := newFakeMksquashfs(t, `printf image > "$2"`)
		expectPayloadBuildError(t, PayloadBuildConfig{
			SourceDir: source, OutputPath: filepath.Join(source, "payload.squashfs"), MksquashfsPath: tool,
		}, "outside the source directory")
	})
}

func TestBuildSquashFSPayloadReportsMksquashfsStderr(t *testing.T) {
	workspace := t.TempDir()
	source := filepath.Join(workspace, "source")
	if err := os.Mkdir(source, 0o700); err != nil {
		t.Fatal(err)
	}
	tool, _ := newFakeMksquashfs(t, "echo 'synthetic compressor failure' >&2\nexit 17")
	output := filepath.Join(workspace, "payload.squashfs")
	_, err := BuildSquashFSPayload(context.Background(), PayloadBuildConfig{
		SourceDir: source, OutputPath: output, MksquashfsPath: tool,
	})
	if err == nil || !strings.Contains(err.Error(), "synthetic compressor failure") || !strings.Contains(err.Error(), "exit status 17") {
		t.Fatalf("mksquashfs failure = %v", err)
	}
	if _, err := os.Lstat(output); !os.IsNotExist(err) {
		t.Fatalf("failed build published output: %v", err)
	}
}

func expectPayloadBuildError(t *testing.T, config PayloadBuildConfig, want string) {
	t.Helper()
	_, err := BuildSquashFSPayload(context.Background(), config)
	if err == nil || !strings.Contains(err.Error(), want) {
		t.Fatalf("build error = %v, want substring %q", err, want)
	}
}

func newFakeMksquashfs(t *testing.T, body string) (string, string) {
	t.Helper()
	directory := t.TempDir()
	tool := filepath.Join(directory, "mksquashfs")
	invocation := filepath.Join(directory, "arguments")
	script := "#!/bin/sh\nset -eu\nprintf '%s\\n' \"$@\" > " + shellQuote(invocation) + "\n" + body + "\n"
	if err := os.WriteFile(tool, []byte(script), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(tool, 0o700); err != nil {
		t.Fatal(err)
	}
	return tool, invocation
}

func readFakeInvocation(t *testing.T, path string) []string {
	t.Helper()
	contents, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimSuffix(string(contents), "\n"), "\n")
}

func shellQuote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "'\"'\"'") + "'"
}
