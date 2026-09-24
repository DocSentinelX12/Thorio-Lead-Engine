# Plan: Continuous Self-Optimization

## Goal
Complete #19 by closing the existing evidence loop so future placement continuously adapts to observed workload outcomes and current fleet capacity without creating a second scheduler, prediction store, queue, or synthetic performance model.

## Task 1: Define optimization evidence
- File: lead_engine/compute_fabric_telemetry.py
- Add a read-time derivation that combines already observed workload/path outcomes into explicit optimization evidence.
- Preserve exact workload keys, physical path IDs, sample counts, observed latency/bandwidth, route state, and fleet-capacity observations supplied by callers.
- Classify only observed conditions: insufficient_evidence, performance_preference, capacity_preservation, and balanced.
- Never invent scores, probabilities, future performance, failure ETA, or missing capacity.
- Tests cover sparse evidence, exact workload/path isolation, deterministic ordering, and no synthetic values.

## Task 2: Make placement continuously adaptive
- File: lead_engine/compute_placement.py
- Add a final optimization preference that evaluates each already-valid candidate against the current eligible fleet.
- Preserve all existing hard gates and existing performance, route health, predictive, workload, and measured-path ordering.
- Optimize only among candidates that survive those existing authorities.
- Prefer candidates that preserve more exact future placement flexibility for the same workload requirements, using observed eligible resources only.
- Expose the optimization evidence in placement evidence and decision trace.
- Tests verify that optimization never admits invalid resources, never crosses provider/domain boundaries, and never overrides stronger observed performance evidence.

## Task 3: Expose continuous optimization from the control loop
- File: lead_engine/compute_fabric.py
- Add a read-only optimization report to each fabric cycle, derived from the same durable inventory and placement intelligence.
- It must remain advisory and deterministic. The controller continues using the existing coordinator and scheduler as authorities.
- No queue mutation or autonomous resource state mutation is introduced.
- Tests verify repeated cycles observe changing capacity and expose corresponding optimization evidence without creating additional state.

## Task 4: Contract and full validation
- File: docs/COMPUTE_FABRIC_ARCHITECTURE.md
- Document the closed-loop boundary: observed execution and fleet state influence subsequent placement, while hard validation and ComputeAllocation remain authoritative.
- Run the complete GPU Fabric Validation workflow on the current branch.
- Inspect every job result and test failure if any. Completion requires a fresh green full validation run.

## Unresolved product decisions
None. The existing architecture already establishes that observed evidence may inform placement while hard physical validation and ComputeAllocation remain authoritative.
