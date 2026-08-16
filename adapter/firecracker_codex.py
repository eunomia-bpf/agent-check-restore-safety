"""Create a ``codex`` executable backed by one Firecracker microVM.

The generated executable preserves Codex's argv/stdin/stdout contract.  It
only fixes the host-owned Firecracker inputs in a minimal environment before
launching ``firecracker-codex-shim``; the existing App Server client therefore
does not need a Firecracker-specific code path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Mapping, Sequence


_CONTROL_CHARACTERS = frozenset(chr(value) for value in range(32)) | {chr(127)}
# Bound raw runner stderr before CodexAppServer's text-mode line reader sees it.
_STDERR_MAX_LINE_BYTES = 64 << 10
_STDERR_MAX_TOTAL_BYTES = 1 << 20
_STDERR_READ_BYTES = 64 << 10
_STDERR_LIMIT_EXIT = 125
_RUNNER_STOP_SECONDS = 2.0
_CONFIG_ENVIRONMENT = {
    "SAFE_CHANGE_RUNNER_SHA256": "runner_sha256",
    "SAFE_CHANGE_FIRECRACKER": "firecracker",
    "SAFE_CHANGE_FIRECRACKER_SHA256": "firecracker_sha256",
    "SAFE_CHANGE_KERNEL": "kernel",
    "SAFE_CHANGE_KERNEL_SHA256": "kernel_sha256",
    "SAFE_CHANGE_GUEST": "guest",
    "SAFE_CHANGE_GUEST_SHA256": "guest_sha256",
    "SAFE_CHANGE_PAYLOAD": "payload",
    "SAFE_CHANGE_PAYLOAD_SHA256": "payload_sha256",
    "SAFE_CHANGE_REPOSITORY": "repository",
    "SAFE_CHANGE_REPOSITORY_SHA256": "repository_sha256",
    "SAFE_CHANGE_CODEX_SHA256": "codex_sha256",
    "SAFE_CHANGE_EVIDENCE_DIR": "evidence_dir",
    "SAFE_CHANGE_WORKSPACE": "workspace",
}


class FirecrackerCodex:
    """A temporary executable suitable for ``CodexAppServer.codex_binary``."""

    def __init__(
        self,
        *,
        executable: Path,
        runner: Path,
        fixed_environment: Mapping[str, str],
        temporary: tempfile.TemporaryDirectory[str],
    ) -> None:
        self.executable = executable
        self.runner = runner
        self.fixed_environment = dict(fixed_environment)
        self._temporary: tempfile.TemporaryDirectory[str] | None = temporary

    def command(self, codex_arguments: Sequence[str] = ()) -> tuple[str, ...]:
        """Return the exact argv ultimately received by the fixed runner."""

        return (os.fspath(self.runner), *tuple(codex_arguments))

    def close(self) -> None:
        temporary, self._temporary = self._temporary, None
        if temporary is not None:
            temporary.cleanup()

    def __fspath__(self) -> str:
        return os.fspath(self.executable)

    def __enter__(self) -> "FirecrackerCodex":
        return self

    def __exit__(self, *unused: object) -> None:
        self.close()


def create_firecracker_codex(
    *,
    runner: str | os.PathLike[str],
    runner_sha256: str,
    firecracker: str | os.PathLike[str],
    firecracker_sha256: str,
    kernel: str | os.PathLike[str],
    kernel_sha256: str,
    guest: str | os.PathLike[str],
    guest_sha256: str,
    payload: str | os.PathLike[str],
    payload_sha256: str,
    repository: str | os.PathLike[str],
    repository_sha256: str,
    codex_sha256: str,
    evidence_dir: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    mcp_host_socket: str | os.PathLike[str] | None = None,
    temp_parent: str | os.PathLike[str] | None = None,
) -> FirecrackerCodex:
    """Create a transparent executable with immutable microVM configuration.

    The host workspace is the client-visible path identity. The repository is
    an immutable canonical bundle that the guest verifies and materializes at
    that path's in-guest counterpart. Evidence is written only to an existing,
    empty, private directory owned by the caller.
    """

    runner_path = _regular_file(runner, "runner", executable=True)
    firecracker_path = _regular_file(
        firecracker, "firecracker", executable=True
    )
    kernel_path = _regular_file(kernel, "kernel")
    guest_path = _regular_file(guest, "guest", executable=True)
    payload_path = _regular_file(payload, "payload")
    repository_path = _regular_file(repository, "repository")
    workspace_path = _directory(workspace, "workspace")
    evidence_path = _directory(evidence_dir, "evidence_dir")
    paths = {
        "runner": runner_path,
        "firecracker": firecracker_path,
        "kernel": kernel_path,
        "guest": guest_path,
        "payload": payload_path,
        "repository": repository_path,
        "workspace": workspace_path,
        "evidence_dir": evidence_path,
    }
    if mcp_host_socket is not None:
        paths["mcp_host_socket"] = _private_socket(
            mcp_host_socket, "mcp_host_socket"
        )
    _require_pairwise_disjoint(paths)
    _require_empty(workspace_path, "workspace")
    _require_empty(evidence_path, "evidence_dir")
    if evidence_path.stat().st_mode & 0o077:
        raise PermissionError("evidence_dir must not grant group or other access")
    hashes = {
        "runner_sha256": _sha256(runner_sha256, "runner_sha256"),
        "firecracker_sha256": _sha256(firecracker_sha256, "firecracker_sha256"),
        "kernel_sha256": _sha256(kernel_sha256, "kernel_sha256"),
        "guest_sha256": _sha256(guest_sha256, "guest_sha256"),
        "payload_sha256": _sha256(payload_sha256, "payload_sha256"),
        "repository_sha256": _sha256(
            repository_sha256, "repository_sha256"
        ),
        "codex_sha256": _sha256(codex_sha256, "codex_sha256"),
    }
    values = {
        **{name: os.fspath(path) for name, path in paths.items()},
        **hashes,
    }
    fixed_environment = {
        environment: values[label]
        for environment, label in _CONFIG_ENVIRONMENT.items()
    }
    if mcp_host_socket is not None:
        fixed_environment["SAFE_CHANGE_MCP_HOST_SOCKET"] = values[
            "mcp_host_socket"
        ]

    parent = _directory(temp_parent, "temp_parent") if temp_parent is not None else None
    temporary = tempfile.TemporaryDirectory(
        prefix="firecracker-codex-", dir=parent
    )
    try:
        temporary_path = Path(temporary.name).resolve(strict=True)
        for label, path in paths.items():
            _require_disjoint(temporary_path, path, "wrapper", label)
        executable = temporary_path / "codex"
        executable.write_text(
            _wrapper_source(runner_path, fixed_environment), encoding="utf-8"
        )
        executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    except BaseException:
        temporary.cleanup()
        raise

    return FirecrackerCodex(
        executable=executable,
        runner=runner_path,
        fixed_environment=fixed_environment,
        temporary=temporary,
    )


def _wrapper_source(runner: Path, fixed_environment: Mapping[str, str]) -> str:
    interpreter = Path(sys.executable).resolve(strict=True)
    runner_literal = json.dumps(os.fspath(runner), ensure_ascii=True)
    environment_literal = json.dumps(
        dict(sorted(fixed_environment.items())),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        f"#!{interpreter}\n"
        "import ctypes\n"
        "import os\n"
        "import select\n"
        "import signal\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        f"runner = {runner_literal}\n"
        f"fixed = {environment_literal}\n"
        f"max_line = {_STDERR_MAX_LINE_BYTES}\n"
        f"max_total = {_STDERR_MAX_TOTAL_BYTES}\n"
        f"read_bytes = {_STDERR_READ_BYTES}\n"
        f"limit_exit = {_STDERR_LIMIT_EXIT}\n"
        f"stop_seconds = {_RUNNER_STOP_SECONDS!r}\n"
        "environment = {\n"
        "    'LANG': 'C.UTF-8',\n"
        "    'LC_ALL': 'C.UTF-8',\n"
        "    'PATH': '/usr/bin:/bin',\n"
        "}\n"
        "environment.update(fixed)\n"
        "wrapper_pid = os.getpid()\n"
        "def die_with_wrapper():\n"
        "    libc = ctypes.CDLL(None, use_errno=True)\n"
        "    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:\n"
        "        os._exit(127)\n"
        "    if os.getppid() != wrapper_pid:\n"
        "        os.kill(os.getpid(), signal.SIGKILL)\n"
        "child = subprocess.Popen(\n"
        "    [runner, *sys.argv[1:]],\n"
        "    env=environment,\n"
        "    stderr=subprocess.PIPE,\n"
        "    bufsize=0,\n"
        "    close_fds=True,\n"
        "    preexec_fn=die_with_wrapper,\n"
        ")\n"
        "shutdown_deadline = None\n"
        "def forward_signal(signum, _frame):\n"
        "    global shutdown_deadline\n"
        "    try:\n"
        "        child.send_signal(signum)\n"
        "    except ProcessLookupError:\n"
        "        pass\n"
        "    if shutdown_deadline is None:\n"
        "        shutdown_deadline = time.monotonic() + stop_seconds\n"
        "signal.signal(signal.SIGINT, forward_signal)\n"
        "signal.signal(signal.SIGTERM, forward_signal)\n"
        "def enforce_signal_deadline():\n"
        "    global shutdown_deadline\n"
        "    if shutdown_deadline is None or time.monotonic() < shutdown_deadline:\n"
        "        return\n"
        "    shutdown_deadline = None\n"
        "    if child.poll() is None:\n"
        "        try:\n"
        "            child.kill()\n"
        "        except ProcessLookupError:\n"
        "            pass\n"
        "def stop_child():\n"
        "    if child.poll() is not None:\n"
        "        return\n"
        "    child.terminate()\n"
        "    try:\n"
        "        child.wait(timeout=stop_seconds)\n"
        "    except subprocess.TimeoutExpired:\n"
        "        child.kill()\n"
        "        child.wait(timeout=stop_seconds)\n"
        "def fail_stderr(reason):\n"
        "    message = ('firecracker-codex: runner stderr ' + reason + '\\n').encode('ascii')\n"
        "    try:\n"
        "        sys.stderr.buffer.write(message)\n"
        "        sys.stderr.buffer.flush()\n"
        "    finally:\n"
        "        if child.stderr is not None:\n"
        "            child.stderr.close()\n"
        "        stop_child()\n"
        "    raise SystemExit(limit_exit)\n"
        "assert child.stderr is not None\n"
        "stderr_fd = child.stderr.fileno()\n"
        "pending = bytearray()\n"
        "total = 0\n"
        "while True:\n"
        "    enforce_signal_deadline()\n"
        "    timeout = 0.1\n"
        "    if shutdown_deadline is not None:\n"
        "        timeout = max(0.0, min(timeout, shutdown_deadline - time.monotonic()))\n"
        "    ready, _, _ = select.select([stderr_fd], [], [], timeout)\n"
        "    enforce_signal_deadline()\n"
        "    if not ready:\n"
        "        if child.poll() is None:\n"
        "            continue\n"
        "        ready, _, _ = select.select([stderr_fd], [], [], 0)\n"
        "        if not ready:\n"
        "            break\n"
        "    chunk = os.read(stderr_fd, read_bytes)\n"
        "    if not chunk:\n"
        "        break\n"
        "    if len(chunk) > max_total - total:\n"
        f"        fail_stderr('exceeded the {_STDERR_MAX_TOTAL_BYTES}-byte total limit')\n"
        "    total += len(chunk)\n"
        "    start = 0\n"
        "    forwarding = bytearray()\n"
        "    while start < len(chunk):\n"
        "        newline = chunk.find(b'\\n', start)\n"
        "        end = len(chunk) if newline < 0 else newline\n"
        "        fragment = chunk[start:end]\n"
        "        if len(fragment) > max_line - len(pending):\n"
        f"            fail_stderr('line exceeded the {_STDERR_MAX_LINE_BYTES}-byte limit')\n"
        "        pending.extend(fragment)\n"
        "        if newline < 0:\n"
        "            break\n"
        "        forwarding.extend(pending)\n"
        "        forwarding.append(10)\n"
        "        pending.clear()\n"
        "        start = newline + 1\n"
        "    if forwarding:\n"
        "        sys.stderr.buffer.write(forwarding)\n"
        "        sys.stderr.buffer.flush()\n"
        "if pending:\n"
        "    sys.stderr.buffer.write(pending)\n"
        "    sys.stderr.buffer.flush()\n"
        "child.stderr.close()\n"
        "while child.poll() is None:\n"
        "    enforce_signal_deadline()\n"
        "    delay = 0.1\n"
        "    if shutdown_deadline is not None:\n"
        "        delay = max(0.0, min(delay, shutdown_deadline - time.monotonic()))\n"
        "    time.sleep(delay)\n"
        "returncode = child.returncode\n"
        "assert returncode is not None\n"
        "raise SystemExit(returncode if returncode >= 0 else 128 - returncode)\n"
    )


def _regular_file(
    value: str | os.PathLike[str], label: str, *, executable: bool = False
) -> Path:
    path = _absolute(value, label)
    original = Path(os.fspath(value))
    if original.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
        raise ValueError(f"{label} must be a nonempty regular file: {path}")
    if executable and not os.access(path, os.X_OK):
        raise PermissionError(f"{label} is not executable: {path}")
    return path


def _directory(value: str | os.PathLike[str], label: str) -> Path:
    path = _absolute(value, label)
    original = Path(os.fspath(value))
    if original.is_symlink() or not path.is_dir():
        raise NotADirectoryError(f"{label} must be a real directory: {path}")
    return path


def _private_socket(value: str | os.PathLike[str], label: str) -> Path:
    path = _absolute(value, label)
    original = Path(os.fspath(value))
    info = original.lstat()
    parent = original.parent
    parent_info = parent.lstat()
    if (
        original.is_symlink()
        or path != original
        or not stat.S_ISSOCK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.geteuid()
    ):
        raise ValueError(
            f"{label} must be a direct current-user Unix socket with mode 0600"
        )
    if (
        parent.is_symlink()
        or parent.resolve(strict=True) != parent
        or not stat.S_ISDIR(parent_info.st_mode)
        or stat.S_IMODE(parent_info.st_mode) != 0o700
        or parent_info.st_uid != os.geteuid()
    ):
        raise ValueError(
            f"{label} parent must be a direct current-user directory with mode 0700"
        )
    return path


def _absolute(value: str | os.PathLike[str], label: str) -> Path:
    raw = os.fspath(value)
    if not raw or not os.path.isabs(raw):
        raise ValueError(f"{label} must be an absolute path")
    if any(character in _CONTROL_CHARACTERS for character in raw):
        raise ValueError(f"{label} contains a control character")
    try:
        return Path(raw).resolve(strict=True)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"{label} does not exist: {raw}") from error


def _sha256(value: str, label: str) -> str:
    normalized = value.lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{label} must be one SHA-256 hex digest")
    return normalized


def _require_empty(path: Path, label: str) -> None:
    with os.scandir(path) as entries:
        if next(entries, None) is not None:
            raise ValueError(f"{label} must be empty: {path}")


def _require_disjoint(
    first: Path,
    second: Path,
    first_label: str,
    second_label: str,
) -> None:
    if first == second or first in second.parents or second in first.parents:
        raise ValueError(f"{first_label} and {second_label} paths must not overlap")


def _require_pairwise_disjoint(paths: Mapping[str, Path]) -> None:
    items = list(paths.items())
    for index, (first_label, first) in enumerate(items):
        for second_label, second in items[index + 1 :]:
            _require_disjoint(first, second, first_label, second_label)


__all__ = ["FirecrackerCodex", "create_firecracker_codex"]
