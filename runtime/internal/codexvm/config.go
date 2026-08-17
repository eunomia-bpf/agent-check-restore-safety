// Package codexvm validates the host-owned inputs for the transparent Codex
// microVM shim. It deliberately contains no process or Firecracker lifecycle
// code: loading configuration grants no authority and changes no host state.
package codexvm

import (
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"unicode"
	"unicode/utf8"

	"golang.org/x/sys/unix"
)

const (
	EnvRunnerSHA256      = "SAFE_CHANGE_RUNNER_SHA256"
	EnvFirecracker       = "SAFE_CHANGE_FIRECRACKER"
	EnvFirecrackerSHA256 = "SAFE_CHANGE_FIRECRACKER_SHA256"
	EnvKernel            = "SAFE_CHANGE_KERNEL"
	EnvKernelSHA256      = "SAFE_CHANGE_KERNEL_SHA256"
	EnvGuest             = "SAFE_CHANGE_GUEST"
	EnvGuestSHA256       = "SAFE_CHANGE_GUEST_SHA256"
	EnvPayload           = "SAFE_CHANGE_PAYLOAD"
	EnvPayloadSHA256     = "SAFE_CHANGE_PAYLOAD_SHA256"
	EnvRepository        = "SAFE_CHANGE_REPOSITORY"
	EnvRepositorySHA256  = "SAFE_CHANGE_REPOSITORY_SHA256"
	EnvCodexSHA256       = "SAFE_CHANGE_CODEX_SHA256"
	EnvEvidenceDir       = "SAFE_CHANGE_EVIDENCE_DIR"
	EnvWorkspace         = "SAFE_CHANGE_WORKSPACE"
	EnvMCPHostSocket     = "SAFE_CHANGE_MCP_HOST_SOCKET"
	EnvCheckpointPolicy  = "SAFE_CHANGE_CHECKPOINT_POLICY"

	CheckpointPolicyRestore     = "restore"
	CheckpointPolicyColdReplace = "cold-replace"

	MaxArguments     = 256
	MaxArgumentBytes = 64 << 10
	MaxTotalArgBytes = 1 << 20
)

var requiredEnvironment = [...]string{
	EnvRunnerSHA256,
	EnvFirecracker,
	EnvFirecrackerSHA256,
	EnvKernel,
	EnvKernelSHA256,
	EnvGuest,
	EnvGuestSHA256,
	EnvPayload,
	EnvPayloadSHA256,
	EnvRepository,
	EnvRepositorySHA256,
	EnvCodexSHA256,
	EnvEvidenceDir,
	EnvWorkspace,
}

// Config is the complete validated input accepted by the host shim. Arguments
// retains the exact Codex arguments, while HostModelTarget fixes the only host
// TCP destination the later transport layer may use. GuestModelPort is the
// matching loopback port that an in-guest forwarder must bind, so Arguments do
// not need a Firecracker-specific rewrite.
type Config struct {
	RunnerSHA256      string
	Firecracker       string
	FirecrackerSHA256 string
	Kernel            string
	KernelSHA256      string
	Guest             string
	GuestSHA256       string
	Payload           string
	PayloadSHA256     string
	Repository        string
	RepositorySHA256  string
	CodexSHA256       string
	EvidenceDir       string
	Workspace         string
	Arguments         []string
	HostModelTarget   string
	GuestModelPort    uint32
	MCPHostSocket     string
	CheckpointPolicy  string
}

