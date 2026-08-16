#!/usr/bin/env bash
set -Eeuo pipefail

export LC_ALL=C

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/../../.." && pwd -P)"
base_app="$repo_root/runtime/deploy/temporal/app"
versions_file="$repo_root/runtime/deploy/temporal/versions.env"
dockerfile="$script_dir/Dockerfile.worker"
expected_base_source_sha256="877a7a5b71b24e3dc309af5cd23bebe77c40dab6b8aec659ef929f1dc771aade"
logical_app_path="runtime/deploy/temporal/app"

output_env="${1:-}"
if [[ -z "$output_env" || $# -ne 1 ]]; then
  echo "usage: $0 OUTPUT_ENV" >&2
  exit 64
fi
output_env="$(realpath -m -- "$output_env")"
output_parent="$(dirname -- "$output_env")"
output_name="$(basename -- "$output_env")"
if [[ "$output_name" == *.* ]]; then
  evidence_name="${output_name%.*}-evidence"
else
  evidence_name="${output_name}-evidence"
fi
evidence_dir="$output_parent/$evidence_name"
if [[ -e "$output_env" || -e "$evidence_dir" ]]; then
  echo "refusing to overwrite existing unsafe target evidence: $output_env or $evidence_dir" >&2
  exit 64
fi
mkdir -p -- "$output_parent"

source_only="${TEMPORAL_UNSAFE_SOURCE_ONLY:-0}"
if [[ "$source_only" != 0 && "$source_only" != 1 ]]; then
  echo "TEMPORAL_UNSAFE_SOURCE_ONLY must be 0 or 1" >&2
  exit 64
fi

for command in awk chmod cmp cp find git go gofmt grep mkdir mktemp mv realpath sed sha256sum sort; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done
if [[ "$source_only" == 0 ]]; then
  for command in docker strings; do
    command -v "$command" >/dev/null || {
      echo "required command not found: $command" >&2
      exit 1
    }
  done
fi

# shellcheck source=/dev/null
source "$versions_file"
for required in \
  TEMPORAL_GO_IMAGE TEMPORAL_RUNTIME_IMAGE TEMPORAL_SAMPLES_COMMIT \
  TEMPORAL_GO_SDK_VERSION; do
  if [[ -z "${!required:-}" ]]; then
    echo "versions.env is missing $required" >&2
    exit 64
  fi
done
for pinned_image in "$TEMPORAL_GO_IMAGE" "$TEMPORAL_RUNTIME_IMAGE"; do
  if [[ ! "$pinned_image" =~ @sha256:[0-9a-f]{64}$ ]]; then
    echo "base image is not digest-pinned: $pinned_image" >&2
    exit 64
  fi
done

patches=(
  "$script_dir/patches/0001-add-charge-payment-v2.patch"
  "$script_dir/patches/0002-add-unsafe-worker-v2.patch"
  "$script_dir/patches/0003-test-unsafe-worker-v2.patch"
)
unexpected_patch="$(find "$script_dir/patches" -mindepth 1 -maxdepth 1 -type f \
  ! -name '0001-add-charge-payment-v2.patch' \
  ! -name '0002-add-unsafe-worker-v2.patch' \
  ! -name '0003-test-unsafe-worker-v2.patch' -print -quit)"
if [[ -n "$unexpected_patch" ]]; then
  echo "unexpected unsafe target patch: $unexpected_patch" >&2
  exit 64
fi
for patch in "${patches[@]}"; do
  if [[ ! -f "$patch" || -L "$patch" ]]; then
    echo "unsafe target patch is missing or not a regular file: $patch" >&2
    exit 64
  fi
done

reject_special_files() {
  local directory="$1" unexpected
  unexpected="$(find "$directory" -mindepth 1 ! -type d ! -type f -print -quit)"
  if [[ -n "$unexpected" ]]; then
    echo "source tree contains a symlink or special file: $unexpected" >&2
    exit 64
  fi
}

source_hash() {
  local directory="$1" logical_root="$2"
  {
    while IFS= read -r -d '' input; do
      local relative="${input#"$directory/"}"
      if [[ "$relative" == *$'\n'* ]]; then
        echo "source path contains a newline: $relative" >&2
        return 64
      fi
      printf '%s\0' "$logical_root/$relative"
      sha256sum -- "$input" | awk '{print $1}'
    done < <(find "$directory" -type f -print0 | sort -z)
  } | sha256sum | awk '{print $1}'
}

write_tree_manifest() {
  local directory="$1" destination="$2"
  : >"$destination"
  while IFS= read -r -d '' input; do
    local relative="${input#"$directory/"}"
    if [[ "$relative" == *$'\n'* ]]; then
      echo "source path contains a newline: $relative" >&2
      return 64
    fi
    printf '%s  %s\n' "$(sha256sum -- "$input" | awk '{print $1}')" "$relative" >>"$destination"
  done < <(find "$directory" -type f -print0 | sort -z)
}

require_exact_line() {
  local file="$1" line="$2"
  if [[ "$(grep -Fxc -- "$line" "$file")" != 1 ]]; then
    echo "generated source does not contain exactly one expected line: $file: $line" >&2
    exit 64
  fi
}

work_dir="$(mktemp -d /tmp/safe-change-temporal-unsafe-build.XXXXXX)"
stage_evidence="$(mktemp -d "$output_parent/.safe-change-temporal-unsafe-evidence.XXXXXX")"
stage_env="$(mktemp "$output_parent/.safe-change-temporal-unsafe-env.XXXXXX")"
container_id=""
cleanup() {
  if [[ -n "$container_id" ]]; then
    docker container rm --force "$container_id" >/dev/null 2>&1 || true
  fi
  case "$work_dir" in
    /tmp/safe-change-temporal-unsafe-build.*) find "$work_dir" -depth -delete 2>/dev/null || true ;;
    *) echo "refusing to clean unexpected build directory: $work_dir" >&2 ;;
  esac
  if [[ -e "$stage_evidence" ]]; then
    case "$stage_evidence" in
      "$output_parent"/.safe-change-temporal-unsafe-evidence.*)
        find "$stage_evidence" -depth -delete 2>/dev/null || true
        ;;
      *) echo "refusing to clean unexpected evidence staging directory: $stage_evidence" >&2 ;;
    esac
  fi
  if [[ -e "$stage_env" ]]; then
    case "$stage_env" in
      "$output_parent"/.safe-change-temporal-unsafe-env.*) find "$stage_env" -delete 2>/dev/null || true ;;
      *) echo "refusing to clean unexpected env staging file: $stage_env" >&2 ;;
    esac
  fi
}
trap cleanup EXIT

