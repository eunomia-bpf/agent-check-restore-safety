#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
mode="${MODE:-auto_upgrade}"
if [[ "$mode" != auto_upgrade && "$mode" != pinned && "$mode" != manual_branch ]]; then
  echo "MODE must be auto_upgrade, pinned, or manual_branch" >&2
  exit 64
fi

for command in cmp find jq python3 realpath sha256sum tee; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done

if [[ -n "${TEMPORAL_PAIR_ROOT:-}" ]]; then
  pair_root="$(realpath -m "$TEMPORAL_PAIR_ROOT")"
  if [[ -d "$pair_root" && -n "$(find "$pair_root" -mindepth 1 -print -quit)" ]]; then
    echo "TEMPORAL_PAIR_ROOT must be absent or empty" >&2
    exit 64
  fi
  mkdir -p "$pair_root"
else
  pair_root="$(mktemp -d "/tmp/safe-change-temporal-pair-${mode}.XXXXXX")"
fi
chmod 700 "$pair_root"

pair_build_env="$pair_root/build.env"
if [[ "${SKIP_BUILD:-0}" == 1 ]]; then
  source_build_env="${HARNESS_BUILD_ENV:-}"
  if [[ -z "$source_build_env" || ! -f "$source_build_env" ]]; then
    echo "SKIP_BUILD=1 requires HARNESS_BUILD_ENV to name an existing file" >&2
    exit 64
  fi
  cp "$source_build_env" "$pair_build_env"
else
  "$script_dir/build-images.sh" >"$pair_build_env" 2>"$pair_root/build.log"
fi
chmod 600 "$pair_build_env"

for case_name in h0 h1; do
  echo "running Temporal $mode/$case_name" >&2
  CASE="$case_name" MODE="$mode" SKIP_BUILD=1 \
    HARNESS_BUILD_ENV="$pair_build_env" \
    TEMPORAL_STATE_ROOT="$pair_root/$case_name" \
    "$script_dir/run-case.sh" | tee "$pair_root/$case_name.stdout"
done

cmp "$pair_build_env" "$pair_root/h0/results/build.env"
cmp "$pair_build_env" "$pair_root/h1/results/build.env"
python3 "$script_dir/check-pair.py" "$pair_root/h0" "$pair_root/h1" | tee "$pair_root/verdict.json"
(
  cd "$pair_root"
  artifacts=(
    build.env h0.stdout h1.stdout verdict.json
    h0/results/SHA256SUMS h1/results/SHA256SUMS
  )
  if [[ -f build.log ]]; then
    artifacts+=(build.log)
  fi
  sha256sum "${artifacts[@]}" >SHA256SUMS
)
echo "Temporal paired evidence: $pair_root" >&2
