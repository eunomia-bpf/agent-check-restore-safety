#!/usr/bin/env python3
"""Build a deterministic, strict-allowlist anonymous supplement archive."""

from __future__ import annotations

import argparse
import gzip
from hashlib import sha256
import io
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MANIFEST = HERE / "ANONYMOUS_MANIFEST.txt"
ALLOWED_ROOTS = {"artifact", "lean"}
STATIC_FORBIDDEN = (
    b"/home/",
    b"/Users/",
    b"yunwei",
    b"eunomia-bpf",
)


def _manifest_paths() -> list[PurePosixPath]:
    entries: list[PurePosixPath] = []
    seen: set[PurePosixPath] = set()
    for line_number, raw in enumerate(MANIFEST.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path = PurePosixPath(line)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise SystemExit(f"manifest line {line_number}: unsafe path {line!r}")
        if path.parts[0] not in ALLOWED_ROOTS:
            raise SystemExit(f"manifest line {line_number}: disallowed root {line!r}")
        if any(character in line for character in "*?[]"):
            raise SystemExit(f"manifest line {line_number}: globs are forbidden")
        if path in seen:
            raise SystemExit(f"manifest line {line_number}: duplicate {line!r}")
        seen.add(path)
        entries.append(path)
    if not entries:
        raise SystemExit("anonymous manifest is empty")
    return entries


def _git_identity_fragments() -> tuple[bytes, ...]:
    command = [
        "git",
        "log",
        "--all",
        "--format=%H%x00%h%x00%an%x00%ae%x00%cn%x00%ce",
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    fragments: set[bytes] = set()
    for field in result.stdout.replace(b"\n", b"\x00").split(b"\x00"):
        value = field.strip().lower()
        if len(value) >= 7:
            fragments.add(value)
    return tuple(sorted(fragments))


def _stage(entries: list[PurePosixPath], stage: Path) -> None:
    for relative in entries:
        source = ROOT.joinpath(*relative.parts)
        if source.is_symlink() or not source.is_file():
            raise SystemExit(f"manifest entry is not a regular file: {relative}")
        target = stage.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    staged = sorted(
        PurePosixPath(path.relative_to(stage).as_posix())
        for path in stage.rglob("*")
        if path.is_file()
    )
    if staged != sorted(entries):
        raise SystemExit("staging contents differ from the anonymous manifest")


def _scan(entries: list[PurePosixPath], stage: Path) -> None:
    forbidden = STATIC_FORBIDDEN + _git_identity_fragments()
    for relative in entries:
        payload = stage.joinpath(*relative.parts).read_bytes().lower()
        for fragment in forbidden:
            if fragment and fragment in payload:
                raise SystemExit(
                    f"anonymity scan rejected {relative}: forbidden identity fragment"
                )


def _archive(entries: list[PurePosixPath], stage: Path, output: Path) -> str:
    digest = sha256()
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as tar:
                for relative in sorted(entries):
                    payload = stage.joinpath(*relative.parts).read_bytes()
                    info = tarfile.TarInfo(relative.as_posix())
                    info.size = len(payload)
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mode = 0o755 if relative.name == "audit.sh" else 0o644
                    tar.addfile(info, io.BytesIO(payload))
    digest.update(output.read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite {output}; pass --force")
    output.parent.mkdir(parents=True, exist_ok=True)

    entries = _manifest_paths()
    with tempfile.TemporaryDirectory(prefix="history-admission-supplement-") as tmp:
        stage = Path(tmp)
        _stage(entries, stage)
        _scan(entries, stage)
        archive_digest = _archive(entries, stage, output)

    print(f"wrote {output}")
    print(f"files {len(entries)}")
    print(f"sha256 {archive_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
