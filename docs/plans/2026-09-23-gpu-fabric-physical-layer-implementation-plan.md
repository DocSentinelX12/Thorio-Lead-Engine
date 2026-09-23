# GPU Physical Fabric Intelligence Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the provider-neutral physical fabric intelligence layer that discovers GPU-to-NIC/RDMA locality, constructs concrete inter-node paths, verifies them, persists evidence and measurements, and feeds the existing placement/allocation/execution architecture without introducing a second execution system or any fixed hardware ceiling.

**Architecture:** Extend the existing `ComputeInventory`, topology, telemetry, placement, allocation, coordinator, worker, reconciliation, and validation boundaries. The new layer owns physical discovery, locality evidence, concrete path identity, verification state, and physical measurements; `ComputeAllocation` remains the reservation authority and the existing coordinator/worker path remains the execution authority.

**Tech Stack:** Python 3.10, SQLite, pytest/pytest-timeout, existing `lead_engine` fabric/topology modules, GitHub Actions `GPU Fabric Validation`.

## Global Constraints

- Work only on `feature/gpu-fabric-foundation`; do not modify `main`.
- The initial 12 computers are physical infrastructure, never a schema, scheduler, workflow, or algorithmic ceiling.
- Preserve the existing placement intelligence and `ComputeAllocation` reservation boundary.
- Preserve the existing coordinator/worker execution path.
- Do not create a second scheduler, allocator, queue, worker system, or execution system.
- Do not fabricate PCIe, NUMA, NIC, RDMA, topology, performance, health, or connectivity evidence.
- Discovery, construction, verification, and measurement remain distinct evidence states.
- Preserve multiple valid physical paths and observations.
- Keep historical evidence instead of destructively replacing it with current state.
- Scope failures to the narrowest evidence-supported domain.
- Do not discard excess resources, paths, providers, or observations.
- Use TDD: add a focused failing test before implementation, verify the failure, implement the smallest production behavior, then run focused and affected integration tests.
- Every independently passing deliverable gets a small commit.
- Before claiming completion, run the affected production validation workflow and report its actual result.

---

### Task 1: Canonical physical inventory and evidence persistence

**Files:**
- Modify: `lead_engine/compute_inventory.py`
- Modify: `lead_engine/compute_resources.py` only if an existing resource type must carry the canonical physical identity without duplicating it
- Test: `tests/test_fabric_physical_inventory.py` (create)
- Reference: existing `lead_engine/compute_inventory.py` tables `compute_resource_inventory`, `compute_fabric_path_health`, `compute_fabric_route_observations`, and `compute_placements`

**Interfaces:**
- Consumes: existing `ProviderResourceSnapshot`, `NodeResource`, `GpuResource`, existing evidence dictionaries, and current SQLite inventory connection lifecycle.
- Produces: canonical physical component observations, stable component identities, idempotent discovery reconciliation, and durable physical evidence APIs used by Tasks 2 through 5.

- [ ] **Step 1: Add focused failing tests**
  - Verify a discovered GPU, NIC, RDMA device/port, PCI identity, and NUMA identity can be persisted with provider/domain/node context.
  - Verify absent optional physical fields remain explicit unknown values rather than inferred values.
  - Verify repeating the same discovery observation converges on one physical identity and does not create duplicates.
  - Verify two independently valid NIC/RDMA observations for one GPU are both retained.
  - Verify a newer observation changes current state without deleting the prior evidence.
  - Verify identities are not derived from list position or transient ordering when stable identity evidence exists.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m pytest -vv -ra --tb=short tests/test_fabric_physical_inventory.py`
  - Expected: the new physical inventory API/tests fail because the canonical physical records and reconciliation contract do not yet exist.

- [ ] **Step 3: Implement the minimum behavior**
  - Add durable physical component/path evidence tables through the existing `ComputeInventory._initialize()` connection and migration pattern.
  - Use stable canonical identity material from explicit provider/hardware identifiers; never synthesize stronger identity from ordering.
  - Store current state separately from immutable observation/evidence records.
  - Use idempotent keys for repeated observations.
  - Keep optional fields nullable/unknown.
  - Do not change existing allocation or placement persistence semantics.
  - Keep all new persistence provider-neutral.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m pytest -vv -ra --tb=short tests/test_fabric_physical_inventory.py`
  - Expected: all new physical inventory tests pass.

- [ ] **Step 5: Run affected integration checks**
  - Run: `python -m pytest -vv -ra --tb=short tests/test_fabric_intelligence.py lead_engine/test_compute_scheduler.py lead_engine/test_compute_fabric.py`
  - Expected: existing inventory, scheduler, and fabric regressions remain green.

- [ ] **Step 6: Commit the passing deliverable**
  - `git add lead_engine/compute_inventory.py lead_engine/compute_resources.py tests/test_fabric_physical_inventory.py`
  - `git commit -m "feat: add durable physical fabric inventory"`

---

### Task 2: Evidence-backed PCIe, NUMA, NIC, and RDMA locality graph

