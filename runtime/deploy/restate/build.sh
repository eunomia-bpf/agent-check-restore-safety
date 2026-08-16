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
compatible_v2_tree="$work_dir/examples-compatible-v2"
unsafe_v2_tree="$work_dir/examples-unsafe-v2"
native_v1_tree="$work_dir/examples-native-v1"
native_v2_tree="$work_dir/examples-native-v2"
native_compatible_v2_tree="$work_dir/examples-native-compatible-v2"
native_unsafe_v2_tree="$work_dir/examples-native-unsafe-v2"
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
git -C "$upstream" worktree add --quiet --detach "$compatible_v2_tree" "$actual_commit"
git -C "$upstream" worktree add --quiet --detach "$unsafe_v2_tree" "$actual_commit"
git -C "$upstream" worktree add --quiet --detach "$native_v1_tree" "$actual_commit"
git -C "$upstream" worktree add --quiet --detach "$native_v2_tree" "$actual_commit"
git -C "$upstream" worktree add --quiet --detach "$native_compatible_v2_tree" "$actual_commit"
git -C "$upstream" worktree add --quiet --detach "$native_unsafe_v2_tree" "$actual_commit"
git -C "$v1_tree" apply "$script_dir/patches/payment-control.patch"
git -C "$v1_tree" apply "$script_dir/patches/completion-control.patch"
git -C "$v2_tree" apply "$script_dir/patches/payment-control.patch"
git -C "$v2_tree" apply "$script_dir/patches/completion-control.patch"
git -C "$v2_tree" apply "$script_dir/patches/remove-payment-v2.patch"
git -C "$compatible_v2_tree" apply "$script_dir/patches/payment-control.patch"
git -C "$compatible_v2_tree" apply "$script_dir/patches/completion-control.patch"
git -C "$compatible_v2_tree" apply "$script_dir/patches/compatible-completion-v2.patch"
git -C "$unsafe_v2_tree" apply "$script_dir/patches/payment-control.patch"
git -C "$unsafe_v2_tree" apply "$script_dir/patches/completion-control.patch"
git -C "$unsafe_v2_tree" apply "$script_dir/patches/unsafe-completion-v2.patch"
git -C "$native_v1_tree" apply "$script_dir/patches/provider-direct.patch"
git -C "$native_v2_tree" apply "$script_dir/patches/provider-direct.patch"
git -C "$native_v2_tree" apply "$script_dir/patches/remove-payment-v2.patch"
git -C "$native_compatible_v2_tree" apply "$script_dir/patches/provider-direct.patch"
git -C "$native_compatible_v2_tree" apply "$script_dir/patches/compatible-completion-direct-v2.patch"
git -C "$native_unsafe_v2_tree" apply "$script_dir/patches/provider-direct.patch"
git -C "$native_unsafe_v2_tree" apply "$script_dir/patches/unsafe-completion-direct-v2.patch"

v1_workflow="$v1_tree/typescript/end-to-end-applications/food-ordering/app/src/order-app/order_workflow/impl.ts"
v2_workflow="$v2_tree/typescript/end-to-end-applications/food-ordering/app/src/order-app/order_workflow/impl.ts"
compatible_v2_workflow="$compatible_v2_tree/typescript/end-to-end-applications/food-ordering/app/src/order-app/order_workflow/impl.ts"
unsafe_v2_workflow="$unsafe_v2_tree/typescript/end-to-end-applications/food-ordering/app/src/order-app/order_workflow/impl.ts"
native_v1_workflow="$native_v1_tree/typescript/end-to-end-applications/food-ordering/app/src/order-app/order_workflow/impl.ts"
native_v2_workflow="$native_v2_tree/typescript/end-to-end-applications/food-ordering/app/src/order-app/order_workflow/impl.ts"
native_compatible_v2_workflow="$native_compatible_v2_tree/typescript/end-to-end-applications/food-ordering/app/src/order-app/order_workflow/impl.ts"
native_unsafe_v2_workflow="$native_unsafe_v2_tree/typescript/end-to-end-applications/food-ordering/app/src/order-app/order_workflow/impl.ts"
python3 - \
  "$v1_workflow" "$v2_workflow" "$compatible_v2_workflow" "$unsafe_v2_workflow" \
  "$native_v1_workflow" "$native_v2_workflow" "$native_compatible_v2_workflow" \
  "$native_unsafe_v2_workflow" <<'PY'
