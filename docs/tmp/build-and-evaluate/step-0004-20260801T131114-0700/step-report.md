# Step 0004 report: concrete Codex lifecycle correspondence

## Question and decision

This step tested RQ3: whether a client that owns one real Codex App Server
dynamic-tool dispatch can instantiate the paper's lifecycle/effect premises for
the fixed C01--C20 histories.  The result is positive for the isolated adapter
boundary and negative as a claim about product-wide Codex safety.

The experiment is deliberately deterministic.  It is correspondence and
fault-recovery evidence, not a prompt benchmark, prevalence estimate, latency
study, or substitute for the conditional unbounded theorem.

## Integrity chronology

The reviewed preflight passed on its first attempt.  An initial 80-run pilot
then completed, but independent result review rejected its observation and
Merge evidence.  That pilot remains under `experiment-001/pilot-rejected/` and
is not reported as a paper result.  Suite revision 2 kept every frozen oracle
decision unchanged while fixing the evidence defects:

- C16/C18 now use their actual next-action grants and explicit typed prefix IDs,
  preserving aliasing under O2 rather than fabricating a common grant;
- C02/C04 execute the physical-attempt admission question while the real
  callback is pending: recovery Dispatch accepts in C02, whereas Retry rejects
  after settlement in C04 and the cached receipt is returned without a sink
  attempt;
- C19 supplies a canonical source/target projection and injective retained-
  claim map checked by independently implemented controller and replay rules;
- the checker joins raw App Server JSONL, declarative operations, provider
  summaries, worker crash boundaries, controller deltas, and sink snapshots.

## Real boundary and controls

- Pinned runtime: `codex-cli 0.146.0`, binary SHA-256
  `2e863156ed35ecc5253b1e2f907a9143077b9f7cb51942070c61996471ff6e04`.
- The installed `codex app-server --stdio` negotiated the experimental API.
- A persistent seed was forked at one exact turn.  Every experiment history
  received a real ephemeral thread ID.  The adapter, not Codex, assigned
  choice/parallel, replacing/live, and Merge meanings.
- Every reached effect traversed an actual client-owned `item/tool/call`.
- The model endpoint was a deterministic loopback Responses fixture.  The only
  protected service was an isolated authenticated, idempotent, queryable
  SQLite sink in a durability domain separate from the controller.
- Fault injection used `SIGKILL` on the controller worker only.  App Server and
  the JSON-RPC frontend retained the same pending callback.
- An unauthenticated sink attempt and stable-key rebinding both rejected.

The accepted preflight retained one sink outcome at the crash boundary while
the controller ticket was inflight; a distinct recovery PID queried and
settled it.  Final state contained one attempt, one outcome, and one receipt.

## Final revision-2 result

Both authoritative commands exited zero.  All 80 policy/case runs ended at an
explicit terminal or earliest-divergence state in 83.78 seconds; the slowest
case took 1.50 seconds, but these one-shot times are diagnostic only.

| Gate | Result |
|---|---:|
| P3 request decisions matching frozen oracle | 89 / 89 |
| P3 complete logs independently replayed | 20 / 20 |
| P3 unsafe accepted requests | 0 |
| Duplicate aggregate effects | 0 |
| Sink outcomes without a matching raw callback | 0 |
| Reached / raw-matched protected dispatches | 44 / 44 |
| Native forks matched to run actions | 187 / 187 |
| Hard worker crashes / distinct-process recoveries | 33 / 33 |
| Executed C02/C04-family attempt probes | 22 |
| Mixed-label fibers O0 / O1 / O2 | 3 / 3 / 0 |

The policy comparison is deterministic and request-level.  `P0` admitted 11
oracle-unsafe requests and rejected no oracle-safe request across all 89
observed decisions.  `P1` admitted no unsafe request but rejected four safe
requests across 87 observed decisions and, after early divergence, did not
execute two later requests.  `P2` admitted no unsafe request but rejected nine
safe requests and did not execute 18 later requests across 71 observed
decisions.  This supports the claimed safety/permissiveness
separation for the fixed suite: workspace/topology-local admission is unsafe,
while mandatory split and parent escrow are safe but incomplete for different
useful histories.

The 187 native forks comprise 80 per-run setup roots and 107 accepted
lifecycle materializations: 80 fork children, 24 restore copies, and three
merge targets.  They are concrete history edges, not 187 abstract topology
transitions; logical ancestry remains adapter metadata.

## Claim boundary

The run supports a narrow statement: for one protected queryable sink, a
dispatch-owning Codex client plus a separately durable authority controller can
map the fixed native-fork, adapter-lifecycle, crash, and effect edges to the
abstract P3 transitions while preserving one stable aggregate outcome.

It does not show that Codex itself implements replacing Restore, semantic
Merge, authority continuity, or product-wide complete mediation.  Ephemeral
children are all native forks of the persistent seed; logical ancestry is an
adapter relation.  Topology operations succeed sequentially but are not tested
against a crash between controller commit and native thread activation.  The
mock model never receives shell/MCP/web access, and a same-user process with
direct database access is outside the modeled sink API.  App Server/frontend
death, power loss, dishonest/non-queryable sinks, arbitrary tools,
natural-language binding, and the generic certificate language remain outside
this experiment.  The full concrete refinement theorem therefore remains
conditional; this step validates one fixed adapter instantiation of its
premises, not every concrete edge of a production runtime.

## Independent result review

The final revision-2 review verdict is **ACCEPT** with no rerun required.  The
reviewer independently joined 80 summaries with 160 SQLite databases and found
zero controller-state, event, sequence/hash, or sink-snapshot mismatch.  The
verdict treats the experiment as supporting fixed-suite composite
correspondence evidence, while keeping production refinement, generic Merge
certificates, topology crash atomicity, and product-wide mediation outside the
claim.  The full verdict and its six reporting constraints are retained in
`experiment-001/result-review.md`.

## Reproduction and retained evidence

```text
python -W always::ResourceWarning -m unittest discover -v adapter
python -m adapter.check_results --suite adapter/litmus.yaml --oracle adapter/oracle.yaml --input adapter/results/litmus.json --output adapter/results/check.json

adapter_run_dir="$(mktemp -d)"
python -m adapter.codex_litmus --suite adapter/litmus.yaml --runtime-lock adapter/runtime-lock.json --raw-dir "$adapter_run_dir/raw" --output "$adapter_run_dir/litmus.json" --workspace .
python -m adapter.check_results --suite adapter/litmus.yaml --oracle adapter/oracle.yaml --input "$adapter_run_dir/litmus.json" --output "$adapter_run_dir/check.json"
```

The first two commands verify the retained evidence; the latter two create and
check a fresh run without overwriting it.

The final unit run passed 33/33 tests.  Important retained SHA-256 values:

- suite: `47985a7d44e4ee35b7fc30f358f1f862c0a547b5d0542842061fda38587555d3`;
- oracle: `f96d245a67a02ddf22d087929d062d1b7afd630b80ca2d35341cf678368c51f1`;
- full JSON: `74fbea12589173e8921641941f8ff530a35f0ad7855934ab246b0c5078efbc8e`;
- checker report: `451f4db67507469c76d9a1bf6aabcd884407ebc7538260d2d2ada637ea6c48be`;
- raw App Server JSONL: `d43886fd08e7a4b97646021cde030a68d8477b8e5fd58581f2510394ff1d687e`.

The accepted preflight, rejected pilot review/artifacts, frozen plan and plan
review, final result review, raw JSONL, 160 isolated SQLite databases, JSON
summary, and compact checker verdict are all retained.
