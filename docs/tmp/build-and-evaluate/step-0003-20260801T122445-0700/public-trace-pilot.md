# Public Trace Pilot: Agent LLM Traces

## Scope and access

This was a read-only, aggregate-only pilot of
`DiscoPosse/agent-llm-traces` through the Hugging Face Dataset Viewer API on
2026-08-01. Dataset revision:
`6b1add7c19f1fb50bb0edf5b240d6149a5c621fb`. The repository was public and
ungated, with CDLA-Permissive-2.0 metadata. The published split contains 1,781
rows in 39 Parquet shards totaling 983,592,848 bytes.

No gated terms were accepted, no full shard was downloaded, no raw message,
token, argument, or tool-result body was retained, and no repository file was
modified during sampling. Raw messages can contain prompt content, tool
parameters/results, and fields named `access_token`; even when benchmark
generated, those values must not be republished or assumed harmless.

## Reproduction surface

```bash
curl -fsSL \
  'https://datasets-server.huggingface.co/is-valid?dataset=DiscoPosse%2Fagent-llm-traces'
curl -fsSL \
  'https://datasets-server.huggingface.co/rows?dataset=DiscoPosse%2Fagent-llm-traces&config=default&split=train&offset=700&length=1'
```

Sampled row-response SHA-256 values:

```text
offset 0     e4fffa13e4dc31b46423c64daf4d125688054ae2eb27b6f1d962855dd74f6f92
offset 500   34de57b5859dc6fbeb18f14b31c22afa2d239fb8ab07ebc0caf17eb1fd9f3d7a
offset 700   21ea86cd87d44dae4644124f907372b1caa670aed47e5a4745c3d739bd64670f
offset 1000  d22dd3a39ca47a817e6eef36ded1f32b340dc93d9d307304aaca61d9a33d586a
offset 1300  d221b73d356a2efbc8f3c0a7dd882acf5e6073a6fe0499d33a5ac2e33fadc87e
offset 1700  63c53e41534afe0ce568fe248226e11d06b27627a1b2722b2e332120a3d309f1
```

The hashes identify the API responses inspected; they are not a promise that
the mutable Viewer endpoint will retain those bytes. A full study must pin the
dataset revision and retain shard checksums in `datasets.lock.json`.

## Observed schema

Top-level fields include `harness`, `benchmark`, `models`, token limits/counts,
`session_id`, `spans`, and `collected_at`. Each sampled span exposes
`span_id`, `trace_id`, `session_id`, start/end time, model/response metadata,
input/output message JSON, tool definitions, resource metadata, and
`status.{code,message}`. Tool calls in output-message JSON have
`{type,id,name,arguments}`; later cumulative input-message JSON contains
`tool_call_response` objects linked by `id`.

The current Viewer feature schema and sampled spans do not expose
`parent_span_id`, even though the dataset card includes it in an example.
Sampled spans were `llm_call` / `SPAN_KIND_CLIENT`; there was no independent
tool-execution span separating dispatch, remote commit, and result receipt.
Errors were LLM-span status, not a normalized tool-failure relation. Because
each later input can repeat the cumulative conversation, call/result statistics
must deduplicate by ID rather than count every message occurrence.

The schema has none of the following structured facts:

- checkpoint/Fork/Restore/Merge operation, source boundary, branch epoch, or
  active/retired topology;
- grant/capability issue, transfer, revocation, demand, or consumption lineage;
- a stable protected-effect identity promised to survive retry/fork;
- Prepare/Dispatch/uncertain/settled phase or a normalized trusted receipt;
- authoritative external before/after state.

## Aggregate workload patterns

The sample supports workload selection, not a safety-violation claim:

1. Offset 0 contains five payment-request calls with distinct call IDs. This
   motivates a controlled retry-versus-new-effect pair but does not show that
   any payment was duplicated.
2. Offset 1000 contains a fan-out of up to ten airline queries followed later
   by three reservation mutations. This motivates read fan-out followed by a
   bounded write, partial completion, and merge/recovery cases.
3. Offset 1700 repeats identical tool name/argument signatures under different
   call IDs (five and three occurrences for two query tools). This directly
   demonstrates that ordinary call IDs alone do not say whether semantically
   equal calls are retries or new invocations.
4. Offsets 0 and 700 contain error-status spans with equal start/end times,
   empty status messages, and no response ID/output. These are useful failure
   workload seeds but do not identify whether a tool was dispatched.

## Decision

A full public scan is worth implementing because 984 MB is manageable and the
statistics can be aggregate-only: parallel calls per model turn, identical
signatures under different call IDs, missing call/result links, LLM-span error
status, and required-field coverage. It must not report “unsafe trajectories”
or infer external success from text. Security truth remains the job of the
labeled, fault-injected runtime litmus suite.
