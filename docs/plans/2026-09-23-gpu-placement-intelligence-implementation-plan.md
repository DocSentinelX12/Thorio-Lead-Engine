# GPU Placement Intelligence Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing GPU fabric scheduler from individual GPU ranking into complete, deterministic, auditable multi-GPU and multi-node placement intelligence while preserving the existing allocation, coordinator, worker, verification, telemetry, and recovery boundaries.

**Architecture:** Build complete placement candidates from the already verified inventory and physical fabric evidence, apply hard validity gates before workload and route intelligence, and persist a first-class placement explanation alongside the existing authoritative `ComputeAllocation`. Feed only verified execution observations back into the existing performance and route-health indexes, and keep recovery in `ComputeCoordinator` and its existing fencing/reconciliation machinery.

**Tech Stack:** Python 3.10, dataclasses, SQLite, pytest, existing `ComputeScheduler`, `ComputeInventory`, `ComputeCoordinator`, `ComputeRequirements`, `ComputeAllocation`, and the existing GitHub Actions workflow `GPU Fabric Validation`.

## Global Constraints

- Work only on `feature/gpu-fabric-foundation`; do not modify `main`.
- The initial 12 computers are the physical foundation, not an architectural ceiling.
- Do not impose fixed limits on nodes, GPUs, providers, NICs, RDMA endpoints, topology domains, or observations.
- Do not create a second execution fabric, allocation system, coordinator, worker system, recovery system, or reconciliation system.
- `ComputeAllocation` remains the authoritative durable reservation and execution boundary.
- Placement intelligence must validate complete GPU sets, not merely rank individual GPUs.
- Hard validity gates precede performance and route-health intelligence.
- Unknown evidence remains unknown. Never fabricate topology, latency, bandwidth, health, or performance values.
- Preserve provider-neutral behavior and use only verified inventory/topology/device facts.
- Placement decisions must be deterministic and explainable through explicit evidence and rejection reasons.
- Only observed execution results may update workload-performance or route-health intelligence.
- Preserve original placement and failure evidence during recovery and exclude only resources or paths concretely established as unusable.
- Do not add arbitrary history expiration or sample-count ceilings.
- Keep the existing `GPU Fabric Validation` workflow as the production gate and do not introduce a parallel validation workflow.
- No credentials, tokens, cookies, passwords, or secrets may be committed.
- Run all affected tests before declaring a change complete.

---

### Task 1: Build complete placement candidates and deterministic placement decisions

**Files:**
- Create: `lead_engine/compute_placement.py`
- Modify: `lead_engine/compute_scheduler.py`
- Test: `tests/test_fabric_placement.py`
- Test: `lead_engine/test_compute_scheduler.py`

**Interfaces:**
- Consumes: `ComputeRequirements`, eligible inventory rows from `ComputeInventory.eligible()`, existing verified GPU/NIC/RDMA evidence, topology and NUMA fields, `workload_performance_key()`, and `ComputeScheduler` route-health/performance providers.
- Produces: immutable placement candidate/decision records containing selected resource identities, nodes, verified endpoints, physical/topology evidence, workload/route evidence, rejection reasons, and a deterministic decision trace. The final decision must expose the exact resource set that `ComputeAllocation` will reserve.

- [ ] **Step 1: Add the focused failing tests**

Add tests proving complete-set behavior rather than individual GPU behavior:
1. Two individually eligible GPUs with incomplete or unverifiable interconnect evidence are rejected as a distributed candidate.
2. Two individually eligible GPUs with complete GPU-to-NIC-to-RDMA evidence and a verified common network domain form a valid candidate.
3. A multi-node candidate is rejected when one participant lacks a required verified physical path.
4. A valid candidate with stronger workload-specific observed performance is selected over another physically valid candidate with weaker observed performance.
5. A candidate with unknown route health remains eligible but does not receive fabricated health values.
6. A physically invalid candidate cannot become selected because it has better historical performance.
7. Equivalent valid candidates produce the same resource ordering and decision trace across repeated evaluation.
8. Candidate rejection evidence identifies the failed validity stage and the affected resource/path without inventing a failure reason.
9. NUMA and topology locality are preserved in complete candidate construction.
10. Heterogeneous GPU capabilities are evaluated per participant before candidate construction.

- [ ] **Step 2: Verify the relevant failure**

