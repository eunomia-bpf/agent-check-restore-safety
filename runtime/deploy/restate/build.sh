#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runtime_dir="$(realpath "$script_dir/../..")"
output_env="${1:-}"
if [[ -z "$output_env" ]]; then
  echo "usage: $0 OUTPUT_ENV" >&2
  exit 2
fi
mkdir -p "$(dirname "$output_env")"
output_env="$(realpath -m "$output_env")"

set -a
# shellcheck source=/dev/null
source "$script_dir/versions.env"
# shellcheck source=/dev/null
source "$script_dir/images.env"
set +a

for command in docker git python3 sha256sum tar; do
  command -v "$command" >/dev/null || {
    echo "required command not found: $command" >&2
    exit 1
  }
done

work_dir="$(mktemp -d /tmp/safe-change-restate-build.XXXXXX)"
cleanup() {
  case "$work_dir" in
    /tmp/safe-change-restate-build.*) rm -rf -- "$work_dir" ;;
    *) echo "refusing to remove unexpected build directory: $work_dir" >&2 ;;
  esac
}
trap cleanup EXIT

upstream="$work_dir/examples"
v1_tree="$work_dir/examples-v1"
v2_tree="$work_dir/examples-v2"
git clone --quiet --depth 1 --branch "$RESTATE_EXAMPLES_TAG" \
  https://github.com/restatedev/examples.git "$upstream"
actual_commit="$(git -C "$upstream" rev-parse HEAD)"
if [[ "$actual_commit" != "$RESTATE_EXAMPLES_COMMIT" ]]; then
  echo "upstream tag resolved to $actual_commit, expected $RESTATE_EXAMPLES_COMMIT" >&2
  exit 1
fi
archive_hash="$(git -C "$upstream" archive "$actual_commit" | sha256sum | awk '{print $1}')"
if [[ "$archive_hash" != "$RESTATE_EXAMPLES_ARCHIVE_SHA256" ]]; then
  echo "upstream archive hash is $archive_hash, expected $RESTATE_EXAMPLES_ARCHIVE_SHA256" >&2
  exit 1
fi

git -C "$upstream" worktree add --quiet --detach "$v1_tree" "$actual_commit"
git -C "$upstream" worktree add --quiet --detach "$v2_tree" "$actual_commit"
git -C "$v1_tree" apply "$script_dir/patches/payment-control.patch"
git -C "$v1_tree" apply "$script_dir/patches/completion-control.patch"
git -C "$v2_tree" apply "$script_dir/patches/payment-control.patch"
git -C "$v2_tree" apply "$script_dir/patches/completion-control.patch"
git -C "$v2_tree" apply "$script_dir/patches/remove-payment-v2.patch"

v1_workflow="$v1_tree/typescript/end-to-end-applications/food-ordering/app/src/order-app/order_workflow/impl.ts"
v2_workflow="$v2_tree/typescript/end-to-end-applications/food-ordering/app/src/order-app/order_workflow/impl.ts"
python3 - "$v1_workflow" "$v2_workflow" <<'PY'
from pathlib import Path
import sys

v1 = Path(sys.argv[1]).read_text()
v2 = Path(sys.argv[2]).read_text()
removed = '''      const paid = await ctx.run("payment", () => paymentClient.charge(id, token, totalCost));

      if (!paid) {
        ctx.set("status", Status.REJECTED);
        return;
      }
'''
if v1.count(removed) != 1:
    raise SystemExit("v1 does not contain the exact payment/rejection block")
if v2 != v1.replace(removed, "", 1):
    raise SystemExit("v2 differs from v1 by more than the payment ctx.run/rejection block")
if "      const token = ctx.rand.uuidv4();" not in v2:
    raise SystemExit("v2 did not retain the bound ctx.rand.uuidv4() call")
if 'ctx.run("payment"' in v2 or "if (!paid)" in v2:
    raise SystemExit("v2 still contains payment execution or its rejection branch")
PY
v1_program_hash="$(sha256sum "$v1_workflow" | awk '{print $1}')"
v2_program_hash="$(sha256sum "$v2_workflow" | awk '{print $1}')"

food_root="typescript/end-to-end-applications/food-ordering"
v1_app="$v1_tree/$food_root/app"
v2_app="$v2_tree/$food_root/app"
webui="$v1_tree/$food_root/webui"
cp "$v1_tree/LICENSE" "$v1_app/LICENSE.restate-examples"
cp "$v2_tree/LICENSE" "$v2_app/LICENSE.restate-examples"
cp "$v1_tree/LICENSE" "$webui/LICENSE.restate-examples"