from pathlib import Path
import sys

v1 = Path(sys.argv[1]).read_text()
v2 = Path(sys.argv[2]).read_text()
compatible_v2 = Path(sys.argv[3]).read_text()
unsafe_v2 = Path(sys.argv[4]).read_text()
native_v1 = Path(sys.argv[5]).read_text()
native_v2 = Path(sys.argv[6]).read_text()
native_compatible_v2 = Path(sys.argv[7]).read_text()
native_unsafe_v2 = Path(sys.argv[8]).read_text()
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
if native_v1 != v1 or native_v2 != v2:
    raise SystemExit("native baseline changed workflow program bytes")

old_completion = '      await ctx.run("completion", () => completionClient.complete(id));'
new_completion = '''      await ctx.run("completion", () =>
        completionClient.complete(id, "compatible-v2"),
      );'''
if v1.count(old_completion) != 1:
    raise SystemExit("v1 does not contain the exact completion closure")
expected_compatible_v2 = v1.replace(old_completion, new_completion, 1)
if compatible_v2 != expected_compatible_v2:
    raise SystemExit("proposed compatible v2 differs from v1 by more than the exact future completion closure")
if native_compatible_v2 != compatible_v2:
    raise SystemExit("proposed and native compatible v2 workflow bytes differ")

unsafe_completion = '''      await ctx.run("completion", () =>
        completionClient.complete(id, "unsafe-v2"),
      );'''
expected_unsafe_v2 = v1.replace(old_completion, unsafe_completion, 1)
if unsafe_v2 != expected_unsafe_v2:
    raise SystemExit("proposed unsafe v2 differs from v1 by more than the exact future completion closure")
if native_unsafe_v2 != unsafe_v2:
    raise SystemExit("proposed and native unsafe v2 workflow bytes differ")
PY
v1_program_hash="$(sha256sum "$v1_workflow" | awk '{print $1}')"
v2_program_hash="$(sha256sum "$v2_workflow" | awk '{print $1}')"
compatible_v2_workflow_hash="$(sha256sum "$compatible_v2_workflow" | awk '{print $1}')"
unsafe_v2_workflow_hash="$(sha256sum "$unsafe_v2_workflow" | awk '{print $1}')"

food_root="typescript/end-to-end-applications/food-ordering"
v1_app="$v1_tree/$food_root/app"
v2_app="$v2_tree/$food_root/app"
compatible_v2_app="$compatible_v2_tree/$food_root/app"
unsafe_v2_app="$unsafe_v2_tree/$food_root/app"
native_v1_app="$native_v1_tree/$food_root/app"
native_v2_app="$native_v2_tree/$food_root/app"
native_compatible_v2_app="$native_compatible_v2_tree/$food_root/app"
native_unsafe_v2_app="$native_unsafe_v2_tree/$food_root/app"
webui="$v1_tree/$food_root/webui"
cp "$v1_tree/LICENSE" "$v1_app/LICENSE.restate-examples"
cp "$v2_tree/LICENSE" "$v2_app/LICENSE.restate-examples"
cp "$compatible_v2_tree/LICENSE" "$compatible_v2_app/LICENSE.restate-examples"
cp "$unsafe_v2_tree/LICENSE" "$unsafe_v2_app/LICENSE.restate-examples"
cp "$native_v1_tree/LICENSE" "$native_v1_app/LICENSE.restate-examples"
cp "$native_v2_tree/LICENSE" "$native_v2_app/LICENSE.restate-examples"
cp "$native_compatible_v2_tree/LICENSE" "$native_compatible_v2_app/LICENSE.restate-examples"
cp "$native_unsafe_v2_tree/LICENSE" "$native_unsafe_v2_app/LICENSE.restate-examples"
cp "$v1_tree/LICENSE" "$webui/LICENSE.restate-examples"

