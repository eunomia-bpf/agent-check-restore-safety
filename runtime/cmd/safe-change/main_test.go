package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/certcheck"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

type fakeControlAPI struct {
	certificate        kernel.Certificate
	projection         json.RawMessage
	state              kernel.State
	outcome            gateway.Outcome
	compileCalls       int
	stateCalls         int
	certificateCalls   int
	activationCalls    int
	recoveryCalls      int
	recoveredOperation string
}

func (f *fakeControlAPI) State(context.Context) (kernel.State, error) {
	f.stateCalls++
	return f.state, nil
}

func (f *fakeControlAPI) Compile(context.Context, kernel.Requirement) (kernel.Certificate, error) {
	f.compileCalls++
	return f.certificate, nil
}

func (f *fakeControlAPI) CertificateState(context.Context, kernel.Certificate) (json.RawMessage, error) {
	f.certificateCalls++
	return append(json.RawMessage(nil), f.projection...), nil
}

func (f *fakeControlAPI) Activate(context.Context, kernel.Certificate) (kernel.State, error) {
	f.activationCalls++
	return f.state, nil
}

func (f *fakeControlAPI) Recover(_ context.Context, operationID string) (gateway.Outcome, error) {
	f.recoveryCalls++
	f.recoveredOperation = operationID
	return f.outcome, nil
}

func testRequirement() kernel.Requirement {
	return kernel.Requirement{
		ID: "orders-v1", Results: map[string]uint32{"paid": 1},
		Capacities: map[string]uint32{"charge": 1},
		Kinds: map[string]kernel.KindSpec{
			"charge": {
				Costs: map[string]uint32{"charge": 1}, Produces: map[string]uint32{"paid": 1},
				RetrySafe: true, Target: "http://payment/v1/charge", Method: http.MethodPost,
				ResponseClassifier: gateway.ResponseReceiptV1,
			},
		},
	}
}

func certificateFixture(t *testing.T, requirement kernel.Requirement) (kernel.Certificate, json.RawMessage) {
	t.Helper()
	controlPath := filepath.Join(t.TempDir(), "runtime.history")
	c, err := control.Open(controlPath)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	certificate, err := c.Compile(requirement)
	if err != nil {
		t.Fatal(err)
	}
	projection, err := c.CertificateState(certificate)
	if err != nil {
		t.Fatal(err)
	}
	return certificate, projection
}

