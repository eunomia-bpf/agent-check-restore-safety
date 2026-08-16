#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -ne 2 ]]; then
  echo "usage: $0 OUTPUT_ROOT BUILD_ENV" >&2
  exit 64
fi
output_root=$1
build_env="$(realpath "$2")"
if [[ ! -f "$build_env" ]]; then
  echo "BUILD_ENV must be an existing regular file" >&2
  exit 64
fi
if [[ -e "$output_root" ]]; then
  if [[ ! -d "$output_root" || -n "$(find "$output_root" -mindepth 1 -print -quit)" ]]; then
    echo "OUTPUT_ROOT must be absent or an empty directory" >&2
    exit 64
  fi
else
  mkdir -p "$output_root"
fi
output_root="$(realpath "$output_root")"
delivery_delay="${COMPATIBLE_DELIVERY_DELAY_MS:-60000}"

sha256sum "$script_dir/run-compatible-full.sh" >"$output_root/wrapper.sha256"
jq -n --arg build_env "$build_env" --argjson delay "$delivery_delay" '{
  schema:1,repetitions:5,methods:["proposed","native"],
  build_env:$build_env,delivery_delay_ms:$delay
}' >"$output_root/matrix.json"

for number in $(seq 1 5); do
  repetition="$(printf '%02d' "$number")"
  order_id="compatible-full-$repetition"
  for method in proposed native; do
    attempt="$output_root/rep-$repetition/$method"
    echo "compatible full rep-$repetition $method"
    env \
      COMPATIBLE_METHOD="$method" \
      COMPATIBLE_STATE_DIR="$attempt" \
      ORDER_ID="$order_id" \
      COMPATIBLE_DELIVERY_DELAY_MS="$delivery_delay" \
      SKIP_BUILD=1 \
      HARNESS_BUILD_ENV="$build_env" \
      "$script_dir/run-compatible-case.sh"
    python3 "$script_dir/check-compatible.py" \
      --method "$method" --evidence "$attempt" \
      >"$attempt/results/check-compatible.json"
    python3 "$script_dir/check-compatible-mutations.py" \
      --method "$method" --evidence "$attempt" \
      >"$attempt/results/check-compatible-mutations.json"
  done
  jq -n \
    --slurpfile proposed "$output_root/rep-$repetition/proposed/results/check-compatible.json" \
    --slurpfile native "$output_root/rep-$repetition/native/results/check-compatible.json" '
      $proposed[0] as $p | $native[0] as $n |
      if ($p.valid == true and $n.valid == true and
          $p.method == "proposed" and $n.method == "native" and
          $p.order_id == $n.order_id and
          $p.delivery_delay_ms == $n.delivery_delay_ms and
          $p.payment_operation_id == $n.payment_operation_id and
          $p.completion_operation_id == $n.completion_operation_id and
          $p.runtime_status == "completed" and $n.runtime_status == "completed" and
          $p.business_status == "DELIVERED" and $n.business_status == "DELIVERED")
      then {
        schema:1,valid:true,repetition:$p.order_id,
        delivery_delay_ms:$p.delivery_delay_ms,
        payment_operation_id:$p.payment_operation_id,
        completion_operation_id:$p.completion_operation_id,
        proposed_digest:$p.evidence_digest,native_digest:$n.evidence_digest
      }
      else error("compatible pair differs") end
    ' >"$output_root/rep-$repetition/pair.json"
done

jq -s '
  if length == 5 and all(.[]; .valid == true)
  then {schema:1,valid:true,repetitions:length,pairs:.}
  else error("compatible matrix is incomplete") end
' "$output_root"/rep-*/pair.json >"$output_root/summary.json"
cat "$output_root/summary.json"