v1_completion_client="$v1_app/src/order-app/clients/completion_client.ts"
compatible_v2_completion_client="$compatible_v2_app/src/order-app/clients/completion_client.ts"
unsafe_v2_completion_client="$unsafe_v2_app/src/order-app/clients/completion_client.ts"
native_v1_completion_client="$native_v1_app/src/order-app/clients/completion_client.ts"
native_compatible_v2_completion_client="$native_compatible_v2_app/src/order-app/clients/completion_client.ts"
native_unsafe_v2_completion_client="$native_unsafe_v2_app/src/order-app/clients/completion_client.ts"
python3 - \
  "$v1_completion_client" "$compatible_v2_completion_client" "$unsafe_v2_completion_client" \
  "$native_v1_completion_client" "$native_compatible_v2_completion_client" \
  "$native_unsafe_v2_completion_client" <<'PY'
from pathlib import Path
import sys

proposed_v1 = Path(sys.argv[1]).read_text()
proposed_compatible_v2 = Path(sys.argv[2]).read_text()
proposed_unsafe_v2 = Path(sys.argv[3]).read_text()
native_v1 = Path(sys.argv[4]).read_text()
native_compatible_v2 = Path(sys.argv[5]).read_text()
native_unsafe_v2 = Path(sys.argv[6]).read_text()

old_signature = '  async complete(id: string): Promise<boolean> {'
new_signature = '  async complete(id: string, closureVersion: "compatible-v2"): Promise<boolean> {'
proposed_old_body = '      JSON.stringify({ order_id: id, status: "DELIVERED" }),'
proposed_new_body = '''      JSON.stringify({
        order_id: id,
        status: "DELIVERED",
        closure_version: closureVersion,
      }),'''
native_old_body = '    const body = Buffer.from(JSON.stringify({ order_id: id, status: "DELIVERED" }), "utf8");'
native_new_body = '''    const body = Buffer.from(
      JSON.stringify({
        order_id: id,
        status: "DELIVERED",
        closure_version: closureVersion,
      }),
      "utf8",
    );'''
unsafe_signature = '  async complete(id: string, closureVersion: "unsafe-v2"): Promise<boolean> {'
proposed_unsafe_body = '''      JSON.stringify({
        order_id: id,
        status: "DELIVERED",
        closure_version: closureVersion,
      }),'''
native_unsafe_body = '''    const body = Buffer.from(
      JSON.stringify({
        order_id: id,
        status: "DELIVERED",
        closure_version: closureVersion,
      }),
      "utf8",
    );'''

def exact_replacement(base, target, old_body, new_body, label):
    if base.count(old_signature) != 1 or base.count(old_body) != 1:
        raise SystemExit(f"{label} v1 completion client does not contain the frozen closure contract")
    expected = base.replace(old_signature, new_signature, 1).replace(old_body, new_body, 1)
    if target != expected:
        raise SystemExit(f"{label} compatible completion client has changes outside the exact closure contract")

exact_replacement(
    proposed_v1, proposed_compatible_v2,
    proposed_old_body, proposed_new_body, "proposed",
)
exact_replacement(
    native_v1, native_compatible_v2,
    native_old_body, native_new_body, "native",
)

def exact_unsafe_replacement(base, target, old_body, new_body, label):
    if base.count(old_signature) != 1 or base.count(old_body) != 1:
        raise SystemExit(f"{label} v1 completion client does not contain the frozen unsafe contract")
    expected = base.replace(old_signature, unsafe_signature, 1).replace(old_body, new_body, 1)
    if target != expected:
        raise SystemExit(f"{label} unsafe completion client has changes outside the exact closure contract")

exact_unsafe_replacement(
    proposed_v1, proposed_unsafe_v2,
    proposed_old_body, proposed_unsafe_body, "proposed",
)
exact_unsafe_replacement(
    native_v1, native_unsafe_v2,
    native_old_body, native_unsafe_body, "native",
)
PY

generate_lock() {
  local image=$1 directory=$2
  docker run --rm --user "$(id -u):$(id -g)" \
    --env HOME=/tmp --env npm_config_cache=/tmp/npm-cache \
    --volume "$directory:/workspace" --workdir /workspace \
    "$image" npm install --package-lock-only --ignore-scripts --no-audit --no-fund >/dev/null
}

