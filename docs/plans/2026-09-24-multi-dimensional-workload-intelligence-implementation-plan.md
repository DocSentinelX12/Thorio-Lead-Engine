# Multi-dimensional Workload Intelligence Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive explainable, multidimensional workload behavior from existing exact execution observations and use that evidence as a subordinate placement preference without inventing unobserved values or creating a second source of truth.

**Architecture:** Extend the existing evidence path in `compute_fabric_telemetry.py` and `compute_inventory.py` so explicit workload dimensions remain attached to durable exact-path observations. Derive workload-by-path evidence at read time, then integrate that evidence into the existing `PlacementEvaluator` ordering after physical gates, route health, and predictive route intelligence. No new scheduler, telemetry store, allocation authority, or opaque score.

**Tech Stack:** Python, SQLite, existing `ComputeInventory`, `compute_fabric_telemetry`, `PlacementEvaluator`, pytest, existing GPU Fabric Validation workflow.

## Global Constraints

- Work only on `feature/gpu-fabric-foundation`; do not modify main.
- Preserve all existing physical identity, concrete path, verification, route health, predictive route, placement, generation, recovery, and `ComputeAllocation` behavior.
- Use only explicitly observed workload dimensions.
- Relevant dimensions are workload class, collective, world size, message size, dtype, reduce operation, algorithm, protocol, latency, bandwidth, exact physical path, topology/path identity, and execution history, where each value is actually present in evidence.
- Never fabricate a missing dimension, estimated measurement, synthetic combination, confidence value, health score, or predicted performance number.
- Do not create a second telemetry database or independent scheduler.
- Multidimensional workload evidence may affect preference only after all existing hard physical and capability gates.
- Insufficient or missing evidence remains neutral and must not become a rejection.
- Workload evidence must remain isolated by explicit workload identity and exact physical path.
- No arbitrary history or backlog ceiling may be introduced.
- Existing latency unit handling remains unchanged: execution latency is persisted through the existing microsecond-to-millisecond conversion path.
- No fake URLs, placeholders, superficial tests, or guessed fixes.
- Follow the existing pattern: audit existing capability, identify the smallest missing intelligence, strengthen it, prove it, and audit again.

---

### Task 1: Define and derive canonical multidimensional workload evidence

**Files:**
- Modify: `lead_engine/compute_fabric_telemetry.py`
- Test: `tests/test_compute_fabric_telemetry.py`

**Interfaces:**
- Consumes: existing `extract_workload_signature(verification)`, `extract_execution_metrics(verification)`, `workload_performance_key(path, workload)`, and persisted route-observation evidence.
- Produces: a deterministic workload evidence derivation interface in `compute_fabric_telemetry.py` that reports only observed dimensions and observed measurements for an exact workload/path context.

- [ ] **Step 1: Add focused failing tests**

Add tests proving that the evidence derivation:
1. preserves every explicitly observed workload dimension;
2. keeps collective, dtype, algorithm, protocol, world size, and message size distinct;
3. keeps exact workload combinations isolated;
4. keeps exact physical paths isolated;
5. does not create a value when a dimension is absent;
6. does not treat a workload dimension from one observation as present in another observation;
7. preserves observed latency and any explicitly available bandwidth without deriving a synthetic bandwidth;
8. reports sample/history information from observations rather than a fabricated confidence score;
9. keeps sparse combinations explicitly sparse rather than borrowing a neighboring workload combination.

- [ ] **Step 2: Verify the focused failure**

Run:
`pytest -q tests/test_compute_fabric_telemetry.py -k "workload or multidimensional"`

Expected: the new evidence tests fail because the multidimensional derivation interface does not yet exist.

- [ ] **Step 3: Implement the minimum evidence derivation**

Build the derivation around the existing workload signature and route-observation evidence. Normalize only in the same deterministic manner already used by `workload_performance_key`; do not add new coercion rules that change supplied semantics.

For each exact workload/path grouping:
- retain only dimensions explicitly present in the observation evidence;
- retain observed latency values only when valid under the existing telemetry rules;
- retain explicitly observed bandwidth when available;
- retain observation timestamps and exact path identity;
- expose sample counts and the actual observed combinations;
- distinguish exact-combination evidence from partial evidence;
- never fill missing dimensions from another sample;
- never calculate an unobserved bandwidth, latency, throughput, or other performance value;
- keep workload-class and performance-signature identity compatible with the existing `workload_performance_key`.

