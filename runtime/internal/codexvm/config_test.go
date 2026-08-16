package codexvm

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"golang.org/x/sys/unix"
)

func TestLoadConfigAcceptsStrictContractAndCopiesArguments(t *testing.T) {
	fixture := newConfigFixture(t)
	lookedUp := make([]string, 0, len(requiredEnvironment))
	lookup := func(name string) (string, bool) {
		lookedUp = append(lookedUp, name)
		value, ok := fixture.environment[name]
		return value, ok
	}
	arguments := validArguments(`http://127.0.0.1:43210/v1`)
	config, err := LoadConfig(arguments, lookup)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(lookedUp, requiredEnvironment[:]) {
		t.Fatalf("environment lookups = %q, want %q", lookedUp, requiredEnvironment)
	}
	if config.RunnerSHA256 != fixture.environment[EnvRunnerSHA256] || config.Firecracker != fixture.environment[EnvFirecracker] || config.FirecrackerSHA256 != fixture.environment[EnvFirecrackerSHA256] ||
		config.Kernel != fixture.environment[EnvKernel] || config.KernelSHA256 != fixture.environment[EnvKernelSHA256] ||
		config.Guest != fixture.environment[EnvGuest] || config.GuestSHA256 != fixture.environment[EnvGuestSHA256] || config.Payload != fixture.environment[EnvPayload] ||
		config.PayloadSHA256 != fixture.environment[EnvPayloadSHA256] || config.Repository != fixture.environment[EnvRepository] || config.RepositorySHA256 != fixture.environment[EnvRepositorySHA256] || config.CodexSHA256 != fixture.environment[EnvCodexSHA256] || config.EvidenceDir != fixture.environment[EnvEvidenceDir] || config.Workspace != fixture.environment[EnvWorkspace] {
		t.Fatalf("loaded environment = %+v", config)
	}
	if config.HostModelTarget != "127.0.0.1:43210" || config.GuestModelPort != 43210 {
		t.Fatalf("model route = %q / %d", config.HostModelTarget, config.GuestModelPort)
	}
	if !reflect.DeepEqual(config.Arguments, arguments) {
		t.Fatalf("arguments = %q, want %q", config.Arguments, arguments)
	}
	arguments[0] = "mutated"
	arguments[3] = "mutated"
	if config.Arguments[0] != "app-server" || strings.Contains(strings.Join(config.Arguments, " "), "mutated") {
		t.Fatalf("Config retained caller's argument backing array: %q", config.Arguments)
	}
}

func TestLoadConfigRejectsUnsupportedGuestIPv6Family(t *testing.T) {
	fixture := newConfigFixture(t)
	arguments := validArguments(`http://[::1]:00080/v1`)
	if _, err := LoadConfig(arguments, fixture.lookup); err == nil || !strings.Contains(err.Error(), "numeric loopback") {
		t.Fatalf("IPv6 guest route rejection = %v", err)
	}
}

func TestLoadConfigRequiresAllFixedEnvironmentValues(t *testing.T) {
	for _, name := range requiredEnvironment {
		name := name
		t.Run(name+" unset", func(t *testing.T) {
			fixture := newConfigFixture(t)
			delete(fixture.environment, name)
			if _, err := LoadConfig(validArguments(`http://127.0.0.1:1/v1`), fixture.lookup); err == nil || !strings.Contains(err.Error(), name) {
				t.Fatalf("unset %s error = %v", name, err)
			}
		})
		t.Run(name+" empty", func(t *testing.T) {
			fixture := newConfigFixture(t)
			fixture.environment[name] = ""
			if _, err := LoadConfig(validArguments(`http://127.0.0.1:1/v1`), fixture.lookup); err == nil || !strings.Contains(err.Error(), name) {
				t.Fatalf("empty %s error = %v", name, err)
			}
		})
	}
	if _, err := LoadConfig(validArguments(`http://127.0.0.1:1/v1`), nil); err == nil {
		t.Fatal("nil environment lookup accepted")
	}
}

