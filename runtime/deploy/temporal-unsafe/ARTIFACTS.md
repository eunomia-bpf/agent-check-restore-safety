# Temporal unsafe-edit evidence contract

`run-unsafe-case.sh` writes one case directory with a flat `results/`
directory plus the recursively copied `results/build-evidence/` directory.
The copied build evidence is the sibling `*-evidence` directory published with
the frozen build environment; its own recursive `SHA256SUMS` remains intact.
The case-level `SHA256SUMS` covers every regular file below `results/` except
itself.  `observed.json` is a convenience summary and is never an oracle.

The proposed and native lanes use the same source image, target image,
workflow inputs, and Operation identities.  `payment_token` must equal
`order_id`.  The fixed Temporal signal identity is
`safe-change-temporal-unsafe-harness`.

## Global artifacts

Every case contains these basenames:

```text
ARTIFACTS.md
build.env
frozen-inputs.env
versions.env
runner.sh
runner.sha256
compose-base.yaml
compose-overlay.yaml
requirement-source.json
requirement-target.json
source-adapter.json
target-adapter.json
git-revision.txt
git-status.txt
compose-environment.json
temporal-image-inspect.json
v1-image-inspect.json
target-image-inspect.json
starter-image-inspect.json
effects-image-inspect.json
adapter-image-inspect.json
control-image-inspect.json
binary-verification.env
run-metadata.json
observed.json
exit-status.txt
SHA256SUMS
```

`compose-environment.json` is schema 1 and records that ambient
`COMPOSE_FILE`, `COMPOSE_PROFILES`, `COMPOSE_PROJECT_NAME`,
`COMPOSE_PATH_SEPARATOR`, `COMPOSE_ENV_FILES`, and
`COMPOSE_DISABLE_ENV_FILE` were empty at entry.  The runner unsets them and
passes a project name and both Compose files explicitly.

`run-metadata.json` is schema 1 and binds the method, clean/main project names,
workflow and order IDs, expected Operation IDs, immutable images, build
environment digest, runner digest, and every captured static input digest.
`observed.json` is schema 1 and contains only a non-oracle execution summary.

## Project and Docker-event contract

Clean and main use distinct project names, state directories, networks, and
live Docker event streams.  Before any Compose service is created, the runner:

1. starts `docker events` with both `type=container` and the exact
   project-label filter;
2. creates and removes one inert begin-sentinel container carrying
   `com.docker.compose.project=<project>`,
   `com.docker.compose.service=event-sentinel-begin`,
   `io.safe-change.event-sentinel=true`, and
   `io.safe-change.event-boundary=begin`;
3. waits until that container's `create` event is present in the live JSONL;
4. records listener readiness; and only then invokes Compose.

After the final container and network capture, while all runtime services still
exist, the runner creates and removes an equivalent end-sentinel with service
`event-sentinel-end` and boundary `end`, waits until its `create` event is in
the same live stream, then terminates and reaps the listener.  A zero listener
exit status and end timestamp are recorded.  Thus listener death cannot be
mistaken for target absence.

The sentinel ID, timestamps, and complete event stream use these basenames:

```text
clean-events-since-at.txt
clean-event-begin-sentinel-id.txt
clean-event-listener-ready-at.txt
clean-event-end-sentinel-id.txt
clean-event-listener-ended-at.txt
clean-event-listener-exit-status.txt
clean-docker-events.jsonl
main-events-since-at.txt
main-event-begin-sentinel-id.txt
main-event-listener-ready-at.txt
main-event-end-sentinel-id.txt
main-event-listener-ended-at.txt
main-event-listener-exit-status.txt
main-docker-events.jsonl
```

Each JSONL line is the unmodified official Docker container-event JSON.  The
begin sentinel `create` must precede every non-sentinel service `create` or
`start`, every such `create` or `start` must precede the end-sentinel `create`,
and the listener must exit cleanly only after the end sentinel was observed.
Health, exec, and other events are not chronology boundaries.  `worker-v2`
must have zero `create` or
`start` events in both projects.  In proposed main,
`worker-unsafe-v2` must also have zero `create` or `start` events.  In native
main, its first `create` and `start` occur after the recorded decision time and
after v1 removal.

## Clean phase

Common clean basenames are:

```text
clean-compose-config.yaml
clean-compose-all-profiles-config.yaml
clean-invocation.json
clean-start.json
clean-run-id.txt
clean-target-containers-before-decision.txt
clean-decision-at.txt
clean-target-workflow-pollers.json
clean-target-activity-pollers.json
clean-deployment-before-current.json
clean-target-version-before-current.json
clean-set-current-target.json
clean-deployment-target-current.json
clean-wait-history.json
clean-wait-describe.json
clean-wait-query.json
clean-payment-wait-stats.json
clean-completion-wait-stats.json
clean-payment-wait.history
clean-completion-wait.history
clean-signal.json
clean-final-history.json
clean-final-describe.json
clean-final-query.json
clean-target-version-final.json
clean-deployment-final.json
clean-payment-final-stats.json
clean-completion-final-stats.json
clean-payment-final.history
clean-completion-final.history
clean-target-container.json
clean-network-probes.json
clean-compose-ps.txt
clean-compose.log
clean-containers.json
clean-networks.json
```

