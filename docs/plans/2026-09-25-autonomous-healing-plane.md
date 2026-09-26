# Autonomous Healing Plane Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dedicated Autonomous Healing Plane on `feature/gpu-fabric-foundation` that detects demonstrated failures, contains them safely, performs reversible transactional recovery across infrastructure, workloads, and control-plane components, verifies closure, learns from outcomes, and preserves degraded-mode safety without becoming a continuous infrastructure optimizer.

**Architecture:** Add a dedicated healing subsystem above the existing physical-fabric, active-path intelligence, recovery orchestrator, placement, execution-feedback, self-optimizing control-plane, and self-coordinating-fabric authorities. The healing subsystem owns healing decisions and durable healing lifecycle state, while existing lower layers remain authoritative for physical reality, exact path identity, measurements, capacity, placement, execution truth, and physical recovery gates.

**Tech Stack:** Python, SQLite, pytest, existing `lead_engine` modules, GitHub Actions GPU validation.

## Global Constraints

- Work only on `feature/gpu-fabric-foundation`; do not modify `main`.
- Do not invent physical paths, worker identities, GPU health, placement authority, or execution truth.
- Treat simultaneous failures independently unless an authoritative dependency establishes a relationship.
- Adaptive decisions cannot override hard safety floors.
- Protected standby capacity retains an immutable floor.
- Proven-good recovery capabilities remain continuously available while alternatives are evaluated.
- Conflicting or uncertain healing actions serialize; proven-independent actions may run concurrently.
- Every action is durable, leased, generation-aware, fenced, idempotent, and provenance-bearing.
- Partial healing cannot become authoritative without required verification.
- Failed autonomous healing stops escalating and enters durable degraded mode.
- Workload migration requires authoritative destination capacity and verified exact fabric paths.
- Control-plane recovery must prevent stale controllers and split-brain behavior.
- Healing state is a dedicated authority for healing lifecycle state only and cannot compete with existing physical, placement, execution, inventory, or recovery authorities.
- No arbitrary backlog cap or work discard.
- Use behavior-first TDD for each deliverable: add a focused failing test, observe the relevant failure, implement the minimum behavior, rerun the focused test, then run the affected integration check.
- Production validation must run against the complete feature on `feature/gpu-fabric-foundation` before claiming completion.

---

### Task 1: Durable healing state and crash-safe action lifecycle

**Files:**
- Create: `lead_engine/autonomous_healing.py` (proposed, dedicated healing coordinator and public interfaces)
- Create: `lead_engine/healing_state.py` (proposed, dedicated SQLite state authority)
- Test: `lead_engine/test_healing_state.py`
- Test: `lead_engine/test_autonomous_healing.py`

**Interfaces:**
- Consumes: `ComputeInventory`, `RecoveryOrchestrator`, exact path identifiers, authoritative capacity/placement results, and execution/control-plane evidence.
- Produces: durable healing actions, leases, fencing generations, checkpoints, compensation records, degraded-mode records, reconciliation results, and closure decisions.

- [ ] **Step 1: Add the focused failing tests**
  - Create a durable action with a unique healing generation and idempotency identity.
  - Claim an action with an owner and lease.
  - Reject a stale generation after a newer generation exists.
  - Reject an old owner after fencing/takeover.
  - Persist checkpoints and compensation boundaries.
  - Reopen a fresh controller against the same SQLite state and recover the action lifecycle.
  - Reconcile an interrupted action against authoritative state before resuming.
  - Preserve every durable action without a backlog cap.

- [ ] **Step 2: Verify the relevant failures**
  - Run: `pytest -q lead_engine/test_healing_state.py lead_engine/test_autonomous_healing.py`
  - Expected: collection/import or missing-interface failures proving the new durable healing behavior is absent.

- [ ] **Step 3: Implement the minimum durable lifecycle**
  - Create explicit tables for healing actions, action events, leases/fencing, checkpoints, compensation records, degraded scopes, and reconciliation state.
  - Use deterministic idempotency keys and generation checks.
  - Make takeover conditional on lease expiry and fencing.
  - Preserve immutable action history.
  - Never infer completion from an interrupted process.
  - Keep healing state separate from `compute_inventory` authority while consuming inventory state for reconciliation.
  - Expose narrowly scoped interfaces for later containment/remediation tasks.