Use the existing durable observations as the source of truth. Do not add a persistence table.

- [ ] **Step 4: Verify the focused pass**

Run:
`pytest -q tests/test_compute_fabric_telemetry.py -k "workload or multidimensional"`

Expected: all new multidimensional evidence tests pass.

- [ ] **Step 5: Run affected telemetry regression tests**

Run:
`pytest -q tests/test_compute_fabric_telemetry.py`

Expected: all telemetry tests pass, including predictive-route tests.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add lead_engine/compute_fabric_telemetry.py tests/test_compute_fabric_telemetry.py
git commit -m "feat: derive multidimensional workload evidence"
```

---

### Task 2: Expose multidimensional workload evidence from durable inventory observations

**Files:**
- Modify: `lead_engine/compute_inventory.py`
- Test: `tests/test_compute_fabric_telemetry.py` and the existing inventory tests covering `fabric_route_health_index`

**Interfaces:**
- Consumes: rows from `compute_fabric_route_observations`, including existing `evidence_json`.
- Produces: route/workload evidence derived from the existing durable observation stream and exposed alongside the existing route-health index.

- [ ] **Step 1: Add focused failing tests**

Verify that inventory-derived evidence:
1. reads the explicit workload dimensions already stored in `evidence_json`;
2. groups observations by exact workload identity and exact `fabric_path_id`;
3. keeps different workload combinations isolated on the same path;
4. keeps the same workload isolated across different paths;
5. preserves sparse evidence without filling combinations;
6. continues exposing existing route-health and predictive-route evidence unchanged;
7. tolerates malformed evidence JSON exactly as the current inventory path does, without manufacturing workload data.

- [ ] **Step 2: Verify the relevant failure**

Run the smallest existing inventory/telemetry test selection covering `fabric_route_health_index` plus the new cases.

Expected: the new assertions fail because the inventory index does not yet expose the multidimensional workload evidence.

- [ ] **Step 3: Implement the minimum integration**

Extend the existing read-time grouping rather than adding a new storage subsystem.

The inventory layer must:
- reuse the existing observation rows;
- decode `evidence_json`;
- retain exact path identity;
- group only where an explicit workload identity is present;
- pass observations to the telemetry evidence derivation;
- keep observations without explicit workload identity available for ordinary route health but exclude them from workload-specific evidence;
- preserve the existing `predictive_by_workload_key` behavior.

Do not alter the existing observation schema unless repository evidence proves a currently missing field is required. If a requested dimension is not currently persisted, it remains unobserved rather than being guessed or reconstructed.

- [ ] **Step 4: Verify the focused pass**

Run the focused inventory and telemetry tests.

Expected: multidimensional inventory evidence passes while existing route-health and predictive evidence remain unchanged.

- [ ] **Step 5: Run affected regression tests**

Run the complete existing inventory test module(s) that exercise route observations and placement evidence.

Expected: all pass.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add lead_engine/compute_inventory.py tests/test_compute_fabric_telemetry.py
git commit -m "feat: expose workload evidence from route observations"
```

---

### Task 3: Integrate multidimensional evidence into existing placement intelligence

**Files:**
- Modify: `lead_engine/compute_placement.py`
- Test: `tests/test_concrete_path_performance_ranking.py` and relevant placement tests already covering candidate evaluation

**Interfaces:**
- Consumes: existing `requirements.workload_class`, `requirements.performance_signature`, exact adaptive/verified path IDs, `route_health`, and the multidimensional evidence exposed by the inventory/read-time path.
- Produces: an explainable candidate workload-evidence preference and placement decision trace.

- [ ] **Step 1: Add focused failing tests**

Add tests proving:
1. a candidate with exact observed workload/path evidence can be preferred over an otherwise equivalent candidate with no workload-specific evidence;
2. evidence for a different message size does not apply to the requested message size;
3. evidence for a different world size does not apply;
4. collective, dtype, algorithm, and protocol mismatches remain isolated;
5. exact path evidence does not transfer to another physical path;
6. sparse evidence remains neutral rather than becoming a fabricated estimate;
7. multidimensional evidence is evaluated after existing route health and predictive route evidence;
8. hard physical/capability rejection still wins over workload preference;
9. deterministic tie-breaking remains unchanged;
10. placement evidence and decision trace expose the supporting observed dimensions and sample history.

- [ ] **Step 2: Verify the relevant failure**

Run:
`pytest -q tests/test_concrete_path_performance_ranking.py -k "workload"`