generate_lock() {
  local image=$1 directory=$2
  docker run --rm --user "$(id -u):$(id -g)" \
    --env HOME=/tmp --env npm_config_cache=/tmp/npm-cache \
    --volume "$directory:/workspace" --workdir /workspace \
    "$image" npm install --package-lock-only --ignore-scripts --no-audit --no-fund >/dev/null
}

# Resolve dependencies once, with a pinned npm runtime, and use the exact same
# lock for both worker variants.
generate_lock "$NODE_IMAGE" "$v1_app"
cp "$v1_app/package-lock.json" "$v2_app/package-lock.json"
generate_lock "$WEBUI_NODE_IMAGE" "$webui"

# Git worktrees and generated locks otherwise carry wall-clock mtimes into the
# Docker context. Normalize them so rebuilding the same pinned inputs reaches
# the same BuildKit cache keys and image content.
python3 - "$v1_app" "$v2_app" "$webui" <<'PY'
import os
import sys

epoch = 946684800  # 2000-01-01T00:00:00Z
for top in sys.argv[1:]:
    for root, directories, files in os.walk(top, topdown=False):
        for name in files + directories:
            os.utime(os.path.join(root, name), (epoch, epoch), follow_symlinks=False)
        os.utime(root, (epoch, epoch), follow_symlinks=False)
PY

output_name="$(basename "$output_env")"
lock_evidence_dir="$(dirname "$output_env")/${output_name%.*}-evidence"
mkdir -p "$lock_evidence_dir"
chmod 700 "$lock_evidence_dir"
app_lock_file="$lock_evidence_dir/app-package-lock.json"
webui_lock_file="$lock_evidence_dir/webui-package-lock.json"
upstream_license_file="$lock_evidence_dir/restate-examples-LICENSE"
cp "$v1_app/package-lock.json" "$app_lock_file"
cp "$webui/package-lock.json" "$webui_lock_file"
cp "$v1_tree/LICENSE" "$upstream_license_file"
chmod 600 "$app_lock_file" "$webui_lock_file" "$upstream_license_file"

context_hash() {
  local directory=$1
  tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
    -cf - -C "$directory" . | sha256sum | awk '{print $1}'
}

v1_context_hash="$(context_hash "$v1_app")"
v2_context_hash="$(context_hash "$v2_app")"
restaurant_context_hash="$({
  tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
    -cf - -C "$v1_app" package.json package-lock.json LICENSE.restate-examples src/restaurant
} | sha256sum | awk '{print $1}')"
app_lock_hash="$(sha256sum "$v1_app/package-lock.json" | awk '{print $1}')"
webui_lock_hash="$(sha256sum "$webui/package-lock.json" | awk '{print $1}')"
payment_patch_hash="$(sha256sum "$script_dir/patches/payment-control.patch" | awk '{print $1}')"
completion_patch_hash="$(sha256sum "$script_dir/patches/completion-control.patch" | awk '{print $1}')"
v2_patch_hash="$(sha256sum "$script_dir/patches/remove-payment-v2.patch" | awk '{print $1}')"

image_prefix="${RESTATE_HARNESS_IMAGE_PREFIX:-safe-change-restate}"
short_commit="${RESTATE_EXAMPLES_COMMIT:0:12}"
order_v1_tag="$image_prefix-order-v1:$short_commit"
order_v2_tag="$image_prefix-order-v2:$short_commit"
webui_tag="$image_prefix-webui:$short_commit"
restaurant_tag="$image_prefix-restaurant:$short_commit"
runtime_tag="$image_prefix-runtime:workspace"

docker build --quiet --pull \
  --build-arg "NODE_IMAGE=$NODE_IMAGE" \
  --build-arg "UPSTREAM_COMMIT=$RESTATE_EXAMPLES_COMMIT" \
  --build-arg WORKER_VARIANT=v1 \
  --file "$script_dir/Dockerfile.worker" --tag "$order_v1_tag" "$v1_app" >/dev/null
docker build --quiet --pull \
  --build-arg "NODE_IMAGE=$NODE_IMAGE" \
  --build-arg "UPSTREAM_COMMIT=$RESTATE_EXAMPLES_COMMIT" \
  --build-arg WORKER_VARIANT=v2 \
  --file "$script_dir/Dockerfile.worker" --tag "$order_v2_tag" "$v2_app" >/dev/null
