#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for command in bash jq docker; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "missing required command: $command" >&2
    exit 1
  fi
done
docker compose version >/dev/null

adapters="$script_dir/examples/config/adapters.json"
jq -e '
  (keys | sort) == ["adapters", "schema"] and
  .schema == 1 and (.adapters | length) == 1 and
  (.adapters[0] | keys | sort) == ["domain", "kinds", "token_file"] and
  .adapters[0].domain == "example-provider" and
  .adapters[0].token_file == "/adapter-token/token" and
  .adapters[0].kinds == ["submit-v1", "submit-v2"]
' "$adapters" >/dev/null

for version in v1 v2; do
  route="$script_dir/examples/config/routes.$version.json"
  if [[ "$version" == v1 ]]; then
    requirement="$script_dir/examples/requirements/initial.json"
  else
    requirement="$script_dir/examples/requirements/upgrade-v2.json"
  fi
  kind="submit-$version"
  target="http://provider-adapter-$version:8080/$version/submit"
  query_target="$target/query"

  jq -e --arg kind "$kind" --arg target "$target" '
    (keys | sort) == ["routes", "schema"] and
    .schema == 1 and (.routes | length) == 1 and
    (.routes[0] | keys | sort) == ["content_types", "kind", "method", "name", "url"] and
    .routes[0] == {
      name:"submit", kind:$kind, method:"POST", url:$target,
      content_types:["application/json"]
    }
  ' "$route" >/dev/null

  jq -e --arg kind "$kind" --arg target "$target" --arg query_target "$query_target" '
    (keys | sort) == ["capacities", "id", "kinds", "results"] and
    (.kinds | keys) == [$kind] and
    (.kinds[$kind] | keys | sort) == [
      "costs", "method", "produces", "query_classifier", "query_method",
      "query_target", "queryable", "response_classifier", "retry_safe", "target"
    ] and
    .kinds[$kind].retry_safe == false and
    .kinds[$kind].queryable == true and
    .kinds[$kind].target == $target and
    .kinds[$kind].method == "POST" and
    .kinds[$kind].response_classifier == "operation-receipt-v1" and
    .kinds[$kind].query_target == $query_target and
    .kinds[$kind].query_method == "POST" and
    .kinds[$kind].query_classifier == "operation-observation-v1"
  ' "$requirement" >/dev/null
done

rendered="$(mktemp)"
trap 'rm -f -- "$rendered"' EXIT
docker compose \
  --env-file "$script_dir/.env.example" \
  -f "$script_dir/compose.yaml" \
  --profile tools config --format json > "$rendered"

jq -e '
  (.services | keys | sort) == ["control", "effect-proxy", "safe-change"] and
  (.networks | keys | sort) == ["control", "provider", "workload"] and
  all(.networks[]; .internal == true) and
  all(.services[];
    .read_only == true and .init == true and
    .cap_drop == ["ALL"] and
    (.security_opt | index("no-new-privileges:true")) != null and
    ((.ports // []) | length) == 0 and
    (.user | test("^[0-9]+:[0-9]+$"))
  ) and
  (.services.control.networks | keys | sort) == ["control", "provider"] and
  (.services["effect-proxy"].networks | keys | sort) == ["control", "workload"] and
  (.services["safe-change"].networks | keys) == ["control"] and
  .services["safe-change"].profiles == ["tools"] and
  ([.services.control.volumes[].target] | sort) ==
    ["/adapter-token", "/admin-token", "/anchor", "/config", "/history"] and
  ([.services["effect-proxy"].volumes[].target] | sort) ==
    ["/adapter-token", "/config"] and
  ([.services["safe-change"].volumes[].target] | sort) ==
    ["/admin-token", "/certificates", "/requirements"] and
  ([.services.control.volumes[].source] | unique | length) == 5 and
  all(.services[].volumes[]; .type == "bind" and .bind.create_host_path == false)
' "$rendered" >/dev/null

echo "starter static checks passed"
