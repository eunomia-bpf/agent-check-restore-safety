#!/usr/bin/env bash
set -Eeuo pipefail

export LC_ALL=C

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/../../.." && pwd -P)"
temporal_dir="$repo_root/runtime/deploy/temporal"
versions_file="$temporal_dir/versions.env"
target_builder="$script_dir/build-target.sh"
adapter_dockerfile="$script_dir/adapter/Dockerfile"
source_adapter_config="$script_dir/configs/source-adapter.json"
target_adapter_config="$script_dir/configs/target-adapter.json"
proposed_compose="$script_dir/compose-proposed.yaml"
native_compose="$script_dir/compose-native.yaml"
frozen_inputs_file="$script_dir/frozen-inputs.env"
control_profile_file="$script_dir/control-profile.env"
control_source_manifest="$script_dir/control-source.manifest"
control_dockerfile="$repo_root/runtime/deploy/restate/Dockerfile.runtime"

expected_frozen_inputs_sha256="b0fe858fb41ed6a982fb2d050a7da321cc6db7b15ee095a9dd4af62e9a90860c"
if [[ ! -f "$frozen_inputs_file" || -L "$frozen_inputs_file" ||
      "$(sha256sum -- "$frozen_inputs_file" | awk '{print $1}')" != "$expected_frozen_inputs_sha256" ]]; then
  echo "frozen unsafe image profile is missing or changed" >&2
  exit 64
fi
# shellcheck source=/dev/null
source "$frozen_inputs_file"
for required in \
  FROZEN_PROFILE_SCHEMA FROZEN_GIT_REVISION \
  FROZEN_TEMPORAL_BUILD_PROFILE_SHA256 FROZEN_CONTROL_BUILD_PROFILE_SHA256 \
  FROZEN_VERSIONS_SHA256 FROZEN_TEMPORAL_SOURCE_SHA256 FROZEN_TEMPORAL_IMAGE \
  FROZEN_WORKER_V1_IMAGE FROZEN_WORKER_V1_ID FROZEN_WORKER_V1_BINARY_SHA256 \
  FROZEN_WORKER_V1_VARIANT_SHA256 FROZEN_WORKER_V2_IMAGE FROZEN_WORKER_V2_ID \
  FROZEN_WORKER_V2_BINARY_SHA256 FROZEN_STARTER_IMAGE FROZEN_STARTER_ID \
  FROZEN_STARTER_BINARY_SHA256 FROZEN_RUNTIME_SOURCE_SHA256 \
  FROZEN_EFFECTS_IMAGE FROZEN_EFFECTS_ID FROZEN_EFFECTS_BINARY_SHA256 \
  FROZEN_CONTROL_IMAGE; do
  if [[ -z "${!required:-}" ]]; then
    echo "frozen-inputs.env is missing $required" >&2
    exit 64
  fi