func TestLoadConfigRejectsMalformedDigests(t *testing.T) {
	for _, name := range []string{EnvRunnerSHA256, EnvFirecrackerSHA256, EnvKernelSHA256, EnvGuestSHA256, EnvPayloadSHA256, EnvRepositorySHA256, EnvCodexSHA256} {
		for label, value := range map[string]string{
			"short":     "abc",
			"uppercase": strings.Repeat("A", 64),
			"nonhex":    strings.Repeat("z", 64),
		} {
			t.Run(name+" "+label, func(t *testing.T) {
				fixture := newConfigFixture(t)
				fixture.environment[name] = value
				if _, err := LoadConfig(validArguments(`http://127.0.0.1:1/v1`), fixture.lookup); err == nil || !strings.Contains(err.Error(), "lowercase SHA-256") {
					t.Fatalf("digest %q error = %v", value, err)
				}
			})
		}
	}
}

func TestLoadConfigRejectsUnsafeArtifactPaths(t *testing.T) {
	tests := []struct {
		name   string
		change func(*configFixture)
		want   string
	}{
		{
			name: "relative", want: "absolute canonical",
			change: func(f *configFixture) { f.environment[EnvPayload] = "payload.squashfs" },
		},
		{
			name: "noncanonical", want: "absolute canonical",
			change: func(f *configFixture) {
				f.environment[EnvPayload] = filepath.Dir(f.environment[EnvPayload]) + "/missing/../" + filepath.Base(f.environment[EnvPayload])
			},
		},
		{
			name: "direct symlink", want: "not a symlink",
			change: func(f *configFixture) {
				link := filepath.Join(f.root, "payload-link")
				if err := os.Symlink(f.environment[EnvPayload], link); err != nil {
					t.Fatal(err)
				}
				f.environment[EnvPayload] = link
			},
		},
		{
			name: "symlink ancestor", want: "must not traverse a symlink",
			change: func(f *configFixture) {
				real := filepath.Join(f.root, "linked-artifacts")
				if err := os.Mkdir(real, 0o700); err != nil {
					t.Fatal(err)
				}
				file := writeConfigFile(t, filepath.Join(real, "payload"), 0o600)
				link := filepath.Join(f.root, "artifact-parent-link")
				if err := os.Symlink(real, link); err != nil {
					t.Fatal(err)
				}
				f.environment[EnvPayload] = filepath.Join(link, filepath.Base(file))
			},
		},
		{
			name: "empty artifact", want: "non-empty direct regular file",
			change: func(f *configFixture) {
				path := filepath.Join(f.root, "empty-payload")
				if err := os.WriteFile(path, nil, 0o600); err != nil {
					t.Fatal(err)
				}
				f.environment[EnvPayload] = path
			},
		},
		{
			name: "artifact directory", want: "non-empty direct regular file",
			change: func(f *configFixture) { f.environment[EnvPayload] = f.root },
		},
		{
			name: "artifact fifo", want: "non-empty direct regular file",
			change: func(f *configFixture) {
				path := filepath.Join(f.root, "payload-fifo")
				if err := unix.Mkfifo(path, 0o600); err != nil {
					t.Fatal(err)
				}
				f.environment[EnvPayload] = path
			},
		},
		{
			name: "Firecracker not executable", want: "executable mode bit",
			change: func(f *configFixture) {
				if err := os.Chmod(f.environment[EnvFirecracker], 0o600); err != nil {
					t.Fatal(err)
				}
			},
		},
		{
			name: "guest not executable", want: "executable mode bit",
			change: func(f *configFixture) {
				if err := os.Chmod(f.environment[EnvGuest], 0o600); err != nil {
					t.Fatal(err)
				}
			},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			fixture := newConfigFixture(t)
			test.change(fixture)
			_, err := LoadConfig(validArguments(`http://127.0.0.1:1/v1`), fixture.lookup)
			if err == nil || !strings.Contains(err.Error(), test.want) {
				t.Fatalf("unsafe artifact error = %v, want %q", err, test.want)
			}
		})
	}
}

