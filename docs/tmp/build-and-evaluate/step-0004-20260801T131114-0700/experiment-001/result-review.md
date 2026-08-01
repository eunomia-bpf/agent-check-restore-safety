# Independent result review: revision 2

## Verdict

**ACCEPT.**  The retained run is valid and does not need to be rerun.

The fixed C01--C20 hypothesis is supported for one protected queryable sink
and worker-only crashes.  The broader claim that a production Agent lifecycle
has been concretely refined remains inconclusive.  The experiment is useful
supporting correspondence/feasibility evidence, not a decisive implementation
proof of the general trace theorem.

## Evidence independently checked

- all 33 unit tests pass;
- P3 matches 89/89 frozen decisions, independently replays 20/20 complete
  controller delta/hash chains, and has no unsafe acceptance;
- all 44 reached callbacks match raw App Server records, all 33 hard worker
  crashes recover in a different process, and 22 physical-attempt probes
  execute rather than inherit an oracle label;
- an independent join of all 80 run summaries with all 160 SQLite databases
  found zero controller-state, event, sequence/hash, or sink-snapshot mismatch;
- C16/C18 use their real `g`/`g2` identifiers and preserve their alias
  relation under O2;
- C02/C04 issue the actual paired accept/reject attempt question;
- C19 carries a fixed singleton projection and injective claim map checked by
  both the controller and an independently implemented replay decoder.

## Required claim limits

1. The 187 native forks comprise 80 per-run setup roots and 107 accepted
   lifecycle materializations (80 fork children, 24 restore copies, and three
   merge targets).  They are not 187 abstract topology transitions.  Every
   native history is a sibling from one seed boundary; logical ancestry is
   adapter metadata.
2. Topology admission and native activation are sequential.  No crash is
   injected in that interval, so the prototype does not implement or test
   crash-atomic topology activation.
3. Replay validates the controller delta/hash chain.  Separate checker joins
   validate App Server, fault, and sink correspondence.  Together these form a
   fixed-suite composite correspondence audit, not a complete
   `SimulatedTrace` or production refinement proof.
4. C19 checks one singleton fixed certificate.  Generic projection circuits,
   fragment transfer, contract hashes, and artifact hashes remain unimplemented.
5. The 44 dispatches, 33 crashes, and 22 attempt probes are totals over all
   four policies.  P3 contributes only its corresponding subset.  Baseline
   denominators are P0 11 unsafe accepts over 89 observed decisions, P1 four
   safe rejects over 87, and P2 nine safe rejects over 71; truncated successors
   are not decisions.
6. P0 is a workspace/topology-local admission or local null control, not a
   faithful uninstrumented workspace-only Agent runtime.

The paper and project documentation must retain these boundaries.