- [ ] **Step 4: Verify the focused pass**
  - Run: `pytest -q lead_engine/test_healing_state.py lead_engine/test_autonomous_healing.py`
  - Expected: all focused durable-state and lifecycle tests pass.

- [ ] **Step 5: Run the affected integration check**
  - Run: `pytest -q lead_engine/test_recovery_orchestrator.py lead_engine/test_self_coordinating_fabric.py lead_engine/test_healing_state.py lead_engine/test_autonomous_healing.py`
  - Expected: existing recovery/coordinator suites remain green and new lifecycle tests pass.

- [ ] **Step 6: Commit the passing deliverable**
  `git add lead_engine/autonomous_healing.py lead_engine/healing_state.py lead_engine/test_healing_state.py lead_engine/test_autonomous_healing.py && git commit -m "feat: add durable autonomous healing lifecycle"`

### Task 2: Evidence fusion, adaptive containment, and transactional remediation

**Files:**
- Modify: `lead_engine/autonomous_healing.py`
- Create: `lead_engine/healing_policy.py` (proposed, evidence thresholds, safety floors, containment and strategy decisions)
- Create: `lead_engine/healing_actions.py` (proposed, bounded remediation execution and transactional checkpoints)
- Test: `lead_engine/test_healing_policy.py`
- Test: `lead_engine/test_healing_actions.py`

**Interfaces:**
- Consumes: healing evidence, authoritative physical/active-path results, failure criticality, redundancy, blast-radius metadata, protected capacity state, historical recovery outcomes, and known-good recovery strategies.
- Produces: containment decisions, selected recovery strategies, bounded action plans, checkpoint transitions, rollback/compensation decisions, and degraded-mode transitions.

- [ ] **Step 1: Add the focused failing tests**
  - Verify adaptive thresholds consider criticality, confidence, reversibility, blast radius, redundancy, fallback capacity, and recovery history.
  - Verify hard safety floors override adaptive recommendations.
  - Verify immediate containment for conditions that cross defined irreversible/cascade/blast-radius boundaries.
  - Verify simultaneous failures remain independently scoped.
  - Verify concurrent healing is allowed only for proven-independent scopes.
  - Verify uncertain/conflicting scopes serialize.
  - Verify partial success preserves only independently verified progress.
  - Verify rollback/compensation occurs when a checkpoint cannot safely continue.
  - Verify protected standby capacity cannot be consumed below its immutable floor.
  - Verify inability to safely recover enters degraded mode instead of escalating indefinitely.

- [ ] **Step 2: Verify the relevant failures**
  - Run: `pytest -q lead_engine/test_healing_policy.py lead_engine/test_healing_actions.py`
  - Expected: focused failures for missing policy/action behavior.

- [ ] **Step 3: Implement the minimum policy and action engine**
  - Represent evidence explicitly and retain provenance.
  - Calculate adaptive remediation eligibility without permitting policy code to bypass hard safety predicates.
  - Implement observe, soft-isolate, quarantine, and immediate-isolate outcomes.
  - Keep infrastructure remediation reversible and bounded.
  - Route physical reinitialization/reprobe/rebind through authoritative lower layers instead of recreating them.
  - Implement checkpointed action execution, rollback/compensation boundaries, and durable intermediate states.
  - Enforce action ownership, generation, fencing, and conflict boundaries from Task 1.
  - Enter durable degraded mode when no safe recovery remains.

- [ ] **Step 4: Verify the focused pass**
  - Run: `pytest -q lead_engine/test_healing_policy.py lead_engine/test_healing_actions.py`
  - Expected: all focused policy and transactional-action tests pass.

- [ ] **Step 5: Run the affected integration check**
  - Run: `pytest -q lead_engine/test_recovery_orchestrator.py lead_engine/test_self_coordinating_fabric.py lead_engine/test_healing_state.py lead_engine/test_autonomous_healing.py lead_engine/test_healing_policy.py lead_engine/test_healing_actions.py`
  - Expected: all existing and new suites pass without weakening lower-level authorities.

