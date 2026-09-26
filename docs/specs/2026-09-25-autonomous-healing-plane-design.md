# Autonomous Healing Plane Design

Date: 2026-09-25
Branch: feature/gpu-fabric-foundation

## 1. Purpose

Introduce a dedicated Autonomous Healing Plane above the existing physical-fabric, active-path intelligence, recovery orchestration, placement, execution-feedback, self-optimizing control-plane, and self-coordinating-fabric layers.

The healing plane detects demonstrated failures, contains them, selects safe recovery strategies, executes reversible remediation, recovers workloads and control-plane components, verifies recovery, and enters durable degraded mode when safe autonomous recovery is unavailable.

It is a healing system, not a continuous infrastructure optimizer.

## 2. Architectural Authority Boundary

The healing plane coordinates recovery but does not replace existing authorities.

- Physical fabric state and exact physical path identity remain owned by the physical-fabric and inventory authorities.
- Active-path measurements and intelligence remain owned by active-path intelligence.
- Physical recovery execution remains coordinated by the recovery orchestrator.
- Capacity and placement remain owned by the self-coordinating fabric and placement authorities.
- Execution truth remains grounded in execution feedback and workload-specific execution state.
- Healing state owns healing decisions, plans, leases, checkpoints, remediation history, learning provenance, and reconciliation state.
- No healing record becomes a competing source of truth for physical reality.

Authority conflicts resolve according to explicit authority ownership, never by last writer wins.

## 3. Autonomy Boundary

The healing plane has full-stack healing scope, including infrastructure, workload execution, and control-plane failures.

Its infrastructure remediation boundary is reversible remediation with graduated escalation. It does not continuously mutate infrastructure for optimization.

Permitted recovery mechanisms include quarantine, restart, reinitialization, endpoint reprobe/rebind through authoritative lower layers, restoration of known-good configuration, workload restart or migration, control-plane reconstruction, and other explicitly bounded reversible actions.

If safe recovery cannot be completed, the affected scope enters degraded mode rather than escalating indefinitely.

## 4. Evidence and Safety

The first remediation decision uses adaptive evidence thresholds.

Thresholds consider failure criticality, confidence, reversibility, blast radius, redundancy, historical recovery success, fallback capacity, and exploration cost.

Hard safety floors cannot be overridden by adaptive logic. These include:

- no irreversible remediation without an authorized recovery boundary;
- no cross-domain blast-radius expansion beyond defined limits;
- protected standby capacity cannot be consumed below its immutable floor;
- exact physical paths must come from authoritative sources;
- required verification authorities cannot be bypassed;
- stale generations and fenced controllers cannot act;
- unsafe or unverifiable states do not become authoritative;
- known-good recovery capability must remain continuously available.

## 5. Failure and Containment Model

Simultaneous failures are treated independently unless an authoritative dependency explicitly establishes a relationship.

Containment is adaptive.

The system may observe, soft-isolate, quarantine, or immediately isolate a suspected failure. Immediate containment is mandatory when continuing operation could plausibly create irreversible damage, cross a defined blast-radius boundary, exhaust protected capacity, or cascade into another failure domain.

The healing plane does not infer a shared root cause merely from temporal or statistical correlation.

## 6. Healing Strategy Selection

The planner selects among known-good recovery, reversible remediation, workload recovery, control-plane recovery, degraded operation, and bounded exploration.

Known-good recovery procedures remain permanent safety anchors.

When established recovery is insufficient, controlled exploration is permitted within bounded risk. Experimental strategies are isolated from established production recovery policy.

A new recovery strategy can become production-capable only after evidence demonstrates sufficient safety and recovery effectiveness, with provenance and automatic rollback/demotion on regression.

An older proven recovery capability cannot be retired until an adequate replacement is continuously available.

## 7. Healing Execution and Concurrency

Every healing action has durable ownership, a lease, generation identity, fencing information, idempotency identity, and immutable action history.

Independent actions may run concurrently when independence can be established from authoritative scope and dependency information.

Conflicting or uncertain actions are serialized.

Expired leases permit safe takeover only after fencing prevents stale owners from acting.

## 8. Transactional Healing

Multi-step healing operations use explicit checkpoints and durable intermediate states.

Each operation defines rollback and compensation boundaries.

Verified progress may be preserved when the resulting state is independently safe and verifiable. Otherwise the system rolls back or compensates to the appropriate last verified state.

An intermediate state never becomes authoritative merely because a healing action reached that step.

Final closure requires existing authoritative verification plus healing-specific validation.

## 9. Workload Healing

In-flight workloads are recovered using the strongest available execution-state semantics.

The planner may restart locally, restore from checkpoint, isolate, or migrate to verified destination capacity.

Migration requires authoritative capacity allocation and verified exact fabric paths.

Recovery must preserve execution correctness and avoid duplicate side effects according to workload-specific recovery semantics.

Workload healing does not invent placement or physical-path identities.

## 10. Control-Plane Healing

The healing plane treats control-plane components as recoverable production components.

It supports redundant operation, durable-state reconstruction, partition detection, stale-coordinator detection, fencing, split-brain prevention, quorum-loss handling, failover, and verified return to service.