# Resolve dependencies once, with a pinned npm runtime, and use the exact same
# lock for every worker variant.
generate_lock "$NODE_IMAGE" "$v1_app"
cp "$v1_app/package-lock.json" "$v2_app/package-lock.json"
cp "$v1_app/package-lock.json" "$compatible_v2_app/package-lock.json"
cp "$v1_app/package-lock.json" "$unsafe_v2_app/package-lock.json"
cp "$v1_app/package-lock.json" "$native_v1_app/package-lock.json"
cp "$v1_app/package-lock.json" "$native_v2_app/package-lock.json"
cp "$v1_app/package-lock.json" "$native_compatible_v2_app/package-lock.json"
cp "$v1_app/package-lock.json" "$native_unsafe_v2_app/package-lock.json"
generate_lock "$WEBUI_NODE_IMAGE" "$webui"

# Git worktrees and generated locks otherwise carry wall-clock mtimes into the
# Docker context. Normalize them so rebuilding the same pinned inputs reaches
# the same BuildKit cache keys and image content.
python3 - \
  "$v1_app" "$v2_app" "$compatible_v2_app" "$unsafe_v2_app" \
  "$native_v1_app" "$native_v2_app" "$native_compatible_v2_app" \
  "$native_unsafe_v2_app" "$webui" <<'PY'
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
compatible_v2_context_hash="$(context_hash "$compatible_v2_app")"
unsafe_v2_context_hash="$(context_hash "$unsafe_v2_app")"
native_v1_context_hash="$(context_hash "$native_v1_app")"
native_v2_context_hash="$(context_hash "$native_v2_app")"
native_compatible_v2_context_hash="$(context_hash "$native_compatible_v2_app")"
native_unsafe_v2_context_hash="$(context_hash "$native_unsafe_v2_app")"
restaurant_context_hash="$({
  tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
    -cf - -C "$v1_app" package.json package-lock.json LICENSE.restate-examples src/restaurant
} | sha256sum | awk '{print $1}')"
app_lock_hash="$(sha256sum "$v1_app/package-lock.json" | awk '{print $1}')"
webui_lock_hash="$(sha256sum "$webui/package-lock.json" | awk '{print $1}')"
payment_patch_hash="$(sha256sum "$script_dir/patches/payment-control.patch" | awk '{print $1}')"
completion_patch_hash="$(sha256sum "$script_dir/patches/completion-control.patch" | awk '{print $1}')"
v2_patch_hash="$(sha256sum "$script_dir/patches/remove-payment-v2.patch" | awk '{print $1}')"
provider_direct_patch_hash="$(sha256sum "$script_dir/patches/provider-direct.patch" | awk '{print $1}')"
compatible_v2_patch_hash="$(sha256sum "$script_dir/patches/compatible-completion-v2.patch" | awk '{print $1}')"
native_compatible_v2_patch_hash="$(sha256sum "$script_dir/patches/compatible-completion-direct-v2.patch" | awk '{print $1}')"
unsafe_v2_patch_hash="$(sha256sum "$script_dir/patches/unsafe-completion-v2.patch" | awk '{print $1}')"
native_unsafe_v2_patch_hash="$(sha256sum "$script_dir/patches/unsafe-completion-direct-v2.patch" | awk '{print $1}')"
native_payment_client_hash="$(sha256sum "$native_v1_app/src/order-app/clients/payment_client.ts" | awk '{print $1}')"
native_completion_client_hash="$(sha256sum "$native_v1_app/src/order-app/clients/completion_client.ts" | awk '{print $1}')"
compatible_v2_completion_client_hash="$(sha256sum "$compatible_v2_completion_client" | awk '{print $1}')"
native_compatible_v2_completion_client_hash="$(sha256sum "$native_compatible_v2_completion_client" | awk '{print $1}')"
unsafe_v2_completion_client_hash="$(sha256sum "$unsafe_v2_completion_client" | awk '{print $1}')"
native_unsafe_v2_completion_client_hash="$(sha256sum "$native_unsafe_v2_completion_client" | awk '{print $1}')"