Run:
`python -m pytest -vv -ra --tb=short tests/test_fabric_placement.py lead_engine/test_compute_scheduler.py`

Expected: the new placement tests fail because complete placement construction, explicit candidate rejection records, and first-class deterministic placement decisions are not yet implemented.

- [ ] **Step 3: Implement the minimum behavior**

Implement `lead_engine/compute_placement.py` as a provider-neutral placement vocabulary and evaluator. Keep the existing scheduler helpers as the source of verified physical facts rather than duplicating device validation.

The evaluator must:
1. Start with individually eligible GPUs that already satisfy `_gpu_matches()` and the existing capability requirements.
2. Construct complete single-node and multi-node GPU sets from compatible nodes and verified topology/network domains.
3. Require every selected GPU to have the physical evidence required by the workload and every required GPU-to-NIC and NIC-to-RDMA relationship to be verified.
4. For multi-node candidates, require a verified shared execution domain and complete inter-node communication evidence. A shared network label alone is not sufficient when concrete endpoint/path evidence is required by the workload.
5. Preserve topology-domain and NUMA relationships as evidence rather than reducing them to an opaque score.
6. Reject incomplete or unverifiable physical candidates before reading workload performance or route-health preference.
7. Apply workload-specific performance history only to candidates that pass all hard physical gates.
8. Apply observed route health only after physical validity and workload evidence.
9. Use stable resource identity ordering as the final tie-breaker.
10. Record a structured decision trace with each evaluation stage, selected evidence, and candidate rejection reason.
11. Keep unknown evidence explicit and never synthesize a default bandwidth, latency, health, or performance value.
12. Avoid any fixed candidate-count, node-count, GPU-count, or history-count limit.
13. Preserve the existing `ComputeAllocation` return contract from `ComputeScheduler.allocate()`; the placement object explains and precedes allocation rather than replacing it.

Refactor `ComputeScheduler._candidates()` and `allocate()` only as necessary to delegate complete candidate construction and final deterministic ordering to the new evaluator. Do not rewrite existing provider, inventory, worker, or coordinator logic in this task.

- [ ] **Step 4: Verify the focused pass**

Run:
`python -m pytest -vv -ra --tb=short tests/test_fabric_placement.py lead_engine/test_compute_scheduler.py`

Expected: all new complete-placement tests and all existing scheduler tests pass, including existing topology, NUMA, network-domain, fabric-path, performance-history, and allocation-reservation behavior.

- [ ] **Step 5: Run the affected integration check**

Run:
`python -m pytest -vv -ra --tb=short tests/test_fabric_intelligence.py tests/test_fabric_topology.py lead_engine/test_compute_execution_fabric.py lead_engine/test_compute_worker_fabric_lifecycle.py lead_engine/test_compute_scheduler.py`

