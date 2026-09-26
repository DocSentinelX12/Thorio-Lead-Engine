# Autonomous Healing Intelligence Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable evidence-driven healing intelligence layer that connects the existing GPU fabric authorities into dependency-aware, crash-safe autonomous recovery.

**Architecture:** Extend the existing HealingIntegrationFabric with a durable evidence graph, dependency and blast-radius analysis, failure correlation, adaptive recovery planning, and restart reconciliation. SQLite remains the durability mechanism; existing authorities retain domain truth and execution authority.

**Tech Stack:** Python, SQLite, pytest, GitHub Actions.

## Global Constraints

- Work only on `feature/gpu-fabric-foundation`.
- Never modify `main`.
- Preserve exact physical `fabric_path_id` identity.
- Do not create competing physical, capacity, allocation, execution, or recovery sources of truth.
- Preserve protected standby capacity.
- Persist recovery intent and observations sufficiently for crash-safe reconciliation.
- Independent failure domains may proceed concurrently; conflicting operations must be ordered.
- Healing closure requires authoritative verification and no secondary damage.
- No placeholders, fake tests, guessed identities, or synthetic production evidence.

---

### Task 1: Durable Evidence Graph

**Files:**
- Create: `lead_engine/healing_evidence.py`
- Test: `lead_engine/test_healing_evidence.py`

**Interfaces:**
- `HealingEvidenceGraph(db_path: str = ":memory:")`
- `record_observation(...) -> dict[str, object]`
- `record_relationship(...) -> dict[str, object]`
- `observations(...) -> tuple[dict[str, object], ...]`
- `relationships(...) -> tuple[dict[str, object], ...]`
- `snapshot(scope_id: str) -> dict[str, object]`

- [ ] **Step 1: Add focused failing tests**
Test durable observation identity, exact path preservation, relationship provenance, and restart persistence.
- [ ] **Step 2: Verify red**
Run `pytest -q lead_engine/test_healing_evidence.py`. Expected: missing graph implementation.
- [ ] **Step 3: Implement minimum durable graph**
Use SQLite tables for immutable observations and relationships with deterministic IDs, source authority, generation, confidence, and JSON payload.
- [ ] **Step 4: Verify green**
Run the focused test and require all graph tests to pass.
- [ ] **Step 5: Integration check**
Run the existing healing authority and integration tests to prove no authority behavior changed.
- [ ] **Step 6: Commit**
Commit `feat: add durable healing evidence graph`.

### Task 2: Dependency, Blast Radius, and Failure Correlation

**Files:**
- Create: `lead_engine/healing_dependencies.py`
- Test: `lead_engine/test_healing_dependencies.py`

**Interfaces:**
- `HealingDependencyAnalyzer(graph: HealingEvidenceGraph)`
- `impact(scope_id: str) -> dict[str, object]`
- `failure_episode(scope_id: str, observed_at: float) -> dict[str, object]`
- `RecoveryDependencyConflict` for conflicting recovery scopes.

- [ ] **Step 1: Add focused failing tests**
Cover direct and transitive dependencies, independent failure domains, temporal correlation, shared dependency correlation, and non-correlation of unrelated failures.
- [ ] **Step 2: Verify red**
Run `pytest -q lead_engine/test_healing_dependencies.py`. Expected: missing module/class implementation.
- [ ] **Step 3: Implement dependency traversal and correlation**
Traverse only persisted graph relationships, preserve provenance, calculate affected entities and failure domains, and correlate observations only when exact identity, dependency, or bounded temporal/failure-domain evidence supports it.
- [ ] **Step 4: Verify green**
Run focused dependency tests.
- [ ] **Step 5: Integration check**
Run evidence plus existing healing integration tests.
- [ ] **Step 6: Commit**
Commit `feat: add healing dependency and failure analysis`.

### Task 3: Adaptive Recovery Planning and Crash-Safe Reconciliation

**Files:**
- Create: `lead_engine/healing_intelligence.py`
- Test: `lead_engine/test_healing_intelligence.py`
- Modify: `lead_engine/healing_authorities.py`

**Interfaces:**
- `HealingIntelligence.plan(...) -> dict[str, object]`
- `HealingIntelligence.reconcile(...) -> dict[str, object]`
- `HealingIntegrationFabric` exposes the intelligence while continuing to delegate physical/recovery execution to existing authorities.

- [ ] **Step 1: Add focused failing tests**
Cover recovery prerequisites, independent parallel groups, conflict serialization, protected standby preservation, migration prerequisites, and restart outcomes of resume/compensate/replan.
- [ ] **Step 2: Verify red**
Run `pytest -q lead_engine/test_healing_intelligence.py`. Expected: missing intelligence behavior.
- [ ] **Step 3: Implement planning**
Consume graph impact and existing healing policy. Produce deterministic durable plan steps with dependency edges, execution authority, exact path identity, and safety constraints. Persist intent in a tightly scoped SQLite intelligence table.
- [ ] **Step 4: Verify green**
Run focused intelligence tests.
- [ ] **Step 5: Integration check**
Run authority, integration, evidence, dependency, recovery orchestrator, self-coordinating fabric, and autonomous healing suites.
- [ ] **Step 6: Commit**
Commit `feat: add dependency-aware healing intelligence`.

### Task 4: End-to-End Verification and Workflow Gate

**Files:**
- Modify: `.github/workflows/gpu-fabric-validation.yml`

**Interfaces:**
- Workflow executes the new evidence, dependency, intelligence, and restart/reconciliation suites alongside all existing GPU fabric gates.

- [ ] **Step 1: Add workflow coverage**
Run the new focused suites before the existing broad regression gates.
- [ ] **Step 2: Verify focused CI**
Confirm every new suite passes on the feature branch.
- [ ] **Step 3: Run complete GPU fabric validation**
Confirm massive-scale proof and all existing healing/recovery/control-plane/execution regressions remain green.
- [ ] **Step 4: Verify branch boundary**
Confirm all implementation commits are on `feature/gpu-fabric-foundation` and `main` remains untouched.
- [ ] **Step 5: Commit workflow gate**
Commit `test: gate healing intelligence in GPU fabric validation`.