- [ ] **Step 6: Commit the passing deliverable**
  `git add lead_engine/autonomous_healing.py lead_engine/healing_policy.py lead_engine/healing_actions.py lead_engine/test_healing_policy.py lead_engine/test_healing_actions.py && git commit -m "feat: add adaptive containment and transactional healing"`

### Task 3: Workload and control-plane autonomous recovery

**Files:**
- Modify: `lead_engine/autonomous_healing.py`
- Create: `lead_engine/healing_workloads.py` (proposed, execution-state-preserving workload recovery)
- Create: `lead_engine/healing_control_plane.py` (proposed, crash-safe control-plane recovery)
- Test: `lead_engine/test_healing_workloads.py`
- Test: `lead_engine/test_healing_control_plane.py`

**Interfaces:**
- Consumes: workload execution state, checkpoint/restart capabilities, authoritative placement/capacity results, exact verified fabric paths, durable control-plane state, leases/fencing, and reconciliation state.
- Produces: restart/migration/reconstruction plans, fenced controller transitions, reconciled control-plane state, and verified return-to-service decisions.

- [ ] **Step 1: Add the focused failing tests**
  - Verify restart is selected when the original execution environment is safely recoverable.
  - Verify migration requires authoritative destination capacity and an exact verified fabric path.
  - Verify recovery does not create duplicate execution side effects.
  - Verify failed local recovery can transition to migration without inventing placement.
  - Verify control-plane takeover fences stale controllers.
  - Verify durable state reconstruction after controller loss.
  - Verify partition and quorum-loss conditions prevent unsafe dual authority.
  - Verify recovered control-plane components cannot resume authority before reconciliation and verification.
  - Verify a controller crash halfway through recovery is reconciled from durable state.

- [ ] **Step 2: Verify the relevant failures**
  - Run: `pytest -q lead_engine/test_healing_workloads.py lead_engine/test_healing_control_plane.py`
  - Expected: focused failures for missing workload/control-plane healing interfaces.

- [ ] **Step 3: Implement minimum workload and control-plane recovery**
  - Preserve the strongest available workload execution state.
  - Use existing placement/capacity authority for destination selection.
  - Require existing exact-path evidence for migration.
  - Make restart, checkpoint recovery, and migration idempotent.
  - Reconstruct control-plane in-memory state only from authoritative durable state.
  - Implement fencing, generation transitions, and safe takeover.
  - Block return to service until required reconciliation and verification pass.
  - Keep simultaneous failures independently scoped.

- [ ] **Step 4: Verify the focused pass**
  - Run: `pytest -q lead_engine/test_healing_workloads.py lead_engine/test_healing_control_plane.py`
  - Expected: all focused workload/control-plane recovery tests pass.

- [ ] **Step 5: Run the affected integration check**
  - Run: `pytest -q lead_engine/test_recovery_orchestrator.py lead_engine/test_self_coordinating_fabric.py lead_engine/test_healing_state.py lead_engine/test_autonomous_healing.py lead_engine/test_healing_policy.py lead_engine/test_healing_actions.py lead_engine/test_healing_workloads.py lead_engine/test_healing_control_plane.py`
  - Expected: all lower-level and healing suites pass together.

- [ ] **Step 6: Commit the passing deliverable**
  `git add lead_engine/autonomous_healing.py lead_engine/healing_workloads.py lead_engine/healing_control_plane.py lead_engine/test_healing_workloads.py lead_engine/test_healing_control_plane.py && git commit -m "feat: add autonomous workload and control-plane healing"`

### Task 4: Verification closure, learning, replicated healing state, and production gate

**Files:**
- Modify: `lead_engine/autonomous_healing.py`
- Modify: `lead_engine/healing_state.py`
- Create: `lead_engine/healing_learning.py` (proposed, outcome provenance and isolated strategy learning)
- Create: `lead_engine/test_healing_learning.py`
- Modify: existing GPU fabric validation workflow identified from the repository's current workflow configuration after implementation files are established
- Test: complete healing test suite plus existing GPU fabric suites

