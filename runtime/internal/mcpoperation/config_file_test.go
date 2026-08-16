package mcpoperation

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadConfigFileRejectsReplacementAndWritableFiles(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "tools.json")
	data := []byte(`{"schema":1,"tools":[{"name":"commit","description":"Commit.","kind":"protected_commit","arguments":[]}]}`)
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadConfigFile(path); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0o622); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadConfigFile(path); err == nil {
		t.Fatal("group-writable MCP config was accepted")
	}
	link := filepath.Join(directory, "tools-link.json")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadConfigFile(link); err == nil {
		t.Fatal("MCP config symlink was accepted")
	}
}
