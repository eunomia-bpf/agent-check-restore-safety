#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
lock_file="$script_dir/assets.lock.json"
cache_root=${FIRECRACKER_CACHE_DIR:-"${XDG_CACHE_HOME:-$HOME/.cache}/safe-change-runtime/firecracker"}

readarray -t locked < <(python3 - "$lock_file" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as stream:
    lock = json.load(stream)
fc = lock["firecracker"]
kernel = lock["kernel"]
for value in (
    fc["version"], fc["archive_url"], fc["archive_size"], fc["archive_sha256"],
    fc["binary_path"], fc["binary_size"], fc["binary_sha256"],
    fc["jailer_path"], fc["jailer_size"], fc["jailer_sha256"],
    kernel["version"], kernel["url"], kernel["size"], kernel["sha256"],
):
    print(value)
PY
)

fc_version=${locked[0]}
archive_url=${locked[1]}
archive_size=${locked[2]}
archive_sha=${locked[3]}
binary_relative=${locked[4]}
binary_size=${locked[5]}
binary_sha=${locked[6]}
jailer_relative=${locked[7]}
jailer_size=${locked[8]}
jailer_sha=${locked[9]}
kernel_version=${locked[10]}
kernel_url=${locked[11]}
kernel_size=${locked[12]}
kernel_sha=${locked[13]}

version_dir="$cache_root/v$fc_version"
archive="$version_dir/firecracker-v$fc_version-x86_64.tgz"
kernel_dir="$cache_root/assets-v1.15"
kernel="$kernel_dir/vmlinux-$kernel_version"
mkdir -p -m 0700 "$version_dir" "$kernel_dir"
chmod 0700 "$cache_root" "$version_dir" "$kernel_dir"

fetch_locked() {
    local url=$1 destination=$2 expected_size=$3 expected_sha=$4
    local partial="${destination}.partial"
    if [[ -f "$destination" ]] &&
       [[ $(stat -c %s -- "$destination") == "$expected_size" ]] &&
       [[ $(sha256sum -- "$destination" | cut -d ' ' -f 1) == "$expected_sha" ]]; then
        return
    fi
    rm -f -- "$partial"
    curl --fail --location --proto '=https' --tlsv1.2 \
        --connect-timeout 20 --retry 3 --retry-all-errors \
        --output "$partial" "$url"
    [[ $(stat -c %s -- "$partial") == "$expected_size" ]]
    [[ $(sha256sum -- "$partial" | cut -d ' ' -f 1) == "$expected_sha" ]]
    chmod 0600 "$partial"
    mv -f -- "$partial" "$destination"
}

fetch_locked "$archive_url" "$archive" "$archive_size" "$archive_sha"
binary="$version_dir/$binary_relative"
jailer="$version_dir/$jailer_relative"

locked_file_ok() {
    local path=$1 expected_size=$2 expected_sha=$3
    [[ -f "$path" ]] &&
        [[ ! -L "$path" ]] &&
        [[ $(stat -c %s -- "$path") == "$expected_size" ]] &&
        [[ $(sha256sum -- "$path" | cut -d ' ' -f 1) == "$expected_sha" ]]
}

if ! locked_file_ok "$binary" "$binary_size" "$binary_sha" ||
   ! locked_file_ok "$jailer" "$jailer_size" "$jailer_sha"; then
    extract_root=$(mktemp -d "$version_dir/.extract.XXXXXXXX")
    cleanup_extract() {
        case ${extract_root:-} in
            "$version_dir"/.extract.*) rm -rf -- "$extract_root" ;;
        esac
    }
    trap cleanup_extract EXIT
    python3 - "$archive" "$extract_root" "$binary_relative" "$jailer_relative" <<'PY'
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

archive = Path(sys.argv[1])
root = Path(sys.argv[2])
required_names = sys.argv[3:]

with tarfile.open(archive, "r:gz") as bundle:
    selected = {}
    for member in bundle.getmembers():
        name = PurePosixPath(member.name)
        if name.is_absolute() or not name.parts or ".." in name.parts:
            raise SystemExit(f"unsafe archive member: {member.name!r}")
        if not member.isfile():
            raise SystemExit(f"non-regular archive member: {member.name!r}")
        if member.name in required_names:
            if member.name in selected:
                raise SystemExit(f"duplicate required archive member: {member.name!r}")
            selected[member.name] = member
    missing = set(required_names) - set(selected)
    if missing:
        raise SystemExit(f"missing required archive members: {sorted(missing)!r}")
    for name in required_names:
        member = selected[name]
        source = bundle.extractfile(member)
        if source is None:
            raise SystemExit(f"cannot read required archive member: {name!r}")
        destination = root.joinpath(*PurePosixPath(name).parts)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(destination, flags, 0o600)
        with source, os.fdopen(descriptor, "wb") as output:
            shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
PY
    extracted_binary="$extract_root/$binary_relative"
    extracted_jailer="$extract_root/$jailer_relative"
    locked_file_ok "$extracted_binary" "$binary_size" "$binary_sha"
    locked_file_ok "$extracted_jailer" "$jailer_size" "$jailer_sha"
    release_dir="$version_dir/${binary_relative%%/*}"
    [[ ${jailer_relative%%/*} == "${binary_relative%%/*}" ]]
    mkdir -p -m 0700 "$release_dir"
    chmod 0700 "$release_dir"
    mv -f -- "$extracted_binary" "$binary"
    mv -f -- "$extracted_jailer" "$jailer"
    rmdir -- "$extract_root/${binary_relative%%/*}" "$extract_root"
    extract_root=
    trap - EXIT
fi

locked_file_ok "$binary" "$binary_size" "$binary_sha"
locked_file_ok "$jailer" "$jailer_size" "$jailer_sha"
chmod 0500 "$binary"
chmod 0500 "$jailer"

fetch_locked "$kernel_url" "$kernel" "$kernel_size" "$kernel_sha"
chmod 0400 "$kernel"

printf '%s\n' "FIRECRACKER=$binary" "JAILER=$jailer" "FIRECRACKER_KERNEL=$kernel"
