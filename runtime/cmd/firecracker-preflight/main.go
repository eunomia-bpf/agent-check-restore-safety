// Command firecracker-preflight performs read-only admission checks for the
// Firecracker backend. It deliberately distinguishes the current KVM prototype
// from a production launch through Firecracker's jailer.
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"debug/buildinfo"
	"debug/elf"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

const (
	prototypeLevel  = "prototype"
	productionLevel = "production"

	firecrackerVersion = "1.16.1"
	firecrackerSize    = int64(3527456)
	firecrackerSHA256  = "2fd0171309af7e24cf8dafc8a6f921c1434c49b5f9349bb996b7ed0a4deb8aa7"
	jailerSize         = int64(2181264)
	jailerSHA256       = "1f3a0c1fe86212d0001819bfe0819071c01208b3ccc9398c3b3bc1b84cf21edd"
	kernelVersion      = "6.1.155"
	kernelSize         = int64(44279576)
	kernelSHA256       = "e20e46d0c36c55c0d1014eb20576171b3f3d922260d9f792017aeff53af3d4f2"

	kvmGetAPIVersion = uintptr(0xAE00)
	kvmAPIVersion    = uintptr(12)

	guestPackage = "github.com/eunomia-bpf/agent-check-restore-safety/runtime/cmd/firecracker-guest"

	// This is intentionally false until firecracker-demo starts every VMM via
	// the pinned jailer and stages all per-instance resources inside its jail.
	runtimeJailerIntegrated = false
)

type options struct {
	level        string
	firecracker  string
	jailer       string
	kernel       string
	guest        string
	privateDir   string
	chrootBase   string
	resourceDir  string
	cgroupParent string
	jailerUser   string
	jailerGroup  string
}

type checkResult struct {
	Level  string `json:"level"`
	Name   string `json:"name"`
	OK     bool   `json:"ok"`
	Detail string `json:"detail"`
}

type scopeReport struct {
	NetworkInterfaces       int    `json:"network_interfaces"`
	RootBlockDevices        int    `json:"root_block_devices"`
	GuestBoot               string `json:"guest_boot"`
	RuntimeJailerIntegrated bool   `json:"runtime_jailer_integrated"`
}

type preflightReport struct {
	Schema              int           `json:"schema"`
	RequestedLevel      string        `json:"requested_level"`
	PrototypeReady      bool          `json:"prototype_ready"`
	ProductionHostReady bool          `json:"production_host_ready"`
	ProductionReady     bool          `json:"production_ready"`
	Scope               scopeReport   `json:"scope"`
	Checks              []checkResult `json:"checks"`
}

type artifactPin struct {
	name       string
	size       int64
	sha256     string
	executable bool
}

func main() {
	config := defaultOptions()
	flag.StringVar(&config.level, "level", prototypeLevel, "readiness level: prototype or production")
	flag.StringVar(&config.firecracker, "firecracker", config.firecracker, "pinned Firecracker executable")
	flag.StringVar(&config.jailer, "jailer", config.jailer, "pinned Firecracker jailer executable")
	flag.StringVar(&config.kernel, "kernel", config.kernel, "pinned guest kernel")
	flag.StringVar(&config.guest, "guest", config.guest, "static firecracker-guest executable")
	flag.StringVar(&config.privateDir, "private-dir", config.privateDir, "0700 prototype work directory")
	flag.StringVar(&config.chrootBase, "chroot-base", config.chrootBase, "production jailer chroot base")
	flag.StringVar(&config.resourceDir, "resource-dir", config.resourceDir, "production trusted resource-staging directory")
	flag.StringVar(&config.cgroupParent, "cgroup-parent", config.cgroupParent, "production cgroup v2 parent")
	flag.StringVar(&config.jailerUser, "jailer-user", config.jailerUser, "dedicated production POSIX user")
	flag.StringVar(&config.jailerGroup, "jailer-group", config.jailerGroup, "dedicated production POSIX group")
	flag.Parse()

	if err := validateOptions(config); err != nil {
		fmt.Fprintf(os.Stderr, "firecracker preflight: %v\n", err)
		os.Exit(2)
	}
	report := evaluate(config)
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(report); err != nil {
		fmt.Fprintf(os.Stderr, "firecracker preflight: encode report: %v\n", err)
		os.Exit(2)
	}

	ready := report.PrototypeReady
	if config.level == productionLevel {
		ready = report.ProductionReady
	}
	if !ready {
		fmt.Fprintf(os.Stderr, "NOT READY: Firecracker %s admission failed\n", config.level)
		os.Exit(1)
	}
	fmt.Fprintf(os.Stderr, "READY: Firecracker %s admission passed\n", config.level)
}

