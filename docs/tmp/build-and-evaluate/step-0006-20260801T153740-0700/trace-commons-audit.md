# Trace Commons real-agent trace audit

## Scope and decision

This audit answers a deliberately narrow question: can a public trace from a
real Claude Code/Codex-style runtime directly tell us whether checkpoint,
restore, or fork preserves the authority needed by already-started effects?

**Answer: no, but the reason is useful evidence for the paper.** Trace Commons
contains real donated sessions and exposes message lineage, tool-call/result
pairs, and Claude Code file-history snapshots. It does not expose an
effect-level commit phase, an idempotence or compensation contract, durable
receipts, credential/grant epochs, or a semantic relation between a file
snapshot and external resources. It therefore supports the workload and
observability-gap claims, but it cannot label a restore as safe or unsafe.

The audit does not use trace contents to estimate security prevalence. The
sample is small and heavily skewed toward one harness. Its value is as a
schema audit and as a source of concrete workload shapes.

## Source and frozen revision

- Dataset: [Trace Commons — Agent Traces](https://huggingface.co/datasets/trace-commons/agent-traces)
- Dataset main revision: `112ebd4d03ce852b00e935d523107c3d0c9a65bf`
- Dataset Viewer parquet revision: `72c58f6a93393d75b1cbff4369430deda2f19c48`
- Retrieved: 2026-08-01
- Dataset server configuration: `default/train`
- Viewer size at retrieval: 30 sessions, 70,202,603 bytes, 11 columns
- Provenance caveat: 28 rows decode as `claude_code`; one Cursor and one
  OpenCode source file are present but have incomplete normalized harness/tool
  fields. The dataset is voluntary, public-repository-only, and not a
  representative sample of all production agents.

The revision and viewer metadata were checked with:

```bash
git ls-remote https://huggingface.co/datasets/trace-commons/agent-traces.git \
  HEAD refs/heads/main refs/convert/parquet
curl -fsSL \
  'https://datasets-server.huggingface.co/size?dataset=trace-commons%2Fagent-traces'
```

All aggregate counts below were computed read-only through the Hugging Face
Dataset Viewer `/rows` API. No donated raw trace was copied into the project.

## What the traces contain

Across the 30 rows, the normalized metadata reports:

| Quantity | Count |
|---|---:|
| Trace events | 18,012 |
| Tool calls | 4,264 |
| User messages | 413 |
| Tool results | 4,262 |
| Tool results explicitly marked as errors | 269 |
| File-history snapshot events | 953 |
| Snapshot roots | 351 |
| Snapshot-update events | 601 |
| Maximum files named by one snapshot | 135 |

The dominant actual tools are `Edit` (972), `Read` (847), `Bash` (794),
`Write` (641), and `PowerShell` (521). This is a stateful coding workload, not
a collection of isolated prompt/response examples.

Claude Code trace events carry `uuid`, `parentUuid`, `sessionId`, timestamp,
working directory, and Git branch fields. This is useful message/tool lineage.
It is not, by itself, a trusted Fork/Restore lineage: apparent fan-out can be
created by parallel tool-use/result records, and all observed `isSidechain`
fields are false. There is no explicit `fork`, `restore`, `rollback`, or
`checkpoint` trace event type in this revision.

The 953 `file-history-snapshot` events have a `trackedFileBackups` map whose
entries contain only `backupFileName`, `backupTime`, and `version`. This is
strong evidence that a real runtime already treats file history as a special
recoverable state plane. The snapshot does not include external service state,
process state, authority provenance, or protected-effect receipts.

## Effects outside file history

The shell calls were conservatively classified by command syntax. Categories
overlap and are not intended as a prevalence estimate.

| Observed shell-command shape | Matching calls |
|---|---:|
| deletion/destructive-filesystem syntax | 77 |
| `git commit` | 27 |
| `git push` | 20 |
| `git reset`, `git clean`, or checkout-restore syntax | 6 |
| network/remote command syntax | 126 |
| package installation | 9 |
| deployment/infrastructure command syntax | 5 |
| database command syntax | 8 |
| background process or service syntax | 36 |

These observations establish the important mismatch. A checkpoint can name
the local files it can restore while the same agent session performs effects
whose truth lives in a remote repository, a running process, a package store,
a database, or another service. Replaying the local snapshot does not imply
replaying, cancelling, or even observing those effects.

Two tool calls have no matching tool-result record. Both are PowerShell calls;
one launches a build, and the other begins by forcibly stopping processes
before building. A missing result is not evidence that the command had no
effect. It is precisely an uncertain observation boundary: the trace records
invocation but provides no durable semantic receipt with which a restore
controller could distinguish not-started, in-flight, committed, compensated,
or externally completed.

The remaining 4,262 tool results expose `tool_use_id`, content, and sometimes
`is_error`. Even an explicit non-error tool result is only a harness-level
observation. It does not state which external facts became durable, what
authority justified them, whether they are idempotent, or which compensation
would be valid after a fork.

## Field-by-field model correspondence

| Trace observation | Paper/model object it can support | What remains unobservable |
|---|---|---|
| `sessionId`, `uuid`, `parentUuid` | candidate execution lineage | trusted restore/fork edge and its state cut |
| `file-history-snapshot` | reconstructable workspace component | external resources and monotone lifecycle state |
| tool call ID and arguments | attempted operation identity | authorization source, support, and durable phase |
| tool result and `is_error` | harness observation | effect receipt, linearization point, compensation |
| working directory and Git branch | local execution context | branch epoch, credential/grant epoch, revocation |
| shell command text | evidence of opaque nested effects | complete effect decomposition and mediation |

This map supports the paper's separation between:

1. **reconstructable state**, such as tracked file versions;
2. **monotone lifecycle state**, such as closed branches, consumed grants, and
   stable operation bindings; and
3. **external reality**, which must be represented by effect-specific receipts
   or conservative uncertainty rather than inferred from a restored snapshot.

## Consequences for the paper and experiment

1. Public traces should motivate the model, not serve as ground-truth safety
   labels. Calling the 2 missing-result cases “unsafe rollback incidents” would
   be unsupported.
2. The minimal industrial instrumentation contract should add a trusted
   checkpoint/fork lineage ID, stable operation ID, authority/grant provenance,
   effect phase, durable receipt or uncertainty marker, and compensation or
   idempotence metadata.
3. The theory must continue to prove what follows from those fields and remain
   explicit about what cannot be proved without complete effect mediation.
4. The formal RQ2 experiment remains the decisive experiment. Trace Commons
   strengthens relevance and the observability-gap argument, but cannot decide
   the final-support/serialization theorem.
5. A later systems evaluation can replay real tool-call shapes through an
   instrumented adapter, but it must not retroactively assign semantic phases
   that the source trace never recorded.

## Reproducibility note

The primary aggregate query was the read-only endpoint:

```text
https://datasets-server.huggingface.co/rows?dataset=trace-commons%2Fagent-traces&config=default&split=train&offset=0&length=30
```

Counts were obtained from normalized `messages[].tool_calls`, raw
`trace[].message.content[]` tool-result blocks, trace event types, and
`file-history-snapshot.snapshot.trackedFileBackups`. Shell categories used
case-insensitive regular expressions over the `command` argument of actual
`Bash` and `PowerShell` calls; they are overlapping descriptive classes, not
mutually exclusive labels.
