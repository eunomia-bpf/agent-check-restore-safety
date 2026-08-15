#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/../../.." && pwd -P)"

# shellcheck source=versions.env
source "$script_dir/versions.env"

for required in TEMPORAL_GO_IMAGE TEMPORAL_RUNTIME_IMAGE TEMPORAL_SAMPLES_COMMIT TEMPORAL_GO_SDK_VERSION; do
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

image_repository="${TEMPORAL_IMAGE_REPOSITORY:-safe-change-temporal}"
if [[ ! "$image_repository" =~ ^[a-z0-9]+([._/-][a-z0-9]+)*$ ]]; then
  echo "TEMPORAL_IMAGE_REPOSITORY must be a lowercase local repository without a tag" >&2
  exit 64
fi

git_revision="$(git -C "$repo_root" rev-parse --verify HEAD)"
if [[ ! "$git_revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo "could not resolve a full git revision" >&2
  exit 1
fi

unexpected_source="$(find "$script_dir/app" -mindepth 1 ! -type d ! -type f -print -quit)"
if [[ -n "$unexpected_source" ]]; then
  echo "Temporal application source contains a symlink or special file: $unexpected_source" >&2
  exit 64
fi

source_sha256="$({
  while IFS= read -r -d '' input; do
    relative="${input#"$repo_root/"}"
    printf '%s\0' "$relative"
    sha256sum -- "$input" | awk '{print $1}'
  done < <(find "$script_dir/app" -type f -print0 | sort -z)
} | sha256sum | awk '{print $1}')"
if [[ ! "$source_sha256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "could not hash Temporal application sources" >&2
  exit 1
fi

runtime_source_inputs=(
  "$repo_root/runtime/go.mod"
  "$repo_root/runtime/go.sum"
  "$repo_root/runtime/cmd/payment"
  "$repo_root/runtime/internal/kernel"
  "$repo_root/runtime/internal/payment"
)
unexpected_runtime_source="$(find "${runtime_source_inputs[@]}" -mindepth 0 ! -type d ! -type f -print -quit)"
if [[ -n "$unexpected_runtime_source" ]]; then
  echo "payment runtime source contains a symlink or special file: $unexpected_runtime_source" >&2
  exit 64
fi
runtime_source_sha256="$({
  while IFS= read -r -d '' input; do
    relative="${input#"$repo_root/"}"
    printf '%s\0' "$relative"
    sha256sum -- "$input" | awk '{print $1}'
  done < <(find "${runtime_source_inputs[@]}" -type f -print0 | sort -z)
} | sha256sum | awk '{print $1}')"
if [[ ! "$runtime_source_sha256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "could not hash payment runtime sources" >&2
  exit 1
fi

image_version="${TEMPORAL_IMAGE_VERSION:-g${git_revision:0:12}-s${source_sha256:0:12}}"
if [[ "$image_version" == "latest" || ! "$image_version" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$ ]]; then
  echo "TEMPORAL_IMAGE_VERSION must be an explicit Docker tag other than latest" >&2
  exit 64
fi

worker_v1_image="${image_repository}-worker-v1:${image_version}"
worker_v2_image="${image_repository}-worker-v2:${image_version}"
starter_image="${image_repository}-starter:${image_version}"
effects_image_version="${TEMPORAL_EFFECTS_IMAGE_VERSION:-g${git_revision:0:12}-r${runtime_source_sha256:0:12}}"
if [[ "$effects_image_version" == "latest" || ! "$effects_image_version" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$ ]]; then
  echo "TEMPORAL_EFFECTS_IMAGE_VERSION must be an explicit Docker tag other than latest" >&2
  exit 64
fi
effects_image="${image_repository}-effects:${effects_image_version}"

common_args=(
  --provenance=false
  --build-arg "GO_IMAGE=$TEMPORAL_GO_IMAGE"
  --build-arg "RUNTIME_IMAGE=$TEMPORAL_RUNTIME_IMAGE"
  --build-arg "GIT_REVISION=$git_revision"
  --build-arg "SOURCE_SHA256=$source_sha256"
  --build-arg "TEMPORAL_SAMPLES_COMMIT=$TEMPORAL_SAMPLES_COMMIT"
  --build-arg "TEMPORAL_GO_SDK_VERSION=$TEMPORAL_GO_SDK_VERSION"
)

docker build --file "$script_dir/Dockerfile.worker" \
  "${common_args[@]}" \
  --build-arg WORKER_TAG=worker_v1 \
  --build-arg WORKER_BUILD_ID=food-order-v1 \
  --tag "$worker_v1_image" "$repo_root"
docker build --file "$script_dir/Dockerfile.worker" \
  "${common_args[@]}" \
  --build-arg WORKER_TAG=worker_v2 \
  --build-arg WORKER_BUILD_ID=food-order-v2 \
  --tag "$worker_v2_image" "$repo_root"
docker build --file "$script_dir/Dockerfile.starter" \
  "${common_args[@]}" \
  --tag "$starter_image" "$repo_root"
docker build --file "$script_dir/Dockerfile.effects" \
  --provenance=false \
  --build-arg "GO_IMAGE=$TEMPORAL_GO_IMAGE" \
  --build-arg "RUNTIME_IMAGE=$TEMPORAL_RUNTIME_IMAGE" \
  --build-arg "GIT_REVISION=$git_revision" \
  --build-arg "RUNTIME_SOURCE_SHA256=$runtime_source_sha256" \
  --tag "$effects_image" "$repo_root"

verify_label() {
  local image="$1" label="$2" expected="$3" actual
  actual="$(docker image inspect --format "{{ index .Config.Labels \"$label\" }}" "$image")"
  if [[ "$actual" != "$expected" ]]; then
    echo "$image label $label is $actual, expected $expected" >&2
    exit 1
  fi
}

for image in "$worker_v1_image" "$worker_v2_image" "$starter_image"; do
  verify_label "$image" org.opencontainers.image.revision "$git_revision"
  verify_label "$image" org.opencontainers.image.base.name "$TEMPORAL_RUNTIME_IMAGE"
  verify_label "$image" io.safe-change.source.sha256 "$source_sha256"
  verify_label "$image" io.safe-change.builder.base "$TEMPORAL_GO_IMAGE"
  verify_label "$image" io.safe-change.temporal.samples.revision "$TEMPORAL_SAMPLES_COMMIT"
  verify_label "$image" io.safe-change.temporal.go-sdk.version "$TEMPORAL_GO_SDK_VERSION"
done
verify_label "$worker_v1_image" io.safe-change.build.target worker_v1
verify_label "$worker_v1_image" io.safe-change.worker.build-id food-order-v1
verify_label "$worker_v2_image" io.safe-change.build.target worker_v2
verify_label "$worker_v2_image" io.safe-change.worker.build-id food-order-v2
verify_label "$starter_image" io.safe-change.build.target starter
verify_label "$effects_image" org.opencontainers.image.revision "$git_revision"
verify_label "$effects_image" org.opencontainers.image.base.name "$TEMPORAL_RUNTIME_IMAGE"
verify_label "$effects_image" io.safe-change.source.sha256 "$runtime_source_sha256"
verify_label "$effects_image" io.safe-change.runtime.source.sha256 "$runtime_source_sha256"
verify_label "$effects_image" io.safe-change.builder.base "$TEMPORAL_GO_IMAGE"
verify_label "$effects_image" io.safe-change.build.target effects

verify_dir="$(mktemp -d /tmp/safe-change-temporal-images.XXXXXX)"
container_ids=()
cleanup() {
  if ((${#container_ids[@]})); then
    docker container rm --force "${container_ids[@]}" >/dev/null 2>&1 || true
  fi
  find "$verify_dir" -depth -delete
}
trap cleanup EXIT

extract_binary() {
  local image="$1" source="$2" destination="$3" container_id
  container_id="$(docker container create "$image")"
  container_ids+=("$container_id")
  docker container cp "$container_id:$source" "$destination"
  docker container rm "$container_id" >/dev/null
  container_ids=("${container_ids[@]:0:${#container_ids[@]}-1}")
}

extract_binary "$worker_v1_image" /usr/local/bin/worker "$verify_dir/worker-v1"
extract_binary "$worker_v2_image" /usr/local/bin/worker "$verify_dir/worker-v2"
extract_binary "$starter_image" /usr/local/bin/starter "$verify_dir/starter"
extract_binary "$effects_image" /usr/local/bin/payment "$verify_dir/payment"

worker_v1_binary_sha256="$(sha256sum "$verify_dir/worker-v1" | awk '{print $1}')"
worker_v2_binary_sha256="$(sha256sum "$verify_dir/worker-v2" | awk '{print $1}')"
starter_binary_sha256="$(sha256sum "$verify_dir/starter" | awk '{print $1}')"
effects_binary_sha256="$(sha256sum "$verify_dir/payment" | awk '{print $1}')"
for binary_sha256 in "$worker_v1_binary_sha256" "$worker_v2_binary_sha256" "$starter_binary_sha256" "$effects_binary_sha256"; do
  if [[ ! "$binary_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    echo "could not hash a built binary" >&2
    exit 1
  fi
done
if [[ ! -x "$verify_dir/payment" ]]; then
  echo "effects image does not contain an executable /usr/local/bin/payment" >&2
  exit 1
fi
effects_entrypoint="$(docker image inspect --format '{{json .Config.Entrypoint}}' "$effects_image")"
if [[ "$effects_entrypoint" != '["/usr/local/bin/payment"]' ]]; then
  echo "effects image has an unexpected entrypoint: $effects_entrypoint" >&2
  exit 1
fi

(cd "$script_dir/app" && go tool nm "$verify_dir/worker-v1") >"$verify_dir/worker-v1.nm"
(cd "$script_dir/app" && go tool nm "$verify_dir/worker-v2") >"$verify_dir/worker-v2.nm"
if ! grep -Fq '(*Activities).ChargePayment' "$verify_dir/worker-v1.nm"; then
  echo "v1 worker binary does not contain ChargePayment" >&2
  exit 1
fi
if grep -Fq '(*Activities).ChargePayment' "$verify_dir/worker-v2.nm"; then
  echo "v2 worker binary unexpectedly contains ChargePayment" >&2
  exit 1
fi

worker_v1_id="$(docker image inspect --format '{{.Id}}' "$worker_v1_image")"
worker_v2_id="$(docker image inspect --format '{{.Id}}' "$worker_v2_image")"
starter_id="$(docker image inspect --format '{{.Id}}' "$starter_image")"
effects_id="$(docker image inspect --format '{{.Id}}' "$effects_image")"
for image_id in "$worker_v1_id" "$worker_v2_id" "$starter_id" "$effects_id"; do
  if [[ ! "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "Docker returned an invalid image ID: $image_id" >&2
    exit 1
  fi
done

printf 'GIT_REVISION=%s\n' "$git_revision"
printf 'SOURCE_SHA256=%s\n' "$source_sha256"
printf 'WORKER_V1_IMAGE=%s\nWORKER_V1_ID=%s\n' "$worker_v1_image" "$worker_v1_id"
printf 'WORKER_V1_BINARY_SHA256=%s\n' "$worker_v1_binary_sha256"
printf 'WORKER_V2_IMAGE=%s\nWORKER_V2_ID=%s\n' "$worker_v2_image" "$worker_v2_id"
printf 'WORKER_V2_BINARY_SHA256=%s\n' "$worker_v2_binary_sha256"
printf 'STARTER_IMAGE=%s\nSTARTER_ID=%s\n' "$starter_image" "$starter_id"
printf 'STARTER_BINARY_SHA256=%s\n' "$starter_binary_sha256"
printf 'RUNTIME_SOURCE_SHA256=%s\n' "$runtime_source_sha256"
printf 'EFFECTS_IMAGE=%s\nEFFECTS_ID=%s\n' "$effects_image" "$effects_id"
printf 'EFFECTS_BINARY_SHA256=%s\n' "$effects_binary_sha256"