Expected: the new workload-intelligence assertions fail because placement currently lacks the multidimensional preference.

- [ ] **Step 3: Implement the minimum placement integration**

Add one narrowly scoped placement helper for multidimensional workload evidence.

The helper should:
- derive the requested workload identity from the existing requirements;
- inspect only exact adaptive or verified physical paths already eligible for the candidate;
- locate only matching observed workload combinations;
- distinguish exact evidence from insufficient/partial evidence;
- return a deterministic preference tuple without inventing numeric performance values;
- remain neutral when no applicable evidence exists.

Integrate it into the existing candidate ordering after:
1. candidate performance;
2. route health;
3. predictive route evidence;

and before the existing concrete-path performance/tie-break layers only if the current placement architecture confirms that ordering is the correct subordinate boundary.

Do not replace `_candidate_performance`, `_candidate_route_health`, `_candidate_predictive_route`, `_candidate_concrete_performance`, or `_stable_key`.

Include the evidence in the existing placement decision trace rather than creating a second decision system.

- [ ] **Step 4: Verify the focused pass**

Run:
`pytest -q tests/test_concrete_path_performance_ranking.py -k "workload"`

Expected: all new multidimensional placement tests pass.

- [ ] **Step 5: Run full placement regression tests**

Run:
`pytest -q tests/test_concrete_path_performance_ranking.py`

Expected: all existing concrete-path, adaptive-route, predictive-route, and deterministic placement tests pass.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add lead_engine/compute_placement.py tests/test_concrete_path_performance_ranking.py
git commit -m "feat: use multidimensional workload evidence in placement"
```

---

### Task 4: End-to-end verification and architecture audit

**Files:**
- Modify: only files required by a verified regression root cause.
- Test: existing GPU Fabric validation workflow and all affected Python test modules.

**Interfaces:**
- Consumes: the completed telemetry, inventory, and placement evidence path.
- Produces: verified end-to-end behavior with no regression to physical gates, predictive routing, recovery, or allocation boundaries.

- [ ] **Step 1: Run the complete focused regression suite**

Run the repository's existing GPU compute/fabric test selection covering telemetry, inventory, placement, concrete paths, adaptive routing, recovery, and allocation.

Expected: all affected tests pass.

- [ ] **Step 2: Inspect failures by root cause**

For every failure, identify the exact file, function, assertion, and architectural contract involved before changing code. Do not make speculative fixes.

- [ ] **Step 3: Run the existing GPU Fabric Validation workflow**

Use the existing:
`gpu-fabric-validation.yml`

Expected: the workflow completes successfully with the multidimensional workload layer enabled.

- [ ] **Step 4: Audit the final evidence chain**

Verify:
- every workload value came from explicit observation;
- no unobserved combination received a fabricated value;
- exact path identity remained intact;
- workload dimensions remained isolated;
- predictive route evidence still behaves exactly as before;
- route health remains authoritative for its existing role;
- physical gates remain hard gates;
- `ComputeAllocation` remains authoritative;
- no new scheduler or telemetry database was introduced;
- no arbitrary observation/history ceiling was introduced;
- placement remains deterministic.

- [ ] **Step 5: Commit only verified fixes**

If and only if validation exposes a real regression, make the smallest root-cause fix, rerun the affected tests, rerun GPU Fabric Validation, and commit that verified fix separately.

```bash
git status --short
git log --oneline -n 10
```

Expected: only intentional changes on `feature/gpu-fabric-foundation`, with main untouched.

---

## Acceptance Criteria

The layer is complete only when the system can use observed multidimensional workload behavior to inform placement while preserving these guarantees:

1. Explicit workload dimensions remain attached to exact execution evidence.
2. Exact workload/path combinations remain isolated.
3. Missing dimensions remain unknown.
4. Sparse evidence remains sparse.
5. No synthetic performance estimate or opaque health score is introduced.
6. Existing route health and predictive route intelligence continue to function.
7. Multidimensional workload evidence cannot bypass physical or capability gates.
8. Existing allocation and generation boundaries remain authoritative.
9. Placement evidence explains which observed workload dimensions supported the decision.
10. The complete affected test suite and GPU Fabric Validation pass.

## Unresolved External Product Decisions

None. The approved architecture specifies evidence-only derivation, exact workload/path isolation, missing-data neutrality, and subordinate placement preference. Any implementation detail not explicitly required above must be resolved from the existing repository rather than by inventing new product behavior.
