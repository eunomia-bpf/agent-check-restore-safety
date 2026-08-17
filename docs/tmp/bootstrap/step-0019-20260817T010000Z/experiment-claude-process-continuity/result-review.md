# Result review: real Claude Code process continuity

## Inputs and completion

- Selected RQ: “RQ4: Is there a deployable algorithmic boundary?”
- Approved supporting hypothesis: the existing host MCP and Operation boundary
  can survive replacement of an unmodified official Claude Code process, not
  only Codex App Server.
- Final raw evidence:
  `docs/tmp/bootstrap/step-0019-20260817T010000Z/experiment-claude-process-continuity/raw/`.
- Producer: `adapter/claude_mcp_runtime_demo.py`.
- Independent analysis: `adapter/check_claude_mcp_evidence.py`.

The final run reached every planned terminal state. The first Claude process
exited `-9`, the replacement exited `0`, the replacement returned `DONE`, and
all three host services closed. The ephemeral socket directory and runtime
admin token were absent after completion.

## Mechanism engagement and recomputation

The tested executable is the official Claude Code 2.1.233 Linux binary with
SHA-256
`55d281096f57d411ebbdd94dbf5e9ff3accb7c05713e37348c2c11d4b83bf9d9`.
The fetcher verified Anthropic's published key fingerprint, detached manifest
signature, signed Linux manifest entry, size, hash, and version output.

The independent checker imports no producer module. It returned:

```json
{"claude_processes":2,"claude_version":"2.1.233","credentials_retained":0,"history_events":7,"mcp_relay_lifetimes":2,"operations":2,"provider_commits":2,"provider_deliveries":2,"replacement_exit_code":0,"schema":1,"source_exit_code":-9,"trusted_mcp_hosts":1,"valid":true}
```

It recomputed rather than copied the following joins:

- all seven binary History frames, the hash chain, and the external head;
- both Operation IDs from the host execution identity and MCP call sequence;
- each stored request and external provider fact;
- four MCP journal records, their request digests, call identities, response
  bytes, and hash chain;
- two provider rows, one for A and one for B;
- two raw Claude streams: source init and A call without a result, followed by
  a distinct session receiving A, B, and `DONE`;
- four Messages requests placed inside the exact two process lifetimes;
- live executable, parent, process-group, and session identities for two Claude
  processes and their two relay children; and
- the strict MCP file, separate private config trees, credential removal, and
  absence of the fixture key from retained evidence.

The decisive clock order is:

```text
provider A commit observed
  < source Claude SIGKILL
  <= provider response released
  <= host journal completed A
  < replacement Claude started
```

Therefore A could not have reached the source process, and the replacement's A
result came from the host journal. The provider contains exactly A and B, so no
second A delivery is hidden by a self-reported counter.

Key raw hashes are:

```text
control.history             60c4c903477e8d5edf51207a711ca22e8fe64aeff5d991fcc783def0ffe827e3
control.head-anchor         a9823004cd6a6b90115dca311754b6d8c2c06f7cdf74bc4106bd475c883d9e39
mcp-calls.jsonl             734d029f6871602d6986a5ccba625021655783e8e9eb2fb6b289501ad06daa35
payment.history             781efe54e81bd97e86788a448bd65bc40678a16c0cf09ec952e8174ddc0c854e
anthropic-requests.json     f0ac8499ddcc78edfaf472b620e3788bfa3be271ed60a06a325a70784e20f624
claude-first.stream.jsonl   27838bb0b008ac360e4b1d53143a6d0488802c0bba2d6685578f38004dc4b112
claude-second.stream.jsonl  453b5b9ace4ae0e2457dab3448fad78dcfc3419adf77a6229706b69b3f655fc0
```

The correctness oracle is not circular: provider rows, History, journal,
vendor streams, model requests, and Linux process observations are separately
generated sources. The checker does inspect the producer summary only to
require that it agrees with those sources.

## Deviations and failed attempts

`raw-attempt-1/` failed before activation because the nested evidence path made
the Unix sandbox socket exceed Linux's address length. `raw-attempt-2/`
completed the workload but correctly failed cleanup because the control-owned
zero-length socket lock remained in the temporary transport directory. The
repair separated ephemeral socket paths from durable evidence and explicitly
validated and removed that lock after service shutdown. The complete planned
workload was rerun from an empty final directory. `raw-attempt-3-pre-final/`
retains a valid run superseded after the source was changed to force the
temporary transport under `/tmp`; the whole workload was then rerun again. No
superseded-attempt value was promoted into the final result.

## Interpretation

```text
run status: valid
tested hypothesis: supported
research value: supporting
paper impact: additional RQ evidence
next paper decision: no paper change in this step; retain provider-independent
  process portability and proceed to complete Claude-in-Firecracker replacement
```

The result is not a reliability or performance measurement and has no matched
superiority baseline. The deterministic Messages endpoint tests the real
Claude executable and MCP client but not a live Anthropic model. Built-in tools
remain visible but unused. A new model decision sequence need not reproduce the
same MCP identity; general semantic reconciliation remains open. The result
does not establish complete mediation, whole-VM Claude replacement, or the
theory-to-runtime refinement theorem.

The current execution policy did not permit a fresh reviewer process. This
report is therefore a root raw-artifact review, not an independent scientific
review. The separately implemented checker supplies implementation
independence for the concrete result.
