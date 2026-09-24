# Predictive Failure and Degradation Detection Implementation Plan

Goal: derive conservative, explainable early-warning evidence from existing exact GPU fabric observations, then expose it to existing placement preference without inventing measurements, quarantining resources, or creating a second decision system.

Branch: feature/gpu-fabric-foundation only. Main remains untouched.

Architecture:
exact observed path -> durable route observations -> read-time temporal failure/degradation analysis -> predictive failure evidence -> existing placement preference.

Rules:
- Existing route observations are the sole source of truth.
- Exact fabric path identity remains attached.
- Use only explicitly observed success/failure, latency, timestamps, workload identity, and explicitly supplied failure-domain evidence.
- Missing or sparse evidence is insufficient_evidence, never a fabricated healthy/bad state.
- Predictive evidence is descriptive and advisory only. It cannot quarantine, fail, reserve, release, rebind, or override hard physical/capability gates.
- Existing route health, predictive latency routing, physical verification, generation fencing, recovery, and ComputeAllocation remain authoritative for their existing roles.
- No new table, scheduler, telemetry store, opaque score, or arbitrary history ceiling.

Task 1: Add read-time predictive failure/degradation derivation in lead_engine/compute_fabric_telemetry.py.
- Validate exact boolean success and finite positive latency/timestamps where available.
- Preserve all valid observations chronologically.
- Derive explicit counts: sample_count, success_count, failure_count, consecutive_failures, consecutive_successes.
- Derive temporal failure evidence by comparing earlier and later observed outcomes without inventing rates for missing observations.
- Detect a failure pattern only from an actual trailing consecutive failure sequence.
- Detect degradation only when the observed temporal pattern is strictly worsening, such as a later failure rate exceeding the earlier observed failure rate or a strictly increasing latency sequence with sufficient observations.
- Keep stable only for genuinely consistent successful observations with low observed latency variation and no worsening failure pattern.
- Otherwise return insufficient_evidence.
- Preserve exact observation timestamps, latency values, success values, workload key/signature when present, fabric path ID, and explicit failure-domain evidence.
- Never create a probability, health score, estimated failure time, synthetic latency, or inferred failure domain.
- Add focused tests for stable, degrading, trailing failures, sparse evidence, noisy evidence, non-latency failures, workload isolation, path isolation, and no fabricated values.

Task 2: Expose the evidence from ComputeInventory.fabric_route_health_index().
- Reuse existing compute_fabric_route_observations rows and evidence_json.
- Preserve current route health and predictive latency fields unchanged.
- Add predictive failure/degradation evidence alongside them.
- Keep workload-specific predictive failure evidence isolated by explicit workload_key.
- Malformed evidence remains ordinary route health but cannot manufacture workload or failure-domain evidence.
- Add inventory integration tests.

Task 3: Integrate the evidence into PlacementEvaluator.
- Add a narrowly scoped helper that inspects only exact adaptive/verified physical paths already eligible.
- Match requested workload key when explicit, otherwise remain neutral.
- Prefer stable/insufficient evidence over degrading/failure-pattern evidence only as a subordinate preference, never as a hard rejection.
- Keep existing ordering: candidate performance -> route health -> predictive latency route -> predictive failure/degradation evidence -> multidimensional workload evidence -> concrete path performance -> deterministic tie-break.
- Include the exact supporting observations and explicit domains in the existing trace/evidence.
- Add tests proving no cross-path/workload contamination, no override of hard gates, and deterministic behavior.

Task 4: Full verification and architecture audit.
- Run affected tests plus the complete existing GPU Fabric Validation workflow.
- Inspect any failure by exact root cause before changing code.
- Verify no workflow changes, no main changes, no new persistence subsystem, no arbitrary caps, no fabricated values, and preservation of recovery/allocation behavior.