package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestCompiledPinsMatchAssetLock(t *testing.T) {
	lockPath := filepath.Join("..", "..", "deploy", "firecracker", "assets.lock.json")
	contents, err := os.ReadFile(lockPath)
	if err != nil {
		t.Fatal(err)
	}
	var lock struct {
		Firecracker struct {
			Version      string `json:"version"`
			BinarySize   int64  `json:"binary_size"`
			BinarySHA256 string `json:"binary_sha256"`
			JailerSize   int64  `json:"jailer_size"`
			JailerSHA256 string `json:"jailer_sha256"`
		} `json:"firecracker"`
		Kernel struct {
			Version string `json:"version"`
			Size    int64  `json:"size"`
			SHA256  string `json:"sha256"`
		} `json:"kernel"`
	}
	if err := json.Unmarshal(contents, &lock); err != nil {
		t.Fatal(err)
	}
	if lock.Firecracker.Version != firecrackerVersion ||
		lock.Firecracker.BinarySize != firecrackerSize ||
		lock.Firecracker.BinarySHA256 != firecrackerSHA256 ||
		lock.Firecracker.JailerSize != jailerSize ||
		lock.Firecracker.JailerSHA256 != jailerSHA256 ||
		lock.Kernel.Version != kernelVersion ||
		lock.Kernel.Size != kernelSize ||
		lock.Kernel.SHA256 != kernelSHA256 {
		t.Fatalf("compiled preflight pins do not match %s", lockPath)
	}
}

func TestValidateOptionsRejectsUnknownLevel(t *testing.T) {
	config := defaultOptions()
	config.level = "sandbox-ish"
	if err := validateOptions(config); err == nil {
		t.Fatal("validateOptions accepted an unknown readiness level")
	}
}

func TestVerifyLockedArtifact(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "asset")
	contents := []byte("checksum-pinned test asset")
	if err := os.WriteFile(path, contents, 0o700); err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(contents)
	pin := artifactPin{
		name: "test asset", size: int64(len(contents)),
		sha256: hex.EncodeToString(digest[:]), executable: true,
	}
	if _, err := verifyLockedArtifact(path, pin); err != nil {
		t.Fatalf("verifyLockedArtifact rejected exact asset: %v", err)
	}
	if err := os.WriteFile(path, []byte("different"), 0o700); err != nil {
		t.Fatal(err)
	}
	if _, err := verifyLockedArtifact(path, pin); err == nil {
		t.Fatal("verifyLockedArtifact accepted changed asset")
	}
	symlink := filepath.Join(directory, "asset-link")
	if err := os.Symlink(path, symlink); err != nil {
		t.Fatal(err)
	}
	if _, err := verifyLockedArtifact(symlink, pin); err == nil {
		t.Fatal("verifyLockedArtifact accepted a symbolic link")
	}
}

func TestProgramVersionExecutesSealedBytesAfterSourceMutation(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "program")
	contents := []byte("#!/bin/sh\nprintf '%s\\n' 'safe version'\n")
	if err := os.WriteFile(path, contents, 0o700); err != nil {
		t.Fatal(err)
	}
	program, _, err := openRegularFile(path)
	if err != nil {
		t.Fatal(err)
	}
	defer program.Close()
	digest := sha256.Sum256(contents)
	sealed, err := sealExecutable(program, artifactPin{
		name: "test program", size: int64(len(contents)),
		sha256: hex.EncodeToString(digest[:]), executable: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer sealed.Close()
	if err := os.WriteFile(path, []byte("#!/bin/sh\nprintf '%s\\n' 'replaced version'\n"), 0o500); err != nil {
		t.Fatal(err)
	}
	version, err := checkProgramVersionFile(sealed, "safe version")
	if err != nil {
		t.Fatalf("execute verified open file: %v", err)
	}
	if version != "safe version" {
		t.Fatalf("version = %q, want original open program", version)
	}
}

func TestStaticGuestAdmission(t *testing.T) {
	if runtime.GOOS != "linux" || runtime.GOARCH != "amd64" {
		t.Skip("Firecracker guest is Linux amd64")
	}
	moduleRoot := filepath.Clean(filepath.Join("..", ".."))
	guest := filepath.Join(t.TempDir(), "firecracker-guest")
	command := exec.Command("go", "build", "-trimpath", "-o", guest, "./cmd/firecracker-guest")
	command.Dir = moduleRoot
	command.Env = append(os.Environ(), "CGO_ENABLED=0", "GOOS=linux", "GOARCH=amd64")
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("build static guest: %v\n%s", err, output)
	}
	if _, err := checkStaticGuest(guest); err != nil {
		t.Fatalf("checkStaticGuest rejected the real static guest: %v", err)
	}

	dynamic := filepath.Join(t.TempDir(), "not-the-guest")
	contents, err := os.ReadFile("/bin/sh")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(dynamic, contents, 0o500); err != nil {
		t.Fatal(err)
	}
	if _, err := checkStaticGuest(dynamic); err == nil {
		t.Fatal("checkStaticGuest accepted /bin/sh")
	}
}

func TestPrivateDirectoryAdmission(t *testing.T) {
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	if _, err := checkPrivateDirectory(directory); err != nil {
		t.Fatalf("checkPrivateDirectory rejected private directory: %v", err)
	}
	if err := os.Chmod(directory, 0o750); err != nil {
		t.Fatal(err)
	}
	if _, err := checkPrivateDirectory(directory); err == nil {
		t.Fatal("checkPrivateDirectory accepted mode 0750")
	}
}

func TestTrustedPathRejectsUnprivilegedWrite(t *testing.T) {
	directory := t.TempDir()
	if err := os.Chmod(directory, 0o777); err != nil {
		t.Fatal(err)
	}
	_, err := checkTrustedPath(directory, true)
	if err == nil || !strings.Contains(err.Error(), "unprivileged write") {
		t.Fatalf("checkTrustedPath error = %v, want unprivileged-write rejection", err)
	}
}

func TestProductionCannotPassWithoutRuntimeJailer(t *testing.T) {
	if runtimeJailerIntegrated {
		t.Fatal("test must be updated when jailer integration is implemented")
	}
	if _, err := checkJailerIntegration(); err == nil {
		t.Fatal("production integration check passed without a jailer launcher")
	}
	checks := []checkResult{{OK: true}, {OK: false}}
	if allChecksOK(checks) {
		t.Fatal("allChecksOK accepted a failed production check")
	}
}
