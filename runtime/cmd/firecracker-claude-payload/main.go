// Command firecracker-claude-payload builds the immutable SquashFS drive for
// the official Claude Code binary, its fixed MCP relay, and the minimal glibc
// runtime selected by the host build.
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/firecracker"
)

type options struct {
	claude, claudeSHA, relay, busybox, bash, bashLibrary, output, result, mksquashfs string
	loader, libraryDirectory                                                         string
}

type inputRecord struct {
	Path   string `json:"path"`
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256"`
}

type payloadRecord struct {
	Schema  int                            `json:"schema"`
	Payload firecracker.PayloadBuildResult `json:"payload"`
	Inputs  map[string]inputRecord         `json:"inputs"`
}

var libraries = []string{"libc.so.6", "libdl.so.2", "libm.so.6", "libpthread.so.0", "librt.so.1"}

const bashLibrary = "libtinfo.so.6"

func main() {
	var config options
	flag.StringVar(&config.claude, "claude", "", "pinned official Claude executable")
	flag.StringVar(&config.claudeSHA, "claude-sha256", "", "required Claude SHA-256")
	flag.StringVar(&config.relay, "relay", "", "static MCP operation relay")
	flag.StringVar(&config.busybox, "busybox", "", "optional static BusyBox for the HTTP/Bash profile")
	flag.StringVar(&config.bash, "bash", "", "Bash executable for the HTTP/Bash profile")
	flag.StringVar(&config.bashLibrary, "bash-library", "", "direct libtinfo.so.6 file for Bash")
	flag.StringVar(&config.loader, "loader", "/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2", "glibc dynamic loader")
	flag.StringVar(&config.libraryDirectory, "library-directory", "/lib/x86_64-linux-gnu", "directory containing the fixed glibc libraries")
	flag.StringVar(&config.output, "output", "", "new absolute SquashFS output")
	flag.StringVar(&config.result, "result", "", "new absolute result JSON")
	flag.StringVar(&config.mksquashfs, "mksquashfs", "", "absolute mksquashfs executable (PATH lookup by default)")
	flag.Parse()
	if err := run(context.Background(), config, os.Stdout); err != nil {
		log.Printf("Claude payload build failed: %v", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, config options, stdout io.Writer) error {
	if ctx == nil || stdout == nil {
		return errors.New("Claude payload build requires context and stdout")
	}
	for label, value := range map[string]string{"Claude": config.claude, "Claude SHA-256": config.claudeSHA, "relay": config.relay, "loader": config.loader, "library directory": config.libraryDirectory, "output": config.output, "result": config.result} {
		if value == "" {
			return fmt.Errorf("%s is required", label)
		}
	}
	for _, path := range []string{config.claude, config.relay, config.loader, config.libraryDirectory, config.output, config.result} {
		if !filepath.IsAbs(path) || filepath.Clean(path) != path || strings.IndexByte(path, 0) >= 0 {
			return fmt.Errorf("payload path must be absolute, canonical, and NUL-free: %q", path)
		}
	}
	if config.busybox != "" && (!filepath.IsAbs(config.busybox) || filepath.Clean(config.busybox) != config.busybox || strings.IndexByte(config.busybox, 0) >= 0) {
		return fmt.Errorf("BusyBox path must be absolute, canonical, and NUL-free: %q", config.busybox)
	}
	if (config.busybox == "") != (config.bash == "") || (config.bash == "") != (config.bashLibrary == "") {
		return errors.New("BusyBox, Bash, and the Bash library must be supplied together")
	}
	if config.bash != "" && (!filepath.IsAbs(config.bash) || filepath.Clean(config.bash) != config.bash || strings.IndexByte(config.bash, 0) >= 0) {
		return fmt.Errorf("Bash path must be absolute, canonical, and NUL-free: %q", config.bash)
	}
	if config.bashLibrary != "" && (!filepath.IsAbs(config.bashLibrary) || filepath.Clean(config.bashLibrary) != config.bashLibrary || strings.IndexByte(config.bashLibrary, 0) >= 0) {
		return fmt.Errorf("Bash library path must be absolute, canonical, and NUL-free: %q", config.bashLibrary)
	}
	if config.output == config.result {
		return errors.New("payload output and result paths must differ")
	}
	resultParent, err := requirePrivateParent(config.result)
	if err != nil {
		return err
	}
	if outputParent, err := requirePrivateParent(config.output); err != nil || !os.SameFile(resultParent, outputParent) {
		return errors.New("payload output and result must share one private parent")
	}
	for _, path := range []string{config.output, config.result} {
		if _, err := os.Lstat(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
	}
	outputInfo, outputErr := os.Lstat(config.output)
	resultInfo, resultErr := os.Lstat(config.result)
	if outputErr == nil || resultErr == nil {
		if outputErr != nil || resultErr != nil || !outputInfo.Mode().IsRegular() || !resultInfo.Mode().IsRegular() {
			return errors.New("existing Claude payload cache is incomplete or unsafe")
		}
		return verifyExisting(config, stdout)
	}

	staging, err := os.MkdirTemp(filepath.Dir(config.output), ".claude-payload-source-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(staging)
	if err := os.Chmod(staging, 0o755); err != nil {
		return fmt.Errorf("make payload root traversable by the guest identity: %w", err)
	}
	for _, directory := range []string{"bin", "lib", "lib64", "lib/x86_64-linux-gnu"} {
		path := filepath.Join(staging, directory)
		if err := os.MkdirAll(path, 0o755); err != nil {
			return err
		}
		if err := os.Chmod(path, 0o755); err != nil {
			return fmt.Errorf("make payload directory %s traversable: %w", directory, err)
		}
	}
	inputs := make(map[string]inputRecord)
	copyInput := func(name, source, relative, expected string, executable bool) error {
		record, err := copyVerified(source, filepath.Join(staging, relative), expected, executable)
		if err != nil {
			return fmt.Errorf("stage %s: %w", name, err)
		}
		inputs[name] = record
		return nil
	}
	if err := copyInput("claude", config.claude, "bin/claude", config.claudeSHA, true); err != nil {
		return err
	}
	if err := copyInput("mcp_operation_relay", config.relay, "bin/mcp-operation-relay", "", true); err != nil {
		return err
	}
	if config.busybox != "" {
		if err := copyInput("busybox", config.busybox, "bin/busybox", "", true); err != nil {
			return err
		}
		if err := copyInput("bash", config.bash, "bin/bash", "", true); err != nil {
			return err
		}
	}
	if err := copyInput("loader", config.loader, "lib64/ld-linux-x86-64.so.2", "", true); err != nil {
		return err
	}
	for _, library := range selectedLibraries(config.busybox != "") {
		if err := copyInput(library, librarySource(config, library), filepath.Join("lib/x86_64-linux-gnu", library), "", false); err != nil {
			return err
		}
	}
	built, err := firecracker.BuildSquashFSPayload(ctx, firecracker.PayloadBuildConfig{
		SourceDir: staging, OutputPath: config.output, MksquashfsPath: config.mksquashfs,
	})
	if err != nil {
		return err
	}
	if err := requireManifest(built.Manifest, inputs); err != nil {
		return fmt.Errorf("built payload is unusable: %w", err)
	}
	schema := 1
	if config.busybox != "" {
		schema = 2
	}
	record := payloadRecord{Schema: schema, Payload: built, Inputs: inputs}
	if err := writeExclusiveJSON(config.result, record); err != nil {
		return err
	}
	return json.NewEncoder(stdout).Encode(map[string]any{
		"payload_path": built.ImagePath, "payload_sha256": built.ImageSHA256,
		"payload_size": built.ImageSize, "manifest_sha256": built.ManifestSHA256,
		"claude_sha256": inputs["claude"].SHA256, "relay_sha256": inputs["mcp_operation_relay"].SHA256,
		"busybox_sha256": inputHash(inputs, "busybox"),
		"bash_sha256":    inputHash(inputs, "bash"),
		"result_path":    config.result,
	})
}

func verifyExisting(config options, stdout io.Writer) error {
	var record payloadRecord
	data, err := os.ReadFile(config.result)
	expectedSchema := 1
	if config.busybox != "" {
		expectedSchema = 2
	}
	if err != nil || json.Unmarshal(data, &record) != nil || record.Schema != expectedSchema {
		return errors.New("existing Claude payload result is malformed")
	}
	payload, err := os.ReadFile(config.output)
	if err != nil {
		return err
	}
	digest := sha256.Sum256(payload)
	if record.Payload.ImagePath != config.output || record.Payload.ImageSize != int64(len(payload)) || record.Payload.ImageSHA256 != hex.EncodeToString(digest[:]) {
		return errors.New("existing Claude payload differs from its result")
	}
	sources := map[string]string{"claude": config.claude, "mcp_operation_relay": config.relay, "loader": config.loader}
	if config.busybox != "" {
		sources["busybox"] = config.busybox
		sources["bash"] = config.bash
	}
	for _, library := range selectedLibraries(config.busybox != "") {
		sources[library] = librarySource(config, library)
	}
	for name, source := range sources {
		value, ok := record.Inputs[name]
		if !ok || value.Path != source {
			return fmt.Errorf("existing Claude payload omits input %s", name)
		}
		raw, err := os.ReadFile(source)
		if err != nil {
			return err
		}
		hash := sha256.Sum256(raw)
		if value.Size != int64(len(raw)) || value.SHA256 != hex.EncodeToString(hash[:]) {
			return fmt.Errorf("existing Claude payload input %s changed", name)
		}
	}
	if record.Inputs["claude"].SHA256 != config.claudeSHA {
		return errors.New("existing Claude payload contains a different Claude binary")
	}
	if err := requireManifest(record.Payload.Manifest, record.Inputs); err != nil {
		return fmt.Errorf("existing Claude payload manifest is unusable: %w", err)
	}
	return json.NewEncoder(stdout).Encode(map[string]any{
		"payload_path": record.Payload.ImagePath, "payload_sha256": record.Payload.ImageSHA256,
		"payload_size": record.Payload.ImageSize, "manifest_sha256": record.Payload.ManifestSHA256,
		"claude_sha256":  record.Inputs["claude"].SHA256,
		"relay_sha256":   record.Inputs["mcp_operation_relay"].SHA256,
		"busybox_sha256": inputHash(record.Inputs, "busybox"),
		"bash_sha256":    inputHash(record.Inputs, "bash"),
		"result_path":    config.result, "reused": true,
	})
}

func requirePrivateParent(path string) (os.FileInfo, error) {
	parent := filepath.Dir(path)
	resolved, err := filepath.EvalSymlinks(parent)
	if err != nil || filepath.Clean(resolved) != parent {
		return nil, errors.New("payload parent must not traverse symlinks")
	}
	info, err := os.Lstat(parent)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() || info.Mode().Perm() != 0o700 {
		return nil, errors.New("payload parent must be a direct private 0700 directory")
	}
	return info, nil
}

func copyVerified(source, target, expected string, executable bool) (inputRecord, error) {
	info, err := os.Lstat(source)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Size() <= 0 {
		return inputRecord{}, errors.New("source is not a nonempty direct regular file")
	}
	input, err := os.Open(source)
	if err != nil {
		return inputRecord{}, err
	}
	defer input.Close()
	mode := os.FileMode(0o444)
	if executable {
		mode = 0o555
	}
	output, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
	if err != nil {
		return inputRecord{}, err
	}
	if err := output.Chmod(mode); err != nil {
		_ = output.Close()
		return inputRecord{}, err
	}
	digest := sha256.New()
	written, copyErr := io.Copy(io.MultiWriter(output, digest), input)
	closeErr := errors.Join(output.Sync(), output.Close())
	if copyErr != nil || closeErr != nil || written != info.Size() {
		return inputRecord{}, errors.Join(copyErr, closeErr, errors.New("source changed or copy was short"))
	}
	hash := hex.EncodeToString(digest.Sum(nil))
	if expected != "" && hash != expected {
		return inputRecord{}, fmt.Errorf("SHA-256 is %s, require %s", hash, expected)
	}
	return inputRecord{Path: source, Size: written, SHA256: hash}, nil
}

func requireManifest(manifest firecracker.PayloadManifest, inputs map[string]inputRecord) error {
	expected := []string{"bin/claude", "bin/mcp-operation-relay", "lib64/ld-linux-x86-64.so.2"}
	if _, ok := inputs["busybox"]; ok {
		expected = append(expected, "bin/bash", "bin/busybox")
	}
	for _, library := range selectedLibraries(inputs["busybox"].Path != "") {
		expected = append(expected, filepath.ToSlash(filepath.Join("lib/x86_64-linux-gnu", library)))
	}
	sort.Strings(expected)
	files := make([]string, 0, len(expected))
	for _, entry := range manifest.Entries {
		if entry.Type == firecracker.PayloadEntryDirectory && entry.Mode&0o005 != 0o005 {
			return fmt.Errorf("payload directory %q is not world-readable and traversable", entry.Path)
		}
		if entry.Type == firecracker.PayloadEntryFile {
			files = append(files, entry.Path)
			if strings.HasPrefix(entry.Path, "bin/") || entry.Path == "lib64/ld-linux-x86-64.so.2" {
				if entry.Mode&0o005 != 0o005 {
					return fmt.Errorf("payload executable %q is not readable and executable by the guest identity", entry.Path)
				}
			} else if entry.Mode&0o004 == 0 {
				return fmt.Errorf("payload library %q is not readable by the guest identity", entry.Path)
			}
		}
	}
	sort.Strings(files)
	if strings.Join(files, "\n") != strings.Join(expected, "\n") {
		return fmt.Errorf("payload files are %q, require %q", files, expected)
	}
	if len(inputs) != len(expected) {
		return errors.New("payload input inventory is incomplete")
	}
	return nil
}

func selectedLibraries(withBash bool) []string {
	selected := append([]string(nil), libraries...)
	if withBash {
		selected = append(selected, bashLibrary)
	}
	return selected
}

func librarySource(config options, library string) string {
	if library == bashLibrary {
		return config.bashLibrary
	}
	return filepath.Join(config.libraryDirectory, library)
}

func inputHash(inputs map[string]inputRecord, name string) string {
	if record, ok := inputs[name]; ok {
		return record.SHA256
	}
	return ""
}

func writeExclusiveJSON(path string, value any) error {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	encoder := json.NewEncoder(file)
	encoder.SetEscapeHTML(false)
	writeErr := encoder.Encode(value)
	return errors.Join(writeErr, file.Sync(), file.Close())
}
