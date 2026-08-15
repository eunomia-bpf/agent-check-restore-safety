# Step 0013: isolate a real Codex process from payment

Date: 2026-08-15 UTC

## Outcome

A real logged-in Codex App Server ran inside a hardened Docker container and
issued one `protected_payment` dynamic-tool call. Codex and payment shared no
network. Docker's saved network state shows exactly Codex and control on the
agent network, exactly control and payment on the internal effects network, and
control as the sole member of both. A positive probe established that Codex
could reach control; later probes could reach payment by neither Docker name
nor its effects-network IP.

Payment durably committed one stable Operation and dropped the first response.
While the Codex callback remained pending, the complete control container
restarted over the same History and external head. The replacement retried the
same Operation, obtained the existing receipt, and returned it to Codex. A
third execution reused the receipt from History. Codex then completed the turn
with exactly `DONE`.

The observed totals were two remote deliveries, one durable payment commit,
one Codex tool call, one callback response, and one completed model turn.

## Reproduction

The retained live run used:

```sh
python3 -m adapter.codex_isolated_runtime_demo \
  --output-dir docs/tmp/bootstrap/step-0013-20260815T124944Z
```

The public explicit-account target is:

```sh
make runtime-codex-isolated-demo
```

It is deliberately excluded from ordinary tests. The retained evidence can be
checked without account access:

```sh
make runtime-codex-isolated-check
```

## Concrete boundaries

- Codex: real `codex-cli 0.147.0`, native binary SHA-256
  `cb0a15567e9a60a5820d54b0f6ae86d504dc3805c1eab21a47f70e3eb7b73a40`,
  model `gpt-5.6-sol`, provider `openai`, and the existing ChatGPT login.
- Container: read-only root filesystem and workspace, all Linux capabilities
  removed, `no-new-privileges`, numeric non-root UID/GID, private temporary
  Codex home, tmpfs, and no host Docker socket.
- Retained model turn: one ephemeral read-only thread, approval policy `never`,
  sandbox network access disabled, no custom model provider, MCP server, app, or
  plugin, and exactly one observed dynamic-tool item. No built-in-tool item
  occurs in the retained protocol; the executable is not claimed to lack them.
- Networks: Codex only on `*_agent`, payment only on internal `*_effects`, and
  control on both. The saved Docker network projection records the exact member
  sets and each network's `Internal` flag.
- Durability: payment state, control History, and the external History head
  lived in separate host bind mounts outside the Codex container.

The runner copied only `auth.json` into a private temporary directory. It
deleted that copy after Codex issued the tool call and before any payment, then
verified that Codex completed without recreating it and that the original file
was unchanged. The retained evidence contains no credential, bearer token, API
key, raw account telemetry, or host mount source. The exact runtime image and
all run containers and networks were removed after capture.

## Identity and failure

The run-specific identity was:

```text
run         = safe-change-codex-1496410-354c5121
requirement = codex-payment-isolated-v1/safe-change-codex-1496410-354c5121
effect_id   = codex-order-A-17
call_id     = protected_payment/v1/codex-order-A-17
operation   = op-9f20f3b6cf55834925b6ce5685cf6ffb80bb6397092e5f102e43d2bd7f2a7563
```

The run ID also appears in the exact request bytes, model prompt, Compose
project, and image tag. The stable Operation ID is derived separately from its
domain and call identity. This lets the checker reject evidence spliced across
runs without changing retry identity within one run.

The control process PID changed from `1496787` to `1498423`. History records
the Operation as `prepared`, generation-1 `dispatched`, `unknown`, generation-2
`dispatched`, then `succeeded`. The two generations have distinct dispatch
owners. The binary History ends at sequence 6 with hash:

```text
ac2d18d549441a6bc60e21756965accd848b91142512c1c6b207324f22114221
```

The payment durability file contains exactly one record for that Operation.
The recovered and reused outcomes contain identical receipt bytes and result
hashes; only the latter has `reused=true`.

## Independent checks

Before Rule activation, the runtime exported the complete Certificate input
State. The standalone Go checker accepted it at the empty History head and Rule
version 1. It imports none of the compiler, control, History, or gateway code.

After shutdown, a separate Python checker that imports no live-runner module:

1. derives the stable Operation identity and all run-specific bindings;
2. parses every binary `HST1` frame with duplicate-key rejection;
3. recomputes all six event hashes over the exact retained `data` bytes;
4. recomputes the external head checksum;
5. recomputes payment, gateway request, and result hashes;
6. joins the durable payment record with the receipt, final Operation, and
   History settlement;
7. checks the privacy-filtered 32-record App Server protocol for one real
   process, thread, turn, dynamic-tool call, callback, final `DONE`, and clean
   exit;
8. checks the minimal Docker projections, exact network members and flags, the
   successful control probe, and both failed direct-payment probes;
9. verifies that the replacement control container's Docker `StartedAt` lies
   strictly after the tool call and before its callback; and
10. verifies credential lifecycle and successful teardown return codes.

Its newly derived verdict is `independent-verdict.json`. Mutation tests alter
the binary History, inject a duplicate JSON key, and fabricate the runner's
payment summary; all are rejected.

## Retained evidence

| Evidence | Checked fact |
|---|---|
| `requirement.json`, `certificate.json`, `certificate-state.json` | exact pre-activation input and output |
| `checker-verdict.json` | standalone Certificate decision |
| `app-server.jsonl` | ordered, privacy-filtered real App Server protocol |
| `docker-inspect.json`, `docker-network-inspect.json` | hardened containers, exact networks and members |
| `network-probes.json`, `network-topology.json` | one reachable control path and two blocked payment paths |
| `credential-lifecycle.json` | temporary auth removed before effect; source unchanged |
| `first-outcome.json` | response loss left the Operation unknown |
| `recovered-outcome.json` | replacement control completed the Operation |
| `reused-outcome.json` | settled retry reused the recorded receipt |
| `payment.history`, `payment-stats.json` | two deliveries and one commit |
| `runtime.history`, `runtime.head`, `history.json` | raw History, external head, and API view |
| `control-after-restart-inspect.json` | different control process and callback ordering |
| `final-state.json` | one succeeded Operation at sequence 6 |
| `teardown.json`, `logs/` | successful cleanup and service output |
| `result.json` | runner summary cross-checked against raw evidence |
| `independent-verdict.json` | downstream independent replay verdict |

## Verification

The following gates passed for the retained run:

```sh
python3 -m unittest \
  adapter.test_docker_codex \
  adapter.test_codex_isolated_runtime_demo \
  adapter.test_check_codex_isolated_evidence

make runtime-verify
```

The verification includes Go build, race tests, vet, Python boundary and
mutation tests, a fresh standalone Certificate check, and independent replay of
the retained evidence. Docker Compose configuration validation, a credential
and privacy scan, and a post-run search for leftover containers, networks, and
images also passed.

## Honest boundary

The payment service is a purpose-built durable HTTP service rather than a bank
or Stripe deployment. Docker state and network probes are strong local
observations, not signed remote attestation. The host kernel, Docker daemon,
native Codex bundle, OpenAI service, bind mounts, and control credentials remain
trusted. Codex needs Internet access to reach its provider, although it cannot
join or address the payment network in this topology.

This run covers one fixed HTTP Operation contract. It does not yet compose the
same live Agent turn with a full QEMU VM and replaceable application service,
mediate arbitrary devices, provide replicated control, or exercise Claude.
Those are the next cross-domain system steps.

No file under `docs/paper/` changed in this step.