func defaultOptions() options {
	cacheRoot := ""
	if cache, err := os.UserCacheDir(); err == nil {
		cacheRoot = filepath.Join(cache, "safe-change-runtime", "firecracker")
	}
	versionRoot := filepath.Join(cacheRoot, "v"+firecrackerVersion, "release-v"+firecrackerVersion+"-x86_64")
	return options{
		level:        prototypeLevel,
		firecracker:  filepath.Join(versionRoot, "firecracker-v"+firecrackerVersion+"-x86_64"),
		jailer:       filepath.Join(versionRoot, "jailer-v"+firecrackerVersion+"-x86_64"),
		kernel:       filepath.Join(cacheRoot, "assets-v1.15", "vmlinux-"+kernelVersion),
		guest:        filepath.Join(cacheRoot, "build", "firecracker-guest"),
		privateDir:   cacheRoot,
		chrootBase:   "/srv/jailer",
		resourceDir:  "/var/lib/safe-change/firecracker",
		cgroupParent: "/sys/fs/cgroup/safe-change-firecracker",
		jailerUser:   "safe-change-firecracker",
		jailerGroup:  "safe-change-firecracker",
	}
}

func validateOptions(config options) error {
	if config.level != prototypeLevel && config.level != productionLevel {
		return fmt.Errorf("-level must be %q or %q", prototypeLevel, productionLevel)
	}
	for _, field := range []struct {
		name  string
		value string
	}{
		{name: "-firecracker", value: config.firecracker},
		{name: "-jailer", value: config.jailer},
		{name: "-kernel", value: config.kernel},
		{name: "-guest", value: config.guest},
		{name: "-private-dir", value: config.privateDir},
		{name: "-chroot-base", value: config.chrootBase},
		{name: "-resource-dir", value: config.resourceDir},
		{name: "-cgroup-parent", value: config.cgroupParent},
		{name: "-jailer-user", value: config.jailerUser},
		{name: "-jailer-group", value: config.jailerGroup},
	} {
		if strings.TrimSpace(field.value) == "" {
			return fmt.Errorf("%s must not be empty", field.name)
		}
	}
	return nil
}