docker build --quiet --pull \
  --build-arg "WEBUI_NODE_IMAGE=$WEBUI_NODE_IMAGE" \
  --build-arg "UPSTREAM_COMMIT=$RESTATE_EXAMPLES_COMMIT" \
  --file "$script_dir/Dockerfile.webui" --tag "$webui_tag" "$webui" >/dev/null
docker build --quiet --pull \
  --build-arg "NODE_IMAGE=$NODE_IMAGE" \
  --build-arg "UPSTREAM_COMMIT=$RESTATE_EXAMPLES_COMMIT" \
  --file "$script_dir/Dockerfile.restaurant" --tag "$restaurant_tag" "$v1_app" >/dev/null
docker build --quiet --pull \
  --build-arg "GO_BUILD_IMAGE=$GO_BUILD_IMAGE" \
  --build-arg "ALPINE_IMAGE=$ALPINE_IMAGE" \
  --file "$script_dir/Dockerfile.runtime" --tag "$runtime_tag" "$runtime_dir" >/dev/null

image_id() {
  docker image inspect --format '{{.Id}}' "$1"
}
order_v1_image="$(image_id "$order_v1_tag")"
order_v2_image="$(image_id "$order_v2_tag")"
webui_image="$(image_id "$webui_tag")"
restaurant_image="$(image_id "$restaurant_tag")"
runtime_image="$(image_id "$runtime_tag")"
if [[ "$order_v1_image" == "$order_v2_image" ]]; then
  echo "v1 and v2 unexpectedly produced the same image" >&2
  exit 1
fi
docker run --rm --entrypoint sh "$restaurant_image" -ec '
  test -f /app/server.js
  test ! -e /usr/src/app
  test ! -e /app/dist/order-app
'

temporary_env="$output_env.next"
{
  printf 'ORDER_V1_IMAGE=%q\n' "$order_v1_image"
  printf 'ORDER_V2_IMAGE=%q\n' "$order_v2_image"
  printf 'WEBUI_IMAGE=%q\n' "$webui_image"
  printf 'RESTAURANT_IMAGE=%q\n' "$restaurant_image"
  printf 'SAFE_CHANGE_RUNTIME_IMAGE=%q\n' "$runtime_image"
  printf 'UPSTREAM_ARCHIVE_SHA256=%q\n' "$archive_hash"
  printf 'APP_LOCK_SHA256=%q\n' "$app_lock_hash"
  printf 'WEBUI_LOCK_SHA256=%q\n' "$webui_lock_hash"
  printf 'PAYMENT_PATCH_SHA256=%q\n' "$payment_patch_hash"
  printf 'COMPLETION_PATCH_SHA256=%q\n' "$completion_patch_hash"
  printf 'V2_PATCH_SHA256=%q\n' "$v2_patch_hash"
  printf 'V1_CONTEXT_SHA256=%q\n' "$v1_context_hash"
  printf 'V2_CONTEXT_SHA256=%q\n' "$v2_context_hash"
  printf 'V1_PROGRAM_SHA256=%q\n' "$v1_program_hash"
  printf 'V2_PROGRAM_SHA256=%q\n' "$v2_program_hash"
  printf 'RESTAURANT_CONTEXT_SHA256=%q\n' "$restaurant_context_hash"
  printf 'APP_LOCK_FILE=%q\n' "$app_lock_file"
  printf 'WEBUI_LOCK_FILE=%q\n' "$webui_lock_file"
  printf 'UPSTREAM_LICENSE_FILE=%q\n' "$upstream_license_file"
} >"$temporary_env"
chmod 600 "$temporary_env"
mv "$temporary_env" "$output_env"

cat <<EOF
Built pinned Restate food-ordering images
  upstream:  $RESTATE_EXAMPLES_COMMIT ($archive_hash)
  worker v1: $order_v1_image ($v1_context_hash)
  worker v2: $order_v2_image ($v2_context_hash)
  program v1: $v1_program_hash
  program v2: $v2_program_hash
  webui:     $webui_image
  restaurant:$restaurant_image ($restaurant_context_hash)
  runtime:   $runtime_image
  metadata:  $output_env
  app lock:  $app_lock_file ($app_lock_hash)
  web lock:  $webui_lock_file ($webui_lock_hash)
EOF