reject_special_files "$base_app"
base_source_sha256="$(source_hash "$base_app" "$logical_app_path")"
if [[ "$base_source_sha256" != "$expected_base_source_sha256" ]]; then
  echo "frozen Temporal base source digest is $base_source_sha256, expected $expected_base_source_sha256" >&2
  exit 64
fi

patch_manifest="$work_dir/patches.manifest"
: >"$patch_manifest"
patch_sha256=()
for patch in "${patches[@]}"; do
  digest="$(sha256sum -- "$patch" | awk '{print $1}')"
  patch_sha256+=("$digest")
  printf '%s  %s\n' "$digest" "$(basename -- "$patch")" >>"$patch_manifest"
done
patch_set_sha256="$(sha256sum -- "$patch_manifest" | awk '{print $1}')"
dockerfile_sha256="$(sha256sum -- "$dockerfile" | awk '{print $1}')"
versions_sha256="$(sha256sum -- "$versions_file" | awk '{print $1}')"

generated_app="$work_dir/generated-app"
mkdir -p -- "$generated_app"
cp -a -- "$base_app/." "$generated_app/"
if [[ "$(source_hash "$generated_app" "$logical_app_path")" != "$base_source_sha256" ]]; then
  echo "temporary base copy differs from the frozen live source" >&2
  exit 1
fi
for patch in "${patches[@]}"; do
  (
    cd -- "$generated_app"
    git apply --check --whitespace=error-all "$patch"
    git apply --whitespace=error-all "$patch"
  )
done
reject_special_files "$generated_app"