func evaluate(config options) preflightReport {
	checks := make([]checkResult, 0, 20)
	add := func(level, name string, probe func() (string, error)) checkResult {
		result := runCheck(level, name, probe)
		checks = append(checks, result)
		return result
	}

	add(prototypeLevel, "platform", checkPlatform)
	add(prototypeLevel, "kvm_api", checkKVM)
	fcAsset := add(prototypeLevel, "firecracker_asset", func() (string, error) {
		return verifyLockedArtifact(config.firecracker, artifactPin{
			name: "Firecracker", size: firecrackerSize, sha256: firecrackerSHA256, executable: true,
		})
	})
	add(prototypeLevel, "firecracker_version", func() (string, error) {
		if !fcAsset.OK {
			return "", errors.New("not executed because the pinned Firecracker asset failed")
		}
		return checkPinnedProgramVersion(config.firecracker, artifactPin{
			name: "Firecracker", size: firecrackerSize, sha256: firecrackerSHA256, executable: true,
		}, "Firecracker v"+firecrackerVersion)
	})
	add(prototypeLevel, "kernel_asset", func() (string, error) {
		return verifyLockedArtifact(config.kernel, artifactPin{
			name: "guest kernel", size: kernelSize, sha256: kernelSHA256,
		})
	})
	add(prototypeLevel, "static_guest", func() (string, error) {
		return checkStaticGuest(config.guest)
	})
	add(prototypeLevel, "private_work_directory", func() (string, error) {
		return checkPrivateDirectory(config.privateDir)
	})

	prototypeReady := allChecksOK(checks)
	productionHostReady := false
	productionReady := false
	if config.level == productionLevel {
		productionStart := len(checks)
		jailerAsset := add("production-host", "jailer_asset", func() (string, error) {
			return verifyLockedArtifact(config.jailer, artifactPin{
				name: "jailer", size: jailerSize, sha256: jailerSHA256, executable: true,
			})
		})
		add("production-host", "jailer_version", func() (string, error) {
			if !jailerAsset.OK {
				return "", errors.New("not executed because the pinned jailer asset failed")
			}
			return checkPinnedProgramVersion(config.jailer, artifactPin{
				name: "jailer", size: jailerSize, sha256: jailerSHA256, executable: true,
			}, "Jailer v"+firecrackerVersion)
		})
		for _, trusted := range []struct {
			name string
			path string
		}{
			{name: "firecracker_trusted_path", path: config.firecracker},
			{name: "jailer_trusted_path", path: config.jailer},
			{name: "kernel_trusted_path", path: config.kernel},
			{name: "guest_trusted_path", path: config.guest},
		} {
			trusted := trusted
			add("production-host", trusted.name, func() (string, error) {
				return checkTrustedPath(trusted.path, false)
			})
		}
		add("production-host", "root_invoker", checkRootInvoker)
		add("production-host", "dedicated_identity", func() (string, error) {
			return checkDedicatedIdentity(config.jailerUser, config.jailerGroup)
		})
		add("production-host", "cgroup_v2", checkCgroupV2)
		add("production-host", "cgroup_parent", func() (string, error) {
			return checkCgroupParent(config.cgroupParent)
		})
		add("production-host", "chroot_base", func() (string, error) {
			return checkTrustedPath(config.chrootBase, true)
		})
		add("production-host", "resource_staging", func() (string, error) {
			return checkTrustedPath(config.resourceDir, true)
		})
		productionHostReady = prototypeReady && allChecksOK(checks[productionStart:])
		integration := add("production-runtime", "jailer_integration", checkJailerIntegration)
		productionReady = productionHostReady && integration.OK
	}

	return preflightReport{
		Schema:              1,
		RequestedLevel:      config.level,
		PrototypeReady:      prototypeReady,
		ProductionHostReady: productionHostReady,
		ProductionReady:     productionReady,
		Scope: scopeReport{
			NetworkInterfaces:       0,
			RootBlockDevices:        0,
			GuestBoot:               "initramfs-only",
			RuntimeJailerIntegrated: runtimeJailerIntegrated,
		},
		Checks: checks,
	}
}

func runCheck(level, name string, probe func() (string, error)) checkResult {
	detail, err := probe()
	if err != nil {
		return checkResult{Level: level, Name: name, OK: false, Detail: err.Error()}
	}
	return checkResult{Level: level, Name: name, OK: true, Detail: detail}
}

func allChecksOK(checks []checkResult) bool {
	if len(checks) == 0 {
		return false
	}
	for _, check := range checks {
		if !check.OK {
			return false
		}
	}
	return true
}

func checkPlatform() (string, error) {
	if runtime.GOOS != "linux" || runtime.GOARCH != "amd64" {
		return "", fmt.Errorf("requires Linux amd64, got %s/%s", runtime.GOOS, runtime.GOARCH)
	}
	return "Linux amd64", nil
}

