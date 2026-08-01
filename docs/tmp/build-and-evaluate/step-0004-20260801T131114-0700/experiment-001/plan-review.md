# Independent Plan Review

## Scope

The reviewer read the frozen RQ3 contract, the proposed runtime-refinement
plan, the current Lean ticket semantics, the local Codex 0.146.0 protocol
schemas, and the fixed C01--C20 workload. The review checked paper-decision
value, real-system engagement, baseline fairness, oracle independence,
crash semantics, executable completion rules, and the proposed observation
witnesses.

## Round 1: blocking findings

1. **Outstanding callback lifetime (P0).** The first plan said to kill the
   adapter while using `codex app-server --stdio`. Codex 0.146.0 keeps the
   outstanding `item/tool/call` callback in App Server memory; losing the
   stdio client can terminate the server, and a new process is not promised to
   replay that callback. The proposed recovery was therefore not executable.
2. **Effect witness typing (P1).** C02/C04 is valid only when its identical
   request is permission for the physical abstract attempt
   `.attempt(e1,c1)`. C02's prepared ticket admits Dispatch; C04's settled
   receipt denies another attempt and returns the cached result as a
   zero-outcome stutter. A generic API success label would not establish the
   LTS claim.
3. **No terminal timeout (P1).** A lost callback could leave the experiment
   hanging without a retained failure outcome.

### Disposition

The plan now keeps App Server and the JSON-RPC frontend alive and hard-kills
only a separate controller worker. It explicitly disclaims callback replay
across frontend/App Server death, gives the C02/C04 labels above, and sets
15-second RPC, 5-second worker-restart, 30-second turn, and 60-second case
timeouts.

## Round 2: blocking findings

1. **P0 crash semantics (P1).** A live frontend retains the same App Server
   `callId` across worker restart, whereas the old P0 description synthesized
   a fresh provider ID. That combination could create or hide a duplicate
   artifact unrelated to the actual tested boundary.
2. **Oracle leakage (P1).** Supplying the same YAML with expected terminal
   labels to the controller could make 20/20 agreement a hard-coded
   conformance result rather than independent evidence.

### Disposition

P0 now uses the actual retained `callId` and is only a topology/rollback null
control; absence of a duplicate says nothing about full-client-loss safety.
Expected decisions and abstract edges live in a separate frozen oracle
fixture. Workers receive only stripped operations, policy, fault site, and an
opaque case ID; they cannot import oracle/checker modules or inspect sink state
except through the declared authenticated recovery query. The checker alone
joins outputs with oracle fixtures and sink snapshots.

## Final verdict

**ACCEPT for execution.** No P0/P1 defects remain.

The reviewer found the experiment decisive and non-tautological for RQ3,
confirmed that the real Codex path and worker-only crash scope are executable,
accepted P1/P2 as credible matched alternatives, and accepted C02/C04 as a
current-LTS effect-phase witness. Three nonblocking follow-ups remain:

- synchronize `docs/runtime-integration.md` with C02/C04 and retained-`callId`
  P0 semantics before freezing the suite;
- name a concrete crash-consistency/litmus precedent in any eventual paper
  report; and
- keep the sink credential out of App Server/model-visible state and describe
  the unauthenticated bypass as a control, not a proof against OS-level theft.
