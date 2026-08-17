#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
lock_file="$script_dir/assets.lock.json"
cache_root=${CLAUDE_CODE_CACHE_DIR:-"${XDG_CACHE_HOME:-$HOME/.cache}/safe-change-runtime/claude"}

readarray -t locked < <(python3 - "$lock_file" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as stream:
    lock = json.load(stream)["claude_code"]
for key in (
    "version", "platform", "signing_key_url", "signing_key_fingerprint",
    "signing_key_size", "signing_key_sha256", "manifest_url",
    "manifest_size", "manifest_sha256", "manifest_signature_url",
    "manifest_signature_size", "manifest_signature_sha256", "binary_url",
    "binary_size", "binary_sha256", "version_output",
):
    print(lock[key])
PY
)

version=${locked[0]}
platform=${locked[1]}
key_url=${locked[2]}
key_fingerprint=${locked[3]}
key_size=${locked[4]}
key_sha=${locked[5]}
manifest_url=${locked[6]}
manifest_size=${locked[7]}
manifest_sha=${locked[8]}
signature_url=${locked[9]}
signature_size=${locked[10]}
signature_sha=${locked[11]}
binary_url=${locked[12]}
binary_size=${locked[13]}
binary_sha=${locked[14]}
version_output=${locked[15]}

[[ $platform == linux-x64 ]]
[[ $(uname -s) == Linux ]]
[[ $(uname -m) == x86_64 ]]

version_dir="$cache_root/$version"
key="$version_dir/claude-code.asc"
manifest="$version_dir/manifest.json"
signature="$version_dir/manifest.json.sig"
binary="$version_dir/claude"
mkdir -p -m 0700 "$cache_root" "$version_dir"
chmod 0700 "$cache_root" "$version_dir"

locked_file_ok() {
    local path=$1 expected_size=$2 expected_sha=$3
    [[ -f "$path" ]] &&
        [[ ! -L "$path" ]] &&
        [[ $(stat -c %u -- "$path") == "$(id -u)" ]] &&
        [[ $(stat -c %s -- "$path") == "$expected_size" ]] &&
        [[ $(sha256sum -- "$path" | cut -d ' ' -f 1) == "$expected_sha" ]]
}

fetch_locked() {
    local url=$1 destination=$2 expected_size=$3 expected_sha=$4
    local partial="${destination}.partial"
    if locked_file_ok "$destination" "$expected_size" "$expected_sha"; then
        return
    fi
    rm -f -- "$partial"
    curl --fail --location --proto '=https' --tlsv1.2 \
        --connect-timeout 20 --retry 3 --retry-all-errors \
        --output "$partial" "$url"
    locked_file_ok "$partial" "$expected_size" "$expected_sha"
    chmod 0600 "$partial"
    mv -f -- "$partial" "$destination"
}

fetch_locked "$key_url" "$key" "$key_size" "$key_sha"
fetch_locked "$manifest_url" "$manifest" "$manifest_size" "$manifest_sha"
fetch_locked "$signature_url" "$signature" "$signature_size" "$signature_sha"

gpg_home=$(mktemp -d "$version_dir/.gnupg.XXXXXXXX")
cleanup_gpg() {
    case ${gpg_home:-} in
        "$version_dir"/.gnupg.*) rm -rf -- "$gpg_home" ;;
    esac
}
trap cleanup_gpg EXIT
gpg --batch --quiet --homedir "$gpg_home" --import "$key"
observed_fingerprint=$(gpg --batch --homedir "$gpg_home" --with-colons \
    --fingerprint security@anthropic.com | awk -F: '$1 == "fpr" { print $10; exit }')
[[ $observed_fingerprint == "$key_fingerprint" ]]
gpg --batch --homedir "$gpg_home" --verify "$signature" "$manifest"

python3 - "$manifest" "$version" "$platform" "$binary_size" "$binary_sha" <<'PY'
import json
import sys

manifest_path, version, platform, size, checksum = sys.argv[1:]
with open(manifest_path, "r", encoding="utf-8") as stream:
    manifest = json.load(stream)
entry = manifest["platforms"][platform]
if (
    manifest.get("version") != version
    or entry.get("binary") != "claude"
    or entry.get("size") != int(size)
    or entry.get("checksum") != checksum
):
    raise SystemExit("signed Claude manifest differs from the release lock")
PY

fetch_locked "$binary_url" "$binary" "$binary_size" "$binary_sha"
chmod 0400 "$key" "$manifest" "$signature"
chmod 0500 "$binary"
[[ "$($binary --version)" == "$version_output" ]]

cleanup_gpg
gpg_home=
trap - EXIT
printf '%s\n' "CLAUDE_CODE=$binary"