func writeTestJSON(t *testing.T, directory, name string, value any) string {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, name)
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func writeTestToken(t *testing.T, directory string) string {
	t.Helper()
	path := filepath.Join(directory, "admin-token")
	if err := os.WriteFile(path, []byte("admin-token-0000000000000000000000000000\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func factoryFor(t *testing.T, expectedToken string, client *fakeControlAPI) clientFactory {
	t.Helper()
	return func(baseURL, token string, httpClient *http.Client) (controlAPI, error) {
		if baseURL != "http://control.test:8787" {
			t.Fatalf("base URL = %q", baseURL)
		}
		if token != expectedToken {
			t.Fatalf("token = %q", token)
		}
		if httpClient.Timeout == 0 {
			t.Fatal("HTTP timeout is absent")
		}
		transport, ok := httpClient.Transport.(*http.Transport)
		if !ok || transport.Proxy != nil || transport.DialContext == nil {
			t.Fatalf("unsafe HTTP transport = %#v", httpClient.Transport)
		}
		return client, nil
	}
}

func commonArguments(tokenPath string) []string {
	return []string{"-control", "http://control.test:8787", "-admin-token-file", tokenPath}
}

func TestPlanChecksAndWritesPrivateCertificate(t *testing.T) {
	directory := t.TempDir()
	requirement := testRequirement()
	certificate, projection := certificateFixture(t, requirement)
	client := &fakeControlAPI{certificate: certificate, projection: projection}
	tokenPath := writeTestToken(t, directory)
	requirementPath := writeTestJSON(t, directory, "requirement.json", requirement)
	certificatePath := filepath.Join(directory, "certificate.json")
	arguments := append([]string{"plan"}, commonArguments(tokenPath)...)
	arguments = append(arguments, "-requirement", requirementPath, "-out", certificatePath)
	var stdout, stderr bytes.Buffer
	status := runWithFactory(
		arguments, &stdout, &stderr,
		factoryFor(t, "admin-token-0000000000000000000000000000", client),
	)
	if status != 0 {
		t.Fatalf("status=%d stdout=%s stderr=%s", status, stdout.String(), stderr.String())
	}
	if client.compileCalls != 1 || client.certificateCalls != 1 {
		t.Fatalf("compile=%d state=%d", client.compileCalls, client.certificateCalls)
	}
	info, err := os.Stat(certificatePath)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("Certificate mode = %o", info.Mode().Perm())
	}
	certificateJSON, err := os.ReadFile(certificatePath)
	if err != nil {
		t.Fatal(err)
	}
	verdict, err := certcheck.CheckJSON(projection, certificateJSON)
	if err != nil || !verdict.Valid || verdict.Decision != "activate" {
		t.Fatalf("verdict=%+v error=%v", verdict, err)
	}
	var output planOutput
	if err := json.Unmarshal(stdout.Bytes(), &output); err != nil {
		t.Fatal(err)
	}
	if output.Decision != kernel.Activate || output.RuleVersion != 1 || output.CertificateFile != certificatePath {
		t.Fatalf("output = %+v", output)
	}
}

func TestApplyRechecksCurrentStateBeforeActivation(t *testing.T) {
	directory := t.TempDir()
	certificate, projection := certificateFixture(t, testRequirement())
	state := *kernel.NewState()
	state.History = kernel.HistoryPoint{Sequence: certificate.History.Sequence + 1, Hash: strings.Repeat("1", 64)}
	state.Rule = certificate.Rule
	state.Requirement = &certificate.Requirement
	client := &fakeControlAPI{certificate: certificate, projection: projection, state: state}
	tokenPath := writeTestToken(t, directory)
	certificatePath := writeTestJSON(t, directory, "certificate.json", certificate)
	arguments := append([]string{"apply"}, commonArguments(tokenPath)...)
	arguments = append(arguments, "-certificate", certificatePath)
	var stdout, stderr bytes.Buffer
	status := runWithFactory(
		arguments, &stdout, &stderr,
		factoryFor(t, "admin-token-0000000000000000000000000000", client),
	)
	if status != 0 {
		t.Fatalf("status=%d stdout=%s stderr=%s", status, stdout.String(), stderr.String())
	}
	if client.certificateCalls != 1 || client.activationCalls != 1 {
		t.Fatalf("Certificate State=%d activate=%d", client.certificateCalls, client.activationCalls)
	}
	var output applyOutput
	if err := json.Unmarshal(stdout.Bytes(), &output); err != nil {
		t.Fatal(err)
	}
	if output.RuleVersion != certificate.Rule.Version || output.History != state.History {
		t.Fatalf("output = %+v", output)
	}
}

func TestApplyRejectsStaleCertificateWithoutActivation(t *testing.T) {
	directory := t.TempDir()
	certificate, projection := certificateFixture(t, testRequirement())
	var changed map[string]any
	if err := json.Unmarshal(projection, &changed); err != nil {
		t.Fatal(err)
	}
	changed["history"] = map[string]any{"sequence": 1, "hash": strings.Repeat("2", 64)}
	projection, err := json.Marshal(changed)
	if err != nil {
		t.Fatal(err)
	}
	client := &fakeControlAPI{certificate: certificate, projection: projection}
	tokenPath := writeTestToken(t, directory)
	certificatePath := writeTestJSON(t, directory, "certificate.json", certificate)
	arguments := append([]string{"apply"}, commonArguments(tokenPath)...)
	arguments = append(arguments, "-certificate", certificatePath)
	var stdout, stderr bytes.Buffer
	status := runWithFactory(
		arguments, &stdout, &stderr,
		factoryFor(t, "admin-token-0000000000000000000000000000", client),
	)
	if status != 1 || client.activationCalls != 0 || !strings.Contains(stderr.String(), "stale") {
		t.Fatalf("status=%d activate=%d stderr=%s", status, client.activationCalls, stderr.String())
	}
}

func TestPlanRecordsImpossibleAndApplyRefusesIt(t *testing.T) {
	directory := t.TempDir()
	requirement := kernel.Requirement{
		ID: "impossible", Results: map[string]uint32{"done": 1},
		Capacities: map[string]uint32{"slot": 1},
		Kinds: map[string]kernel.KindSpec{
			"finish": {
				Costs: map[string]uint32{"slot": 2}, Produces: map[string]uint32{"done": 1},
				RetrySafe: true,
			},
		},
	}
	certificate, projection := certificateFixture(t, requirement)
	if certificate.Decision != kernel.Impossible {
		t.Fatalf("decision = %q", certificate.Decision)
	}
	client := &fakeControlAPI{certificate: certificate, projection: projection}
	tokenPath := writeTestToken(t, directory)
	requirementPath := writeTestJSON(t, directory, "requirement.json", requirement)
	certificatePath := filepath.Join(directory, "certificate.json")
	planArguments := append([]string{"plan"}, commonArguments(tokenPath)...)
	planArguments = append(planArguments, "-requirement", requirementPath, "-out", certificatePath)
	var planOut, planErr bytes.Buffer
	if status := runWithFactory(
		planArguments, &planOut, &planErr,
		factoryFor(t, "admin-token-0000000000000000000000000000", client),
	); status != 0 {
		t.Fatalf("plan status=%d stderr=%s", status, planErr.String())
	}
	applyArguments := append([]string{"apply"}, commonArguments(tokenPath)...)
	applyArguments = append(applyArguments, "-certificate", certificatePath)
	var applyOut, applyErr bytes.Buffer
	if status := runWithFactory(
		applyArguments, &applyOut, &applyErr,
		factoryFor(t, "admin-token-0000000000000000000000000000", client),
	); status != 1 || client.activationCalls != 0 || !strings.Contains(applyErr.String(), "cannot be applied") {
		t.Fatalf("apply status=%d activate=%d stderr=%s", status, client.activationCalls, applyErr.String())
	}
}

func TestStateAndRecoverUseExplicitAdminPath(t *testing.T) {
	directory := t.TempDir()
	tokenPath := writeTestToken(t, directory)
	operationID := "op-" + strings.Repeat("a", 64)
	client := &fakeControlAPI{
		state:   *kernel.NewState(),
		outcome: gateway.Outcome{OperationID: operationID, Phase: kernel.Succeeded},
	}
	factory := factoryFor(t, "admin-token-0000000000000000000000000000", client)
	for _, arguments := range [][]string{
		append([]string{"state"}, commonArguments(tokenPath)...),
		append(append([]string{"recover"}, commonArguments(tokenPath)...), "-operation", operationID),
	} {
		var stdout, stderr bytes.Buffer
		if status := runWithFactory(arguments, &stdout, &stderr, factory); status != 0 {
			t.Fatalf("arguments=%v status=%d stderr=%s", arguments, status, stderr.String())
		}
		if !json.Valid(stdout.Bytes()) {
			t.Fatalf("invalid JSON: %s", stdout.String())
		}
	}
	if client.stateCalls != 1 || client.recoveryCalls != 1 || client.recoveredOperation != operationID {
		t.Fatalf("state=%d recover=%d operation=%q", client.stateCalls, client.recoveryCalls, client.recoveredOperation)
	}
}

func TestPrivateTokenRejectsBroadPermissionsAndSymlink(t *testing.T) {
	directory := t.TempDir()
	path := writeTestToken(t, directory)
	if err := os.Chmod(path, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := readPrivateToken(path); err == nil || !strings.Contains(err.Error(), "private regular file") {
		t.Fatalf("broad token error = %v", err)
	}
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(directory, "token-link")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	if _, err := readPrivateToken(link); err == nil || !strings.Contains(err.Error(), "private regular file") {
		t.Fatalf("symlink token error = %v", err)
	}
}

func TestPlanRejectsUnknownRequirementFieldsBeforeNetwork(t *testing.T) {
	directory := t.TempDir()
	tokenPath := writeTestToken(t, directory)
	requirementPath := filepath.Join(directory, "requirement.json")
	if err := os.WriteFile(requirementPath, []byte(`{"id":"v1","results":{},"capacities":{},"kinds":{},"extra":true}`), 0o600); err != nil {
		t.Fatal(err)
	}
	certificatePath := filepath.Join(directory, "certificate.json")
	factoryCalled := false
	factory := func(string, string, *http.Client) (controlAPI, error) {
		factoryCalled = true
		return &fakeControlAPI{}, nil
	}
	arguments := append([]string{"plan"}, commonArguments(tokenPath)...)
	arguments = append(arguments, "-requirement", requirementPath, "-out", certificatePath)
	var stdout, stderr bytes.Buffer
	if status := runWithFactory(arguments, &stdout, &stderr, factory); status != 1 {
		t.Fatalf("status=%d stderr=%s", status, stderr.String())
	}
	if factoryCalled || !strings.Contains(stderr.String(), "unknown field") {
		t.Fatalf("factory=%v stderr=%s", factoryCalled, stderr.String())
	}
}

func TestOperationIdentityIsCanonical(t *testing.T) {
	if !validOperationID("op-" + strings.Repeat("a", 64)) {
		t.Fatal("canonical Operation identity was rejected")
	}
	for _, value := range []string{"", "op-" + strings.Repeat("a", 63), "op-" + strings.Repeat("A", 64), strings.Repeat("a", 64)} {
		if validOperationID(value) {
			t.Fatalf("invalid Operation identity accepted: %q", value)
		}
	}
}