unsafe_variant="$generated_app/internal/workerapp/variant_unsafe_v2.go"
unsafe_test="$generated_app/internal/workerapp/variant_unsafe_v2_test.go"
require_exact_line "$unsafe_variant" '//go:build worker_unsafe_v2'
require_exact_line "$unsafe_variant" 'const buildID = "food-order-unsafe-v2"'
require_exact_line "$unsafe_variant" $'\tunsafePaymentCapacityChangeID = "unsafe-payment-capacity-v1"'
require_exact_line "$unsafe_variant" $'\tunsafePaymentCapacityVersion  = workflow.Version(1)'
require_exact_line "$unsafe_variant" $'\tw.RegisterActivityWithOptions(activities.ChargePayment, activityOptions(harness.PaymentActivityName))'
require_exact_line "$unsafe_variant" $'\tw.RegisterActivityWithOptions(activities.ChargePaymentV2, activityOptions(harness.PaymentV2ActivityName))'
require_exact_line "$unsafe_variant" $'\tw.RegisterActivityWithOptions(activities.PrepareFood, activityOptions(harness.PreparationActivityName))'
require_exact_line "$unsafe_variant" $'\tw.RegisterActivityWithOptions(activities.ScheduleDelivery, activityOptions(harness.DeliveryActivityName))'
require_exact_line "$unsafe_variant" $'\tw.RegisterActivityWithOptions(activities.CompleteOrder, activityOptions(harness.CompletionActivityName))'
require_exact_line "$unsafe_variant" $'\tversion := workflow.GetVersion('
require_exact_line "$unsafe_variant" $'\t\tpaymentActivity = harness.PaymentV2ActivityName'
require_exact_line "$unsafe_variant" $'\tif err := finishFoodOrder(ctx, order, status, "unsafe-v2"); err != nil {'
require_exact_line "$generated_app/internal/workerapp/activities.go" $'\tpaymentV2EffectPath = "/v2/charge"'
require_exact_line "$generated_app/internal/workerapp/activities.go" 'func (a *Activities) ChargePaymentV2(ctx context.Context, request harness.EffectRequest) (harness.EffectReceipt, error) {'
require_exact_line "$generated_app/internal/harness/types.go" $'\tPaymentV2ActivityName         = "ChargePaymentV2"'
require_exact_line "$unsafe_test" 'func TestChargePaymentV2UsesV2Endpoint(t *testing.T) {'
if ! cmp -s -- \
  "$base_app/internal/workerapp/variant_v1.go" \
  "$generated_app/internal/workerapp/variant_v1.go"; then
  echo "unsafe target generation changed the frozen v1 variant" >&2
  exit 1
fi
if ! cmp -s -- "$base_app/go.mod" "$generated_app/go.mod" || \
   ! cmp -s -- "$base_app/go.sum" "$generated_app/go.sum"; then
  echo "unsafe target generation changed the frozen Go dependency lock" >&2
  exit 1
fi
generated_source_sha256="$(source_hash "$generated_app" "$logical_app_path")"

mapfile -d '' go_sources < <(find "$generated_app" -name '*.go' -type f -print0 | sort -z)
gofmt_diff="$work_dir/gofmt.diff"
if ! gofmt -d "${go_sources[@]}" >"$gofmt_diff"; then
  echo "gofmt failed for generated unsafe target" >&2
  exit 1
fi
if [[ -s "$gofmt_diff" ]]; then
  echo "generated unsafe target is not gofmt-clean" >&2
  sed -n '1,200p' "$gofmt_diff" >&2
  exit 64
fi

selected_files="$(
  cd -- "$generated_app"
  go list -tags worker_unsafe_v2 -f '{{range .GoFiles}}{{println .}}{{end}}' ./internal/workerapp | sort
)"
if [[ "$(grep -Fxc 'variant_unsafe_v2.go' <<<"$selected_files")" != 1 ]]; then
  echo "worker_unsafe_v2 does not select exactly one unsafe variant" >&2
  exit 64
fi
for forbidden in variant_missing.go variant_v1.go variant_v2.go variant_compatible_v2.go; do
  if grep -Fxq "$forbidden" <<<"$selected_files"; then
    echo "worker_unsafe_v2 also selects $forbidden" >&2
    exit 64
  fi
done
(
  cd -- "$generated_app"
  go test -count=1 -tags worker_unsafe_v2 ./...
  go test -count=1 -tags worker_v1 ./...
)
if [[ "$(source_hash "$generated_app" "$logical_app_path")" != "$generated_source_sha256" ]]; then
  echo "generated source changed while static verification ran" >&2
  exit 1