func TestLoadConfigRequiresPrivateEmptyEvidenceDirectory(t *testing.T) {
	tests := []struct {
		name   string
		change func(*configFixture)
		want   string
	}{
		{
			name: "public mode", want: "exactly 0700",
			change: func(f *configFixture) {
				if err := os.Chmod(f.environment[EnvEvidenceDir], 0o755); err != nil {
					t.Fatal(err)
				}
			},
		},
		{
			name: "nonempty", want: "must be empty",
			change: func(f *configFixture) {
				writeConfigFile(t, filepath.Join(f.environment[EnvEvidenceDir], "existing"), 0o600)
			},
		},
		{
			name: "regular file", want: "real directory",
			change: func(f *configFixture) {
				f.environment[EnvEvidenceDir] = writeConfigFile(t, filepath.Join(f.root, "not-evidence-dir"), 0o600)
			},
		},
		{
			name: "symlink", want: "not a symlink",
			change: func(f *configFixture) {
				link := filepath.Join(f.root, "evidence-link")
				if err := os.Symlink(f.environment[EnvEvidenceDir], link); err != nil {
					t.Fatal(err)
				}
				f.environment[EnvEvidenceDir] = link
			},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			fixture := newConfigFixture(t)
			test.change(fixture)
			_, err := LoadConfig(validArguments(`http://127.0.0.1:1/v1`), fixture.lookup)
			if err == nil || !strings.Contains(err.Error(), test.want) {
				t.Fatalf("evidence directory error = %v, want %q", err, test.want)
			}
		})
	}
}

func TestLoadConfigRequiresSeparateEmptyWorkspace(t *testing.T) {
	fixture := newConfigFixture(t)
	writeConfigFile(t, filepath.Join(fixture.environment[EnvWorkspace], "unexpected"), 0o600)
	if _, err := LoadConfig(validArguments(`http://127.0.0.1:1/v1`), fixture.lookup); err == nil || !strings.Contains(err.Error(), "must be empty") {
		t.Fatalf("nonempty workspace error = %v", err)
	}

	fixture = newConfigFixture(t)
	fixture.environment[EnvWorkspace] = fixture.environment[EnvEvidenceDir]
	if _, err := LoadConfig(validArguments(`http://127.0.0.1:1/v1`), fixture.lookup); err == nil || !strings.Contains(err.Error(), "overlap") {
		t.Fatalf("overlapping workspace error = %v", err)
	}
}

func TestLoadConfigRejectsUnsafeOrUnboundedArguments(t *testing.T) {
	tests := []struct {
		name      string
		arguments func() []string
		want      string
	}{
		{name: "wrong command", arguments: func() []string { return []string{"exec", "--stdio"} }, want: "must begin"},
		{name: "wrong transport", arguments: func() []string { return []string{"app-server", "--listen"} }, want: "must begin"},
		{name: "empty", arguments: func() []string { args := validArguments(`http://127.0.0.1:1/v1`); return append(args, "") }, want: "argument"},
		{name: "control", arguments: func() []string { args := validArguments(`http://127.0.0.1:1/v1`); return append(args, "bad\nargument") }, want: "control"},
		{name: "Unicode control", arguments: func() []string {
			args := validArguments(`http://127.0.0.1:1/v1`)
			return append(args, "bad\u0085argument")
		}, want: "control"},
		{name: "invalid UTF-8", arguments: func() []string {
			args := validArguments(`http://127.0.0.1:1/v1`)
			return append(args, string([]byte{0xff}))
		}, want: "invalid UTF-8"},
		{name: "oversized argument", arguments: func() []string {
			args := validArguments(`http://127.0.0.1:1/v1`)
			return append(args, strings.Repeat("x", MaxArgumentBytes+1))
		}, want: "too large"},
		{name: "too many", arguments: func() []string {
			args := validArguments(`http://127.0.0.1:1/v1`)
			for len(args) <= MaxArguments {
				args = append(args, "x")
			}
			return args
		}, want: "at most"},
		{name: "total too large", arguments: func() []string {
			args := validArguments(`http://127.0.0.1:1/v1`)
			for totalArgumentBytes(args) <= MaxTotalArgBytes {
				args = append(args, strings.Repeat("x", MaxArgumentBytes))
			}
			return args
		}, want: "exceed"},
		{name: "dangling -c", arguments: func() []string { return []string{"app-server", "--stdio", "-c"} }, want: "requires"},
		{name: "option terminator", arguments: func() []string {
			return []string{"app-server", "--stdio", "--", "-c", `base_url="http://127.0.0.1:1/v1"`}
		}, want: "terminate option parsing"},
		{name: "attached -c", arguments: func() []string { return []string{"app-server", "--stdio", `-cbase_url="http://127.0.0.1:1/v1"`} }, want: "separate -c"},
		{name: "long config alias", arguments: func() []string {
			return []string{"app-server", "--stdio", "--config", `base_url="http://127.0.0.1:1/v1"`}
		}, want: "separate -c"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			fixture := newConfigFixture(t)
			_, err := LoadConfig(test.arguments(), fixture.lookup)
			if err == nil || !strings.Contains(err.Error(), test.want) {
				t.Fatalf("argument error = %v, want %q", err, test.want)
			}
		})
	}
}

