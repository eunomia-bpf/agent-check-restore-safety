# Scientific and system contract: safe change after external operations

**Status:** active research contract, 2026-08-16. This supersedes the Agent-only
project scope while preserving the existing Agent theorem and artifacts as one
special case.

## Thesis

The system should let an operator replace a running program after it has
already performed or attempted real external actions, without handwritten
per-state migration code. It should automatically continue every execution
that can still meet its obligations, and return checkable evidence for each
execution that cannot.

The target is not a new hot-update mechanism. The target is the missing bridge
from what actually happened to what a real runtime must enforce next:

> Derive the obligations, stable external identities, observable uncertainty,
> and controllable actions from the complete execution record; synthesize a
> safe change using established control techniques; then enforce that change
> at the shared boundary among Agents, virtual machines, services, and the
> external world.

If successful, the striking demonstration is:

> A Codex or Claude task running inside a full Linux VM invokes a real
> microservice workflow. A remote payment may have committed while its response
> was lost. While the task, VM, and services are still live, the operator
> changes the program and restores or replaces local state. Without a custom
> migration function, the runtime either continues safely without a duplicate
> payment or explains from durable evidence why no safe continuation exists.

## Five terms

The public model uses only **History**, **Requirement**, **Operation**,
**Rule**, and **Certificate**.

- History records all facts that a local restore cannot erase, including
  logical progress, stable Operation identity, external status, authorization,
  and active/closed versions.
- Requirement states invariants and every result that the changed execution
  must still be able to complete.
- Operation describes an external action, what the runtime can delay or stop,
  what the environment decides, and whether retry, query, cancellation, or
  compensation is available.
- Rule is the behavior the runtime will enforce from the current History.
- Certificate lets a small checker validate a Rule change or a genuine
  impossibility result against the same History.

Adapters and protocols may have ordinary implementation fields, but they must
not introduce another paper-level concept.

## What is new, if the project succeeds

Classical work already supplies maximal nonblocking supervision, live
controller update, state transfer, workflow versioning, output commit, stable
request identifiers, result reuse, safe network update, and several
coordination boundaries. We use those results; we do not rename them.

The candidate contribution is the conjunction of four properties that existing
systems leave to developers or assume as input:

1. History is automatically converted into the exact old obligations and
   external facts relevant to this requested change.
2. One abstract Rule applies across Agent, VM, and service boundaries rather
   than stopping at one process or workflow engine.
3. Concrete enforcement is crash-safe: a concurrent Operation is wholly before
   or wholly after the Rule change, and an old actor cannot bypass the new Rule.
4. Every refusal is tied back to History, the registered Operation contracts,
   and the exact external fact that the runtime cannot observe or control.

The hard theorem is therefore not that a maximal controller exists. It is that
the History abstraction preserves every change answer for the registered
program slice, and that each concrete adapter implements exactly the abstract
actions and observations it declares.

## System shape

The runtime sits above Linux/KVM and below effect-bearing code. It does not
replace Linux.

```text
Codex / Claude       Linux VM       microservices
       |                |                 |
       +---------- typed adapters --------+
                        |
              mandatory Operation gateway
                        |
              History + active Rule
                        |
       compiler ---------------- small checker
          |                            |
          +-------- Certificate -------+
                        |
             external APIs and devices
```

The durable control service owns the History and current Rule. A compiler may
use supervisory control, games, SMT, decision diagrams, or specialized fast
paths. A separately implemented checker accepts only a Certificate bound to the
current History. Rule activation fences old actors, records the new epoch, and
opens the new actors through one crash-recoverable protocol.

The enforcement boundary differs by environment but must preserve the same
Operation identity:

- Agent tools enter through Codex App Server callbacks or a Claude tool proxy.
- Microservices enter through an SDK/sidecar plus an egress gateway.
- A VM enters through a host-owned virtual network/device boundary and a guest
  adapter; local snapshot state is evidence but never the whole History.

No safety claim applies to an external path that can bypass the gateway.

## Theorem program

The end state should prove the following, scoped to registered finite
effect-bearing program slices and declared external capabilities.

1. **Answer preservation.** Two Histories have the same normalized state if and
   only if every registered change receives the same answer. The reverse
   direction supplies information lower bounds for omitted progress, identity,
   external status, or version facts.
2. **Rule correctness.** The selected control backend preserves every invariant
   and does not make a still-required result unreachable. Any behaviorally
   maximal claim is explicitly relative to the supplied finite model.
3. **Adapter correspondence.** A two-way correspondence yields exact behavior;
   a one-way correspondence yields safety only. The paper must not claim exact
   rejection for an adapter that proves only the latter.
4. **Atomic change.** Rule activation and every external Operation have one
   durable order under crashes, stale requests, old actors, and delayed remote
   results.
5. **Checkable refusal.** A refusal identifies a real uncontrollable event,
   missing observation, exhausted resource, or incompatible Requirement. It
   does not merely report that a solver timed out.

The existing Agent fixed-point theorem, identity results, coordination result,
and atomic race model become lemmas and one frontend for this program.

## Real evaluation contract

One cross-domain execution is more important than three disconnected demos.
The primary workload will combine:

- a full QEMU/KVM Linux VM;
- Codex and, when an executable is available, Claude;
- a real long-running workflow or microservice application;
- an independently durable payment or infrastructure service; and
- lost responses, process death, VM restore, network partition, delayed old
  calls, and Rule changes.