Recovered in-memory coordination state is reconstructed from authoritative durable state.

A replacement controller cannot resume authority until required reconciliation and verification gates pass.

## 11. Degraded Operation

If autonomous healing cannot safely resolve a failure, it stops escalating and preserves healthy operation.

The affected scope enters durable degraded mode.

Degraded mode protects healthy workloads, capacity, fabric paths, and control-plane resources.

The healing plane may reconsider recovery when materially new evidence or an authorized recovery capability becomes available, but it does not repeatedly mutate infrastructure without sufficient evidence.

## 12. Crash-Safe Recovery

Healing controller failure is handled through durable reconciliation.

On takeover, a controller reconciles healing state with authoritative system state before resuming work.

Ambiguous external effects require independent verification.

Durable generations, leases, fencing tokens, idempotency keys, immutable action history, intermediate states, checkpoints, and compensation records prevent stale controllers from executing obsolete actions.

The system never assumes an interrupted operation either fully succeeded or fully failed without evidence.

## 13. Standby Capacity

The healing plane may temporarily consume standby capacity when recovery evidence justifies it, but an immutable protected reserve floor remains outside autonomous healing authority.

Any action that would cross that floor must enter degraded mode instead.

Reserve consumption is attributable to a durable healing action and reconciled as capacity recovers.

The self-coordinating fabric remains authoritative for capacity allocation.

## 14. Learning and Experimentation

Healing outcomes become durable learning signals.

The system may learn failure patterns, recovery success rates, environmental conditions, and strategy effectiveness.

Experimental learning is isolated from production recovery policy.

Promotion requires evidence, provenance, safety floors, continuous availability of known-good recovery, and automatic rollback or demotion on regression.

Learning cannot override physical-path identity, authoritative verification, capacity floors, leases, fencing, or degraded-mode boundaries.

## 15. Durable Healing State

The healing plane has a dedicated durable state model with replicated state for controller/state-instance failure.

Its state includes, at minimum:

- healing plans;
- action generations;
- ownership and leases;
- fencing tokens;
- checkpoints;
- intermediate states;
- compensation records;
- action outcomes;
- degraded-mode state;
- reconciliation state;
- strategy provenance;
- learning evidence;
- promotion and rollback history.

This state is not a replacement for authoritative physical, placement, execution, or inventory state.

## 16. Recovery Closure

A healing action closes only when:

1. the intended remediation has completed;
2. the existing authoritative verification layers confirm the resulting system state;
3. healing-specific validation confirms the remediation itself succeeded;
4. no secondary damage introduced by the action remains unresolved;
5. durable healing state records the final outcome.

Failure of closure leaves the action recoverable or moves the affected scope into degraded mode.

## 17. Observability and Provenance

Every healing decision must be explainable from durable evidence.

Records must identify the affected scope, evidence observed, authority consulted, strategy selected, safety checks, action generation, owner, remediation steps, verification results, outcome, and learning consequences.

No production recovery behavior should depend on an untraceable heuristic.

## 18. Non-Goals

This layer does not:

- replace physical fabric verification;
- replace active-path intelligence;
- replace the recovery orchestrator;
- replace placement or capacity authorities;
- invent physical paths;
- infer shared failure causes without authoritative dependency evidence;
- continuously optimize infrastructure;
- consume protected standby capacity below its floor;
- make partially healed state authoritative without verification;
- discard durable healing work because of an arbitrary backlog limit;
- modify main as part of this GPU-fabric build.

## 19. Verification Requirements

Implementation must use behavior-first tests and production validation.

Coverage must include:

- adaptive containment and hard safety floors;
- independent simultaneous failures;
- reversible remediation;
- action leases and takeover;
- fencing and stale-generation rejection;
- concurrent independent healing;
- serialization of conflicting healing;
- transactional checkpoints;
- rollback and compensation;
- workload restart and migration;
- exact-path preservation;
- control-plane failover and reconstruction;
- split-brain and partition protection;
- degraded-mode entry;
- protected standby floor enforcement;
- crash-safe reconciliation;
- replicated healing state;
- learning provenance and strategy promotion/demotion;
- authoritative verification closure;
- restart persistence;
- idempotency.

Production validation must exercise the complete layer on feature/gpu-fabric-foundation without modifying main.

## 20. Architectural Invariants

The following invariants are mandatory:

1. Healing coordinates recovery but does not become a competing source of physical truth.
2. Adaptive intelligence cannot override hard safety floors.
3. Unknown or unsafe conditions become more conservative, not more invasive.
4. Independent failures remain independently scoped unless an authoritative dependency proves otherwise.
5. Concurrency requires proven independence; uncertainty requires serialization.
6. Stale controllers cannot act after fencing or generation changes.
7. Partial progress cannot silently become authoritative.
8. Workload migration requires authoritative destination capacity and verified exact paths.
9. Protected standby capacity always retains its immutable floor.
10. Known-good recovery capabilities remain continuously available while alternatives are being proven.
11. Failed autonomous healing stops escalating and preserves healthy operation through degraded mode.
12. Every production healing decision has durable evidence and provenance.