**Files:**
- Modify: `lead_engine/fabric_topology.py`
- Modify: `lead_engine/fabric_topology_runtime.py`
- Modify: `lead_engine/compute_inventory.py` only where Task 1 persistence APIs must be consumed
- Test: `tests/test_fabric_physical_locality.py` (create)
- Reference: existing topology reconciliation/runtime interfaces

**Interfaces:**
- Consumes: Task 1 physical component identities and existing runtime topology evidence.
- Produces: typed GPU-to-PCIe-to-NUMA-to-NIC-to-RDMA locality relationships with explicit evidence state for path construction.

- [ ] **Step 1: Add focused failing tests**
  - Verify a GPU-to-NIC relationship is accepted only when explicit locality evidence correlates the identities.
  - Verify PCIe and NUMA relationships remain unknown when not supplied.
  - Verify same-node co-existence does not create locality.
  - Verify multiple NICs and RDMA ports can be related to one GPU without a fixed count.
  - Verify conflicting locality evidence is represented as conflict/unknown rather than resolved by guessing.
  - Verify repeated topology reconciliation is deterministic.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m pytest -vv -ra --tb=short tests/test_fabric_physical_locality.py`
  - Expected: locality tests fail until the typed physical relationships are exposed.

- [ ] **Step 3: Implement the minimum behavior**
  - Extend the existing topology graph rather than creating a second topology authority.
  - Normalize explicit PCI, NUMA, NIC, RDMA device, and port identities.
  - Represent each edge with provenance/evidence and an explicit known/unknown state.
  - Preserve all valid relationships.
  - Reject ambiguous or contradictory correlations from being promoted to verified locality.
  - Keep topology provider-neutral.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m pytest -vv -ra --tb=short tests/test_fabric_physical_locality.py`
  - Expected: all locality tests pass.

- [ ] **Step 5: Run affected integration checks**
  - Run: `python -m pytest -vv -ra --tb=short lead_engine/test_fabric.py lead_engine/test_compute_fabric.py tests/test_fabric_intelligence.py`
  - Expected: existing fabric/topology behavior remains green.

- [ ] **Step 6: Commit the passing deliverable**
  - `git add lead_engine/fabric_topology.py lead_engine/fabric_topology_runtime.py lead_engine/compute_inventory.py tests/test_fabric_physical_locality.py`
  - `git commit -m "feat: add evidence-backed GPU fabric locality"`

---

### Task 3: Concrete fabric path construction and verification state machine

**Files:**
- Create: `lead_engine/physical_fabric.py`
- Modify: `lead_engine/fabric_topology.py` only for shared topology/path contracts that belong to the existing topology authority
- Modify: `lead_engine/compute_inventory.py` for durable concrete path and verification evidence
- Test: `tests/test_physical_fabric.py` (create)

**Interfaces:**
- Consumes: Task 2 locality graph, existing workload/placement requirements, and existing fabric verification/runtime evidence.
- Produces: stable `PhysicalFabricPath` identity, hierarchical path construction, verification lifecycle, failure-domain evidence, and path-level capability observations.

- [ ] **Step 1: Add focused failing tests**
  - Verify a complete source-GPU-to-destination-GPU path includes both endpoint locality chains and a fabric domain.
  - Verify incomplete locality cannot produce a verified path.
  - Verify path construction preserves multiple valid NIC/RDMA/fabric alternatives.
  - Verify candidate construction is hierarchical and does not enumerate impossible combinations.
  - Verify path state transitions are monotonic through `DISCOVERED`, `CONSTRUCTED`, `VERIFIED`, and `MEASURED`, while degradation/failure/recovery retain history.
  - Verify verification records identify the exact path and verification stage.
  - Verify generic endpoint existence cannot mark GPU-to-GPU communication verified.
  - Verify no fixed maximum is applied to nodes, GPUs, NICs, RDMA ports, paths, or fabric domains.
  - Verify invalid or contradictory evidence produces a rejected/unverified path with a reason, not a guessed path.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m pytest -vv -ra --tb=short tests/test_physical_fabric.py`
  - Expected: path/verification tests fail because the concrete path contract and state machine are not implemented.

- [ ] **Step 3: Implement the minimum behavior**
  - Define provider-neutral path dataclasses/protocols in `lead_engine/physical_fabric.py`.
  - Build paths from indexed eligible endpoints instead of unrestricted Cartesian products.
  - Preserve every valid candidate unless it fails an explicit hard compatibility gate.
  - Require evidence for each required path segment before promotion to verified.
  - Persist path identity and verification observations idempotently.
  - Keep verification depth workload-dependent: CPU-only paths do not require GPU communication proof; distributed GPU workloads do.
  - Record exact failure domains without broad quarantine.
  - Do not create an executor or scheduler.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m pytest -vv -ra --tb=short tests/test_physical_fabric.py`
  - Expected: all path construction and verification tests pass.

- [ ] **Step 5: Run affected integration checks**
  - Run: `python -m pytest -vv -ra --tb=short tests/test_physical_fabric.py tests/test_fabric_placement.py lead_engine/test_compute_fabric.py lead_engine/test_compute_execution_fabric.py`
  - Expected: path/placement/execution fabric regressions remain green.