image_prefix="${RESTATE_HARNESS_IMAGE_PREFIX:-safe-change-restate}"
short_commit="${RESTATE_EXAMPLES_COMMIT:0:12}"
order_v1_tag="$image_prefix-order-v1:$short_commit"
order_v2_tag="$image_prefix-order-v2:$short_commit"
order_compatible_v2_tag="$image_prefix-order-compatible-v2:$short_commit"
order_unsafe_v2_tag="$image_prefix-order-unsafe-v2:$short_commit"
native_order_v1_tag="$image_prefix-native-order-v1:$short_commit"
native_order_v2_tag="$image_prefix-native-order-v2:$short_commit"
native_order_compatible_v2_tag="$image_prefix-native-order-compatible-v2:$short_commit"
native_order_unsafe_v2_tag="$image_prefix-native-order-unsafe-v2:$short_commit"
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
  --build-arg "NODE_IMAGE=$NODE_IMAGE" \
  --build-arg "UPSTREAM_COMMIT=$RESTATE_EXAMPLES_COMMIT" \
  --build-arg WORKER_VARIANT=compatible-v2 \
  --file "$script_dir/Dockerfile.worker" --tag "$order_compatible_v2_tag" "$compatible_v2_app" >/dev/null
docker build --quiet --pull \
  --build-arg "NODE_IMAGE=$NODE_IMAGE" \
  --build-arg "UPSTREAM_COMMIT=$RESTATE_EXAMPLES_COMMIT" \
  --build-arg WORKER_VARIANT=unsafe-v2 \
  --file "$script_dir/Dockerfile.worker" --tag "$order_unsafe_v2_tag" "$unsafe_v2_app" >/dev/null
docker build --quiet --pull \
  --build-arg "NODE_IMAGE=$NODE_IMAGE" \
  --build-arg "UPSTREAM_COMMIT=$RESTATE_EXAMPLES_COMMIT" \
  --build-arg WORKER_VARIANT=native-v1 \
  --file "$script_dir/Dockerfile.worker" --tag "$native_order_v1_tag" "$native_v1_app" >/dev/null
docker build --quiet --pull \
  --build-arg "NODE_IMAGE=$NODE_IMAGE" \
  --build-arg "UPSTREAM_COMMIT=$RESTATE_EXAMPLES_COMMIT" \
  --build-arg WORKER_VARIANT=native-v2 \
  --file "$script_dir/Dockerfile.worker" --tag "$native_order_v2_tag" "$native_v2_app" >/dev/null
docker build --quiet --pull \
  --build-arg "NODE_IMAGE=$NODE_IMAGE" \
  --build-arg "UPSTREAM_COMMIT=$RESTATE_EXAMPLES_COMMIT" \
  --build-arg WORKER_VARIANT=native-compatible-v2 \
  --file "$script_dir/Dockerfile.worker" --tag "$native_order_compatible_v2_tag" "$native_compatible_v2_app" >/dev/null
docker build --quiet --pull \
  --build-arg "NODE_IMAGE=$NODE_IMAGE" \
  --build-arg "UPSTREAM_COMMIT=$RESTATE_EXAMPLES_COMMIT" \
  --build-arg WORKER_VARIANT=native-unsafe-v2 \
  --file "$script_dir/Dockerfile.worker" --tag "$native_order_unsafe_v2_tag" "$native_unsafe_v2_app" >/dev/null
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
order_compatible_v2_image="$(image_id "$order_compatible_v2_tag")"
order_unsafe_v2_image="$(image_id "$order_unsafe_v2_tag")"
native_order_v1_image="$(image_id "$native_order_v1_tag")"
native_order_v2_image="$(image_id "$native_order_v2_tag")"
native_order_compatible_v2_image="$(image_id "$native_order_compatible_v2_tag")"
native_order_unsafe_v2_image="$(image_id "$native_order_unsafe_v2_tag")"
webui_image="$(image_id "$webui_tag")"
restaurant_image="$(image_id "$restaurant_tag")"
runtime_image="$(image_id "$runtime_tag")"
if [[ "$order_v1_image" == "$order_v2_image" ]]; then
  echo "v1 and v2 unexpectedly produced the same image" >&2
  exit 1