Mandatory baselines include MTSA dynamic controller update, Temporal or Restate
version pinning, QEMU save/restore and replay, Kubernetes rolling/blue-green
deployment, idempotent retry, Saga/compensation, deny-all, and old-version
draining. At least one workload must come from a maintained real application,
such as DeathStarBench Hotel Reservation, rather than a local fixture.

Success requires both safety and useful continuation: the runtime must preserve
substantially more live executions or concurrency than deny-all, global
serialization, or keeping every old version indefinitely.

The first vertical system smoke now exists. One live run combined a logged-in
Codex App Server, a replaceable order service, a complete Ubuntu QEMU guest,
and three durable external services under one History. It changed Rule v1 to
v2, replaced order, restarted control, and restored the VM. The observed result
was five deliveries and three commits, with old Operation meaning preserved
across the v2 process and the restored VM receiving its recorded result. This
meets the integration milestone, not the evaluation contract above: the
services are purpose-built and the run used TCG once without baselines. A
separate checker independently replays the retained cross-domain evidence and
fails closed under mutations to each recorded runtime boundary.

## Build sequence

0. **Durable control path — implemented.** A Go History, external head anchor,
   stable Operation lifecycle, resource/result planner, history-bound
   Certificate, strict-receipt HTTP gateway, local control daemon, state replay,
   and a separately synced payment file now run under public commands. Later
   container and Codex paths replace the complete control process.
1. **Enforced multi-process change — implemented.** Separate order, control,
   payment, and fixed-ingress containers now replace the whole order process
   after a committed payment loses its response. The changed process contains
   only v2 configuration; History supplies the old Operation meaning. Internal
   Docker networks make control the only process that can reach payment, and
   the scenario restarts control before completing old work.
2. **Independent checking — implemented; compiler isolation remains.** A
   standard-library-only checker binary independently reconstructs the exact
   bounded answer using a separate implementation. Compilation, live
   activation, and History replay all require its verdict over a versioned,
   answer-preserving State projection. The compiler still shares the control
   process; proof-object Certificates, authenticated query evidence, and a
   systematic crash matrix remain open.
3. Run a maintained multi-service application behind enforced egress and
   change it while requests are active.
4. **Complete Linux VM restore path — implemented for the HTTP boundary.** A
   checksum-pinned Ubuntu image boots under rootless QEMU TCG with
   `restrict=on` and only fixed metadata/control forwards. QEMU saves the live
   guest before an Operation, payment commits and loses its response, and QEMU
   restores the whole guest. Host History turns the repeated call into one
   successful Operation with one remote commit. Device-output mediation remains
   open.
5. **VM and isolated-service composition — implemented for the HTTP path.**
   One real Codex callback now spans a replaceable order container, a complete
   Ubuntu QEMU VM, and separate payment, inventory, and ledger services, all
   using one History. During the same purchase, Rule v1 changes to v2, order is
   replaced, control restarts, and QEMU loads its saved whole-VM state. The v2
   order process requests `reserve-v2`, but stable identity recovers the old
   `reserve-v1` Operation and its v1 target; the restored guest reuses its
   recorded audit result without another ledger delivery. Docker and QEMU
   network boundaries block direct effect access. Block and device output tests
   remain open.
6. **Real Codex App Server path — implemented with enforced network
   isolation.** A logged-in model runs in a hardened container and invokes one
   strict dynamic tool. Codex and payment share no Docker network; control is
   the only bridge. A control-health probe from Codex must succeed before
   direct payment name and IP probes must fail. The
   callback remains pending while payment commits, loses its response, and the
   control container restarts. A separate checker then joins raw App Server
   JSONL with a replayed binary History, external head, and payment record.
   Adding Claude and a provider-independent Agent protocol remain open.
7. **Native Codex-in-Firecracker continuity path — implemented for one
   credential-free callback.** An unchanged App Server client now reaches the
   exact native Codex binary inside a no-NIC microVM through a transparent
   executable. The runtime checkpoints a two-way stream, drains the model
   path, pauses and snapshots G1, kills and reaps its exact VMM, loads the same
   guest into an independently started paused G3, arms host endpoints before
   resume, reconnects, and only then exposes the callback. A separate checker
   joins 22 lifecycle events, 16 retained artifact hashes, bridge commitments,
   App Server records, VMM API traces, process identities, and snapshot inputs.
   This establishes a real continuity substrate, not yet the History/Rule join
   or a production sandbox; the exact boundary is documented in
   `docs/firecracker-codex-runtime.md`.
8. Replace bounded enumeration with a symbolic backend and cross-check it
   against the existing exact Python oracle.
9. Prove the generic finite theorem, the durable control refinement, and each
   adapter correspondence in Lean.
10. Run scale, availability, fault, usability, and strongest-baseline studies;
   only then rebuild the paper around the larger result.

The current composition is not yet the intended final system or evaluation. It
still needs a maintained real application; a live Claude frontend; an Agent
running inside the full guest rather than beside it; repeated KVM experiments
and the declared baselines; block, GPU, passthrough, and other device-output
mediation; signed remote evidence; replicated control; and an end-to-end
refinement proof connecting each concrete adapter to the finite model.

## Kill tests

The direction should be abandoned or narrowed if any of the following holds:

- the runtime needs handwritten migration logic for each old execution state;
- History cannot be derived substantially more automatically than the
  transition requirements expected by MTSA or Live Synthesis;
- VM, Agent, and service adapters require different semantic cores;
- a realistic effect path cannot be forced through the Operation gateway;
- the exact method accepts too little useful work compared with old-version
  draining; or
- the claimed History abstraction cannot distinguish two real executions whose
  correct change answers differ.