func checkKVM() (string, error) {
	info, err := os.Lstat("/dev/kvm")
	if err != nil {
		return "", fmt.Errorf("/dev/kvm: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || info.Mode()&os.ModeCharDevice == 0 {
		return "", errors.New("/dev/kvm is not a direct character device")
	}
	fd, err := unix.Open("/dev/kvm", unix.O_RDWR|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return "", fmt.Errorf("open /dev/kvm read/write: %w", err)
	}
	defer unix.Close(fd)
	version, _, errno := unix.Syscall(unix.SYS_IOCTL, uintptr(fd), kvmGetAPIVersion, 0)
	if errno != 0 {
		return "", fmt.Errorf("KVM_GET_API_VERSION: %w", errno)
	}
	if version != kvmAPIVersion {
		return "", fmt.Errorf("KVM API version is %d, require %d", version, kvmAPIVersion)
	}
	pidfd, err := unix.PidfdOpen(os.Getpid(), 0)
	if err != nil {
		return "", fmt.Errorf("pidfd_open current process: %w", err)
	}
	if err := unix.Close(pidfd); err != nil {
		return "", fmt.Errorf("close pidfd probe: %w", err)
	}
	return fmt.Sprintf("/dev/kvm opened read/write; KVM API version %d; pidfd available", version), nil
}

func verifyLockedArtifact(path string, pin artifactPin) (string, error) {
	file, info, err := openRegularFile(path)
	if err != nil {
		return "", fmt.Errorf("%s: %w", pin.name, err)
	}
	defer file.Close()
	return verifyOpenedArtifact(file, info, pin)
}

func verifyOpenedArtifact(file *os.File, info os.FileInfo, pin artifactPin) (string, error) {
	if file == nil || info == nil {
		return "", fmt.Errorf("%s has no open file identity", pin.name)
	}
	if info.Size() != pin.size {
		return "", fmt.Errorf("%s size is %d, require %d", pin.name, info.Size(), pin.size)
	}
	if pin.executable && info.Mode().Perm()&0o111 == 0 {
		return "", fmt.Errorf("%s is not executable", pin.name)
	}
	digest := sha256.New()
	if _, err := io.Copy(digest, file); err != nil {
		return "", fmt.Errorf("hash %s: %w", pin.name, err)
	}
	actual := hex.EncodeToString(digest.Sum(nil))
	if actual != pin.sha256 {
		return "", fmt.Errorf("%s SHA-256 is %s, require %s", pin.name, actual, pin.sha256)
	}
	return fmt.Sprintf("%s bytes; SHA-256 %s", strconv.FormatInt(pin.size, 10), pin.sha256), nil
}

func openRegularFile(path string) (*os.File, os.FileInfo, error) {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return nil, nil, err
	}
	fd, err := unix.Open(filepath.Clean(absolute), unix.O_RDONLY|unix.O_CLOEXEC|unix.O_NOFOLLOW, 0)
	if err != nil {
		return nil, nil, err
	}
	file := os.NewFile(uintptr(fd), filepath.Clean(absolute))
	if file == nil {
		unix.Close(fd)
		return nil, nil, errors.New("cannot create file handle")
	}
	info, err := file.Stat()
	if err != nil {
		file.Close()
		return nil, nil, err
	}
	if !info.Mode().IsRegular() {
		file.Close()
		return nil, nil, errors.New("not a regular file")
	}
	return file, info, nil
}

func checkPinnedProgramVersion(path string, pin artifactPin, expected string) (string, error) {
	file, info, err := openRegularFile(path)
	if err != nil {
		return "", fmt.Errorf("%s: %w", pin.name, err)
	}
	defer file.Close()
	if _, err := verifyOpenedArtifact(file, info, pin); err != nil {
		return "", err
	}
	sealed, err := sealExecutable(file, pin)
	if err != nil {
		return "", err
	}
	defer sealed.Close()
	return checkProgramVersionFile(sealed, expected)
}

