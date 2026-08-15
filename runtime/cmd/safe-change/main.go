// Command safe-change plans, independently checks, and applies a live Rule
// change through the control API. It also exposes read-only state and explicit
// recovery commands for operators.
package main

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/apiclient"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/certcheck"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

const maxTokenBytes = 4096

type controlAPI interface {
	State(context.Context) (kernel.State, error)
	Compile(context.Context, kernel.Requirement) (kernel.Certificate, error)
	CertificateState(context.Context, kernel.Certificate) (json.RawMessage, error)
	Activate(context.Context, kernel.Certificate) (kernel.State, error)
	Recover(context.Context, string) (gateway.Outcome, error)
}

type clientFactory func(string, string, *http.Client) (controlAPI, error)

var defaultClientFactory clientFactory = func(baseURL, token string, client *http.Client) (controlAPI, error) {
	return apiclient.New(baseURL, token, client)
}

type commonFlags struct {
	controlURL string
	tokenFile  string
	timeout    time.Duration
}

func addCommonFlags(flags *flag.FlagSet, common *commonFlags) {
	controlDefault := os.Getenv("SAFE_CHANGE_CONTROL_URL")
	if controlDefault == "" {
		controlDefault = "http://127.0.0.1:8787"
	}
	tokenDefault := os.Getenv("SAFE_CHANGE_ADMIN_TOKEN_FILE")
	if tokenDefault == "" {
		tokenDefault = "runtime.history.admin-token"
	}
	flags.StringVar(&common.controlURL, "control", controlDefault, "control API base URL")
	flags.StringVar(&common.tokenFile, "admin-token-file", tokenDefault, "private admin token file")
	flags.DurationVar(&common.timeout, "timeout", 45*time.Second, "whole-request timeout")
}

func (c commonFlags) client(factory clientFactory) (controlAPI, error) {
	if c.timeout <= 0 || c.timeout > 10*time.Minute {
		return nil, errors.New("timeout must be greater than zero and at most 10m")
	}
	token, err := readPrivateToken(c.tokenFile)
	if err != nil {
		return nil, fmt.Errorf("admin token: %w", err)
	}
	return factory(c.controlURL, token, directHTTPClient(c.timeout))
}

func directHTTPClient(timeout time.Duration) *http.Client {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	// The admin credential is scoped to one control API. Never route it through
	// an ambient HTTP_PROXY inherited from the operator's shell.
	transport.Proxy = nil
	transport.DialContext = (&net.Dialer{Timeout: 5 * time.Second, KeepAlive: 30 * time.Second}).DialContext
	transport.TLSHandshakeTimeout = 5 * time.Second
	transport.ResponseHeaderTimeout = timeout
	return &http.Client{Transport: transport, Timeout: timeout}
}

type planOutput struct {
	Schema          int                 `json:"schema"`
	Command         string              `json:"command"`
	Decision        kernel.Decision     `json:"decision"`
	History         kernel.HistoryPoint `json:"history"`
	RuleVersion     uint64              `json:"rule_version,omitempty"`
	CertificateFile string              `json:"certificate_file"`
}

type applyOutput struct {
	Schema      int                 `json:"schema"`
	Command     string              `json:"command"`
	Decision    kernel.Decision     `json:"decision"`
	History     kernel.HistoryPoint `json:"history"`
	RuleVersion uint64              `json:"rule_version"`
}

func usage(writer io.Writer) {
	fmt.Fprintln(writer, "usage: safe-change <plan|apply|state|recover> [options]")
}

func run(arguments []string, stdout, stderr io.Writer) int {
	return runWithFactory(arguments, stdout, stderr, defaultClientFactory)
}

func runWithFactory(arguments []string, stdout, stderr io.Writer, factory clientFactory) int {
	if len(arguments) == 0 {
		usage(stderr)
		return 2
	}
	var err error
	switch arguments[0] {
	case "plan":
		err = runPlan(arguments[1:], stdout, stderr, factory)
	case "apply":
		err = runApply(arguments[1:], stdout, stderr, factory)
	case "state":
		err = runState(arguments[1:], stdout, stderr, factory)
	case "recover":
		err = runRecover(arguments[1:], stdout, stderr, factory)
	case "help", "-h", "--help":
		usage(stdout)
		return 0
	default:
		usage(stderr)
		fmt.Fprintf(stderr, "safe-change: unknown command %q\n", arguments[0])
		return 2
	}
	if err == nil {
		return 0
	}
	fmt.Fprintf(stderr, "safe-change %s: %v\n", arguments[0], err)
	return 1
}