fi
if [[ "$native_order_v1_image" == "$native_order_v2_image" ]]; then
  echo "native v1 and v2 unexpectedly produced the same image" >&2
  exit 1
fi
if [[ "$order_compatible_v2_image" == "$order_v1_image" ||
      "$order_compatible_v2_image" == "$order_v2_image" ]]; then
  echo "proposed compatible v2 did not produce a distinct immutable image" >&2
  exit 1
fi
if [[ "$native_order_compatible_v2_image" == "$native_order_v1_image" ||
      "$native_order_compatible_v2_image" == "$native_order_v2_image" ]]; then
  echo "native compatible v2 did not produce a distinct immutable image" >&2
  exit 1
fi
if [[ "$order_compatible_v2_image" == "$native_order_compatible_v2_image" ]]; then
  echo "proposed and native compatible adapters unexpectedly produced the same image" >&2
  exit 1
fi
if [[ "$order_unsafe_v2_image" == "$order_v1_image" ||
      "$order_unsafe_v2_image" == "$order_v2_image" ||
      "$order_unsafe_v2_image" == "$order_compatible_v2_image" ]]; then
  echo "proposed unsafe v2 did not produce a distinct immutable image" >&2
  exit 1
fi
if [[ "$native_order_unsafe_v2_image" == "$native_order_v1_image" ||
      "$native_order_unsafe_v2_image" == "$native_order_v2_image" ||
      "$native_order_unsafe_v2_image" == "$native_order_compatible_v2_image" ]]; then
  echo "native unsafe v2 did not produce a distinct immutable image" >&2
  exit 1
fi
if [[ "$order_unsafe_v2_image" == "$native_order_unsafe_v2_image" ]]; then
  echo "proposed and native unsafe adapters unexpectedly produced the same image" >&2
  exit 1
fi
native_v1_compiled_hash="$(
  docker run --rm --entrypoint sha256sum "$native_order_v1_image" \
    /usr/src/app/dist/order-app/order_workflow/impl.js | awk '{print $1}'
)"
native_v2_compiled_hash="$(
  docker run --rm --entrypoint sha256sum "$native_order_v2_image" \
    /usr/src/app/dist/order-app/order_workflow/impl.js | awk '{print $1}'
)"
compatible_v2_compiled_hash="$(
  docker run --rm --entrypoint sha256sum "$order_compatible_v2_image" \
    /usr/src/app/dist/order-app/order_workflow/impl.js | awk '{print $1}'
)"
native_compatible_v2_compiled_hash="$(
  docker run --rm --entrypoint sha256sum "$native_order_compatible_v2_image" \
    /usr/src/app/dist/order-app/order_workflow/impl.js | awk '{print $1}'
)"
unsafe_v2_compiled_hash="$(
  docker run --rm --entrypoint sha256sum "$order_unsafe_v2_image" \
    /usr/src/app/dist/order-app/order_workflow/impl.js | awk '{print $1}'
)"
native_unsafe_v2_compiled_hash="$(
  docker run --rm --entrypoint sha256sum "$native_order_unsafe_v2_image" \
    /usr/src/app/dist/order-app/order_workflow/impl.js | awk '{print $1}'
)"
if [[ "$compatible_v2_compiled_hash" != "$native_compatible_v2_compiled_hash" ]]; then
  echo "proposed and native compatible v2 compiled workflow bytes differ" >&2
  exit 1
fi
if [[ "$unsafe_v2_compiled_hash" != "$native_unsafe_v2_compiled_hash" ]]; then
  echo "proposed and native unsafe v2 compiled workflow bytes differ" >&2
  exit 1
fi
docker run --rm --entrypoint sh "$order_compatible_v2_image" -ec '
  grep -q compatible-v2 /usr/src/app/dist/order-app/order_workflow/impl.js
  grep -q closure_version /usr/src/app/dist/order-app/clients/completion_client.js
  grep -q SAFE_CHANGE_CONTROL_URL /usr/src/app/dist/order-app/clients/completion_client.js
