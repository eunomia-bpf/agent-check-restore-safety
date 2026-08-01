# Orchard Access and Schema Check

## Why this check exists

Independent reviews disagreed about whether Microsoft Orchard was paused or
public. The current official API/card/Viewer were therefore checked directly on
2026-08-01. This record supersedes cached page interpretations for this step.

## Pinned result

- Dataset revision: `70c05ec1f20f823ae6adc60374922e9271bb74e2`
- Last-modified metadata: `2026-07-28T21:27:19Z`
- Access: public, ungated, not disabled; MIT metadata
- Configs: `swe/train` and `gui/train`
- Files: 19 SWE Parquet shards and three GUI Parquet shards
- Published rows: 107,185 SWE trajectories and 3,070 GUI prefixes
- Viewer service: preview, rows, search, filter, and statistics enabled

The card reports about 9.72 GB for SWE, 2,788 repositories, 74,649 resolved and
32,536 unresolved trajectories. One untruncated `swe/train` Viewer row was
inspected without retaining its text. It contained 109 messages and the
expected top-level `tools`, `messages`, and `metadata` fields; messages expose
`role`, `content`, `tool_call_id`, and tool calls with ID/type/function
name/arguments.

## Read-only commands

```bash
curl -fsSL 'https://huggingface.co/api/datasets/microsoft/Orchard'
curl -fsSL 'https://huggingface.co/datasets/microsoft/Orchard/raw/main/README.md'
curl -fsSL \
  'https://datasets-server.huggingface.co/is-valid?dataset=microsoft%2FOrchard'
curl -fsSL \
  'https://datasets-server.huggingface.co/rows?dataset=microsoft%2FOrchard&config=swe&split=train&offset=0&length=1'
```

No shard was downloaded and no raw row content was retained or quoted. The SWE
card says trajectory text is anonymized, but the study should still emit only
aggregate statistics and hashes.

## Scientific boundary

Orchard is now a valid public controlled workload/schema corpus, not a natural
checkpoint/restore corpus. Its resolved/unresolved label is task success, not
authority safety. The inspected schema still lacks typed lifecycle topology,
grant/claim lineage, stable protected-effect phase, and trusted external
receipts.
