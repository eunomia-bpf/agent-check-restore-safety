# Independent plan review

## Verdict

APPROVE.

The experiment is scientifically discriminating and executable for a narrow
RQ4 claim: an official Claude binary can use built-in Bash HTTP inside a no-NIC
Firecracker VM, through a host-owned registered Operation boundary, survive
source-VMM loss, and complete against an unchanged DeathStarBench deployment
without duplicate application state.

## Required clarifications applied before implementation

- Scope “decisive” to the ordinary-tool mediation gap within RQ4, not arbitrary
  transparent egress or production deployability.
- Freeze the failure barrier: observe the Mongo commit before SIGKILL and prove
  that no response byte reached the source guest. The VMM kill must create the
  uncertainty.
- Actively submit an old-generation request after cutover and require rejection
  with no new adapter delivery or Mongo row.
- Treat Mongo multiplicity as the primary external oracle; adapter delivery is
  secondary evidence. Retain commit -> death -> cutover -> replacement order.
- Treat raw retry as a matched lower bound, not superiority over receiver-side
  idempotency or manual query-before-retry.
- Say the full 24-service deployment is running without implying that one
  reservation traverses all 24 services; define transparency as no Claude or
  DeathStarBench source modification while route/key registration remains.

No blocking defect remains after these corrections.