'
docker run --rm --entrypoint sh "$native_order_compatible_v2_image" -ec '
  grep -q compatible-v2 /usr/src/app/dist/order-app/order_workflow/impl.js
  grep -q closure_version /usr/src/app/dist/order-app/clients/completion_client.js
  grep -q COMPLETION_ENDPOINT /usr/src/app/dist/order-app/clients/completion_client.js
  ! grep -q SAFE_CHANGE_CONTROL_URL /usr/src/app/dist/order-app/clients/completion_client.js
'
docker run --rm --entrypoint sh "$order_unsafe_v2_image" -ec '
  grep -q unsafe-v2 /usr/src/app/dist/order-app/order_workflow/impl.js
  grep -q closure_version /usr/src/app/dist/order-app/clients/completion_client.js
  grep -q SAFE_CHANGE_CONTROL_URL /usr/src/app/dist/order-app/clients/completion_client.js
'
docker run --rm --entrypoint sh "$native_order_unsafe_v2_image" -ec '
  grep -q unsafe-v2 /usr/src/app/dist/order-app/order_workflow/impl.js
  grep -q closure_version /usr/src/app/dist/order-app/clients/completion_client.js
  grep -q COMPLETION_ENDPOINT /usr/src/app/dist/order-app/clients/completion_client.js
  ! grep -q SAFE_CHANGE_CONTROL_URL /usr/src/app/dist/order-app/clients/completion_client.js
'
docker run --rm --entrypoint sh "$native_order_v1_image" -ec '
  grep -q PAYMENT_ENDPOINT /usr/src/app/dist/order-app/clients/payment_client.js
  grep -q COMPLETION_ENDPOINT /usr/src/app/dist/order-app/clients/completion_client.js
  ! grep -q SAFE_CHANGE_CONTROL_URL /usr/src/app/dist/order-app/clients/payment_client.js
'
docker run --rm --entrypoint sh "$restaurant_image" -ec '
  test -f /app/server.js
  test ! -e /usr/src/app
  test ! -e /app/dist/order-app
'