done
if [[ "$FROZEN_PROFILE_SCHEMA" != 1 || ! "$FROZEN_GIT_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  echo "frozen-inputs.env has an invalid schema or revision" >&2
  exit 64
fi

# Internal aliases keep later verification concise. None follows live HEAD.
frozen_revision="$FROZEN_GIT_REVISION"
frozen_temporal_source_sha256="$FROZEN_TEMPORAL_SOURCE_SHA256"
frozen_temporal_build_profile_sha256="$FROZEN_TEMPORAL_BUILD_PROFILE_SHA256"
frozen_control_build_profile_sha256="$FROZEN_CONTROL_BUILD_PROFILE_SHA256"
frozen_versions_sha256="$FROZEN_VERSIONS_SHA256"
frozen_worker_v1_image="$FROZEN_WORKER_V1_IMAGE"
frozen_worker_v1_id="$FROZEN_WORKER_V1_ID"
frozen_worker_v1_binary_sha256="$FROZEN_WORKER_V1_BINARY_SHA256"
frozen_worker_v1_variant_sha256="$FROZEN_WORKER_V1_VARIANT_SHA256"
frozen_worker_v2_image="$FROZEN_WORKER_V2_IMAGE"
frozen_worker_v2_id="$FROZEN_WORKER_V2_ID"
frozen_worker_v2_binary_sha256="$FROZEN_WORKER_V2_BINARY_SHA256"
frozen_starter_image="$FROZEN_STARTER_IMAGE"
frozen_starter_id="$FROZEN_STARTER_ID"
frozen_starter_binary_sha256="$FROZEN_STARTER_BINARY_SHA256"
frozen_runtime_source_sha256="$FROZEN_RUNTIME_SOURCE_SHA256"
frozen_effects_image="$FROZEN_EFFECTS_IMAGE"
frozen_effects_id="$FROZEN_EFFECTS_ID"
frozen_effects_binary_sha256="$FROZEN_EFFECTS_BINARY_SHA256"
frozen_control_image="$FROZEN_CONTROL_IMAGE"

for input in "$control_profile_file" "$control_source_manifest" "$control_dockerfile"; do
  if [[ ! -f "$input" || -L "$input" ]]; then
    echo "control profile input is missing or unsafe: $input" >&2
    exit 64
  fi
done
if [[ "$(sha256sum -- "$control_profile_file" | awk '{print $1}')" != "$frozen_control_build_profile_sha256" ]]; then
  echo "independent control profile differs from frozen-inputs.env" >&2
  exit 64
fi
# shellcheck source=/dev/null
source "$control_profile_file"
for required in \
  CONTROL_PROFILE_SCHEMA CONTROL_GIT_REVISION CONTROL_IMAGE CONTROL_BINARY_SHA256 \
  CONTROL_SOURCE_MANIFEST_SHA256 CONTROL_DOCKERFILE_SHA256 \
  CONTROL_GO_BUILD_IMAGE CONTROL_RUNTIME_IMAGE; do
  if [[ -z "${!required:-}" ]]; then
    echo "control-profile.env is missing $required" >&2
    exit 64
  fi
done
if [[ "$CONTROL_PROFILE_SCHEMA" != 1 || "$CONTROL_GIT_REVISION" != "$frozen_revision" ||
      "$CONTROL_IMAGE" != "$frozen_control_image" ||
      ! "$CONTROL_BINARY_SHA256" =~ ^[0-9a-f]{64}$ ||
      ! "$CONTROL_GO_BUILD_IMAGE" =~ @sha256:[0-9a-f]{64}$ ||
      ! "$CONTROL_RUNTIME_IMAGE" =~ @sha256:[0-9a-f]{64}$ ]]; then
  echo "independent control profile identity differs" >&2
  exit 64
fi
if [[ "$(sha256sum -- "$control_source_manifest" | awk '{print $1}')" != "$CONTROL_SOURCE_MANIFEST_SHA256" ||
      "$(sha256sum -- "$control_dockerfile" | awk '{print $1}')" != "$CONTROL_DOCKERFILE_SHA256" ]]; then
  echo "independent control source or Dockerfile profile differs" >&2
  exit 64
fi
(
  cd -- "$repo_root"
  sha256sum --check --strict "$control_source_manifest" >/dev/null
)
expected_control_sources="$(awk '{print $2}' "$control_source_manifest" | sort)"
actual_control_sources="$({
  cd -- "$repo_root/runtime"
  go list -deps -f '{{if not .Standard}}{{range .GoFiles}}{{$.Dir}}/{{.}}{{"\n"}}{{end}}{{range .CgoFiles}}{{$.Dir}}/{{.}}{{"\n"}}{{end}}{{range .EmbedFiles}}{{$.Dir}}/{{.}}{{"\n"}}{{end}}{{end}}' \
    ./cmd/control | sed '/^$/d' | sed "s#^$repo_root/##"
  printf '%s\n' runtime/go.mod runtime/go.sum
} | sort -u)"
if [[ "$actual_control_sources" != "$expected_control_sources" ]]; then
  echo "control dependency closure differs from the frozen source manifest" >&2
  exit 64
fi

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
  echo "refusing to overwrite existing unsafe build evidence: $output_env or $evidence_dir" >&2
  exit 64
fi
mkdir -p -- "$output_parent"

for command in awk chmod cp docker find git go grep jq mkdir mktemp mv realpath sed sha256sum sort; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done

if [[ "$(sha256sum -- "$versions_file" | awk '{print $1}')" != "$frozen_versions_sha256" ]]; then
  echo "Temporal versions.env no longer matches the frozen build profile" >&2
  exit 64
fi
# shellcheck source=/dev/null
source "$versions_file"
for required in TEMPORAL_IMAGE TEMPORAL_GO_IMAGE TEMPORAL_RUNTIME_IMAGE; do
  if [[ -z "${!required:-}" ]]; then
    echo "versions.env is missing $required" >&2
    exit 64
  fi
done
for pinned_image in "$TEMPORAL_IMAGE" "$TEMPORAL_GO_IMAGE" "$TEMPORAL_RUNTIME_IMAGE"; do
  if [[ ! "$pinned_image" =~ @sha256:[0-9a-f]{64}$ ]]; then
    echo "frozen image is not digest-pinned: $pinned_image" >&2
    exit 64
  fi
done
if [[ "$TEMPORAL_IMAGE" != "$FROZEN_TEMPORAL_IMAGE" ]]; then
  echo "versions.env Temporal server image differs from frozen-inputs.env" >&2
  exit 64