Expected: the existing intelligence, topology, execution-fabric, worker-lifecycle, and scheduler regressions pass with no change to the existing `ComputeAllocation` contract.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add lead_engine/compute_placement.py lead_engine/compute_scheduler.py tests/test_fabric_placement.py lead_engine/test_compute_scheduler.py
git commit -m "feat: construct complete GPU placements"
```

---

### Task 2: Persist first-class placement evidence without creating a second allocation system

**Files:**
- Modify: `lead_engine/compute_inventory.py`
- Modify: `lead_engine/compute_scheduler.py`
- Modify: `lead_engine/compute_coordinator.py`
- Test: `tests/test_fabric_placement.py`
- Test: `lead_engine/test_compute_inventory.py`
- Test: `lead_engine/test_compute_coordinator.py`

**Interfaces:**
- Consumes: the complete placement decision produced by Task 1 and the existing `ComputeAllocation` returned by `ComputeScheduler.allocate()`.
- Produces: durable placement records retrievable by `placement_id`, while `ComputeInventory.reserve_allocation()` and `ComputeAllocation` remain authoritative for resource reservation and execution.

- [ ] **Step 1: Add the focused failing tests**

Add tests proving:
1. A successful placement persists selected GPU and node identities.
2. Verified NIC/RDMA endpoints, physical path evidence, topology/NUMA evidence, workload signature, performance evidence, route-health evidence, candidate/rejection evidence, and decision trace are persisted without loss.
3. Placement identity is stable for identical stable inputs and does not change merely because observation timestamps differ.
4. Placement records include schema/version information.
5. Placement persistence is idempotent for the same placement identity.
6. A placement record does not create or reserve resources independently of the existing `ComputeAllocation`.
7. Binding an allocation through `ComputeCoordinator.bind_physical_allocation()` can reference the persisted placement without replacing the existing allocation boundary.
8. Released allocations do not silently erase the historical placement record.

- [ ] **Step 2: Verify the relevant failure**

Run:
`python -m pytest -vv -ra --tb=short tests/test_fabric_placement.py lead_engine/test_compute_inventory.py lead_engine/test_compute_coordinator.py`

Expected: persistence and placement retrieval tests fail because the durable placement table and scheduler/coordinator placement boundary do not yet exist.

- [ ] **Step 3: Implement the minimum behavior**

Add one durable placement table to `ComputeInventory` with:
- `placement_id` primary key
- stable workload signature JSON
- selected GPU/resource IDs JSON
- selected node IDs JSON
- verified NIC/RDMA endpoint JSON
- physical path evidence JSON
- topology/NUMA evidence JSON
- workload-performance evidence JSON
- route-health evidence JSON
- candidate/rejection evidence JSON
- deterministic decision trace JSON
- `created_at`
- placement schema/version field

Compute the placement identity only from stable placement inputs such as provider/domain, workload signature, selected resources, verified path/topology identity, and decision semantics. Do not include volatile timestamps or mutable observation counters in the identity.

Expose focused inventory methods:
- `persist_placement(placement)`
- `placement(placement_id)`
- `placements(...)` for deterministic historical inspection

Have `ComputeScheduler.allocate()` persist the verified placement immediately before or as part of the existing reservation boundary, with failure behavior that prevents an orphaned placement from being presented as successfully allocated.

Extend the existing allocation evidence returned by `ComputeAllocation.capability_evidence` only with placement identity and explicit decision evidence. Do not add a second reservation record.

Extend `ComputeCoordinator` only enough to retain the placement identity on the existing execution attempt/allocation boundary. The coordinator must continue to use `bind_physical_allocation()`, `ComputeInventory.bind_allocation()`, and the existing participant launch machinery.

- [ ] **Step 4: Verify the focused pass**

Run:
`python -m pytest -vv -ra --tb=short tests/test_fabric_placement.py lead_engine/test_compute_inventory.py lead_engine/test_compute_coordinator.py`

Expected: placement persistence, idempotency, stable identity, allocation-boundary, and historical-retention tests pass.

- [ ] **Step 5: Run the affected integration check**

Run:
`python -m pytest -vv -ra --tb=short lead_engine/test_compute_execution_fabric.py lead_engine/test_compute_worker_fabric_lifecycle.py lead_engine/test_compute_path_recovery.py lead_engine/test_compute_reconciliation.py`

Expected: the existing execution, worker lifecycle, path recovery, and reconciliation flows continue to use the same allocation and execution tables and APIs.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add lead_engine/compute_inventory.py lead_engine/compute_scheduler.py lead_engine/compute_coordinator.py tests/test_fabric_placement.py lead_engine/test_compute_inventory.py lead_engine/test_compute_coordinator.py
git commit -m "feat: persist GPU placement evidence"
```

---

### Task 3: Close the placement-to-execution feedback and evidence-driven recovery loop

**Files:**
- Modify: `lead_engine/compute_coordinator.py`
- Modify: `lead_engine/compute_inventory.py`
- Modify: `lead_engine/compute_fabric_telemetry.py`
- Modify: `lead_engine/compute_scheduler.py`
- Test: `tests/test_fabric_placement.py`
- Test: `tests/test_fabric_intelligence.py`
- Test: `lead_engine/test_compute_path_recovery.py`
- Test: `lead_engine/test_compute_reconciliation.py`

**Interfaces:**
- Consumes: persisted placement identity, existing execution verification evidence, `extract_execution_metrics()`, route observations, existing recovery events, and the existing coordinator/reconciliation APIs.
- Produces: verified feedback tied to the exact placement/attempt/generation and replacement scheduling that reuses the same complete-placement validation path.

- [ ] **Step 1: Add the focused failing tests**