temporary_env="$output_env.next"
{
  printf 'ORDER_V1_IMAGE=%q\n' "$order_v1_image"
  printf 'ORDER_V2_IMAGE=%q\n' "$order_v2_image"
  printf 'ORDER_COMPATIBLE_V2_IMAGE=%q\n' "$order_compatible_v2_image"
  printf 'ORDER_UNSAFE_V2_IMAGE=%q\n' "$order_unsafe_v2_image"
  printf 'NATIVE_ORDER_V1_IMAGE=%q\n' "$native_order_v1_image"
  printf 'NATIVE_ORDER_V2_IMAGE=%q\n' "$native_order_v2_image"
  printf 'NATIVE_ORDER_COMPATIBLE_V2_IMAGE=%q\n' "$native_order_compatible_v2_image"
  printf 'NATIVE_ORDER_UNSAFE_V2_IMAGE=%q\n' "$native_order_unsafe_v2_image"
  printf 'WEBUI_IMAGE=%q\n' "$webui_image"
  printf 'RESTAURANT_IMAGE=%q\n' "$restaurant_image"
  printf 'SAFE_CHANGE_RUNTIME_IMAGE=%q\n' "$runtime_image"
  printf 'UPSTREAM_ARCHIVE_SHA256=%q\n' "$archive_hash"
  printf 'APP_LOCK_SHA256=%q\n' "$app_lock_hash"
  printf 'WEBUI_LOCK_SHA256=%q\n' "$webui_lock_hash"
  printf 'PAYMENT_PATCH_SHA256=%q\n' "$payment_patch_hash"
  printf 'COMPLETION_PATCH_SHA256=%q\n' "$completion_patch_hash"
  printf 'V2_PATCH_SHA256=%q\n' "$v2_patch_hash"
  printf 'PROVIDER_DIRECT_PATCH_SHA256=%q\n' "$provider_direct_patch_hash"
  printf 'COMPATIBLE_V2_PATCH_SHA256=%q\n' "$compatible_v2_patch_hash"
  printf 'NATIVE_COMPATIBLE_V2_PATCH_SHA256=%q\n' "$native_compatible_v2_patch_hash"
  printf 'UNSAFE_V2_PATCH_SHA256=%q\n' "$unsafe_v2_patch_hash"
  printf 'NATIVE_UNSAFE_V2_PATCH_SHA256=%q\n' "$native_unsafe_v2_patch_hash"
  printf 'V1_CONTEXT_SHA256=%q\n' "$v1_context_hash"
  printf 'V2_CONTEXT_SHA256=%q\n' "$v2_context_hash"
  printf 'COMPATIBLE_V2_CONTEXT_SHA256=%q\n' "$compatible_v2_context_hash"
  printf 'UNSAFE_V2_CONTEXT_SHA256=%q\n' "$unsafe_v2_context_hash"
  printf 'NATIVE_V1_CONTEXT_SHA256=%q\n' "$native_v1_context_hash"
  printf 'NATIVE_V2_CONTEXT_SHA256=%q\n' "$native_v2_context_hash"
  printf 'NATIVE_COMPATIBLE_V2_CONTEXT_SHA256=%q\n' "$native_compatible_v2_context_hash"
  printf 'NATIVE_UNSAFE_V2_CONTEXT_SHA256=%q\n' "$native_unsafe_v2_context_hash"
  printf 'V1_PROGRAM_SHA256=%q\n' "$v1_program_hash"
  printf 'V2_PROGRAM_SHA256=%q\n' "$v2_program_hash"
  printf 'COMPATIBLE_V2_WORKFLOW_SHA256=%q\n' "$compatible_v2_workflow_hash"
  printf 'UNSAFE_V2_WORKFLOW_SHA256=%q\n' "$unsafe_v2_workflow_hash"
  printf 'COMPATIBLE_V2_COMPLETION_CLIENT_SHA256=%q\n' "$compatible_v2_completion_client_hash"
  printf 'NATIVE_COMPATIBLE_V2_COMPLETION_CLIENT_SHA256=%q\n' "$native_compatible_v2_completion_client_hash"
  printf 'UNSAFE_V2_COMPLETION_CLIENT_SHA256=%q\n' "$unsafe_v2_completion_client_hash"
  printf 'NATIVE_UNSAFE_V2_COMPLETION_CLIENT_SHA256=%q\n' "$native_unsafe_v2_completion_client_hash"
  printf 'COMPATIBLE_V2_COMPILED_SHA256=%q\n' "$compatible_v2_compiled_hash"
  printf 'NATIVE_COMPATIBLE_V2_COMPILED_SHA256=%q\n' "$native_compatible_v2_compiled_hash"
  printf 'UNSAFE_V2_COMPILED_SHA256=%q\n' "$unsafe_v2_compiled_hash"
  printf 'NATIVE_UNSAFE_V2_COMPILED_SHA256=%q\n' "$native_unsafe_v2_compiled_hash"
  printf 'NATIVE_PAYMENT_CLIENT_SHA256=%q\n' "$native_payment_client_hash"
  printf 'NATIVE_COMPLETION_CLIENT_SHA256=%q\n' "$native_completion_client_hash"
  printf 'NATIVE_V1_COMPILED_SHA256=%q\n' "$native_v1_compiled_hash"
  printf 'NATIVE_V2_COMPILED_SHA256=%q\n' "$native_v2_compiled_hash"
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
  compatible v2: $order_compatible_v2_image ($compatible_v2_context_hash)
  unsafe v2: $order_unsafe_v2_image ($unsafe_v2_context_hash)
  native v1: $native_order_v1_image ($native_v1_context_hash)
  native v2: $native_order_v2_image ($native_v2_context_hash)
  native compatible v2: $native_order_compatible_v2_image ($native_compatible_v2_context_hash)
  native unsafe v2: $native_order_unsafe_v2_image ($native_unsafe_v2_context_hash)
  program v1: $v1_program_hash
  program v2: $v2_program_hash
  compatible workflow: $compatible_v2_workflow_hash
  compatible compiled: $compatible_v2_compiled_hash
  unsafe workflow: $unsafe_v2_workflow_hash
  unsafe compiled: $unsafe_v2_compiled_hash
  webui:     $webui_image
  restaurant:$restaurant_image ($restaurant_context_hash)
  runtime:   $runtime_image
  metadata:  $output_env
  app lock:  $app_lock_file ($app_lock_hash)
  web lock:  $webui_lock_file ($webui_lock_hash)
EOF
