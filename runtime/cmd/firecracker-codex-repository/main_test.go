package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/repobundle"
)

func TestCommandBuildsAndPublishesRepositoryIdentity(t *testing.T) {
	root := privateTempDir(t)
	source := filepath.Join(root, "source")
	if err := os.Mkdir(source, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "main.go"), []byte("package main\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(source, "scripts"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "scripts", "test"), []byte("#!/bin/sh\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	output := filepath.Join(root, "repository.bundle")
	result := filepath.Join(root, "repository.json")
	var stdout bytes.Buffer
	if err := run(options{source: source, output: output, result: result}, &stdout); err != nil {
		t.Fatal(err)
	}
	var got summary
	if err := json.Unmarshal(stdout.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got.Schema != 1 || got.RepositoryPath != output || got.ResultPath != result || got.EntryCount != 3 || got.FileCount != 2 || got.DirectoryCount != 1 || len(got.RepositorySHA256) != 64 || len(got.TreeRoot) != 64 {
		t.Fatalf("summary = %+v", got)
	}
	resultInfo, err := os.Stat(result)
	if err != nil || resultInfo.Mode().Perm() != 0o600 {
		t.Fatalf("identity info=%v err=%v", resultInfo, err)
	}
	var record repositoryRecord
	data, err := os.ReadFile(result)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(data, &record); err != nil || record.TreeRoot != got.TreeRoot || record.RepositorySHA256 != got.RepositorySHA256 {
		t.Fatalf("record=%+v err=%v", record, err)
	}
	bundleFile, err := os.Open(output)
	if err != nil {
		t.Fatal(err)
	}
	bundle, decodeErr := repobundle.Decode(bundleFile, repobundle.DefaultLimits())
	closeErr := bundleFile.Close()
	if decodeErr != nil || closeErr != nil || bundle.TreeRoot.String() != got.TreeRoot {
		t.Fatalf("bundle root=%s decode=%v close=%v", bundle.TreeRoot, decodeErr, closeErr)
	}
}

func TestCommandIsDeterministicAndNeverOverwrites(t *testing.T) {
	root := privateTempDir(t)
	source := filepath.Join(root, "source")
	if err := os.Mkdir(source, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(source, "a"), []byte{0, 1, 2}, 0o600); err != nil {
		t.Fatal(err)
	}
	firstOutput, firstResult := filepath.Join(root, "first.bundle"), filepath.Join(root, "first.json")
	secondOutput, secondResult := filepath.Join(root, "second.bundle"), filepath.Join(root, "second.json")
	if err := run(options{source: source, output: firstOutput, result: firstResult}, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	if err := run(options{source: source, output: secondOutput, result: secondResult}, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	first, _ := os.ReadFile(firstOutput)
	second, _ := os.ReadFile(secondOutput)
	if !bytes.Equal(first, second) {
		t.Fatal("same source produced different repository bundle bytes")
	}
	if err := run(options{source: source, output: firstOutput, result: filepath.Join(root, "third.json")}, &bytes.Buffer{}); err == nil || !strings.Contains(err.Error(), "exists") {
		t.Fatalf("existing bundle error = %v", err)
	}
	keep := filepath.Join(root, "keep.json")
	if err := os.WriteFile(keep, []byte("keep"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := run(options{source: source, output: filepath.Join(root, "third.bundle"), result: keep}, &bytes.Buffer{}); err == nil || !strings.Contains(err.Error(), "exists") {
		t.Fatalf("existing identity error = %v", err)
	}
	if got, _ := os.ReadFile(keep); string(got) != "keep" {
		t.Fatalf("existing identity was overwritten: %q", got)
	}
}

func TestCommandRejectsPublicOrNestedOutput(t *testing.T) {
	root := privateTempDir(t)
	source := filepath.Join(root, "source")
	if err := os.Mkdir(source, 0o700); err != nil {
		t.Fatal(err)
	}
	public := filepath.Join(root, "public")
	if err := os.Mkdir(public, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(public, 0o755); err != nil {
		t.Fatal(err)
	}
	for name, config := range map[string]options{
		"public": {source: source, output: filepath.Join(public, "repository.bundle"), result: filepath.Join(root, "result.json")},
		"nested": {source: source, output: filepath.Join(source, "repository.bundle"), result: filepath.Join(root, "result.json")},
		"same":   {source: source, output: filepath.Join(root, "one"), result: filepath.Join(root, "one")},
	} {
		t.Run(name, func(t *testing.T) {
			if err := run(config, &bytes.Buffer{}); err == nil {
				t.Fatal("unsafe output configuration was accepted")
			}
		})
	}
}

func privateTempDir(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	if err := os.Chmod(root, 0o700); err != nil {
		t.Fatal(err)
	}
	return root
}
