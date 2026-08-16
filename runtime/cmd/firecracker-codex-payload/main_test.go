package main

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPayloadCommandBuildsAndPublishesNativeCodexIdentity(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0o700); err != nil {
		t.Fatal(err)
	}
	source := filepath.Join(root, "vendor")
	if err := os.MkdirAll(filepath.Join(source, "bin"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "bin", "codex"), []byte("native-codex"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "bin", "mcp-operation-relay"), []byte("native-mcp-relay"), 0o500); err != nil {
		t.Fatal(err)
	}
	tool := fakeMksquashfs(t, root)
	output := filepath.Join(root, "payload.squashfs")
	result := filepath.Join(root, "payload.json")
	var stdout bytes.Buffer
	if err := run(context.Background(), options{source: source, output: output, result: result, mksquashfs: tool, requireMCPRelay: true}, &stdout); err != nil {
		t.Fatal(err)
	}
	var got summary
	if err := json.Unmarshal(stdout.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got.PayloadPath != output || len(got.PayloadSHA256) != 64 || len(got.CodexSHA256) != 64 || got.CodexSize != int64(len("native-codex")) || got.ResultPath != result {
		t.Fatalf("summary = %+v", got)
	}
	info, err := os.Stat(result)
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("result mode=%v err=%v", info, err)
	}
	var record payloadRecord
	data, _ := os.ReadFile(result)
	if err := json.Unmarshal(data, &record); err != nil || record.Codex.Path != "bin/codex" || record.Codex.SHA256 != got.CodexSHA256 {
		t.Fatalf("record=%+v err=%v", record, err)
	}
}

func TestPayloadCommandCanRequireMCPRelay(t *testing.T) {
	root := t.TempDir()
	if err := os.Chmod(root, 0o700); err != nil {
		t.Fatal(err)
	}
	source := filepath.Join(root, "vendor")
	if err := os.MkdirAll(filepath.Join(source, "bin"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "bin", "codex"), []byte("native-codex"), 0o700); err != nil {
		t.Fatal(err)
	}
	err := run(context.Background(), options{
		source: source, output: filepath.Join(root, "payload"), result: filepath.Join(root, "result"),
		mksquashfs: fakeMksquashfs(t, root), requireMCPRelay: true,
	}, &bytes.Buffer{})
	if err == nil || !strings.Contains(err.Error(), "bin/mcp-operation-relay") {
		t.Fatalf("missing MCP relay error = %v", err)
	}
}

func TestPayloadCommandRejectsMissingNonExecutableAndExistingResult(t *testing.T) {
	for _, executable := range []bool{false, true} {
		t.Run(map[bool]string{false: "non-executable", true: "missing"}[executable], func(t *testing.T) {
			root := t.TempDir()
			_ = os.Chmod(root, 0o700)
			source := filepath.Join(root, "vendor")
			_ = os.MkdirAll(filepath.Join(source, "bin"), 0o700)
			if !executable {
				_ = os.WriteFile(filepath.Join(source, "bin", "codex"), []byte("x"), 0o600)
			}
			err := run(context.Background(), options{source: source, output: filepath.Join(root, "payload"), result: filepath.Join(root, "result"), mksquashfs: fakeMksquashfs(t, root)}, &bytes.Buffer{})
			if err == nil || !strings.Contains(err.Error(), "bin/codex") {
				t.Fatalf("error=%v", err)
			}
		})
	}
	root := t.TempDir()
	_ = os.Chmod(root, 0o700)
	result := filepath.Join(root, "existing")
	_ = os.WriteFile(result, []byte("keep"), 0o600)
	if _, err := validateResultPath(result, filepath.Join(root, "source"), filepath.Join(root, "image")); err == nil {
		t.Fatal("existing result accepted")
	}
}

func fakeMksquashfs(t *testing.T, root string) string {
	t.Helper()
	tool := filepath.Join(root, "mksquashfs-"+strings.ReplaceAll(t.Name(), "/", "-"))
	script := "#!/bin/sh\nset -eu\nprintf 'squashfs-fixture' > \"$2\"\n"
	if err := os.WriteFile(tool, []byte(script), 0o700); err != nil {
		t.Fatal(err)
	}
	return tool
}
