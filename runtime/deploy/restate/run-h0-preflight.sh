#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${H0_STATE_DIR:-}" && -z "${H1_STATE_DIR:-}" ]]; then
  export H1_STATE_DIR="$H0_STATE_DIR"
fi
export PREFLIGHT_CASE=h0
exec "$script_dir/run-h1-preflight.sh" "$@"