func TestLoadConfigRequiresExactlyOneStrictBasicStringBaseURL(t *testing.T) {
	tests := []struct {
		name     string
		override string
		want     string
	}{
		{name: "none", override: `model="gpt"`, want: "exactly one"},
		{name: "literal string", override: `base_url='http://127.0.0.1:1/v1'`, want: "basic string"},
		{name: "bare value", override: `base_url=http://127.0.0.1:1/v1`, want: "basic string"},
		{name: "unterminated", override: `base_url="http://127.0.0.1:1/v1`, want: "unterminated"},
		{name: "escaped control", override: `base_url="http://127.0.0.1:1/v1\n"`, want: "control"},
		{name: "unclosed inline table", override: `provider={base_url="http://127.0.0.1:1/v1"`, want: "unclosed"},
		{name: "bad trailing TOML", override: `base_url="http://127.0.0.1:1/v1"oops`, want: "following"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			fixture := newConfigFixture(t)
			arguments := []string{"app-server", "--stdio", "-c", test.override}
			_, err := LoadConfig(arguments, fixture.lookup)
			if err == nil || !strings.Contains(err.Error(), test.want) {
				t.Fatalf("TOML override error = %v, want %q", err, test.want)
			}
		})
	}

	t.Run("duplicate", func(t *testing.T) {
		fixture := newConfigFixture(t)
		arguments := validArguments(`http://127.0.0.1:1/v1`)
		arguments = append(arguments, "-c", `base_url="http://[::1]:2/v1"`)
		if _, err := LoadConfig(arguments, fixture.lookup); err == nil || !strings.Contains(err.Error(), "found 2") {
			t.Fatalf("duplicate base_url error = %v", err)
		}
	})

	t.Run("malformed unrelated override", func(t *testing.T) {
		fixture := newConfigFixture(t)
		arguments := append(validArguments(`http://127.0.0.1:1/v1`), "-c", "this is not TOML")
		if _, err := LoadConfig(arguments, fixture.lookup); err == nil || !strings.Contains(err.Error(), "no assignment") {
			t.Fatalf("malformed unrelated override error = %v", err)
		}
	})

	t.Run("multiple top-level assignments", func(t *testing.T) {
		fixture := newConfigFixture(t)
		arguments := append(validArguments(`http://127.0.0.1:1/v1`), "-c", "broken==1")
		if _, err := LoadConfig(arguments, fixture.lookup); err == nil || !strings.Contains(err.Error(), "top-level assignment") {
			t.Fatalf("multiple-assignment override error = %v", err)
		}
	})

	t.Run("name inside string ignored", func(t *testing.T) {
		fixture := newConfigFixture(t)
		arguments := []string{
			"app-server", "--stdio",
			"-c", `description="base_url=not-an-assignment"`,
			"-c", `provider={database_url="http://example.invalid",base_url="http://127.0.0.1:9/v1"}`,
		}
		config, err := LoadConfig(arguments, fixture.lookup)
		if err != nil {
			t.Fatal(err)
		}
		if config.HostModelTarget != "127.0.0.1:9" {
			t.Fatalf("target = %q", config.HostModelTarget)
		}
	})
}