**Interfaces:**
- Consumes: remediation outcomes, authoritative verification results, healing-specific validation evidence, immutable action history, strategy provenance, and replicated healing state.
- Produces: closure decisions, strategy outcome records, promotion/demotion evidence, replicated state checkpoints, and production validation results.

- [ ] **Step 1: Add the focused failing tests**
  - Verify closure requires both existing authoritative verification and healing-specific validation.
  - Verify secondary damage blocks closure.
  - Verify failed closure remains recoverable or enters degraded mode.
  - Verify learning records immutable provenance without changing production policy immediately.
  - Verify experimental strategies cannot bypass safety floors.
  - Verify promotion requires sufficient evidence and continuous known-good capability.
  - Verify regression causes automatic demotion/rollback.
  - Verify replicated healing state survives controller/state-instance failure.
  - Verify protected standby reserve remains enforced during recovery.

- [ ] **Step 2: Verify the relevant failures**
  - Run: `pytest -q lead_engine/test_healing_learning.py` plus the focused closure/state tests.
  - Expected: focused failures for missing closure, learning, or replication behavior.

- [ ] **Step 3: Implement closure, learning, and replicated state**
  - Require lower-layer authoritative verification before closure.
  - Add healing-specific validation of intended remediation and secondary effects.
  - Record strategy outcomes, evidence, provenance, and promotion history durably.
  - Keep experimental learning isolated from active production recovery policy.
  - Preserve proven-good strategies until replacements are continuously available.
  - Replicate healing state without creating a second physical-state authority.
  - Enforce reserve floor and degraded-mode boundaries at final decision time.

- [ ] **Step 4: Verify the focused pass**
  - Run: `pytest -q lead_engine/test_healing_learning.py lead_engine/test_healing_state.py lead_engine/test_autonomous_healing.py`
  - Expected: all focused closure, learning, and persistence tests pass.

- [ ] **Step 5: Run the full repository-level validation**
  - Run: `pytest -q`
  - Expected: existing repository tests and the complete healing suite pass with no regressions.
  - Run the existing GPU fabric validation GitHub Actions workflow on `feature/gpu-fabric-foundation`.
  - Expected: the complete GPU fabric validation, including existing massive-scale proof, physical identity, recovery orchestrator, unified self-optimizing control plane, self-coordinating fabric, and autonomous healing validation, passes on the resulting feature commit.

- [ ] **Step 6: Commit the passing deliverable**
  `git add lead_engine/autonomous_healing.py lead_engine/healing_state.py lead_engine/healing_learning.py lead_engine/test_healing_learning.py [validated workflow file if modified] && git commit -m "feat: close autonomous healing verification and learning"`

---

## Explicit interface boundaries

The following existing interfaces are observed in the current repository and must remain authoritative:

- `RecoveryOrchestrator.discover()`
- `RecoveryOrchestrator.due()`
- `RecoveryOrchestrator.claim()`
- `RecoveryOrchestrator.execute()`
- `RecoveryOrchestrator.run_due()`
- `ActivePathIntelligence.analyze(..., path_id=...)`
- `ComputeInventory` physical-path, active-measurement, and durable recovery-action APIs
- `FabricCoordinator.coordinate(...)`
- `FabricCoordinator.reconcile_node_failure(...)`
- `FabricCoordinator.can_experiment(...)`
- `FabricCoordinator.snapshot()`

The proposed healing interfaces must consume these authorities rather than duplicate them.

## Repository-grounded implementation notes

- Existing recovery orchestration delegates evidence-gated execution to `ComputeInventory`; the healing plane should coordinate that authority rather than reimplementing physical-path recovery.
- Existing active-path intelligence scopes measurements by exact `path_id` and endpoint identity; healing must preserve that exact scope.
- Existing self-coordinating fabric persists node/workload/allocation/decision state and already protects standby capacity; healing must use its capacity authority rather than maintaining a competing allocation ledger.
- Existing tests use SQLite temporary databases and pytest, so the new healing tests should follow the same pattern.
- Existing GPU validation is already the production integration gate for this feature branch.

## Unresolved externally observable product decisions

None remain from the approved design specification. Engineering-level details such as exact SQLite table/column names, Python class decomposition, and internal helper names remain implementation choices, provided they preserve the interfaces and invariants above.