// LoadConfig reads exactly the fixed host-shim environment contract and
// validates the unmodified Codex argv. It neither hashes artifacts nor starts
// a process; later layers bind these validated paths to separately verified
// file contents.
func LoadConfig(arguments []string, lookupEnv func(string) (string, bool)) (Config, error) {
	if lookupEnv == nil {
		return Config{}, errors.New("Codex VM configuration requires an environment lookup function")
	}
	values := make(map[string]string, len(requiredEnvironment))
	for _, name := range requiredEnvironment {
		value, present := lookupEnv(name)
		if !present || value == "" {
			return Config{}, fmt.Errorf("required environment variable %s is unset or empty", name)
		}
		values[name] = value
	}

	config := Config{}
	var err error
	if config.RunnerSHA256, err = validateSHA256(values[EnvRunnerSHA256], EnvRunnerSHA256); err != nil {
		return Config{}, err
	}
	if config.Firecracker, err = validateArtifactPath(values[EnvFirecracker], EnvFirecracker, true); err != nil {
		return Config{}, err
	}
	if config.Kernel, err = validateArtifactPath(values[EnvKernel], EnvKernel, false); err != nil {
		return Config{}, err
	}
	if config.Guest, err = validateArtifactPath(values[EnvGuest], EnvGuest, true); err != nil {
		return Config{}, err
	}
	if config.Payload, err = validateArtifactPath(values[EnvPayload], EnvPayload, false); err != nil {
		return Config{}, err
	}
	if config.Repository, err = validateArtifactPath(values[EnvRepository], EnvRepository, false); err != nil {
		return Config{}, err
	}
	if config.FirecrackerSHA256, err = validateSHA256(values[EnvFirecrackerSHA256], EnvFirecrackerSHA256); err != nil {
		return Config{}, err
	}
	if config.KernelSHA256, err = validateSHA256(values[EnvKernelSHA256], EnvKernelSHA256); err != nil {
		return Config{}, err
	}
	if config.GuestSHA256, err = validateSHA256(values[EnvGuestSHA256], EnvGuestSHA256); err != nil {
		return Config{}, err
	}
	if config.PayloadSHA256, err = validateSHA256(values[EnvPayloadSHA256], EnvPayloadSHA256); err != nil {
		return Config{}, err
	}
	if config.RepositorySHA256, err = validateSHA256(values[EnvRepositorySHA256], EnvRepositorySHA256); err != nil {
		return Config{}, err
	}
	if config.CodexSHA256, err = validateSHA256(values[EnvCodexSHA256], EnvCodexSHA256); err != nil {
		return Config{}, err
	}
	if config.EvidenceDir, err = validateEvidenceDirectory(values[EnvEvidenceDir]); err != nil {
		return Config{}, err
	}
	if config.Workspace, err = validateEmptyWorkspace(values[EnvWorkspace]); err != nil {
		return Config{}, err
	}
	if pathsOverlap(config.Workspace, config.EvidenceDir) {
		return Config{}, errors.New("workspace and evidence directory must not overlap")
	}
	if pathsOverlap(config.Repository, config.Workspace) || pathsOverlap(config.Repository, config.EvidenceDir) {
		return Config{}, errors.New("repository, workspace, and evidence paths must not overlap")
	}
	if mcpSocket, present := lookupEnv(EnvMCPHostSocket); present {
		if mcpSocket == "" {
			return Config{}, fmt.Errorf("optional environment variable %s is empty", EnvMCPHostSocket)
		}
		if config.MCPHostSocket, err = validatePrivateUnixSocket(mcpSocket, EnvMCPHostSocket); err != nil {
			return Config{}, err
		}
		for label, path := range map[string]string{
			EnvEvidenceDir: config.EvidenceDir,
			EnvWorkspace:   config.Workspace,
			EnvRepository:  config.Repository,
		} {
			if pathsOverlap(config.MCPHostSocket, path) {
				return Config{}, fmt.Errorf("%s and %s paths must not overlap", EnvMCPHostSocket, label)
			}
		}
	}
	config.CheckpointPolicy = CheckpointPolicyRestore
	if policy, present := lookupEnv(EnvCheckpointPolicy); present {
		switch policy {
		case CheckpointPolicyRestore, CheckpointPolicyColdReplace:
			config.CheckpointPolicy = policy
		case "":
			return Config{}, fmt.Errorf("optional environment variable %s is empty", EnvCheckpointPolicy)
		default:
			return Config{}, fmt.Errorf("%s must be %q or %q", EnvCheckpointPolicy, CheckpointPolicyRestore, CheckpointPolicyColdReplace)
		}
	}

	modelURL, err := validateArguments(arguments)
	if err != nil {
		return Config{}, err
	}
	config.HostModelTarget, config.GuestModelPort, err = validateModelBaseURL(modelURL)
	if err != nil {
		return Config{}, err
	}
	config.Arguments = append([]string(nil), arguments...)
	return config, nil
}