fi

for input in \
  "$frozen_inputs_file" "$target_builder" "$adapter_dockerfile" \
  "$source_adapter_config" "$target_adapter_config" \
  "$proposed_compose" "$native_compose"; do
  if [[ ! -f "$input" || -L "$input" ]]; then
    echo "unsafe build input is missing or not a regular file: $input" >&2
    exit 64
  fi
done

build_script_sha256="$(sha256sum -- "$script_dir/build-images.sh" | awk '{print $1}')"
target_builder_sha256="$(sha256sum -- "$target_builder" | awk '{print $1}')"
adapter_dockerfile_sha256="$(sha256sum -- "$adapter_dockerfile" | awk '{print $1}')"
source_adapter_config_sha256="$(sha256sum -- "$source_adapter_config" | awk '{print $1}')"
target_adapter_config_sha256="$(sha256sum -- "$target_adapter_config" | awk '{print $1}')"
proposed_compose_sha256="$(sha256sum -- "$proposed_compose" | awk '{print $1}')"
native_compose_sha256="$(sha256sum -- "$native_compose" | awk '{print $1}')"
base_compose_sha256="$(sha256sum -- "$temporal_dir/compose.yaml" | awk '{print $1}')"
frozen_inputs_sha256="$(sha256sum -- "$frozen_inputs_file" | awk '{print $1}')"

work_dir="$(mktemp -d /tmp/safe-change-temporal-unsafe-images.XXXXXX)"
stage_evidence="$(mktemp -d "$output_parent/.safe-change-temporal-unsafe-images-evidence.XXXXXX")"
stage_env="$(mktemp "$output_parent/.safe-change-temporal-unsafe-images-env.XXXXXX")"
container_ids=()
cleanup() {
  if ((${#container_ids[@]})); then
    docker container rm --force "${container_ids[@]}" >/dev/null 2>&1 || true
  fi
  case "$work_dir" in
    /tmp/safe-change-temporal-unsafe-images.*) find "$work_dir" -depth -delete 2>/dev/null || true ;;
    *) echo "refusing to clean unexpected build directory: $work_dir" >&2 ;;
  esac
  if [[ -e "$stage_evidence" ]]; then
    case "$stage_evidence" in
      "$output_parent"/.safe-change-temporal-unsafe-images-evidence.*)
        find "$stage_evidence" -depth -delete 2>/dev/null || true
        ;;
      *) echo "refusing to clean unexpected evidence directory: $stage_evidence" >&2 ;;
    esac
  fi
  if [[ -e "$stage_env" ]]; then
    case "$stage_env" in
      "$output_parent"/.safe-change-temporal-unsafe-images-env.*)
        find "$stage_env" -delete 2>/dev/null || true
        ;;
      *) echo "refusing to clean unexpected environment file: $stage_env" >&2 ;;
    esac
  fi
}
trap cleanup EXIT

verify_image_id() {
  local reference="$1" expected="$2" actual
  actual="$(docker image inspect --format '{{.Id}}' "$reference")"
  if [[ "$actual" != "$expected" ]]; then
    echo "frozen image $reference resolved to $actual, expected $expected" >&2
    exit 1
  fi
}