- [ ] **Step 6: Commit the passing deliverable**
  - `git add lead_engine/physical_fabric.py lead_engine/fabric_topology.py lead_engine/compute_inventory.py tests/test_physical_fabric.py`
  - `git commit -m "feat: add concrete physical fabric paths"`

---

### Task 4: Measurement, placement integration, execution feedback, and continuous recovery

**Files:**
- Modify: `lead_engine/compute_fabric_telemetry.py`
- Modify: `lead_engine/compute_placement.py`
- Modify: `lead_engine/compute_scheduler.py`
- Modify: `lead_engine/compute_coordinator.py`
- Modify: `lead_engine/compute_reconciliation.py`
- Modify: `lead_engine/compute_inventory.py`
- Modify: `.github/workflows/gpu-fabric-validation.yml` only if a dependency/order gap is proven by the failing production run
- Test: `tests/test_fabric_physical_integration.py` (create)

**Interfaces:**
- Consumes: Task 3 verified physical paths and existing placement/allocation/execution telemetry.
- Produces: path-bound measurements, placement consumption of physical evidence, narrow failure classification, reverification-aware recovery, and end-to-end physical path traceability.

- [ ] **Step 1: Add focused failing tests**
  - Verify a measurement persists with exact path identity, placement identity, workload signature, and execution attempt where available.
  - Verify placement rejects a candidate when required physical path evidence is incomplete.
  - Verify placement can consume multiple verified physical paths without imposing a path count ceiling.
  - Verify a path failure is classified at path/RDMA/NIC/GPU scope when that is the proven scope, without poisoning the node.
  - Verify unresolved evidence remains unresolved.
  - Verify recovery retains the failed path evidence and requires a fresh verified path before producing a replacement placement.
  - Verify execution telemetry feeds observed path measurements back without inventing health scores.
  - Verify existing `ComputeAllocation` remains the only reservation authority.
  - Verify the existing coordinator/worker execution path remains the only execution authority.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m pytest -vv -ra --tb=short tests/test_fabric_physical_integration.py`
  - Expected: integration tests fail on the new path-bound measurement and recovery contracts before implementation.

- [ ] **Step 3: Implement the minimum behavior**
  - Extend existing telemetry records rather than introducing a parallel telemetry authority.
  - Carry `fabric_path_id` through placement/allocation/execution evidence where a concrete path exists.
  - Feed verified physical path evidence into the existing placement evaluator as a hard physical gate before performance/route preferences.
  - Preserve the existing allocation lease/reservation flow.
  - Reuse existing coordinator/recovery paths and narrow failure classifier.
  - On physical path failure, preserve evidence, reconstruct complete candidates, and require fresh verification before replacement execution.
  - Keep historical measurements immutable and derive current capability state from observations.
  - Do not add a new worker, scheduler, or queue.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m pytest -vv -ra --tb=short tests/test_fabric_physical_integration.py tests/test_fabric_intelligence.py tests/test_fabric_placement.py`
  - Expected: all new integration tests and existing placement/intelligence tests pass.

- [ ] **Step 5: Run the full existing production test command**
  - Run: `python -m pytest -vv -ra --tb=short --timeout=120 lead_engine/test_nvidia_provider.py`
  - Then run the regression set already defined by `.github/workflows/gpu-fabric-validation.yml`.
  - Expected: the complete existing GPU discovery and compute/fabric regression suite passes.

- [ ] **Step 6: Run production workflow verification**
  - Run the repository's existing `GPU Fabric Validation` workflow on `feature/gpu-fabric-foundation`.
  - Expected: the workflow completes successfully with all existing jobs green.
  - If it fails, inspect the exact failing test/log before changing code. Do not infer a fix from the workflow name alone.

- [ ] **Step 7: Commit the passing deliverable**
  - `git add lead_engine/compute_fabric_telemetry.py lead_engine/compute_placement.py lead_engine/compute_scheduler.py lead_engine/compute_coordinator.py lead_engine/compute_reconciliation.py lead_engine/compute_inventory.py tests/test_fabric_physical_integration.py`
  - Add the workflow file only if a proven dependency-order defect requires it.
  - `git commit -m "feat: integrate physical fabric intelligence"`

---

## Repository-Level Verification

After Task 4:

1. Confirm the working branch is `feature/gpu-fabric-foundation`.
2. Confirm `main` has no commits from this implementation.
3. Run the complete `GPU Fabric Validation` workflow.
4. Run the complete affected pytest set locally/in CI.
5. Inspect the final diff for accidental workflow, schema, or execution-boundary changes.
6. Verify there is exactly one scheduler, one allocation authority, and one coordinator/worker execution path.
7. Verify no fixed 12-node, GPU-count, NIC-count, RDMA-count, or path-count constant was introduced.
8. Verify every production claim is supported by fresh test/workflow output.

## Unresolved Product Decisions

None remain from the approved design. Provider-specific discovery commands and hardware APIs are implementation details constrained by the evidence contracts above, not unresolved product behavior.