func validateEmptyWorkspace(value string) (string, error) {
	info, err := validateCanonicalPath(value, EnvWorkspace)
	if err != nil {
		return "", err
	}
	if !info.IsDir() {
		return "", fmt.Errorf("%s must be a real directory", EnvWorkspace)
	}
	directory, err := os.Open(value)
	if err != nil {
		return "", fmt.Errorf("open %s: %w", EnvWorkspace, err)
	}
	defer directory.Close()
	names, readErr := directory.Readdirnames(1)
	if len(names) != 0 || readErr == nil {
		return "", fmt.Errorf("%s must be empty", EnvWorkspace)
	}
	if !errors.Is(readErr, io.EOF) {
		return "", fmt.Errorf("read %s: %w", EnvWorkspace, readErr)
	}
	return value, nil
}

func pathsOverlap(first, second string) bool {
	relative, err := filepath.Rel(first, second)
	if err == nil && (relative == "." || relative == ".." || !strings.HasPrefix(relative, ".."+string(filepath.Separator))) {
		return true
	}
	relative, err = filepath.Rel(second, first)
	return err == nil && (relative == "." || relative == ".." || !strings.HasPrefix(relative, ".."+string(filepath.Separator)))
}

func validateArtifactPath(value, label string, executable bool) (string, error) {
	info, err := validateCanonicalPath(value, label)
	if err != nil {
		return "", err
	}
	if !info.Mode().IsRegular() || info.Size() <= 0 {
		return "", fmt.Errorf("%s must be a non-empty direct regular file", label)
	}
	if executable && info.Mode().Perm()&0o111 == 0 {
		return "", fmt.Errorf("%s must have an executable mode bit", label)
	}
	return value, nil
}