func parseFlags(flags *flag.FlagSet, arguments []string) error {
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("unexpected positional arguments: %s", strings.Join(flags.Args(), " "))
	}
	return nil
}

func runPlan(arguments []string, stdout, stderr io.Writer, factory clientFactory) error {
	flags := flag.NewFlagSet("safe-change plan", flag.ContinueOnError)
	flags.SetOutput(stderr)
	var common commonFlags
	var requirementPath, certificatePath string
	addCommonFlags(flags, &common)
	flags.StringVar(&requirementPath, "requirement", "", "target Requirement JSON")
	flags.StringVar(&certificatePath, "out", "", "private output path for the checked Certificate")
	if err := parseFlags(flags, arguments); err != nil {
		return err
	}
	if requirementPath == "" || certificatePath == "" {
		return errors.New("-requirement and -out are required")
	}
	var requirement kernel.Requirement
	if _, err := readDocument(requirementPath, &requirement); err != nil {
		return fmt.Errorf("Requirement: %w", err)
	}
	client, err := common.client(factory)
	if err != nil {
		return err
	}
	ctx := context.Background()
	certificate, err := client.Compile(ctx, requirement)
	if err != nil {
		return fmt.Errorf("compile: %w", err)
	}
	certificateJSON, err := json.Marshal(certificate)
	if err != nil {
		return fmt.Errorf("encode Certificate: %w", err)
	}
	projection, err := client.CertificateState(ctx, certificate)
	if err != nil {
		return fmt.Errorf("fetch Certificate State: %w", err)
	}
	verdict, err := certcheck.CheckJSON(projection, certificateJSON)
	if err != nil {
		return fmt.Errorf("independent Certificate check: %w", err)
	}
	if !verdict.Valid || verdict.Decision != string(certificate.Decision) ||
		verdict.Sequence != certificate.History.Sequence || verdict.HistoryHash != certificate.History.Hash ||
		(certificate.Rule != nil && verdict.RuleVersion != certificate.Rule.Version) {
		return errors.New("independent Certificate verdict differs from the compiled Certificate")
	}
	encoded, err := json.MarshalIndent(certificate, "", "  ")
	if err != nil {
		return fmt.Errorf("encode Certificate: %w", err)
	}
	encoded = append(encoded, '\n')
	if err := writePrivateAtomic(certificatePath, encoded); err != nil {
		return fmt.Errorf("write Certificate: %w", err)
	}
	absolutePath, err := filepath.Abs(certificatePath)
	if err != nil {
		return fmt.Errorf("resolve Certificate path: %w", err)
	}
	output := planOutput{
		Schema: 1, Command: "plan", Decision: certificate.Decision,
		History: certificate.History, CertificateFile: absolutePath,
	}
	if certificate.Rule != nil {
		output.RuleVersion = certificate.Rule.Version
	}
	return writeJSON(stdout, output)
}

func runApply(arguments []string, stdout, stderr io.Writer, factory clientFactory) error {
	flags := flag.NewFlagSet("safe-change apply", flag.ContinueOnError)
	flags.SetOutput(stderr)
	var common commonFlags
	var certificatePath string
	addCommonFlags(flags, &common)
	flags.StringVar(&certificatePath, "certificate", "", "checked Certificate JSON from plan")
	if err := parseFlags(flags, arguments); err != nil {
		return err
	}
	if certificatePath == "" {
		return errors.New("-certificate is required")
	}
	var certificate kernel.Certificate
	certificateJSON, err := readDocument(certificatePath, &certificate)
	if err != nil {
		return fmt.Errorf("Certificate: %w", err)
	}
	client, err := common.client(factory)
	if err != nil {
		return err
	}
	ctx := context.Background()
	projection, err := client.CertificateState(ctx, certificate)
	if err != nil {
		return fmt.Errorf("fetch current Certificate State: %w", err)
	}
	verdict, err := certcheck.CheckJSON(projection, certificateJSON)
	if err != nil {
		return fmt.Errorf("independent Certificate check: %w", err)
	}
	if !verdict.Valid {
		return errors.New("independent Certificate check returned an invalid verdict")
	}
	if certificate.Decision != kernel.Activate || certificate.Rule == nil || verdict.Decision != string(kernel.Activate) {
		return fmt.Errorf("Certificate decision %q cannot be applied", certificate.Decision)
	}
	state, err := client.Activate(ctx, certificate)
	if err != nil {
		return fmt.Errorf("activate: %w", err)
	}
	if state.Rule == nil || state.Rule.Version != certificate.Rule.Version || state.History.Sequence <= certificate.History.Sequence {
		return errors.New("activation response does not contain the expected newer Rule state")
	}
	return writeJSON(stdout, applyOutput{
		Schema: 1, Command: "apply", Decision: kernel.Activate,
		History: state.History, RuleVersion: state.Rule.Version,
	})
}

