# Result review

Verdict: **PASS, scoped to functional full-VMM continuity**.

## Final run

The final KVM run used official Claude Code 2.1.233, Firecracker 1.16.1, and
Linux 6.1.155. Source VMM PID 2797993 requested A. The provider committed A;
the supervisor killed and reaped that VMM before the held response was
released. Replacement VMM PID 2798018 booted cold with a different instance ID
and Claude session. It obtained A through the host journal, committed B, and
returned `DONE`.

The retained counts are:

- two VMM lifetimes and two Claude sessions;
- four model requests;
- four MCP journal records for two calls;
- two History Operations, each reaching `succeeded`;
- two provider deliveries and exactly two durable commits; and
- zero NICs and zero root block devices in each VM.

The source and replacement use the same read-only payload hash. No snapshot
state or guest memory is retained or loaded.

## Independent evidence check

`adapter/check_firecracker_claude_evidence.py` imports no producer module. It
passed both `/tmp/firecracker-claude-step-0020-final` and the relocated `raw/`
copy. It recomputed all named artifact hashes, parsed the binary History and
MCP journal, joined their Operation identities to provider facts, verified the
strict fault timeline and official Claude stream, checked exact Firecracker
device configuration, and bound both AF_VSOCK relay lifetimes to the recorded
VMM processes.

An exact copied run with `source/result.json` changed from `valid=true` to
`valid=false` was rejected. This is a focused negative test rather than a
complete mutation suite.

## Development failures retained outside the accepted result

Early runs found three implementation defects: the cell runner omitted `HOME`
when deriving default assets; SquashFS staging inherited private directory
modes that UID 1000 could not traverse; and waiting for host-side Unix EOF was
incorrect for Firecracker's AF_VSOCK backend. The final code fixes each defect,
and the accepted evidence comes only from the rebuilt final run. Old failed
runs remain under `/tmp` and are not part of the result.

## Interpretation

The result rejects the explanation that Claude process state or VM memory must
carry external-operation continuity. It supports the architecture in which
Firecracker is a replaceable containment backend and host History/Operation
state owns correctness across replacement.

It does not establish performance, arbitrary built-in-tool mediation, remote
attestation, `jailer` deployment, repeated-run reliability, or a general
refinement proof.
