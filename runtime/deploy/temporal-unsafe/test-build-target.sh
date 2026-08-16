#!/usr/bin/env bash
set -Eeuo pipefail

export LC_ALL=C

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
test_dir="$(mktemp -d /tmp/safe-change-temporal-unsafe-source-test.XXXXXX)"
cleanup() {
  case "$test_dir" in
    /tmp/safe-change-temporal-unsafe-source-test.*) find "$test_dir" -depth -delete 2>/dev/null || true ;;
    *) echo "refusing to clean unexpected test directory: $test_dir" >&2 ;;
  esac
}
trap cleanup EXIT

output_env="$test_dir/build.env"
TEMPORAL_UNSAFE_SOURCE_ONLY=1 "$script_dir/build-target.sh" "$output_env"

# shellcheck source=/dev/null
source "$output_env"
if [[ "$BUILD_MODE" != source-only || "$SOURCE_TESTS_PASSED" != true ]]; then
  echo "source-only target build did not report successful source tests" >&2
  exit 1
fi
if [[ "$FROZEN_BASE_SOURCE_SHA256" != 877a7a5b71b24e3dc309af5cd23bebe77c40dab6b8aec659ef929f1dc771aade ]]; then
  echo "source-only target build used an unexpected frozen base" >&2
  exit 1
fi

evidence_dir="$test_dir/build-evidence"
if [[ ! -d "$evidence_dir/generated-app" || -e "$evidence_dir/image-inspect.json" ]]; then
  echo "source-only evidence has an invalid file set" >&2
  exit 1
fi
if [[ "$(sha256sum -- "$evidence_dir/generated-tree.manifest" | awk '{print $1}')" != "$GENERATED_TREE_MANIFEST_SHA256" ]]; then
  echo "published generated-tree manifest digest differs from build.env" >&2
  exit 1
fi
(
  cd -- "$evidence_dir/generated-app"
  sha256sum --check --strict ../generated-tree.manifest >/dev/null
)
if [[ "$(sha256sum -- "$evidence_dir/patches.manifest" | awk '{print $1}')" != "$PATCH_SET_SHA256" ]]; then
  echo "published patch-set digest differs from build.env" >&2
  exit 1
fi
for patch_number in 0001 0002 0003; do
  variable="PATCH_${patch_number}_SHA256"
  patch="$(find "$evidence_dir/patches" -maxdepth 1 -type f -name "${patch_number}-*.patch" -print)"
  if [[ -z "$patch" || "$(sha256sum -- "$patch" | awk '{print $1}')" != "${!variable}" ]]; then
    echo "published patch $patch_number differs from build.env" >&2
    exit 1
  fi
done

variant="$evidence_dir/generated-app/internal/workerapp/variant_unsafe_v2.go"
for exact_line in \
  'const buildID = "food-order-unsafe-v2"' \
  $'\tunsafePaymentCapacityChangeID = "unsafe-payment-capacity-v1"' \
  $'\tw.RegisterActivityWithOptions(activities.PrepareFood, activityOptions(harness.PreparationActivityName))' \
  $'\tw.RegisterActivityWithOptions(activities.ScheduleDelivery, activityOptions(harness.DeliveryActivityName))' \
  $'\t\tOperationID: harness.OperationID(order.PaymentToken),' \
  $'\tif err := finishFoodOrder(ctx, order, status, "unsafe-v2"); err != nil {'; do
  if [[ "$(grep -Fxc -- "$exact_line" "$variant")" != 1 ]]; then
    echo "generated unsafe variant lost exact contract: $exact_line" >&2
    exit 1
  fi
done

echo "Temporal unsafe target source generation tests passed"
