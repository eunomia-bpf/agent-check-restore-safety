# Safe-change Compose starter

This directory is a deployment skeleton for putting real workload effects
behind the safe-change runtime. It deliberately contains no sample order,
payment, ingress, or provider service. Your workload and your versioned
provider adapter remain separate applications.

The three networks are authority boundaries:

```text
workload -> effect-proxy -> control -> versioned provider adapter
            workload+control  control+provider

operator -> one-shot safe-change CLI -> control
            control only
```

Nothing publishes a host port. The control service is the only History writer.
The effect proxy owns the adapter token and exact provider targets; workload
containers receive neither. The `safe-change` service exists only in the
`tools` profile and owns the admin token only for one command.

## Prepare the starter

From the repository root, build the current runtime image:

```sh
make runtime-image
cd runtime/deploy/starter
```

Create a private deployment directory and an environment file using the
current user's numeric identity:

```sh
umask 077
mkdir -p .local/{history,anchor,admin-token,adapter-token,config,requirements,certificates}
cp examples/config/*.json .local/config/
cp examples/config/routes.v1.json .local/config/routes.json
cp examples/requirements/*.json .local/requirements/
printf '%s\n' \
  'COMPOSE_PROJECT_NAME=safe-change' \
  'RUNTIME_IMAGE=safe-change-runtime:local' \
  'STARTER_DATA_DIR=./.local' \
  "SAFE_CHANGE_UID=$(id -u)" \
  "SAFE_CHANGE_GID=$(id -g)" > .env
chmod 700 .local .local/*
chmod 600 .env .local/config/* .local/requirements/*
./check.sh
```

For a shared deployment, use a unique Compose project name and pin
`RUNTIME_IMAGE` to an immutable digest. The control process creates separate
0600 admin and adapter tokens inside their host directories on first start.

## Supply a versioned provider adapter

Start the control plane first; this also creates the three internal networks:

```sh
docker compose up -d control
```

Your provider adapter is a separate service. Attach it to
`safe-change_provider` (or `<COMPOSE_PROJECT_NAME>_provider`) with the DNS alias
`provider-adapter-v1`. The checked examples bind the initial Operation to these
exact endpoints:

```text
POST http://provider-adapter-v1:8080/v1/submit
POST http://provider-adapter-v1:8080/v1/submit/query
```

The `provider` network is internal. If the adapter must call an Internet API,
attach only that adapter to a second egress-enabled network; never add egress
to `control`, `effect-proxy`, or the `provider` network itself.

The effect endpoint receives `Idempotency-Key` and `X-Operation-ID`. A settled
200 JSON response must implement `operation-receipt-v1`:

```json
{"schema":1,"operation_id":"<X-Operation-ID>","outcome":"succeeded","result_hash":"<64 lowercase hex>","remote_reference":"provider/object-id"}
```

The query endpoint receives the original body plus `X-Operation-ID` and
`X-Operation-Request-Hash`. It must return `operation-observation-v1`, echoing
both identities and reporting `succeeded`, `failed`, or `inconclusive`:

```json
{"schema":1,"operation_id":"<X-Operation-ID>","request_hash":"<X-Operation-Request-Hash>","outcome":"inconclusive","fact_hash":"","remote_reference":"provider/query-reference"}
```

For `succeeded` or `failed`, `fact_hash` must be a 64-character lowercase
SHA-256 digest of the adapter's durable external fact. Use the same fact digest
in the effect receipt and later query result. Keep this adapter version
available while any Operation bound to it is unresolved.

The examples intentionally set `retry_safe` to `false` and `queryable` to
`true`. Never change `retry_safe` to true merely because the HTTP method or
provider API looks idempotent. Set it only when the adapter guarantees that a
repeat with the same runtime identity cannot duplicate the external effect.

## Activate the initial Requirement

Plan first. The CLI independently checks the returned Certificate and writes
it with mode 0600:

```sh
docker compose --profile tools run --rm safe-change \
  plan -requirement /requirements/initial.json \
  -out /certificates/initial.json
```

Inspect the decision, History point, targets, and allowed kind. Apply the same
unchanged Certificate in a separate command:

```sh
docker compose --profile tools run --rm safe-change \
  apply -certificate /certificates/initial.json
docker compose up -d effect-proxy
```

Attach workload containers to `safe-change_workload`. A workload invokes the
named route, not a physical provider URL:

```http
POST /v1/effects/submit HTTP/1.1
Host: effect-proxy:8788
Content-Type: application/json
Idempotency-Key: record/2026-000042/submit

{"record_id":"2026-000042","value":4200}
```

Send exactly one of `Idempotency-Key` or `X-Safe-Change-Call-ID`. Its value must
be stable for one logical external action and must not be reused for different
bytes. Preserve the returned Operation ID for recovery.

## Change to provider adapter v2

1. Start the separate v2 adapter on the provider network with alias
   `provider-adapter-v2`. Do not remove v1 yet.
2. Plan and inspect the v2 Requirement against the current complete History.
3. Apply that exact Certificate.
4. Replace the proxy route atomically, then recreate only the proxy.

```sh
docker compose --profile tools run --rm safe-change \
  plan -requirement /requirements/upgrade-v2.json \
  -out /certificates/upgrade-v2.json
docker compose --profile tools run --rm safe-change \
  apply -certificate /certificates/upgrade-v2.json

cp .local/config/routes.v2.json .local/config/routes.json.next
chmod 600 .local/config/routes.json.next
mv .local/config/routes.json.next .local/config/routes.json
docker compose up -d --force-recreate --no-deps effect-proxy
```

An existing call identity is still resolved from its frozen Operation, so a
retry cannot reinterpret old work as v2. Keep each old adapter reachable until
`state` shows that all Operations bound to it are settled:

```sh
docker compose --profile tools run --rm safe-change state
docker compose --profile tools run --rm safe-change \
  recover -operation op-<64-lowercase-hex-digits>
```

For more routes, every route name must be unique; its kind, method, target, and
query contract must exactly match the active Requirement, and the kind must be
listed for the adapter credential in `adapters.json`.

## Cold backup and restore boundary

Quiesce callers and stop both runtime processes before copying History:

```sh
docker compose stop effect-proxy control
backup_dir=/path/to/encrypted-backup/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -m 700 "$backup_dir"
tar -C .local -czf "$backup_dir/runtime-data.tgz" \
  history config requirements certificates
docker compose start control effect-proxy
```

Back up the admin and adapter token directories only through your encrypted
secret store. Replicate `anchor/runtime.head` to a separately protected,
non-rollback store. Never restore the anchor together with an older History:
the retained anchor is what makes a History rollback fail closed. A restore is
acceptable only when the restored History head agrees with the independently
retained anchor.

## Current boundaries

- Run exactly one control writer. This starter has no HA, leader election, or
  shared-filesystem failover.
- The networks are security boundaries. Any workload admitted to `workload`
  can invoke configured route names. HTTP inside the networks has no TLS; add
  authenticated transport outside this starter before crossing a host or
  cluster boundary.
- History durably stores the allowed public request headers, exact request
  body, and provider result. Do not put secrets or unencrypted PII in them.
- Requests are limited to 1 MiB. Provider and query responses are limited to
  64 KiB. Streaming bodies and streaming responses are not supported.
- Routes are loaded at proxy start. A route change requires a proxy recreate.
- The example is one route and one kind per active Requirement. Extend it by
  preserving the same one-to-one route/Requirement binding.