Add tests proving:
1. Verified execution metrics retain placement identity, workload identity, physical path identity, generation, attempt, worker, and observed time.
2. Successful observed all-reduce results update workload-specific performance and route-health evidence without fabricating missing fields.
3. A verification result that does not identify a physical path does not create a fake route observation.
4. Intended-versus-actual placement discrepancies are retained as evidence.
5. A concrete GPU/path failure narrows recovery exclusion to the affected resource/path.
6. An unresolved failure records the failure evidence but does not quarantine every GPU in the allocation.
7. A replacement allocation is evaluated through the same complete physical validity gates before performance and route intelligence.
8. The replacement receives a new placement identity while the original placement and failure evidence remain queryable.
9. A stale generation cannot mutate the newer placement or execution attempt.
10. Repeated identical execution evidence is idempotent.

- [ ] **Step 2: Verify the relevant failure**

Run:
`python -m pytest -vv -ra --tb=short tests/test_fabric_placement.py tests/test_fabric_intelligence.py lead_engine/test_compute_path_recovery.py lead_engine/test_compute_reconciliation.py`

Expected: the new placement feedback and narrow failure-domain assertions fail where placement identity is not yet carried through execution and recovery.

- [ ] **Step 3: Implement the minimum behavior**

Extend the existing verification path in `ComputeCoordinator.record_execution_verification()` rather than creating another telemetry pipeline.

The implementation must:
1. Resolve the persisted placement from the exact allocation/attempt.
2. Preserve placement identity with execution metrics.
3. Continue using `extract_execution_metrics()` and `workload_performance_key()` as the source of workload-specific observed performance.
4. Continue recording route observations only when an actual physical path is present in verified execution evidence.
5. Record intended-versus-actual path or GPU binding mismatches as evidence.
6. Keep `recover_fabric_attempt()`, `reconcile_fabric()`, and existing path quarantine/revalidation authoritative for fencing and recovery.
7. Classify a failure domain only from explicit evidence. If the evidence cannot distinguish GPU, node, GPU-NIC path, NIC/RDMA endpoint, inter-node route, workload path, or attempt, record the domain as unresolved rather than guessing.
8. Exclude a resource/path only when concrete evidence establishes it as unusable. Preserve transient or unexplained failures as historical evidence without permanent poisoning.
9. Requeue through the existing recovery path and let the next physical claim run the complete placement evaluator from Task 1.
10. Ensure the replacement gets a new placement identity and trace while the original placement remains immutable historical evidence.

Do not alter the existing lease, generation fence, participant binding, or recovery state machine except where placement identity must be carried alongside it.

- [ ] **Step 4: Verify the focused pass**

Run:
`python -m pytest -vv -ra --tb=short tests/test_fabric_placement.py tests/test_fabric_intelligence.py lead_engine/test_compute_path_recovery.py lead_engine/test_compute_reconciliation.py`

Expected: placement feedback, evidence retention, narrow failure-domain handling, replacement placement, and stale-generation tests pass.

- [ ] **Step 5: Run the affected integration check**

Run:
`python -m pytest -vv -ra --tb=short lead_engine/test_compute_coordinator.py lead_engine/test_compute_execution_fabric.py lead_engine/test_compute_worker_fabric_lifecycle.py lead_engine/test_compute_process_group.py lead_engine/test_compute_remote_contract.py`