func validatePrivateUnixSocket(value, label string) (string, error) {
	info, err := validateCanonicalPath(value, label)
	if err != nil {
		return "", err
	}
	if info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0o600 {
		return "", fmt.Errorf("%s must be a direct Unix socket with mode 0600", label)
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != uint32(os.Geteuid()) {
		return "", fmt.Errorf("%s must be owned by the current user", label)
	}
	parent := filepath.Dir(value)
	parentInfo, err := validateCanonicalPath(parent, label+" parent")
	if err != nil || !parentInfo.IsDir() || parentInfo.Mode().Perm() != 0o700 {
		return "", fmt.Errorf("%s parent must be a direct current-user directory with mode 0700", label)
	}
	parentStat, ok := parentInfo.Sys().(*syscall.Stat_t)
	if !ok || parentStat.Uid != uint32(os.Geteuid()) {
		return "", fmt.Errorf("%s parent must be owned by the current user", label)
	}
	return value, nil
}

func validateCanonicalPath(value, label string) (os.FileInfo, error) {
	if value == "" || !utf8.ValidString(value) || strings.IndexFunc(value, unicode.IsControl) >= 0 {
		return nil, fmt.Errorf("%s must be a non-empty path without control characters", label)
	}
	if !filepath.IsAbs(value) || filepath.Clean(value) != value {
		return nil, fmt.Errorf("%s must be an absolute canonical path", label)
	}
	info, err := os.Lstat(value)
	if err != nil {
		return nil, fmt.Errorf("inspect %s: %w", label, err)
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return nil, fmt.Errorf("%s must be a direct path, not a symlink", label)
	}
	resolved, err := filepath.EvalSymlinks(value)
	if err != nil {
		return nil, fmt.Errorf("resolve %s: %w", label, err)
	}
	if resolved != value {
		return nil, fmt.Errorf("%s path must not traverse a symlink", label)
	}
	return info, nil
}

func validateSHA256(value, label string) (string, error) {
	if len(value) != 64 || strings.ToLower(value) != value {
		return "", fmt.Errorf("%s must be one lowercase SHA-256 digest", label)
	}
	if _, err := hex.DecodeString(value); err != nil {
		return "", fmt.Errorf("%s must be one lowercase SHA-256 digest", label)
	}
	return value, nil
}

func validateEvidenceDirectory(value string) (string, error) {
	initial, err := validateCanonicalPath(value, EnvEvidenceDir)
	if err != nil {
		return "", err
	}
	if !initial.IsDir() {
		return "", fmt.Errorf("%s must be a real directory", EnvEvidenceDir)
	}
	descriptor, err := unix.Open(value, unix.O_RDONLY|unix.O_CLOEXEC|unix.O_DIRECTORY|unix.O_NOFOLLOW, 0)
	if err != nil {
		return "", fmt.Errorf("open %s: %w", EnvEvidenceDir, err)
	}
	directory := os.NewFile(uintptr(descriptor), value)
	if directory == nil {
		_ = unix.Close(descriptor)
		return "", fmt.Errorf("wrap %s descriptor", EnvEvidenceDir)
	}
	defer directory.Close()
	current, err := directory.Stat()
	if err != nil {
		return "", fmt.Errorf("stat %s: %w", EnvEvidenceDir, err)
	}
	if !current.IsDir() || !os.SameFile(initial, current) {
		return "", fmt.Errorf("%s changed while it was opened", EnvEvidenceDir)
	}
	if current.Mode().Perm() != 0o700 || current.Mode()&(os.ModeSetuid|os.ModeSetgid|os.ModeSticky) != 0 {
		return "", fmt.Errorf("%s mode is %04o, require exactly 0700", EnvEvidenceDir, current.Mode().Perm())
	}
	stat, ok := current.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != uint32(os.Geteuid()) {
		return "", fmt.Errorf("%s must be owned by the current user", EnvEvidenceDir)
	}
	names, readErr := directory.Readdirnames(1)
	if len(names) != 0 || readErr == nil {
		return "", fmt.Errorf("%s must be empty", EnvEvidenceDir)
	}
	if !errors.Is(readErr, io.EOF) {
		return "", fmt.Errorf("read %s: %w", EnvEvidenceDir, readErr)
	}
	return value, nil
}

func validateArguments(arguments []string) (string, error) {
	if len(arguments) < 2 || len(arguments) > MaxArguments || arguments[0] != "app-server" || arguments[1] != "--stdio" {
		return "", fmt.Errorf("Codex arguments must begin with app-server --stdio and contain at most %d entries", MaxArguments)
	}
	total := 0
	for index, argument := range arguments {
		if argument == "" || len(argument) > MaxArgumentBytes || !utf8.ValidString(argument) || strings.IndexFunc(argument, unicode.IsControl) >= 0 {
			return "", fmt.Errorf("Codex argument %d is empty, too large, invalid UTF-8, or contains a control character", index)
		}
		total += len(argument)
		if total > MaxTotalArgBytes {
			return "", fmt.Errorf("Codex arguments exceed %d bytes", MaxTotalArgBytes)
		}
	}

	baseURLs := make([]string, 0, 1)
	for index := 2; index < len(arguments); index++ {
		argument := arguments[index]
		if argument == "--" {
			return "", errors.New("Codex arguments must not terminate option parsing before the required -c override")
		}
		if argument == "-c" {
			if index+1 >= len(arguments) {
				return "", errors.New("Codex -c requires one TOML override argument")
			}
			index++
			found, err := scanTOMLOverride(arguments[index])
			if err != nil {
				return "", fmt.Errorf("parse Codex -c override %d: %w", index, err)
			}
			baseURLs = append(baseURLs, found...)
			continue
		}
		if argument == "--config" || strings.HasPrefix(argument, "--config=") || strings.HasPrefix(argument, "-c") {
			return "", fmt.Errorf("Codex configuration override %q must use a separate -c argument", argument)
		}
	}
	if len(baseURLs) != 1 {
		return "", fmt.Errorf("Codex arguments must contain exactly one TOML basic-string base_url override, found %d", len(baseURLs))
	}
	return baseURLs[0], nil
}

func scanTOMLOverride(override string) ([]string, error) {
	if err := validateTOMLOverrideAssignment(override); err != nil {
		return nil, err
	}
	var baseURLs []string
	stack := make([]byte, 0, 4)
	topLevelAssignments := 0
	for index := 0; index < len(override); {
		value := override[index]
		switch {
		case value == ' ':
			index++
		case value == '#':
			index = len(override)
		case value == '"':
			decoded, next, err := scanTOMLBasicString(override, index)
			if err != nil {
				return nil, err
			}
			if !utf8.ValidString(decoded) || strings.IndexFunc(decoded, unicode.IsControl) >= 0 {
				return nil, errors.New("TOML basic string escape produced invalid UTF-8 or a control character")
			}
			index = next
		case value == '\'':
			next := strings.IndexByte(override[index+1:], '\'')
			if next < 0 {
				return nil, errors.New("unterminated TOML literal string")
			}
			index += next + 2
		case value == '{' || value == '[':
			stack = append(stack, value)
			index++
		case value == '}' || value == ']':
			if len(stack) == 0 || (value == '}' && stack[len(stack)-1] != '{') || (value == ']' && stack[len(stack)-1] != '[') {
				return nil, errors.New("mismatched TOML delimiter")
			}
			stack = stack[:len(stack)-1]
			index++
		case isTOMLBareKeyByte(value):
			start := index
			for index < len(override) && isTOMLBareKeyByte(override[index]) {
				index++
			}
			if override[start:index] != "base_url" {
				continue
			}
			assignment := skipTOMLSpaces(override, index)
			if assignment >= len(override) || override[assignment] != '=' {
				return nil, errors.New("TOML base_url must be an assignment")
			}
			if len(stack) == 0 {
				topLevelAssignments++
			}
			assignment = skipTOMLSpaces(override, assignment+1)
			if assignment >= len(override) || override[assignment] != '"' {
				return nil, errors.New("TOML base_url value must be a basic string")
			}
			decoded, next, err := scanTOMLBasicString(override, assignment)
			if err != nil {
				return nil, fmt.Errorf("decode TOML base_url: %w", err)
			}
			if !utf8.ValidString(decoded) || strings.IndexFunc(decoded, unicode.IsControl) >= 0 {
				return nil, errors.New("TOML base_url escape produced invalid UTF-8 or a control character")
			}
			following := skipTOMLSpaces(override, next)
			if following < len(override) && !strings.ContainsRune(",}]#", rune(override[following])) {
				return nil, errors.New("invalid TOML following base_url basic string")
			}
			baseURLs = append(baseURLs, decoded)
			index = next
		case value >= utf8.RuneSelf:
			return nil, errors.New("TOML bare syntax contains non-ASCII data")
		case value == '=':
			if len(stack) == 0 {
				topLevelAssignments++
			}
			index++
		case strings.ContainsRune(".,+:", rune(value)):
			index++
		default:
			return nil, fmt.Errorf("invalid TOML byte %q", value)
		}
	}
	if len(stack) != 0 {
		return nil, errors.New("unclosed TOML delimiter")
	}
	if topLevelAssignments != 1 {
		return nil, fmt.Errorf("TOML override must contain exactly one top-level assignment, found %d", topLevelAssignments)
	}
	return baseURLs, nil
}

func validateTOMLOverrideAssignment(override string) error {
	assignment := strings.IndexByte(override, '=')
	if assignment < 0 {
		return errors.New("TOML override has no assignment")
	}
	key := strings.TrimSpace(override[:assignment])
	if key == "" {
		return errors.New("TOML override has an empty key")
	}
	for _, component := range strings.Split(key, ".") {
		component = strings.TrimSpace(component)
		if component == "" {
			return errors.New("TOML override has an empty dotted-key component")
		}
		for index := range []byte(component) {
			if !isTOMLBareKeyByte(component[index]) {
				return errors.New("TOML override key must use bare dotted-key syntax")
			}
		}
	}
	if strings.TrimSpace(override[assignment+1:]) == "" {
		return errors.New("TOML override has no value")
	}
	return nil
}

func scanTOMLBasicString(value string, start int) (string, int, error) {
	for index := start + 1; index < len(value); index++ {
		switch value[index] {
		case '\\':
			index++
			if index >= len(value) {
				return "", 0, errors.New("unterminated TOML basic-string escape")
			}
		case '"':
			raw := value[start : index+1]
			decoded, err := strconv.Unquote(raw)
			if err != nil {
				return "", 0, fmt.Errorf("unquote TOML basic string: %w", err)
			}
			return decoded, index + 1, nil
		}
	}
	return "", 0, errors.New("unterminated TOML basic string")
}

func skipTOMLSpaces(value string, index int) int {
	for index < len(value) && value[index] == ' ' {
		index++
	}
	return index
}

func isTOMLBareKeyByte(value byte) bool {
	return value >= 'a' && value <= 'z' || value >= 'A' && value <= 'Z' || value >= '0' && value <= '9' || value == '_' || value == '-'
}

func validateModelBaseURL(value string) (string, uint32, error) {
	target, err := url.Parse(value)
	if err != nil {
		return "", 0, fmt.Errorf("parse model base_url: %w", err)
	}
	if target.Scheme != "http" || !target.IsAbs() || target.Opaque != "" || target.Host == "" {
		return "", 0, errors.New("model base_url must be an absolute hierarchical HTTP URL")
	}
	if target.User != nil || target.RawQuery != "" || target.ForceQuery || target.Fragment != "" || target.RawFragment != "" || strings.Contains(value, "#") {
		return "", 0, errors.New("model base_url must not contain user information, a query, or a fragment")
	}
	if target.Path == "" || !strings.HasPrefix(target.EscapedPath(), "/") || strings.IndexFunc(target.Path, unicode.IsControl) >= 0 {
		return "", 0, errors.New("model base_url must contain an absolute path without control characters")
	}
	host := target.Hostname()
	// The first guest proxy intentionally binds tcp4 only. IPv6 loopback can
	// be admitted when the immutable guest config also carries the address
	// family; accepting it here would otherwise create a host/guest split.
	if host != "127.0.0.1" {
		return "", 0, fmt.Errorf("model base_url host %q is not exact numeric loopback", host)
	}
	portText := target.Port()
	if portText == "" {
		return "", 0, errors.New("model base_url must contain an explicit port")
	}
	if len(portText) > 5 {
		return "", 0, errors.New("model base_url port must contain at most five decimal digits")
	}
	for _, digit := range []byte(portText) {
		if digit < '0' || digit > '9' {
			return "", 0, errors.New("model base_url port must contain only decimal digits")
		}
	}
	port, err := strconv.ParseUint(portText, 10, 16)
	if err != nil || port == 0 {
		return "", 0, errors.New("model base_url port must be between 1 and 65535")
	}
	if port == 7000 {
		return "", 0, errors.New("model base_url port conflicts with the fixed agent stream port 7000")
	}
	if target.Host != net.JoinHostPort(host, portText) {
		return "", 0, errors.New("model base_url authority is not canonical numeric loopback")
	}
	return net.JoinHostPort(host, strconv.FormatUint(port, 10)), uint32(port), nil
}