func runState(arguments []string, stdout, stderr io.Writer, factory clientFactory) error {
	flags := flag.NewFlagSet("safe-change state", flag.ContinueOnError)
	flags.SetOutput(stderr)
	var common commonFlags
	addCommonFlags(flags, &common)
	if err := parseFlags(flags, arguments); err != nil {
		return err
	}
	client, err := common.client(factory)
	if err != nil {
		return err
	}
	state, err := client.State(context.Background())
	if err != nil {
		return fmt.Errorf("fetch state: %w", err)
	}
	return writeJSON(stdout, state)
}

func runRecover(arguments []string, stdout, stderr io.Writer, factory clientFactory) error {
	flags := flag.NewFlagSet("safe-change recover", flag.ContinueOnError)
	flags.SetOutput(stderr)
	var common commonFlags
	var operationID string
	addCommonFlags(flags, &common)
	flags.StringVar(&operationID, "operation", "", "Operation identity to query and recover")
	if err := parseFlags(flags, arguments); err != nil {
		return err
	}
	if !validOperationID(operationID) {
		return errors.New("-operation must be op- followed by 64 lowercase hexadecimal digits")
	}
	client, err := common.client(factory)
	if err != nil {
		return err
	}
	outcome, err := client.Recover(context.Background(), operationID)
	if err != nil {
		return fmt.Errorf("recover: %w", err)
	}
	return writeJSON(stdout, outcome)
}

func validOperationID(value string) bool {
	if len(value) != len("op-")+64 || !strings.HasPrefix(value, "op-") {
		return false
	}
	decoded, err := hex.DecodeString(strings.TrimPrefix(value, "op-"))
	return err == nil && len(decoded) == 32 && hex.EncodeToString(decoded) == strings.TrimPrefix(value, "op-")
}

func readDocument(path string, target any) ([]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	contents, err := io.ReadAll(io.LimitReader(file, certcheck.MaxDocumentBytes+1))
	if err != nil {
		return nil, err
	}
	if len(contents) > certcheck.MaxDocumentBytes {
		return nil, fmt.Errorf("JSON document exceeds %d bytes", certcheck.MaxDocumentBytes)
	}
	decoder := json.NewDecoder(bytes.NewReader(contents))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return nil, err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return nil, errors.New("JSON document contains multiple values")
		}
		return nil, err
	}
	return contents, nil
}

func readPrivateToken(path string) (string, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return "", err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0o077 != 0 {
		return "", errors.New("token file must be a private regular file, not a symlink")
	}
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	openedInfo, err := file.Stat()
	if err != nil {
		return "", err
	}
	if !os.SameFile(info, openedInfo) {
		return "", errors.New("token file changed while it was opened")
	}
	contents, err := io.ReadAll(io.LimitReader(file, maxTokenBytes+1))
	if err != nil {
		return "", err
	}
	if len(contents) > maxTokenBytes {
		return "", errors.New("token file exceeds size limit")
	}
	token := strings.TrimSpace(string(contents))
	if len(token) < 32 || strings.IndexFunc(token, unicode.IsSpace) >= 0 {
		return "", errors.New("token must contain at least 32 non-whitespace bytes")
	}
	return token, nil
}

func writePrivateAtomic(path string, contents []byte) (returnErr error) {
	if path == "" {
		return errors.New("output path is empty")
	}
	directory := filepath.Dir(path)
	temporary, err := os.CreateTemp(directory, ".safe-change-certificate-*")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	defer func() {
		if returnErr != nil {
			_ = temporary.Close()
			_ = os.Remove(temporaryPath)
		}
	}()
	if err := temporary.Chmod(0o600); err != nil {
		return err
	}
	if _, err := temporary.Write(contents); err != nil {
		return err
	}
	if err := temporary.Sync(); err != nil {
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	if err := os.Rename(temporaryPath, path); err != nil {
		return err
	}
	return nil
}

func writeJSON(writer io.Writer, value any) error {
	encoder := json.NewEncoder(writer)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	return encoder.Encode(value)
}

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}