fi
generated_manifest="$work_dir/generated-tree.manifest"
write_tree_manifest "$generated_app" "$generated_manifest"
generated_tree_manifest_sha256="$(sha256sum -- "$generated_manifest" | awk '{print $1}')"
unsafe_variant_sha256="$(sha256sum -- "$unsafe_variant" | awk '{print $1}')"

mkdir -p -- "$stage_evidence/patches" "$stage_evidence/generated-app"
cp -- "$patch_manifest" "$stage_evidence/patches.manifest"
for patch in "${patches[@]}"; do
  cp -- "$patch" "$stage_evidence/patches/"
done
cp -- "$generated_manifest" "$stage_evidence/generated-tree.manifest"
cp -- "$dockerfile" "$stage_evidence/Dockerfile.worker"
cp -- "$versions_file" "$stage_evidence/versions.env"
cp -a -- "$generated_app/." "$stage_evidence/generated-app/"

git_revision="$(git -C "$repo_root" rev-parse --verify HEAD)"
if [[ ! "$git_revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo "could not resolve a full git revision" >&2
  exit 1
fi

build_mode="source-only"
unsafe_worker_image=""
unsafe_worker_id=""
unsafe_worker_binary_sha256=""
unsafe_worker_nm_sha256=""
unsafe_worker_go_version_sha256=""
if [[ "$source_only" == 0 ]]; then
  build_mode="image"
  image_repository="${TEMPORAL_UNSAFE_IMAGE_REPOSITORY:-safe-change-temporal-worker-unsafe-v2}"
  if [[ ! "$image_repository" =~ ^[a-z0-9]+([._/-][a-z0-9]+)*$ ]]; then
    echo "TEMPORAL_UNSAFE_IMAGE_REPOSITORY must be a lowercase local repository without a tag" >&2
    exit 64
  fi
  image_version="${TEMPORAL_UNSAFE_IMAGE_VERSION:-g${git_revision:0:12}-b${base_source_sha256:0:12}-s${generated_source_sha256:0:12}-p${patch_set_sha256:0:12}}"
  if [[ "$image_version" == latest || ! "$image_version" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$ ]]; then
    echo "TEMPORAL_UNSAFE_IMAGE_VERSION must be an explicit Docker tag other than latest" >&2
    exit 64
  fi
  unsafe_worker_image="$image_repository:$image_version"

  docker build --provenance=false --file "$dockerfile" \
    --build-arg "GO_IMAGE=$TEMPORAL_GO_IMAGE" \
    --build-arg "RUNTIME_IMAGE=$TEMPORAL_RUNTIME_IMAGE" \
    --build-arg "GIT_REVISION=$git_revision" \
    --build-arg "TEMPORAL_SAMPLES_COMMIT=$TEMPORAL_SAMPLES_COMMIT" \
    --build-arg "TEMPORAL_GO_SDK_VERSION=$TEMPORAL_GO_SDK_VERSION" \
    --build-arg "FROZEN_BASE_SOURCE_SHA256=$base_source_sha256" \
    --build-arg "GENERATED_SOURCE_SHA256=$generated_source_sha256" \
    --build-arg "GENERATED_TREE_MANIFEST_SHA256=$generated_tree_manifest_sha256" \
    --build-arg "PATCH_SET_SHA256=$patch_set_sha256" \
    --build-arg "PATCH_0001_SHA256=${patch_sha256[0]}" \
    --build-arg "PATCH_0002_SHA256=${patch_sha256[1]}" \
    --build-arg "PATCH_0003_SHA256=${patch_sha256[2]}" \
    --build-arg "DOCKERFILE_SHA256=$dockerfile_sha256" \
    --tag "$unsafe_worker_image" "$generated_app"

  verify_label() {
    local label="$1" expected="$2" actual
    actual="$(docker image inspect --format "{{ index .Config.Labels \"$label\" }}" "$unsafe_worker_image")"
    if [[ "$actual" != "$expected" ]]; then
      echo "unsafe worker label $label is $actual, expected $expected" >&2
      exit 1
    fi
  }
  verify_label org.opencontainers.image.revision "$git_revision"
  verify_label org.opencontainers.image.base.name "$TEMPORAL_RUNTIME_IMAGE"
  verify_label io.safe-change.source.sha256 "$generated_source_sha256"
  verify_label io.safe-change.build.target worker_unsafe_v2
  verify_label io.safe-change.worker.build-id food-order-unsafe-v2
  verify_label io.safe-change.builder.base "$TEMPORAL_GO_IMAGE"
  verify_label io.safe-change.temporal.samples.revision "$TEMPORAL_SAMPLES_COMMIT"
  verify_label io.safe-change.temporal.go-sdk.version "$TEMPORAL_GO_SDK_VERSION"
  verify_label io.safe-change.temporal.frozen-base-source.sha256 "$base_source_sha256"
  verify_label io.safe-change.temporal.generated-tree-manifest.sha256 "$generated_tree_manifest_sha256"
  verify_label io.safe-change.temporal.patch-set.sha256 "$patch_set_sha256"
  verify_label io.safe-change.temporal.patch-0001.sha256 "${patch_sha256[0]}"
  verify_label io.safe-change.temporal.patch-0002.sha256 "${patch_sha256[1]}"
  verify_label io.safe-change.temporal.patch-0003.sha256 "${patch_sha256[2]}"
  verify_label io.safe-change.temporal.dockerfile.sha256 "$dockerfile_sha256"

  unsafe_worker_id="$(docker image inspect --format '{{.Id}}' "$unsafe_worker_image")"
  if [[ ! "$unsafe_worker_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "Docker returned an invalid unsafe worker image ID: $unsafe_worker_id" >&2
    exit 1
  fi
  if [[ "$(docker image inspect --format '{{json .Config.Entrypoint}}' "$unsafe_worker_image")" != '["/usr/local/bin/worker"]' ]]; then
    echo "unsafe worker image has an unexpected entrypoint" >&2
    exit 1
  fi
  docker image inspect "$unsafe_worker_image" >"$stage_evidence/image-inspect.json"

  extracted_worker="$work_dir/worker-unsafe-v2"
  container_id="$(docker container create "$unsafe_worker_id")"
  docker container cp "$container_id:/usr/local/bin/worker" "$extracted_worker"
  docker container rm "$container_id" >/dev/null
  container_id=""
  if [[ ! -x "$extracted_worker" ]]; then
    echo "unsafe worker image does not contain an executable worker" >&2
    exit 1
  fi
  unsafe_worker_binary_sha256="$(sha256sum -- "$extracted_worker" | awk '{print $1}')"
  (
    cd -- "$generated_app"
    go tool nm "$extracted_worker"
  ) >"$stage_evidence/worker-unsafe-v2.nm"
  go version -m "$extracted_worker" >"$stage_evidence/worker-unsafe-v2.go-version.txt"
  unsafe_worker_nm_sha256="$(sha256sum -- "$stage_evidence/worker-unsafe-v2.nm" | awk '{print $1}')"
  unsafe_worker_go_version_sha256="$(sha256sum -- "$stage_evidence/worker-unsafe-v2.go-version.txt" | awk '{print $1}')"
  for symbol in \
    '(*Activities).ChargePayment' \
    '(*Activities).ChargePaymentV2' \
    '(*Activities).PrepareFood' \
    '(*Activities).ScheduleDelivery' \
    '(*Activities).CompleteOrder'; do
    if ! grep -Fq -- "$symbol" "$stage_evidence/worker-unsafe-v2.nm"; then
      echo "unsafe worker binary does not contain $symbol" >&2
      exit 1
    fi
  done
  strings "$extracted_worker" >"$work_dir/worker-unsafe-v2.strings"
  for marker in \
    food-order-unsafe-v2 \
    unsafe-payment-capacity-v1 \
    /v1/charge \
    /v2/charge \
    preparation_finished \
    driver_selected \
    driver_at_restaurant \
    delivery_finished \
    unsafe-v2; do
    if ! grep -Fq -- "$marker" "$work_dir/worker-unsafe-v2.strings"; then
      echo "unsafe worker binary does not contain marker $marker" >&2
      exit 1
    fi
  done
fi

# Fail closed if any input changed while tests or the image build ran.
if [[ "$(source_hash "$base_app" "$logical_app_path")" != "$base_source_sha256" || \
      "$(source_hash "$generated_app" "$logical_app_path")" != "$generated_source_sha256" || \
      "$(sha256sum -- "$dockerfile" | awk '{print $1}')" != "$dockerfile_sha256" || \
      "$(sha256sum -- "$versions_file" | awk '{print $1}')" != "$versions_sha256" ]]; then
  echo "unsafe target build input changed while verification ran" >&2
  exit 1
fi
for index in "${!patches[@]}"; do
  if [[ "$(sha256sum -- "${patches[$index]}" | awk '{print $1}')" != "${patch_sha256[$index]}" ]]; then
    echo "unsafe target patch changed while verification ran: ${patches[$index]}" >&2
    exit 1
  fi
done
published_manifest="$work_dir/published-generated-tree.manifest"
write_tree_manifest "$stage_evidence/generated-app" "$published_manifest"
if ! cmp -s -- "$published_manifest" "$generated_manifest"; then
  echo "published generated source differs from the build input" >&2
  exit 1
fi

{
  printf 'BUILD_MODE=%s\n' "$build_mode"
  printf 'GIT_REVISION=%s\n' "$git_revision"
  printf 'FROZEN_BASE_SOURCE_SHA256=%s\n' "$base_source_sha256"
  printf 'GENERATED_SOURCE_SHA256=%s\n' "$generated_source_sha256"
  printf 'GENERATED_TREE_MANIFEST_SHA256=%s\n' "$generated_tree_manifest_sha256"
  printf 'PATCH_SET_SHA256=%s\n' "$patch_set_sha256"
  printf 'PATCH_0001_SHA256=%s\n' "${patch_sha256[0]}"
  printf 'PATCH_0002_SHA256=%s\n' "${patch_sha256[1]}"
  printf 'PATCH_0003_SHA256=%s\n' "${patch_sha256[2]}"
  printf 'DOCKERFILE_SHA256=%s\n' "$dockerfile_sha256"
  printf 'VERSIONS_SHA256=%s\n' "$versions_sha256"
  printf 'UNSAFE_VARIANT_SHA256=%s\n' "$unsafe_variant_sha256"
  printf 'SOURCE_TESTS_PASSED=true\n'
  if [[ "$source_only" == 0 ]]; then
    printf 'UNSAFE_WORKER_IMAGE=%s\n' "$unsafe_worker_image"
    printf 'UNSAFE_WORKER_ID=%s\n' "$unsafe_worker_id"
    printf 'UNSAFE_WORKER_BINARY_SHA256=%s\n' "$unsafe_worker_binary_sha256"
    printf 'UNSAFE_WORKER_NM_SHA256=%s\n' "$unsafe_worker_nm_sha256"
    printf 'UNSAFE_WORKER_GO_VERSION_SHA256=%s\n' "$unsafe_worker_go_version_sha256"
    printf 'PROPOSED_UNSAFE_WORKER_IMAGE=%s\n' "$unsafe_worker_image"
    printf 'PROPOSED_UNSAFE_WORKER_ID=%s\n' "$unsafe_worker_id"
    printf 'NATIVE_UNSAFE_WORKER_IMAGE=%s\n' "$unsafe_worker_image"
    printf 'NATIVE_UNSAFE_WORKER_ID=%s\n' "$unsafe_worker_id"
    printf 'PROPOSED_NATIVE_IMAGE_ID_EQUAL=true\n'
  fi
} >"$stage_env"

chmod -R u=rwX,go= -- "$stage_evidence"
chmod 600 -- "$stage_env"
mv -- "$stage_evidence" "$evidence_dir"
stage_evidence=""
mv -- "$stage_env" "$output_env"
stage_env=""

printf 'unsafe Temporal target build mode: %s\n' "$build_mode"
printf 'frozen base source: %s\n' "$base_source_sha256"
printf 'generated source: %s\n' "$generated_source_sha256"
printf 'generated tree manifest: %s\n' "$generated_tree_manifest_sha256"
printf 'patch set: %s\n' "$patch_set_sha256"
if [[ "$source_only" == 0 ]]; then
  printf 'one proposed/native image ID: %s\n' "$unsafe_worker_id"
fi