`clean-compose-config.yaml` is the resolved config for the explicitly selected
runtime services.  `clean-compose-all-profiles-config.yaml` is the resolved
`--profile '*'` config and exposes the neutralized, unreachable base
`worker-v2` definition for audit.  The clean workflow is a real target-image
AutoUpgrade execution: it schedules `ChargePaymentV2`, commits `/v2/charge`,
waits, receives the fixed-identity signal, completes with closure
`unsafe-v2`, and commits `/v1/complete`.

Proposed clean additionally contains:

```text
clean-control-endpoint.json
clean-control-container.json
clean-certificate-target.json
clean-certificate-target-state.json
clean-certificate-target-verdict.json
clean-active-target.json
clean-control-after-activate.json
clean-control-history-after-activate.json
clean-final-control-state.json
clean-final-control-history.json
clean-runtime.history
clean-runtime.head
```

The Certificate verdict is produced independently by `cmd/check-certificate`.
The final State must show the target Requirement active and settled
`charge-v2` and `finish-v2` Operations, using one unit of approval while
producing both required results.

Native clean additionally contains `clean-native-absence.json`, a schema-1
record showing that no control or adapter container exists.

## Main phase

Common main basenames are:

```text
main-compose-config.yaml
main-compose-all-profiles-config.yaml
main-invocation.json
main-start.json
main-run-id.txt
main-source-workflow-pollers.json
main-source-activity-pollers.json
main-deployment-before-current.json
main-source-version-before-current.json
main-set-current-source.json
main-deployment-source-current.json
main-cut-history.json
main-cut-describe.json
main-cut-query.json
main-cut-deployment.json
main-cut-source-version.json
main-payment-cut-stats.json
main-completion-cut-stats.json
main-payment-cut.history
main-completion-cut.history
main-source-container-at-cut.json
main-target-containers-before-decision.txt
main-worker-v2-containers-before-decision.txt
main-containers-before-decision.json
main-networks-before-decision.json
main-network-probes.json
main-decision-requested-at.txt
main-decision-recorded-at.txt
main-history-after-decision.json
main-payment-after-decision-stats.json
main-completion-after-decision-stats.json
main-payment-after-decision.history
main-completion-after-decision.history
main-signal.json
main-final-history.json
main-final-describe.json
main-final-query.json
main-payment-final-stats.json
main-completion-final-stats.json
main-payment-final.history
main-completion-final.history
main-deployment-final.json
main-compose-ps.txt
main-compose.log
main-containers.json
main-networks.json
```

At the common cut, exactly one v1 payment is externally committed and the
same AutoUpgrade run is waiting for `complete`; no completion Operation or
target container exists.  The cut includes official workflow/activity
pollers, deployment/version descriptions, Workflow History, describe/query,
provider statistics and append-only records, container inspect, and network
inspect.

Proposed main additionally contains:

```text
main-control-endpoint.json
main-control-container.json
main-certificate-source.json
main-certificate-source-state.json
main-certificate-source-verdict.json
main-active-source.json
main-control-after-source-activate.json
main-control-history-after-source-activate.json
main-control-at-cut.json
main-control-history-at-cut.json
main-certificate-unsafe.json
main-certificate-unsafe-state.json
main-certificate-unsafe-verdict.json
main-control-after-refusal.json
main-control-history-after-refusal.json
main-final-source-container.json
main-final-source-version.json
main-final-control-state.json
main-final-control-history.json
main-runtime.history
main-runtime.head
main-proposed-target-absence.json
```

The target compile occurs while the target worker and target adapter have never
been created.  Its exact
decision is `impossible`, with witness reason
`no completion fits the remaining resources for delivered:1`.  Control State,
control API History, Temporal History, provider statistics, and append-only
provider records are byte-identical across the rejected compile.  The retained
v1 worker then completes under the still-active source Rule; official final
deployment evidence still names v1 current and no target version exists.

Native main additionally contains:

```text
main-native-absence.json
main-remove-source.txt
main-source-removed-inspect.json
main-source-removed-inspect.stderr
main-source-removed-inspect-status.txt
main-target-workflow-pollers.json
main-target-activity-pollers.json
main-target-version-before-current.json
main-set-current-target.json
main-deployment-target-current.json
main-target-container.json
main-target-version-final.json
```

Native removes v1, starts the same immutable target image, makes
`food-order-unsafe-v2` current, and only then signals the same run.  Temporal's
handwritten `GetVersion` branch replays the historical `ChargePayment` and the
target schedules only the future `CompleteOrder` with closure `unsafe-v2`.

## JSON schemas

All `*-history.json`, `*-describe.json`, `*-query.json`, deployment/version,
poller, signal, start, image/container/network inspect, provider statistics,
control State/History, Certificate, and Certificate-State files preserve the
official producer JSON without a runner-defined wrapper.  `*-network-probes.json`
is a schema-1 object with a `probes` array; each entry records phase, service,
URL, expected reachability, and exit status.  `*-native-absence.json` and
`main-proposed-target-absence.json` are schema-1 objects containing exact
service names and empty Compose container-ID arrays.  No checker imports
`runner.sh` or trusts `observed.json` to reconstruct the verdict.