func checkProgramVersionFile(program *os.File, expected string) (string, error) {
	if program == nil {
		return "", errors.New("version program file is nil")
	}
	seals, err := unix.FcntlInt(program.Fd(), unix.F_GET_SEALS, 0)
	if err != nil || seals != unix.F_SEAL_SEAL|unix.F_SEAL_SHRINK|unix.F_SEAL_GROW|unix.F_SEAL_WRITE {
		return "", errors.New("version program is not an immutable sealed file")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	// ExtraFiles maps the already-open, hash-verified inode to descriptor 3 in
	// the child. Executing through /proc/self/fd/3 avoids reopening a pathname
	// that another account could replace between verification and execve.
	command := exec.CommandContext(ctx, "/proc/self/fd/3", "--version")
	command.ExtraFiles = []*os.File{program}
	command.Env = []string{"LC_ALL=C", "PATH=/usr/sbin:/usr/bin:/sbin:/bin"}
	var stdout, stderr bytes.Buffer
	command.Stdout = &stdout
	command.Stderr = &stderr
	if err := command.Run(); err != nil {
		if ctx.Err() != nil {
			return "", fmt.Errorf("version command: %w", ctx.Err())
		}
		return "", fmt.Errorf("version command: %w (stderr %q)", err, strings.TrimSpace(stderr.String()))
	}
	lines := strings.Split(strings.TrimSpace(stdout.String()), "\n")
	if len(lines) == 0 || strings.TrimSpace(lines[0]) != expected {
		return "", fmt.Errorf("first version line is %q, require %q", strings.TrimSpace(stdout.String()), expected)
	}
	return expected, nil
}

func sealExecutable(source *os.File, pin artifactPin) (*os.File, error) {
	if source == nil {
		return nil, errors.New("executable source file is nil")
	}
	if _, err := source.Seek(0, io.SeekStart); err != nil {
		return nil, fmt.Errorf("rewind %s: %w", pin.name, err)
	}
	fd, err := unix.MemfdCreate("verified-"+strings.ToLower(pin.name), unix.MFD_CLOEXEC|unix.MFD_ALLOW_SEALING)
	if err != nil {
		return nil, fmt.Errorf("create sealed %s: %w", pin.name, err)
	}
	sealed := os.NewFile(uintptr(fd), "sealed-"+pin.name)
	if sealed == nil {
		unix.Close(fd)
		return nil, fmt.Errorf("create sealed %s file handle", pin.name)
	}
	fail := func(failure error) (*os.File, error) {
		_ = sealed.Close()
		return nil, failure
	}
	digest := sha256.New()
	written, err := io.Copy(io.MultiWriter(sealed, digest), source)
	if err != nil {
		return fail(fmt.Errorf("copy %s into sealed file: %w", pin.name, err))
	}
	if written != pin.size || hex.EncodeToString(digest.Sum(nil)) != pin.sha256 {
		return fail(fmt.Errorf("%s changed while making its sealed execution copy", pin.name))
	}
	if err := unix.Fchmod(fd, 0o500); err != nil {
		return fail(fmt.Errorf("make sealed %s executable: %w", pin.name, err))
	}
	wanted := unix.F_SEAL_SEAL | unix.F_SEAL_SHRINK | unix.F_SEAL_GROW | unix.F_SEAL_WRITE
	if _, err := unix.FcntlInt(sealed.Fd(), unix.F_ADD_SEALS, wanted); err != nil {
		return fail(fmt.Errorf("seal %s: %w", pin.name, err))
	}
	if actual, err := unix.FcntlInt(sealed.Fd(), unix.F_GET_SEALS, 0); err != nil || actual != wanted {
		return fail(fmt.Errorf("verify sealed %s", pin.name))
	}
	return sealed, nil
}

func checkStaticGuest(path string) (string, error) {
	file, info, err := openRegularFile(path)
	if err != nil {
		return "", fmt.Errorf("guest: %w", err)
	}
	defer file.Close()
	if info.Mode().Perm()&0o111 == 0 {
		return "", errors.New("guest is not executable")
	}
	binary, err := elf.NewFile(file)
	if err != nil {
		return "", fmt.Errorf("guest ELF: %w", err)
	}
	defer binary.Close()
	if binary.Class != elf.ELFCLASS64 || binary.Machine != elf.EM_X86_64 || binary.Type != elf.ET_EXEC {
		return "", fmt.Errorf("guest must be a 64-bit x86-64 executable, got class=%v machine=%v type=%v", binary.Class, binary.Machine, binary.Type)
	}
	for _, program := range binary.Progs {
		if program.Type == elf.PT_INTERP {
			return "", errors.New("guest has a userspace ELF interpreter")
		}
	}
	libraries, err := binary.ImportedLibraries()
	if err != nil {
		return "", fmt.Errorf("read guest imports: %w", err)
	}
	if len(libraries) != 0 {
		return "", fmt.Errorf("guest imports dynamic libraries: %s", strings.Join(libraries, ", "))
	}
	infoBuild, err := buildinfo.Read(file)
	if err != nil {
		return "", fmt.Errorf("guest Go build information: %w", err)
	}
	if infoBuild.Path != guestPackage {
		return "", fmt.Errorf("guest package is %q, require %q", infoBuild.Path, guestPackage)
	}
	settings := make(map[string]string, len(infoBuild.Settings))
	for _, setting := range infoBuild.Settings {
		settings[setting.Key] = setting.Value
	}
	for _, required := range []struct {
		key   string
		value string
	}{
		{key: "CGO_ENABLED", value: "0"},
		{key: "GOOS", value: "linux"},
		{key: "GOARCH", value: "amd64"},
		{key: "-buildmode", value: "exe"},
	} {
		if settings[required.key] != required.value {
			return "", fmt.Errorf("guest build setting %s is %q, require %q", required.key, settings[required.key], required.value)
		}
	}
	return fmt.Sprintf("static Linux amd64 %s built with CGO_ENABLED=0", infoBuild.Path), nil
}

func checkPrivateDirectory(path string) (string, error) {
	absolute, err := canonicalDirectPath(path)
	if err != nil {
		return "", err
	}
	info, err := os.Lstat(absolute)
	if err != nil {
		return "", err
	}
	if !info.IsDir() {
		return "", fmt.Errorf("%s is not a directory", absolute)
	}
	if info.Mode().Perm() != 0o700 {
		return "", fmt.Errorf("%s mode is %04o, require 0700", absolute, info.Mode().Perm())
	}
	uid, _, err := ownerIDs(info)
	if err != nil {
		return "", err
	}
	if uid != uint32(os.Geteuid()) {
		return "", fmt.Errorf("%s owner UID is %d, require current UID %d", absolute, uid, os.Geteuid())
	}
	return absolute + " is canonical, direct, current-UID-owned, and mode 0700", nil
}

func canonicalDirectPath(path string) (string, error) {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	absolute = filepath.Clean(absolute)
	for _, component := range pathComponents(absolute) {
		info, err := os.Lstat(component)
		if err != nil {
			return "", fmt.Errorf("%s: %w", component, err)
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return "", fmt.Errorf("%s is a symbolic-link component", component)
		}
	}
	resolved, err := filepath.EvalSymlinks(absolute)
	if err != nil {
		return "", err
	}
	if filepath.Clean(resolved) != absolute {
		return "", fmt.Errorf("%s resolves to %s", absolute, resolved)
	}
	return absolute, nil
}

func pathComponents(absolute string) []string {
	if absolute == string(filepath.Separator) {
		return []string{absolute}
	}
	parts := strings.Split(strings.TrimPrefix(absolute, string(filepath.Separator)), string(filepath.Separator))
	components := make([]string, 0, len(parts)+1)
	current := string(filepath.Separator)
	components = append(components, current)
	for _, part := range parts {
		current = filepath.Join(current, part)
		components = append(components, current)
	}
	return components
}

func ownerIDs(info os.FileInfo) (uint32, uint32, error) {
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return 0, 0, errors.New("file ownership is unavailable")
	}
	return stat.Uid, stat.Gid, nil
}