Expected: the existing coordinator, execution fabric, worker lifecycle, process-group, and remote-contract tests pass without introducing a second execution boundary.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add lead_engine/compute_coordinator.py lead_engine/compute_inventory.py lead_engine/compute_fabric_telemetry.py lead_engine/compute_scheduler.py tests/test_fabric_placement.py tests/test_fabric_intelligence.py lead_engine/test_compute_path_recovery.py lead_engine/test_compute_reconciliation.py
git commit -m "feat: close placement feedback and recovery loop"
```

---

### Task 4: Prove the full architecture through the existing production gate

**Files:**
- Modify: `tests/test_fabric_placement.py`
- Modify: `tests/test_fabric_intelligence.py`
- Modify: `tests/test_fabric_topology.py` only if an existing topology assertion must be extended
- Modify: `lead_engine/test_compute_scheduler.py` only if an existing scheduler regression needs a placement-reason assertion
- Modify: `lead_engine/test_compute_coordinator.py` only if an existing coordinator assertion needs placement identity coverage
- Modify: `docs/COMPUTE_FABRIC_ARCHITECTURE.md` to document the completed placement boundary
- Do not create a new workflow

**Interfaces:**
- Consumes: all placement, persistence, feedback, and recovery behavior from Tasks 1 through 3.
- Produces: a production-gate-verifiable proof that complete placement intelligence preserves the existing execution architecture.

- [ ] **Step 1: Add the focused failing coverage**

Ensure the final test matrix explicitly covers:
1. Complete valid single-node placement.
2. Complete valid multi-node placement.
3. Invalid or incomplete physical path rejection.
4. Capability and heterogeneous-GPU rejection.
5. Topology and NUMA preservation.
6. Workload-specific performance ordering after hard gates.
7. Route-health ordering with known evidence and neutral handling of unknown evidence.
8. Stable deterministic equivalent-candidate ordering.
9. Explicit candidate rejection reasons and final decision trace.
10. Durable placement persistence and stable identity.
11. Placement to execution verification feedback.
12. Failure-domain evidence preservation and replacement placement.
13. Scaling behavior without a hardcoded 12-node or 12-GPU limit.

- [ ] **Step 2: Verify the relevant failure**

Run the complete existing production command from `.github/workflows/gpu-fabric-validation.yml` locally:

`python -m pytest -vv -ra --tb=short --timeout=120 tests/test_fabric_intelligence.py lead_engine/test_agent_queue.py lead_engine/test_compute_remote_contract.py lead_engine/test_compute_execution_fabric.py lead_engine/test_compute_fabric.py lead_engine/test_compute_worker_fabric_lifecycle.py lead_engine/test_compute_scheduler.py lead_engine/test_compute_checkpoints.py lead_engine/test_compute_lead_persistence.py lead_engine/test_compute_bridge.py lead_engine/test_research_section_checkpoints.py lead_engine/test_public_research_checkpoints.py lead_engine/test_handoff_recovery.py lead_engine/test_revenue_execution.py lead_engine/test_revenue_conversation.py`

Expected: any newly added placement assertions fail before the final implementation is wired into all existing paths.

- [ ] **Step 3: Implement the minimum documentation/test integration**

Update the architecture documentation to describe:
- complete placement as the intelligence unit
- `ComputeAllocation` as the reservation boundary
- existing coordinator/worker execution as the execution boundary
- observed workload and route feedback
- evidence classes and unknown handling
- recovery replacement flow
- provider-neutral scaling beyond the initial 12 computers

Keep documentation descriptive and consistent with the committed design spec. Do not introduce new workflows or duplicate existing execution concepts.

- [ ] **Step 4: Verify the focused pass**

Run the complete production test command from Step 2.

Expected: all tests pass with no skipped placement cases and no regression to existing compute-fabric behavior.

- [ ] **Step 5: Run the production workflow**

Dispatch the existing `GPU Fabric Validation` workflow on `feature/gpu-fabric-foundation`.

Expected: the workflow completes successfully, including the existing GPU discovery contract and the complete regression suite. Verify the successful run is attached to the implementation commit.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add docs/COMPUTE_FABRIC_ARCHITECTURE.md tests/test_fabric_placement.py tests/test_fabric_intelligence.py tests/test_fabric_topology.py lead_engine/test_compute_scheduler.py lead_engine/test_compute_coordinator.py
git commit -m "test: verify GPU placement intelligence end to end"
```

---

## Unresolved externally observable decisions

- **Placement record retention policy:** The design requires historical placement evidence to remain available and forbids arbitrary history-size ceilings, but it does not define a separate archival or deletion mechanism. Recommendation: retain placement records under the same durable-storage lifecycle as existing compute execution evidence until a later storage-retention requirement is explicitly approved.
- **Failure-domain classification precedence:** The design defines the allowed domains but does not define a precedence when one concrete failure contains multiple independent symptoms. Recommendation: record every directly evidenced affected domain in the failure evidence and use the narrowest directly evidenced domain for quarantine/replacement decisions; use `unresolved` when no domain is established.
- **Candidate enumeration strategy at very large scale:** The design permits hierarchical candidate construction but does not mandate a particular topology index. Recommendation: start with the existing provider/domain/network/topology grouping and introduce additional hierarchical indexing only when measured inventory size makes the current deterministic candidate construction materially expensive. No fixed cap should be introduced as a workaround.

## Execution Handoff

Saved plan artifact: `docs/plans/2026-09-23-gpu-placement-intelligence-implementation-plan.md`

Recommended execution mode after plan review:
1. **Inline Execution** using the available `executing-plans` workflow for task-by-task implementation with blockers surfaced immediately.
2. **Subagent-Driven** only if a suitable subagent workflow is exposed by the host and the user explicitly wants independent task workers.

