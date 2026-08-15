package main

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

func writeJSON(t *testing.T, directory, name string, value any) string {
	t.Helper()
	contents, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, name)
	if err := os.WriteFile(path, contents, 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func emptyProjection(state *kernel.State) any {
	fromRule := uint64(0)
	if state.Rule != nil {
		fromRule = state.Rule.Version
	}
	return struct {
		Schema         int                       `json:"schema"`
		History        kernel.HistoryPoint       `json:"history"`
		FromRule       uint64                    `json:"from_rule"`
		Settled        map[string]map[string]any `json:"settled"`
		OpenOperations map[string]any            `json:"open_operations"`
	}{
		Schema: 1, History: state.History, FromRule: fromRule,
		Settled: map[string]map[string]any{
			"used": {}, "results": {},
		},
		OpenOperations: map[string]any{},
	}
}

func TestCommandAcceptsCompilerCertificate(t *testing.T) {
	state := kernel.NewState()
	requirement := kernel.Requirement{
		ID: "command-test", Results: map[string]uint32{"done": 1},
		Kinds: map[string]kernel.KindSpec{
			"finish": {Produces: map[string]uint32{"done": 1}, RetrySafe: true},
		},
	}
	certificate, err := kernel.Compile(state, requirement, 1)
	if err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	statePath := writeJSON(t, directory, "state.json", emptyProjection(state))
	certificatePath := writeJSON(t, directory, "certificate.json", certificate)
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	if status := run([]string{"-state", statePath, "-certificate", certificatePath}, &stdout, &stderr); status != 0 {
		t.Fatalf("status=%d stdout=%s stderr=%s", status, stdout.String(), stderr.String())
	}
	var result output
	if err := json.Unmarshal(stdout.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if !result.Valid || result.Decision != "activate" || result.RuleVersion != 1 || result.Error != "" {
		t.Fatalf("unexpected output: %+v", result)
	}
}

func TestCommandRejectsStaleCertificate(t *testing.T) {
	state := kernel.NewState()
	requirement := kernel.Requirement{
		ID: "command-test", Results: map[string]uint32{"done": 1},
		Kinds: map[string]kernel.KindSpec{
			"finish": {Produces: map[string]uint32{"done": 1}, RetrySafe: true},
		},
	}
	certificate, err := kernel.Compile(state, requirement, 1)
	if err != nil {
		t.Fatal(err)
	}
	state.History = kernel.HistoryPoint{Sequence: 1, Hash: strings.Repeat("2", 64)}
	directory := t.TempDir()
	statePath := writeJSON(t, directory, "state.json", emptyProjection(state))
	certificatePath := writeJSON(t, directory, "certificate.json", certificate)
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	if status := run([]string{"-state", statePath, "-certificate", certificatePath}, &stdout, &stderr); status != 1 {
		t.Fatalf("status=%d stdout=%s stderr=%s", status, stdout.String(), stderr.String())
	}
	var result output
	if err := json.Unmarshal(stdout.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if result.Valid || !strings.Contains(result.Error, "stale") {
		t.Fatalf("unexpected rejection: %+v", result)
	}
}

func TestCommandBinaryDoesNotLinkRuntimeCompiler(t *testing.T) {
	_, filename, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot locate command package")
	}
	command := exec.Command("go", "list", "-deps", ".")
	command.Dir = filepath.Dir(filename)
	output, err := command.Output()
	if err != nil {
		t.Fatal(err)
	}
	dependencies := "\n" + string(output)
	for _, forbidden := range []string{
		"/runtime/internal/kernel\n",
		"/runtime/internal/control\n",
		"/runtime/internal/history\n",
		"/runtime/internal/gateway\n",
	} {
		if strings.Contains(dependencies, forbidden) {
			t.Errorf("checker command links forbidden dependency %s", strings.TrimSpace(forbidden))
		}
	}
}
