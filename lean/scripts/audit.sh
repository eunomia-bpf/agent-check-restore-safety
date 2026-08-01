#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
lean_root="$(dirname -- "$script_dir")"
cd "$lean_root"

frozen_constants=(
  checkAC_sound
  guardClosure_iff
  simulation_preserves_ac
  restriction_preserves_wf_ac
  prepare_preserves_wf_ac
  ticket_step_preserves_wf_ac
  step_preserves_wf_ac
  trace_preserves_wf_ac
  effect_coverage
  concrete_trace_authority_safety
)

placeholder_pattern='(^|[^[:alnum:]_])(sorryAx|sorry|admit)([^[:alnum:]_]|$)'
if rg --line-number --glob '*.lean' "$placeholder_pattern" AuthorityContinuity; then
  echo "audit: proof placeholder found in project source" >&2
  exit 1
fi

declaration_pattern='^[[:space:]]*((private|protected|noncomputable|scoped)[[:space:]]+)*(axiom|constant)[[:space:]]'
if rg --line-number --glob '*.lean' "$declaration_pattern" AuthorityContinuity; then
  echo "audit: project axiom/constant declaration found" >&2
  exit 1
fi

for name in "${frozen_constants[@]}"; do
  if ! rg --quiet --glob '*.lean' \
      "^[[:space:]]*(theorem|lemma)[[:space:]]+${name}([^[:alnum:]_]|$)" \
      AuthorityContinuity; then
    echo "audit: frozen theorem is missing: $name" >&2
    exit 1
  fi
done

lake build AuthorityContinuity

mkdir -p results
audit_log="results/axioms.log"
lake env lean AuthorityContinuity/Audit.lean 2>&1 | tee "$audit_log"

for name in "${frozen_constants[@]}"; do
  if ! rg --quiet "${name}' (does not depend on any axioms|depends on axioms:)" \
      "$audit_log"; then
    echo "audit: Audit.lean did not print dependencies for: $name" >&2
    exit 1
  fi
done

if rg --quiet 'sorryAx' "$audit_log"; then
  echo "audit: kernel dependency on a proof placeholder" >&2
  exit 1
fi

mapfile -t reported_axioms < <(
  sed -nE 's/.*depends on axioms: \[([^]]*)\].*/\1/p' "$audit_log" |
    tr ',' '\n' |
    sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' |
    sed '/^$/d' |
    sort -u
)
for dependency in "${reported_axioms[@]}"; do
  case "$dependency" in
    propext|Quot.sound|Classical.choice) ;;
    *)
      echo "audit: non-whitelisted kernel dependency: $dependency" >&2
      exit 1
      ;;
  esac
done

lake env leanchecker --fresh AuthorityContinuity.Main
echo "audit: all frozen theorems present; source and kernel replay checks passed"
