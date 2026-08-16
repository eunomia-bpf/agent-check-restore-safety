// Command firecracker-codex-payload builds the immutable native Codex drive
// consumed by firecracker-codex-shim.
package main

import (
	"context"
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

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/firecracker"
)

type options struct {
	source, output, result, mksquashfs string
}

type payloadRecord struct {
	Schema  int                              `json:"schema"`
	Payload firecracker.PayloadBuildResult   `json:"payload"`
	Codex   firecracker.PayloadManifestEntry `json:"codex"`
}

type summary struct {
	PayloadPath    string `json:"payload_path"`
	PayloadSHA256  string `json:"payload_sha256"`
	PayloadSize    int64  `json:"payload_size"`
	CodexSHA256    string `json:"codex_sha256"`
	CodexSize      int64  `json:"codex_size"`
	ManifestSHA256 string `json:"manifest_sha256"`
	ResultPath     string `json:"result_path"`
}

func main() {
	var config options
	flag.StringVar(&config.source, "source", "", "absolute native Codex vendor bundle")
	flag.StringVar(&config.output, "output", "", "new absolute SquashFS output path")
	flag.StringVar(&config.result, "result", "", "new absolute JSON result path")
	flag.StringVar(&config.mksquashfs, "mksquashfs", "", "absolute mksquashfs executable (PATH lookup by default)")
	flag.Parse()
	if err := run(context.Background(), config, os.Stdout); err != nil {
		log.Printf("Codex payload build failed: %v", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, config options, stdout io.Writer) error {
	if stdout == nil {
		return errors.New("payload summary writer is nil")
	}
	resultPath, err := validateResultPath(config.result, config.source, config.output)
	if err != nil {
		return err
	}
	built, err := firecracker.BuildSquashFSPayload(ctx, firecracker.PayloadBuildConfig{
		SourceDir: config.source, OutputPath: config.output, MksquashfsPath: config.mksquashfs,
	})
	if err != nil {
		return err
	}
	codex, err := requireNativeCodex(built.Manifest)
	if err != nil {
		return fmt.Errorf("payload image %q was built but is unusable: %w", built.ImagePath, err)
	}
	record := payloadRecord{Schema: 1, Payload: built, Codex: codex}
	if err := writeExclusiveJSON(resultPath, record); err != nil {
		return fmt.Errorf("payload image %q was built but result publication failed: %w", built.ImagePath, err)
	}
	return writeJSONLine(stdout, summary{
		PayloadPath: built.ImagePath, PayloadSHA256: built.ImageSHA256, PayloadSize: built.ImageSize,
		CodexSHA256: codex.SHA256, CodexSize: codex.Size, ManifestSHA256: built.ManifestSHA256, ResultPath: resultPath,
	})
}

func requireNativeCodex(manifest firecracker.PayloadManifest) (firecracker.PayloadManifestEntry, error) {
	var matches []firecracker.PayloadManifestEntry
	for _, entry := range manifest.Entries {
		if entry.Path == "bin/codex" {
			matches = append(matches, entry)
		}
	}
	if len(matches) != 1 {
		return firecracker.PayloadManifestEntry{}, fmt.Errorf("manifest contains %d bin/codex entries, require one", len(matches))
	}
	codex := matches[0]
	if codex.Type != firecracker.PayloadEntryFile || codex.Size <= 0 || codex.Mode&0o111 == 0 || len(codex.SHA256) != 64 {
		return firecracker.PayloadManifestEntry{}, errors.New("bin/codex must be a nonempty executable regular file with SHA-256")
	}
	return codex, nil
}

func validateResultPath(result, source, output string) (string, error) {
	if result == "" || strings.IndexByte(result, 0) >= 0 || !filepath.IsAbs(result) || filepath.Clean(result) != result {
		return "", errors.New("payload result path must be absolute, canonical, and NUL-free")
	}
	if result == output {
		return "", errors.New("payload result and image paths must differ")
	}
	if filepath.IsAbs(source) && pathWithin(filepath.Clean(source), result) {
		return "", errors.New("payload result must be outside the source directory")
	}
	parent := filepath.Dir(result)
	resolved, err := filepath.EvalSymlinks(parent)
	if err != nil || filepath.Clean(resolved) != parent {
		return "", errors.New("payload result parent must exist without symlink traversal")
	}
	info, err := os.Lstat(parent)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || info.Mode().Perm() != 0o700 {
		return "", errors.New("payload result parent must be a real private directory with mode 0700")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != uint32(os.Geteuid()) {
		return "", errors.New("payload result parent must be owned by the current user")
	}
	if _, err := os.Lstat(result); err == nil {
		return "", errors.New("payload result path already exists")
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", fmt.Errorf("inspect payload result path: %w", err)
	}
	return result, nil
}

func pathWithin(root, candidate string) bool {
	relative, err := filepath.Rel(root, candidate)
	return err == nil && !filepath.IsAbs(relative) && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator))
}

func writeExclusiveJSON(path string, value any) error {
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return err
	}
	encoder := json.NewEncoder(file)
	encoder.SetEscapeHTML(false)
	writeErr := encoder.Encode(value)
	syncErr := file.Sync()
	closeErr := file.Close()
	return errors.Join(writeErr, syncErr, closeErr)
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
