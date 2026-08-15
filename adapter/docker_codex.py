"""Create a ``codex`` executable that crosses a hardened Docker boundary.

The caller owns the lifecycle and contents of ``codex_home``.  This module
only verifies that it names a directory and bind-mounts that directory; it
never discovers, reads, or copies authentication material.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Sequence


_DOCKER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_CONTROL_CHARACTERS = frozenset(chr(value) for value in range(32)) | {chr(127)}
_CLEANUP_TIMEOUT_SECONDS = 5.0
_CONTAINER_CODEX_HOME = Path("/var/lib/safe-change/codex-home")


class DockerCodex:
    """A temporary executable suitable for ``CodexAppServer.codex_binary``.

    ``docker_command`` is the exact fixed argv used by the executable.  Codex
    arguments supplied by ``CodexAppServer`` are appended without shell
    interpretation.  The container name is generated once and reused by this
    executable, so concurrent reuse fails closed instead of starting an
    untracked second container.
    """

    def __init__(
        self,
        *,
        executable: Path,
        container_name: str,
        docker_command: tuple[str, ...],
        temporary: tempfile.TemporaryDirectory[str],
    ) -> None:
        self.executable = executable
        self.container_name = container_name
        self.docker_command = docker_command
        self.cleanup_command = (
            docker_command[0],
            "rm",
            "-f",
            container_name,
        )
        self._temporary: tempfile.TemporaryDirectory[str] | None = temporary
        self._container_cleaned = False

    def command(self, codex_arguments: Sequence[str] = ()) -> tuple[str, ...]:
        """Return the complete auditable argv for one Codex invocation."""

        return self.docker_command + tuple(codex_arguments)

    def close(self) -> None:
        """Remove this exact container, if present, and the host wrapper."""

        cleanup_error: BaseException | None = None
        if not self._container_cleaned:
            try:
                _remove_container(self.cleanup_command)
            except BaseException as error:
                cleanup_error = error
            else:
                self._container_cleaned = True
        temporary, self._temporary = self._temporary, None
        if temporary is not None:
            temporary.cleanup()
        if cleanup_error is not None:
            raise cleanup_error

    def __fspath__(self) -> str:
        return os.fspath(self.executable)

    def __enter__(self) -> DockerCodex:
        return self

    def __exit__(self, *unused: object) -> None:
        self.close()


def create_docker_codex(
    *,
    vendor_bundle: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    codex_home: str | os.PathLike[str],
    network: str,
    runtime_image: str,
    docker_binary: str | os.PathLike[str] = "docker",
    container_name: str | None = None,
    uid: int | None = None,
    gid: int | None = None,
    temp_parent: str | os.PathLike[str] | None = None,
) -> DockerCodex:
    """Create a hardened Docker-backed Codex executable.

    ``vendor_bundle`` is the absolute platform bundle whose native executable
    is ``bin/codex``.  ``workspace`` must be an empty absolute directory and
    is mounted read-only at the identical container path.  ``codex_home`` must
    be an already-prepared absolute directory; it is mounted read-write at a
    fixed private container path and is not inspected.

    Numeric host UID/GID are used by default.  Numeric users do not need an
    ``/etc/passwd`` entry in the runtime image, and using the host IDs avoids
    leaving root-owned state in the caller-managed Codex home.  Callers whose
    image genuinely requires root may explicitly pass ``uid=0, gid=0``.
    """

    workspace_path = _absolute_directory(workspace, "workspace")
    codex_home_path = _absolute_directory(codex_home, "codex_home")
    vendor_path = _absolute_directory(vendor_bundle, "vendor_bundle")
    _require_disjoint(workspace_path, codex_home_path, "workspace", "codex_home")
    _require_disjoint(workspace_path, vendor_path, "workspace", "vendor_bundle")
    _require_disjoint(codex_home_path, vendor_path, "codex_home", "vendor_bundle")

    _require_empty(workspace_path)
    codex_executable = _vendor_executable(vendor_path)
    resolved_docker = _executable(docker_binary, "docker_binary")
    validated_network = _docker_name(network, "network")
    validated_image = _image_reference(runtime_image)
    fixed_container_name = _docker_name(
        container_name or f"safe-change-codex-{secrets.token_hex(8)}",
        "container_name",
    )
    run_uid, run_gid = _user_ids(uid, gid)
    if (run_uid, run_gid) == (os.getuid(), os.getgid()) and not os.access(
        codex_home_path, os.W_OK | os.X_OK
    ):
        raise PermissionError(
            f"codex_home is not writable by host UID/GID: {codex_home_path}"
        )

    workspace_mount = _bind_mount(
        workspace_path, destination=workspace_path, readonly=True
    )
    codex_home_mount = _bind_mount(
        codex_home_path, destination=_CONTAINER_CODEX_HOME, readonly=False
    )
    vendor_mount = _bind_mount(vendor_path, destination=vendor_path, readonly=True)
    docker_command = (
        os.fspath(resolved_docker),
        "run",
        "--rm",
        "-i",
        "--name",
        fixed_container_name,
        "--network",
        validated_network,
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,mode=1777",
        "--user",
        f"{run_uid}:{run_gid}",
        "--workdir",
        os.fspath(workspace_path),
        "--env",
        f"CODEX_HOME={_CONTAINER_CODEX_HOME}",
        "--env",
        "CODEX_MANAGED_BY_NPM=1",
        "--mount",
        workspace_mount,
        "--mount",
        codex_home_mount,
        "--mount",
        vendor_mount,
        "--entrypoint",
        os.fspath(codex_executable),
        validated_image,
    )

    parent = None
    if temp_parent is not None:
        parent = _absolute_directory(temp_parent, "temp_parent")
    temporary = tempfile.TemporaryDirectory(prefix="docker-codex-", dir=parent)
    try:
        temporary_path = Path(temporary.name).resolve(strict=True)
        _require_disjoint(temporary_path, workspace_path, "wrapper", "workspace")
        _require_disjoint(temporary_path, codex_home_path, "wrapper", "codex_home")
        _require_disjoint(temporary_path, vendor_path, "wrapper", "vendor_bundle")
        executable = temporary_path / "codex"
        executable.write_text(
            _wrapper_source(docker_command, workspace_path), encoding="utf-8"
        )
        executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    except BaseException:
        temporary.cleanup()
        raise

    return DockerCodex(
        executable=executable,
        container_name=fixed_container_name,
        docker_command=docker_command,
        temporary=temporary,
    )


def _absolute_directory(value: str | os.PathLike[str], label: str) -> Path:
    raw = os.fspath(value)
    if not raw or not os.path.isabs(raw):
        raise ValueError(f"{label} must be an absolute path")
    if any(character in _CONTROL_CHARACTERS for character in raw):
        raise ValueError(f"{label} contains a control character")
    try:
        path = Path(raw).resolve(strict=True)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"{label} does not exist: {raw}") from error
    if not path.is_dir():
        raise NotADirectoryError(f"{label} is not a directory: {path}")
    if "," in os.fspath(path):
        raise ValueError(f"{label} cannot contain ',' in a Docker mount path")
    return path


def _require_empty(path: Path) -> None:
    with os.scandir(path) as entries:
        if next(entries, None) is not None:
            raise ValueError(f"workspace must be empty: {path}")


def _require_disjoint(
    first: Path,
    second: Path,
    first_label: str,
    second_label: str,
) -> None:
    if first == second or first in second.parents or second in first.parents:
        raise ValueError(f"{first_label} and {second_label} paths must not overlap")


def _vendor_executable(vendor_bundle: Path) -> Path:
    candidate = vendor_bundle / "bin" / "codex"
    try:
        executable = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"vendor_bundle has no bin/codex executable: {vendor_bundle}"
        ) from error
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise PermissionError(f"vendor Codex is not executable: {executable}")
    if executable != vendor_bundle and vendor_bundle not in executable.parents:
        raise ValueError("vendor bin/codex resolves outside vendor_bundle")
    return executable


def _executable(value: str | os.PathLike[str], label: str) -> Path:
    raw = os.fspath(value)
    if not raw or any(character in _CONTROL_CHARACTERS for character in raw):
        raise ValueError(f"{label} must name one executable")
    if os.path.isabs(raw):
        try:
            resolved = Path(raw).resolve(strict=True)
        except FileNotFoundError as error:
            raise FileNotFoundError(f"{label} does not exist: {raw}") from error
    else:
        if os.sep in raw or (os.altsep is not None and os.altsep in raw):
            raise ValueError(f"{label} must be a command name or absolute path")
        found = shutil.which(raw)
        if found is None:
            raise FileNotFoundError(f"{label} was not found: {raw}")
        resolved = Path(found).resolve(strict=True)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise PermissionError(f"{label} is not executable: {resolved}")
    return resolved


def _docker_name(value: str, label: str) -> str:
    if not isinstance(value, str) or _DOCKER_NAME.fullmatch(value) is None:
        raise ValueError(f"invalid Docker {label}: {value!r}")
    return value


def _image_reference(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or value.startswith("-")
        or any(
            character.isspace() or character in _CONTROL_CHARACTERS
            for character in value
        )
    ):
        raise ValueError(f"invalid Docker runtime_image: {value!r}")
    return value


def _user_ids(uid: int | None, gid: int | None) -> tuple[int, int]:
    if (uid is None) != (gid is None):
        raise ValueError("uid and gid must be supplied together")
    if uid is None:
        return os.getuid(), os.getgid()
    if (
        isinstance(uid, bool)
        or isinstance(gid, bool)
        or not isinstance(uid, int)
        or not isinstance(gid, int)
        or uid < 0
        or gid < 0
        or uid >= 2**32 - 1
        or gid >= 2**32 - 1
    ):
        raise ValueError("uid and gid must be valid non-negative numeric IDs")
    return uid, gid


def _bind_mount(path: Path, *, destination: Path, readonly: bool) -> str:
    mount = f"type=bind,src={path},dst={destination}"
    return f"{mount},readonly" if readonly else mount


def _remove_container(command: tuple[str, ...]) -> None:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_CLEANUP_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(
            f"failed to remove Docker container: {command[-1]}"
        ) from error
    if completed.returncode == 0:
        return
    diagnostic = "\n".join((completed.stdout or "", completed.stderr or "")).lower()
    if "no such container" in diagnostic or "not found" in diagnostic:
        return
    raise RuntimeError(
        f"Docker could not remove container {command[-1]!r} "
        f"(exit {completed.returncode})"
    )


def _wrapper_source(command: tuple[str, ...], workspace: Path) -> str:
    python = Path(sys.executable).resolve(strict=True)
    if any(character in _CONTROL_CHARACTERS for character in os.fspath(python)):
        raise ValueError("Python executable path contains a control character")
    return (
        f"#!{python}\n"
        "import os\n"
        "import sys\n\n"
        f"_COMMAND = {command!r}\n"
        f"_WORKSPACE = {os.fspath(workspace)!r}\n\n"
        "try:\n"
        "    with os.scandir(_WORKSPACE) as entries:\n"
        "        if next(entries, None) is not None:\n"
        "            raise RuntimeError(\n"
        "                f'workspace is no longer empty: {_WORKSPACE}'\n"
        "            )\n"
        "except (OSError, RuntimeError) as error:\n"
        "    sys.stderr.write(f'docker-codex: {error}\\n')\n"
        "    raise SystemExit(2) from error\n"
        "os.execv(_COMMAND[0], [*_COMMAND, *sys.argv[1:]])\n"
    )


__all__ = ["DockerCodex", "create_docker_codex"]