func TestLoadConfigRejectsNonLoopbackOrAmbiguousModelURLs(t *testing.T) {
	invalid := []string{
		`https://127.0.0.1:80/v1`,
		`//127.0.0.1:80/v1`,
		`http://localhost:80/v1`,
		`http://127.1:80/v1`,
		`http://2130706433:80/v1`,
		`http://0177.0.0.1:80/v1`,
		`http://127.000.000.001:80/v1`,
		`http://127.0.0.1.:80/v1`,
		`http://127.0.0.2:80/v1`,
		`http://[::1]:80/v1`,
		`http://[0:0:0:0:0:0:0:1]:80/v1`,
		`http://[::ffff:127.0.0.1]:80/v1`,
		`http://[::1%25lo]:80/v1`,
		`http://user@127.0.0.1:80/v1`,
		`http://127.0.0.1/v1`,
		`http://127.0.0.1:0/v1`,
		`http://127.0.0.1:65536/v1`,
		`http://127.0.0.1:7000/v1`,
		`http://127.0.0.1:000080/v1`,
		`http://127.0.0.1:http/v1`,
		`http://127.0.0.1:80`,
		`http://127.0.0.1:80/v1?query=yes`,
		`http://127.0.0.1:80/v1?`,
		`http://127.0.0.1:80/v1#fragment`,
		`http://127.0.0.1:80/v1#`,
		`http://127.0.0.1:80/v1%0aheader`,
	}
	for _, modelURL := range invalid {
		t.Run(modelURL, func(t *testing.T) {
			fixture := newConfigFixture(t)
			if _, err := LoadConfig(validArguments(modelURL), fixture.lookup); err == nil {
				t.Fatalf("accepted model URL %q", modelURL)
			}
		})
	}
}

type configFixture struct {
	root        string
	environment map[string]string
}

func newConfigFixture(t *testing.T) *configFixture {
	t.Helper()
	root := t.TempDir()
	artifacts := filepath.Join(root, "artifacts")
	if err := os.Mkdir(artifacts, 0o700); err != nil {
		t.Fatal(err)
	}
	evidence := filepath.Join(root, "evidence")
	if err := os.Mkdir(evidence, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(evidence, 0o700); err != nil {
		t.Fatal(err)
	}
	workspace := filepath.Join(root, "workspace")
	if err := os.Mkdir(workspace, 0o700); err != nil {
		t.Fatal(err)
	}
	return &configFixture{
		root: root,
		environment: map[string]string{
			EnvRunnerSHA256:      strings.Repeat("0", 64),
			EnvFirecracker:       writeConfigFile(t, filepath.Join(artifacts, "firecracker"), 0o700),
			EnvFirecrackerSHA256: strings.Repeat("1", 64),
			EnvKernel:            writeConfigFile(t, filepath.Join(artifacts, "kernel"), 0o600),
			EnvKernelSHA256:      strings.Repeat("2", 64),
			EnvGuest:             writeConfigFile(t, filepath.Join(artifacts, "guest"), 0o700),
			EnvGuestSHA256:       strings.Repeat("5", 64),
			EnvPayload:           writeConfigFile(t, filepath.Join(artifacts, "payload.squashfs"), 0o600),
			EnvPayloadSHA256:     strings.Repeat("3", 64),
			EnvRepository:        writeConfigFile(t, filepath.Join(artifacts, "repository.bundle"), 0o600),
			EnvRepositorySHA256:  strings.Repeat("6", 64),
			EnvCodexSHA256:       strings.Repeat("4", 64),
			EnvEvidenceDir:       evidence,
			EnvWorkspace:         workspace,
		},
	}
}

func (fixture *configFixture) lookup(name string) (string, bool) {
	value, ok := fixture.environment[name]
	return value, ok
}

func validArguments(modelURL string) []string {
	return []string{
		"app-server", "--stdio",
		"-c", `model="gpt-5.6-sol"`,
		"-c", `model_providers.safe_change={name="fixture",base_url="` + modelURL + `",wire_api="responses",requires_openai_auth=false}`,
	}
}

func writeConfigFile(t *testing.T, path string, mode os.FileMode) string {
	t.Helper()
	if err := os.WriteFile(path, []byte("artifact\n"), mode); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, mode); err != nil {
		t.Fatal(err)
	}
	return path
}

func totalArgumentBytes(arguments []string) int {
	total := 0
	for _, argument := range arguments {
		total += len(argument)
	}
	return total
}
