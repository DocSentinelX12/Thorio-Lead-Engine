# Predictive Route Intelligence Implementation Plan

## Scope

Add an evidence-derived predictive route layer for the GPU fabric. The layer consumes existing exact-path and workload-specific observations and exposes descriptive temporal evidence to the existing placement preference ordering.

## Contract

Prediction is subordinate to all existing hard physical and capability gates. It cannot reject, quarantine, fence, invent measurements, create a health score, or replace route health or ComputeAllocation.

Prediction is derived at read time from durable observations rather than persisted as a second source of truth.

## Tasks

1. Add a deterministic predictive evidence function in `lead_engine/compute_fabric_telemetry.py`.
   - Scope observations by exact physical path and workload key at the caller boundary.
   - Sort valid timestamped observations chronologically.
   - Report evidence sufficiency, baseline, recent behavior, trend, and consistency using observed measurements only.
   - Emit descriptive states: `insufficient_evidence`, `stable`, `improving`, or `degrading`.
   - Preserve supporting observation provenance.

2. Integrate predictive evidence into `lead_engine/compute_scheduler.py` only after existing hard gates, physical validity, performance history, and route health.
   - Prediction changes preference ordering only.
   - Insufficient evidence remains neutral.
   - Deterministic tie-breaking remains intact.

3. Add focused tests in `tests/test_compute_fabric_telemetry.py` and the scheduler placement tests.
   - Cover insufficient, stable, improving, degrading, noisy, missing data, exact path/workload isolation, and hard-gate precedence.
   - Verify no synthetic observations or arbitrary history ceiling is introduced.

4. Run focused tests, affected regression tests, and the existing GPU Fabric Validation workflow. Inspect failures by root cause before any fix.

## Non-goals

This layer does not implement predictive hardware failure detection, fleet-scale intelligence, continuous self-optimization, new workflow files, new persistence, new scheduler authority, quarantine, or generation fencing.

## Acceptance

The complete evidence chain remains exact-path and workload-specific, deterministic, auditable, and subordinate to physical truth and existing allocation boundaries.