func checkTrustedPath(path string, requireDirectory bool) (string, error) {
	absolute, err := canonicalDirectPath(path)
	if err != nil {
		return "", err
	}
	for _, component := range pathComponents(absolute) {
		info, err := os.Lstat(component)
		if err != nil {
			return "", err
		}
		uid, _, err := ownerIDs(info)
		if err != nil {
			return "", err
		}
		if uid != 0 {
			return "", fmt.Errorf("%s is owned by UID %d, require root ownership", component, uid)
		}
		if info.Mode().Perm()&0o022 != 0 {
			return "", fmt.Errorf("%s mode %04o permits an unprivileged write", component, info.Mode().Perm())
		}
		if err := rejectPOSIXACL(component); err != nil {
			return "", err
		}
	}
	if requireDirectory {
		info, err := os.Lstat(absolute)
		if err != nil {
			return "", err
		}
		if !info.IsDir() {
			return "", fmt.Errorf("%s is not a directory", absolute)
		}
	}
	return absolute + " and every parent are root-owned with no group/world write or POSIX ACL", nil
}

func rejectPOSIXACL(path string) error {
	for _, name := range []string{"system.posix_acl_access", "system.posix_acl_default"} {
		size, err := unix.Getxattr(path, name, nil)
		switch {
		case err == nil && size > 0:
			return fmt.Errorf("%s has %s; production trust cannot be established", path, name)
		case err == nil:
			continue
		case errors.Is(err, unix.ENODATA), errors.Is(err, unix.ENOTSUP), errors.Is(err, unix.EOPNOTSUPP):
			continue
		default:
			return fmt.Errorf("inspect %s on %s: %w", name, path, err)
		}
	}
	return nil
}

func checkRootInvoker() (string, error) {
	if os.Geteuid() != 0 {
		return "", fmt.Errorf("jailer setup requires root; effective UID is %d", os.Geteuid())
	}
	return "effective UID 0", nil
}