verify_label() {
  local image="$1" label="$2" expected="$3" actual
  actual="$(docker image inspect --format "{{ index .Config.Labels \"$label\" }}" "$image")"
  if [[ "$actual" != "$expected" ]]; then
    echo "$image label $label is $actual, expected $expected" >&2
    exit 1
  fi
}

extract_binary() {
  local image="$1" source="$2" destination="$3" container_id
  container_id="$(docker container create "$image")"
  container_ids+=("$container_id")
  docker container cp "$container_id:$source" "$destination"
}

verify_binary() {
  local image="$1" source="$2" expected="$3" name="$4" destination actual
  destination="$work_dir/$name"
  extract_binary "$image" "$source" "$destination"
  if [[ ! -x "$destination" ]]; then
    echo "$image does not contain executable $source" >&2
    exit 1
  fi
  actual="$(sha256sum -- "$destination" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "$name binary digest is $actual, expected $expected" >&2
    exit 1
  fi
}

verify_image_id "$frozen_worker_v1_image" "$frozen_worker_v1_id"
verify_image_id "$frozen_worker_v2_image" "$frozen_worker_v2_id"
verify_image_id "$frozen_starter_image" "$frozen_starter_id"
verify_image_id "$frozen_effects_image" "$frozen_effects_id"
verify_image_id "$frozen_control_image" "$frozen_control_image"
temporal_image_id="$(docker image inspect --format '{{.Id}}' "$TEMPORAL_IMAGE")"
if [[ ! "$temporal_image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "Docker returned an invalid Temporal server image ID: $temporal_image_id" >&2
  exit 1
fi

for image in "$frozen_worker_v1_id" "$frozen_worker_v2_id" "$frozen_starter_id"; do
  verify_label "$image" org.opencontainers.image.revision "$frozen_revision"
  verify_label "$image" io.safe-change.source.sha256 "$frozen_temporal_source_sha256"
done
verify_label "$frozen_worker_v1_id" io.safe-change.build.target worker_v1
verify_label "$frozen_worker_v1_id" io.safe-change.worker.build-id food-order-v1
verify_label "$frozen_worker_v2_id" io.safe-change.build.target worker_v2
verify_label "$frozen_worker_v2_id" io.safe-change.worker.build-id food-order-v2
verify_label "$frozen_starter_id" io.safe-change.build.target starter
verify_label "$frozen_effects_id" org.opencontainers.image.revision "$frozen_revision"
verify_label "$frozen_effects_id" io.safe-change.runtime.source.sha256 "$frozen_runtime_source_sha256"
verify_label "$frozen_effects_id" io.safe-change.build.target effects

verify_binary "$frozen_worker_v1_id" /usr/local/bin/worker "$frozen_worker_v1_binary_sha256" worker-v1
verify_binary "$frozen_worker_v2_id" /usr/local/bin/worker "$frozen_worker_v2_binary_sha256" worker-v2
verify_binary "$frozen_starter_id" /usr/local/bin/starter "$frozen_starter_binary_sha256" starter
verify_binary "$frozen_effects_id" /usr/local/bin/payment "$frozen_effects_binary_sha256" effects
extract_binary "$frozen_control_image" /usr/local/bin/control "$work_dir/control"
if [[ ! -x "$work_dir/control" ]]; then
  echo "frozen control image does not contain an executable control binary" >&2
  exit 1
fi
control_binary_sha256="$(sha256sum -- "$work_dir/control" | awk '{print $1}')"
if [[ "$control_binary_sha256" != "$CONTROL_BINARY_SHA256" ]]; then
  echo "control image binary differs from the independent control profile" >&2
  exit 1
fi
(
  cd -- "$repo_root/runtime"
  CGO_ENABLED=0 go build -buildvcs=false -trimpath -ldflags='-s -w' \
    -o "$work_dir/control-rebuilt" ./cmd/control
)
if [[ "$(sha256sum -- "$work_dir/control-rebuilt" | awk '{print $1}')" != "$CONTROL_BINARY_SHA256" ]]; then
  echo "independently rebuilt control binary differs from the frozen image binary" >&2
  exit 1
fi

# The target builder is the only command that builds worker_unsafe_v2. Its env
# intentionally maps both lanes to the one resulting image ID.
target_env="$work_dir/target.env"
"$target_builder" "$target_env"
target_evidence="$work_dir/target-evidence"
if [[ ! -f "$target_env" || ! -d "$target_evidence" ]]; then
  echo "unsafe target builder did not publish complete evidence" >&2
  exit 1
fi

env_value() {
  local file="$1" key="$2" value count
  count="$(grep -c "^${key}=" "$file" || true)"
  if [[ "$count" != 1 ]]; then
    echo "$file must contain exactly one $key assignment" >&2
    exit 1
  fi
  value="$(sed -n "s/^${key}=//p" "$file")"
  if [[ -z "$value" || "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
    echo "$file contains an invalid $key value" >&2
    exit 1
  fi
  printf '%s' "$value"
}

unsafe_worker_image="$(env_value "$target_env" UNSAFE_WORKER_IMAGE)"
unsafe_worker_id="$(env_value "$target_env" UNSAFE_WORKER_ID)"
unsafe_worker_binary_sha256="$(env_value "$target_env" UNSAFE_WORKER_BINARY_SHA256)"
target_frozen_base_source_sha256="$(env_value "$target_env" FROZEN_BASE_SOURCE_SHA256)"
target_generated_source_sha256="$(env_value "$target_env" GENERATED_SOURCE_SHA256)"
target_generated_tree_manifest_sha256="$(env_value "$target_env" GENERATED_TREE_MANIFEST_SHA256)"
target_patch_set_sha256="$(env_value "$target_env" PATCH_SET_SHA256)"
target_patch_0001_sha256="$(env_value "$target_env" PATCH_0001_SHA256)"
target_patch_0002_sha256="$(env_value "$target_env" PATCH_0002_SHA256)"
target_patch_0003_sha256="$(env_value "$target_env" PATCH_0003_SHA256)"
target_dockerfile_sha256="$(env_value "$target_env" DOCKERFILE_SHA256)"
target_unsafe_variant_sha256="$(env_value "$target_env" UNSAFE_VARIANT_SHA256)"
target_worker_nm_sha256="$(env_value "$target_env" UNSAFE_WORKER_NM_SHA256)"
target_worker_go_version_sha256="$(env_value "$target_env" UNSAFE_WORKER_GO_VERSION_SHA256)"
target_build_env_sha256="$(sha256sum -- "$target_env" | awk '{print $1}')"
if [[ "$(env_value "$target_env" BUILD_MODE)" != image ||
      "$(env_value "$target_env" SOURCE_TESTS_PASSED)" != true ||
      "$(env_value "$target_env" PROPOSED_UNSAFE_WORKER_ID)" != "$unsafe_worker_id" ||
      "$(env_value "$target_env" NATIVE_UNSAFE_WORKER_ID)" != "$unsafe_worker_id" ||
      "$(env_value "$target_env" PROPOSED_NATIVE_IMAGE_ID_EQUAL)" != true ]]; then
  echo "unsafe target builder did not bind proposed and native to one image" >&2
  exit 1
fi

# Hash only the non-standard Go files that can affect the adapter binary, plus
# the module lock. This stays stable when unrelated experiment harnesses change.
mapfile -t adapter_sources < <(
  cd -- "$repo_root/runtime"
  go list -deps -f '{{if not .Standard}}{{range .GoFiles}}{{$.Dir}}/{{.}}{{"\n"}}{{end}}{{range .CgoFiles}}{{$.Dir}}/{{.}}{{"\n"}}{{end}}{{range .EmbedFiles}}{{$.Dir}}/{{.}}{{"\n"}}{{end}}{{end}}' \
    ./deploy/temporal-unsafe/adapter | sed '/^$/d' | sort -u
)
adapter_sources+=("$repo_root/runtime/go.mod" "$repo_root/runtime/go.sum")
for input in "${adapter_sources[@]}"; do
  if [[ ! -f "$input" || -L "$input" ]]; then
    echo "adapter dependency is missing or not a regular file: $input" >&2
    exit 64
  fi
  case "$input" in
    "$repo_root"/runtime/*) ;;
    *)
      echo "adapter dependency escaped the repository runtime tree: $input" >&2
      exit 64
      ;;
  esac
done
adapter_source_manifest="$work_dir/adapter-source.manifest"
: >"$adapter_source_manifest"
for input in "${adapter_sources[@]}"; do
  relative="${input#"$repo_root/"}"
  printf '%s  %s\n' "$(sha256sum -- "$input" | awk '{print $1}')" "$relative" >>"$adapter_source_manifest"
done
sort -u -o "$adapter_source_manifest" "$adapter_source_manifest"
adapter_source_sha256="$(sha256sum -- "$adapter_source_manifest" | awk '{print $1}')"

(
  cd -- "$repo_root/runtime"
  go test -count=1 ./deploy/temporal-unsafe/adapter
)

git_revision="$(git -C "$repo_root" rev-parse --verify HEAD)"
if [[ ! "$git_revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo "could not resolve a full git revision" >&2
  exit 1
fi
adapter_repository="${TEMPORAL_UNSAFE_ADAPTER_REPOSITORY:-safe-change-temporal-provider-adapter}"
if [[ ! "$adapter_repository" =~ ^[a-z0-9]+([._/-][a-z0-9]+)*$ ]]; then
  echo "TEMPORAL_UNSAFE_ADAPTER_REPOSITORY must be a lowercase local repository without a tag" >&2
  exit 64
fi
adapter_version="${TEMPORAL_UNSAFE_ADAPTER_VERSION:-g${git_revision:0:12}-s${adapter_source_sha256:0:12}-d${adapter_dockerfile_sha256:0:12}}"
if [[ "$adapter_version" == latest || ! "$adapter_version" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$ ]]; then
  echo "TEMPORAL_UNSAFE_ADAPTER_VERSION must be an explicit Docker tag other than latest" >&2
  exit 64
fi
adapter_image="$adapter_repository:$adapter_version"

# Exactly one adapter image is built and then instantiated twice with separate
# immutable route files. It has no generic forwarding configuration.
docker build --provenance=false --file "$adapter_dockerfile" \
  --build-arg "GO_IMAGE=$TEMPORAL_GO_IMAGE" \
  --build-arg "RUNTIME_IMAGE=$TEMPORAL_RUNTIME_IMAGE" \
  --build-arg "GIT_REVISION=$git_revision" \
  --build-arg "SOURCE_SHA256=$adapter_source_sha256" \
  --tag "$adapter_image" "$repo_root"

adapter_id="$(docker image inspect --format '{{.Id}}' "$adapter_image")"
if [[ ! "$adapter_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "Docker returned an invalid adapter image ID: $adapter_id" >&2
  exit 1
fi
verify_label "$adapter_id" org.opencontainers.image.revision "$git_revision"
verify_label "$adapter_id" org.opencontainers.image.base.name "$TEMPORAL_RUNTIME_IMAGE"
verify_label "$adapter_id" io.safe-change.source.sha256 "$adapter_source_sha256"
if [[ "$(docker image inspect --format '{{json .Config.Entrypoint}}' "$adapter_id")" != '["/usr/local/bin/temporal-provider-adapter"]' ]]; then
  echo "adapter image has an unexpected entrypoint" >&2
  exit 1
fi
extract_binary "$adapter_id" /usr/local/bin/temporal-provider-adapter "$work_dir/temporal-provider-adapter"
if [[ ! -x "$work_dir/temporal-provider-adapter" ]]; then
  echo "adapter image does not contain an executable adapter" >&2
  exit 1
fi
adapter_binary_sha256="$(sha256sum -- "$work_dir/temporal-provider-adapter" | awk '{print $1}')"

# Fail closed if any live build or topology input changed during compilation.
if [[ "$(sha256sum -- "$script_dir/build-images.sh" | awk '{print $1}')" != "$build_script_sha256" ||
      "$(sha256sum -- "$target_builder" | awk '{print $1}')" != "$target_builder_sha256" ||
      "$(sha256sum -- "$adapter_dockerfile" | awk '{print $1}')" != "$adapter_dockerfile_sha256" ||
      "$(sha256sum -- "$source_adapter_config" | awk '{print $1}')" != "$source_adapter_config_sha256" ||
      "$(sha256sum -- "$target_adapter_config" | awk '{print $1}')" != "$target_adapter_config_sha256" ||
      "$(sha256sum -- "$proposed_compose" | awk '{print $1}')" != "$proposed_compose_sha256" ||
      "$(sha256sum -- "$native_compose" | awk '{print $1}')" != "$native_compose_sha256" ||
      "$(sha256sum -- "$temporal_dir/compose.yaml" | awk '{print $1}')" != "$base_compose_sha256" ||
      "$(sha256sum -- "$frozen_inputs_file" | awk '{print $1}')" != "$frozen_inputs_sha256" ||
      "$(sha256sum -- "$control_profile_file" | awk '{print $1}')" != "$frozen_control_build_profile_sha256" ||
      "$(sha256sum -- "$control_source_manifest" | awk '{print $1}')" != "$CONTROL_SOURCE_MANIFEST_SHA256" ||
      "$(sha256sum -- "$control_dockerfile" | awk '{print $1}')" != "$CONTROL_DOCKERFILE_SHA256" ||
      "$(sha256sum -- "$versions_file" | awk '{print $1}')" != "$frozen_versions_sha256" ]]; then
  echo "unsafe Temporal build input changed during the image build" >&2
  exit 1
fi
for input in "${adapter_sources[@]}"; do
  relative="${input#"$repo_root/"}"
  expected="$(awk -v path="$relative" '$2 == path {print $1}' "$adapter_source_manifest")"
  if [[ -z "$expected" || "$(sha256sum -- "$input" | awk '{print $1}')" != "$expected" ]]; then
    echo "adapter dependency changed during the image build: $relative" >&2
    exit 1
  fi
done

mkdir -p -- \
  "$stage_evidence/frozen" "$stage_evidence/adapter/source" \
  "$stage_evidence/builder" "$stage_evidence/topology" "$stage_evidence/control/source"
cp -- "$target_env" "$stage_evidence/target.env"
cp -a -- "$target_evidence" "$stage_evidence/target"
cp -- "$adapter_source_manifest" "$stage_evidence/adapter/source.manifest"
for input in "${adapter_sources[@]}"; do
  relative="${input#"$repo_root/"}"
  destination="$stage_evidence/adapter/source/$relative"
  mkdir -p -- "$(dirname -- "$destination")"
  cp -- "$input" "$destination"
done
cp -- "$adapter_dockerfile" "$stage_evidence/adapter/Dockerfile"
go version -m "$work_dir/temporal-provider-adapter" >"$stage_evidence/adapter/go-version.txt"
docker image inspect "$adapter_id" >"$stage_evidence/adapter/image-inspect.json"
docker image inspect \
  "$TEMPORAL_IMAGE" "$frozen_worker_v1_id" "$frozen_worker_v2_id" \
  "$frozen_starter_id" "$frozen_effects_id" "$frozen_control_image" \
  >"$stage_evidence/frozen/image-inspect.json"
cp -- "$frozen_inputs_file" "$stage_evidence/frozen/frozen-inputs.env"
cp -- "$versions_file" "$stage_evidence/frozen/versions.env"
cp -- "$control_profile_file" "$stage_evidence/control/control-profile.env"
cp -- "$control_source_manifest" "$stage_evidence/control/control-source.manifest"
cp -- "$control_dockerfile" "$stage_evidence/control/Dockerfile.runtime"
while read -r _ relative; do
  destination="$stage_evidence/control/source/$relative"
  mkdir -p -- "$(dirname -- "$destination")"
  cp -- "$repo_root/$relative" "$destination"
done <"$control_source_manifest"
docker image inspect "$frozen_control_image" >"$stage_evidence/control/image-inspect.json"
go version -m "$work_dir/control" >"$stage_evidence/control/go-version.txt"
cp -- "$script_dir/build-images.sh" "$stage_evidence/builder/build-images.sh"
cp -- "$target_builder" "$stage_evidence/builder/build-target.sh"
cp -- "$temporal_dir/compose.yaml" "$stage_evidence/topology/compose-base.yaml"
cp -- "$proposed_compose" "$native_compose" "$stage_evidence/topology/"
cp -- "$source_adapter_config" "$target_adapter_config" "$stage_evidence/topology/"

{
  printf 'GIT_REVISION=%s\n' "$git_revision"
  printf 'FROZEN_GIT_REVISION=%s\n' "$frozen_revision"
  printf 'FROZEN_TEMPORAL_BUILD_PROFILE_SHA256=%s\n' "$frozen_temporal_build_profile_sha256"
  printf 'FROZEN_CONTROL_BUILD_PROFILE_SHA256=%s\n' "$frozen_control_build_profile_sha256"
  printf 'FROZEN_INPUTS_SHA256=%s\n' "$frozen_inputs_sha256"
  printf 'FROZEN_VERSIONS_SHA256=%s\n' "$frozen_versions_sha256"
  printf 'FROZEN_TEMPORAL_SOURCE_SHA256=%s\n' "$frozen_temporal_source_sha256"
  printf 'FROZEN_RUNTIME_SOURCE_SHA256=%s\n' "$frozen_runtime_source_sha256"
  printf 'TEMPORAL_IMAGE=%s\n' "$TEMPORAL_IMAGE"
  printf 'TEMPORAL_IMAGE_ID=%s\n' "$temporal_image_id"
  printf 'WORKER_V1_IMAGE=%s\nWORKER_V1_ID=%s\n' "$frozen_worker_v1_image" "$frozen_worker_v1_id"
  printf 'WORKER_V1_BINARY_SHA256=%s\n' "$frozen_worker_v1_binary_sha256"
  printf 'WORKER_V1_VARIANT_SHA256=%s\n' "$frozen_worker_v1_variant_sha256"
  printf 'WORKER_V2_IMAGE=%s\nWORKER_V2_ID=%s\n' "$frozen_worker_v2_image" "$frozen_worker_v2_id"
  printf 'WORKER_V2_BINARY_SHA256=%s\n' "$frozen_worker_v2_binary_sha256"
  printf 'STARTER_IMAGE=%s\nSTARTER_ID=%s\n' "$frozen_starter_image" "$frozen_starter_id"
  printf 'STARTER_BINARY_SHA256=%s\n' "$frozen_starter_binary_sha256"
  printf 'EFFECTS_IMAGE=%s\nEFFECTS_ID=%s\n' "$frozen_effects_image" "$frozen_effects_id"
  printf 'EFFECTS_BINARY_SHA256=%s\n' "$frozen_effects_binary_sha256"
  printf 'SAFE_CHANGE_CONTROL_IMAGE=%s\n' "$frozen_control_image"
  printf 'SAFE_CHANGE_RUNTIME_IMAGE=%s\n' "$frozen_control_image"
  printf 'CONTROL_BINARY_SHA256=%s\n' "$control_binary_sha256"
  printf 'CONTROL_SOURCE_MANIFEST_SHA256=%s\n' "$CONTROL_SOURCE_MANIFEST_SHA256"
  printf 'CONTROL_DOCKERFILE_SHA256=%s\n' "$CONTROL_DOCKERFILE_SHA256"
  printf 'TEMPORAL_UNSAFE_WORKER_IMAGE=%s\n' "$unsafe_worker_image"
  printf 'TEMPORAL_UNSAFE_WORKER_ID=%s\n' "$unsafe_worker_id"
  printf 'UNSAFE_WORKER_IMAGE=%s\n' "$unsafe_worker_image"
  printf 'UNSAFE_WORKER_ID=%s\n' "$unsafe_worker_id"
  printf 'WORKER_UNSAFE_V2_ID=%s\n' "$unsafe_worker_id"
  printf 'TEMPORAL_UNSAFE_WORKER_BINARY_SHA256=%s\n' "$unsafe_worker_binary_sha256"
  printf 'UNSAFE_WORKER_BINARY_SHA256=%s\n' "$unsafe_worker_binary_sha256"
  printf 'PROPOSED_UNSAFE_WORKER_ID=%s\n' "$unsafe_worker_id"
  printf 'NATIVE_UNSAFE_WORKER_ID=%s\n' "$unsafe_worker_id"
  printf 'PROPOSED_NATIVE_IMAGE_ID_EQUAL=true\n'
  printf 'FROZEN_BASE_SOURCE_SHA256=%s\n' "$target_frozen_base_source_sha256"
  printf 'GENERATED_SOURCE_SHA256=%s\n' "$target_generated_source_sha256"
  printf 'GENERATED_TREE_MANIFEST_SHA256=%s\n' "$target_generated_tree_manifest_sha256"
  printf 'PATCH_SET_SHA256=%s\n' "$target_patch_set_sha256"
  printf 'PATCH_0001_SHA256=%s\n' "$target_patch_0001_sha256"
  printf 'PATCH_0002_SHA256=%s\n' "$target_patch_0002_sha256"
  printf 'PATCH_0003_SHA256=%s\n' "$target_patch_0003_sha256"
  printf 'TARGET_DOCKERFILE_SHA256=%s\n' "$target_dockerfile_sha256"
  printf 'UNSAFE_VARIANT_SHA256=%s\n' "$target_unsafe_variant_sha256"
  printf 'UNSAFE_WORKER_NM_SHA256=%s\n' "$target_worker_nm_sha256"
  printf 'UNSAFE_WORKER_GO_VERSION_SHA256=%s\n' "$target_worker_go_version_sha256"
  printf 'TARGET_BUILD_ENV_SHA256=%s\n' "$target_build_env_sha256"
  printf 'TEMPORAL_UNSAFE_ADAPTER_IMAGE=%s\n' "$adapter_image"
  printf 'TEMPORAL_UNSAFE_ADAPTER_ID=%s\n' "$adapter_id"
  printf 'TEMPORAL_UNSAFE_ADAPTER_SOURCE_SHA256=%s\n' "$adapter_source_sha256"
  printf 'TEMPORAL_UNSAFE_ADAPTER_BINARY_SHA256=%s\n' "$adapter_binary_sha256"
  printf 'SOURCE_ADAPTER_CONFIG_SHA256=%s\n' "$source_adapter_config_sha256"
  printf 'TARGET_ADAPTER_CONFIG_SHA256=%s\n' "$target_adapter_config_sha256"
  printf 'BASE_COMPOSE_SHA256=%s\n' "$base_compose_sha256"
  printf 'PROPOSED_COMPOSE_SHA256=%s\n' "$proposed_compose_sha256"
  printf 'NATIVE_COMPOSE_SHA256=%s\n' "$native_compose_sha256"
  printf 'BUILD_IMAGES_SHA256=%s\n' "$build_script_sha256"
  printf 'TARGET_BUILDER_SHA256=%s\n' "$target_builder_sha256"
  printf 'ADAPTER_DOCKERFILE_SHA256=%s\n' "$adapter_dockerfile_sha256"
  printf 'TEMPORAL_UNSAFE_PAYMENT_TOKEN_CONTRACT=payment_token_equals_order_id\n'
  printf 'TEMPORAL_UNSAFE_COMPOSE_PROFILES_CONTRACT=empty\n'
  printf 'TEMPORAL_UNSAFE_EXCLUDED_PROFILE=excluded-base-worker-v2\n'
} >"$stage_env"

# Publish the exact environment beside every source/topology input and cover
# the complete recursive evidence tree with one independent checksum index.
# The outer copy and OUTPUT_ENV must remain byte-identical.
cp -- "$stage_env" "$stage_evidence/build.env"
(
  cd -- "$stage_evidence"
  while IFS= read -r -d '' artifact; do
    sha256sum -- "$artifact"
  done < <(find . -type f ! -name SHA256SUMS -print0 | sort -z)
) >"$stage_evidence/SHA256SUMS"

chmod -R u=rwX,go= -- "$stage_evidence"
chmod 600 -- "$stage_env"
mv -- "$stage_evidence" "$evidence_dir"
stage_evidence=""
mv -- "$stage_env" "$output_env"
stage_env=""

printf 'frozen source worker: %s\n' "$frozen_worker_v1_id"
printf 'one proposed/native target worker: %s\n' "$unsafe_worker_id"
printf 'one adapter image, two immutable configs: %s\n' "$adapter_id"
printf 'frozen control: %s\n' "$frozen_control_image"