func checkDedicatedIdentity(userName, groupName string) (string, error) {
	account, err := user.Lookup(userName)
	if err != nil {
		return "", fmt.Errorf("lookup user %q: %w", userName, err)
	}
	group, err := user.LookupGroup(groupName)
	if err != nil {
		return "", fmt.Errorf("lookup group %q: %w", groupName, err)
	}
	uid, err := strconv.ParseUint(account.Uid, 10, 32)
	if err != nil {
		return "", fmt.Errorf("parse user UID: %w", err)
	}
	gid, err := strconv.ParseUint(group.Gid, 10, 32)
	if err != nil {
		return "", fmt.Errorf("parse group GID: %w", err)
	}
	primaryGID, err := strconv.ParseUint(account.Gid, 10, 32)
	if err != nil {
		return "", fmt.Errorf("parse user primary GID: %w", err)
	}
	if uid == 0 || gid == 0 {
		return "", errors.New("dedicated jailer UID and GID must both be nonzero")
	}
	if primaryGID != gid {
		return "", fmt.Errorf("user primary GID is %d, dedicated group GID is %d", primaryGID, gid)
	}
	if uint64(os.Geteuid()) == uid {
		return "", errors.New("dedicated jailer UID is the current invoker UID")
	}
	return fmt.Sprintf("dedicated non-root identity %s:%s is UID %d GID %d", userName, groupName, uid, gid), nil
}

func checkCgroupV2() (string, error) {
	var stats unix.Statfs_t
	if err := unix.Statfs("/sys/fs/cgroup", &stats); err != nil {
		return "", fmt.Errorf("stat cgroup mount: %w", err)
	}
	if int64(stats.Type) != int64(unix.CGROUP2_SUPER_MAGIC) {
		return "", fmt.Errorf("/sys/fs/cgroup filesystem type is %#x, require cgroup2", stats.Type)
	}
	if stats.Flags&unix.ST_RDONLY != 0 {
		return "", errors.New("/sys/fs/cgroup is read-only")
	}
	controllers, err := readWordSet("/sys/fs/cgroup/cgroup.controllers")
	if err != nil {
		return "", err
	}
	if missing := missingWords(controllers, []string{"cpu", "memory", "pids"}); len(missing) != 0 {
		return "", fmt.Errorf("cgroup v2 lacks controllers: %s", strings.Join(missing, ", "))
	}
	return "writable cgroup v2 mount with cpu, memory, and pids controllers", nil
}

func checkCgroupParent(path string) (string, error) {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	absolute = filepath.Clean(absolute)
	relative, err := filepath.Rel("/sys/fs/cgroup", absolute)
	if err != nil || relative == "." || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("%s must be a dedicated child of /sys/fs/cgroup", absolute)
	}
	if _, err := checkTrustedPath(absolute, true); err != nil {
		return "", err
	}
	controllers, err := readWordSet(filepath.Join(absolute, "cgroup.controllers"))
	if err != nil {
		return "", err
	}
	enabled, err := readWordSet(filepath.Join(absolute, "cgroup.subtree_control"))
	if err != nil {
		return "", err
	}
	required := []string{"cpu", "memory", "pids"}
	if missing := missingWords(controllers, required); len(missing) != 0 {
		return "", fmt.Errorf("cgroup parent cannot delegate controllers: %s", strings.Join(missing, ", "))
	}
	if missing := missingWords(enabled, required); len(missing) != 0 {
		return "", fmt.Errorf("cgroup parent has not enabled subtree controllers: %s", strings.Join(missing, ", "))
	}
	processes, err := os.ReadFile(filepath.Join(absolute, "cgroup.procs"))
	if err != nil {
		return "", err
	}
	if strings.TrimSpace(string(processes)) != "" {
		return "", errors.New("cgroup parent contains processes; require an empty delegating parent")
	}
	return absolute + " is an empty root-owned parent delegating cpu, memory, and pids", nil
}

func readWordSet(path string) (map[string]struct{}, error) {
	contents, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read %s: %w", path, err)
	}
	words := make(map[string]struct{})
	for _, word := range strings.Fields(string(contents)) {
		words[strings.TrimPrefix(word, "+")] = struct{}{}
	}
	return words, nil
}

func missingWords(actual map[string]struct{}, required []string) []string {
	missing := make([]string, 0, len(required))
	for _, word := range required {
		if _, ok := actual[word]; !ok {
			missing = append(missing, word)
		}
	}
	sort.Strings(missing)
	return missing
}

func checkJailerIntegration() (string, error) {
	if !runtimeJailerIntegrated {
		return "", errors.New("runner still starts Firecracker directly; jailer launch, per-instance chroot staging, cgroup limits, PID namespace, and privilege drop are not wired")
	}
	return "runner launches only through the pinned jailer", nil
}
