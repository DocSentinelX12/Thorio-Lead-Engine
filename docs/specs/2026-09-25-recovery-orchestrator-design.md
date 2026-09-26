# Recovery Orchestrator Design

Date: 2026-09-25
Branch: feature/gpu-fabric-foundation

## Purpose

Build the orchestration layer that turns exact physical fabric recovery signals into durable, leased, evidence-gated recovery work without replacing the existing physical-fabric or active-path intelligence authorities.

The orchestrator is responsible for deciding what recovery work must be scheduled, when it is eligible to run, who owns an attempt, and whether the durable recovery action can advance to its next stage. It must not invent physical truth, bypass verification, or reactivate a path from orchestration state alone.

## Current foundation

The branch already contains durable exact-path recovery primitives:

- Physical fabric paths have stable `fabric_path_id` identities and durable physical verification state.
- Active measurements are persisted against the exact `fabric_path_id`.
- Active path intelligence evaluates repeated verified observations for the exact path.
- Failed, degraded, unstable, and recovery-triggering states can require fresh physical reverification.
- Physical reverification transitions a path to `REVERIFIED`, but that state is intentionally not sufficient for routing.
- A fresh verified active measurement is required after reverification.
- Durable recovery actions already have generation, trigger fingerprint, lease ownership, retry timing, lifecycle state, and exact-path deduplication.
- Queue discovery already scans all triggered paths without an arbitrary backlog cap.

The next layer therefore focuses on orchestration semantics and integration rather than duplicating those authorities.

## Goals

1. Discover every exact path requiring recovery.
2. Preserve every recovery action durably until it reaches a terminal state.
3. Prevent duplicate concurrent execution with leases.
4. Execute recovery in the required order:
   physical reverification, then fresh active measurement, then intelligence evaluation.
5. Prevent stale recovery generations from reactivating newer path states.
6. Retry incomplete or insufficient evidence without falsely enabling routing.
7. Keep all decisions scoped to the exact `fabric_path_id`.
8. Make orchestration observable through durable action state and error information.
9. Preserve the existing no-backlog-cap behavior.
10. Keep routing eligibility authoritative to the existing physical fabric and active intelligence gates.

## Non-goals

- Replacing `PhysicalFabricVerification`.
- Replacing `ActivePathIntelligence`.
- Creating a second physical path identity system.
- Reconstructing a path from worker, GPU, NIC, or endpoint identity.
- Automatically deleting, collapsing, or capping recovery backlog.
- Enabling routing because an action was claimed, reverification passed, or a worker reported success.
- Changing the main branch.
- Introducing provider-specific recovery policy into the provider-neutral inventory layer.

## Architecture

### 1. Recovery discovery

The orchestrator periodically or explicitly invokes durable queue discovery.

For every persisted physical path:

1. Read the current physical path state.
2. Read exact-path active intelligence.
3. Determine whether the existing recovery trigger rules require action.
4. Create or reuse the durable action for the current path generation and trigger fingerprint.
5. Never discard an already-created action merely because more actions exist.

Discovery must remain idempotent. Re-running discovery over the same path state must not create duplicate work.

### 2. Scheduling

Due actions are selected from durable recovery state.

An action is due only when:

- it is non-terminal,
- its retry time has arrived,
- it is not held by a live lease,
- its generation still matches the current exact path generation.

Claiming uses the existing transactional lease mechanism. A second worker must not execute the same live lease. An expired lease may be reclaimed, and reclaim increments the attempt count.

Scheduling must not reorder work by deleting lower-priority actions. Ordering may be deterministic for operational stability, but every due action remains durable.

### 3. Evidence-gated execution

Each execution attempt follows the authoritative sequence:

1. Claim the action.
2. Validate the action generation against the current exact path generation.
3. If stale, cancel the action without mutating the newer path state.
4. If fresh physical reverification is required, execute it using complete segment evidence.
5. Persist the physical result.
6. If physical state becomes `REVERIFIED`, transition the action to `AWAITING_ACTIVE_MEASUREMENT`.
7. Require a new verified active measurement for the exact path.
8. Persist the active measurement through the existing inventory method.
9. Recompute exact-path active intelligence.
10. Close the action only when the existing recovery and routing gates say the path is eligible.
11. Otherwise enter `RETRY_WAIT` with durable error/reason state.

No stage may skip the evidence required by the existing lower layers.

### 4. Failure isolation

All recovery reads and writes must remain keyed by the exact `fabric_path_id`.

A recovery attempt for path A must never:

- mutate path B,
- use path B's active measurements,
- use path B's physical evidence,
- infer health from shared GPU or NIC identity,
- reactivate a newer generation of path A.

Generation checks must occur immediately before state-changing operations, not only at action creation.

### 5. Lifecycle

The durable action lifecycle is:

`PENDING -> CLAIMED -> PHYSICAL_REVERIFYING -> AWAITING_ACTIVE_MEASUREMENT -> ACTIVE_MEASURING -> SUCCEEDED`

Alternative terminal or retry paths are:

- `RETRY_WAIT` when evidence is incomplete or the recovery gates remain unsatisfied.
- `FAILED` only for a terminal execution condition that the existing recovery policy identifies as non-retryable.
- `CANCELLED` for stale generations or explicit invalidation.

State transitions must be durable and owner-aware while a lease is active.

### 6. Adaptive recovery control

The orchestrator consumes existing exact-path intelligence signals, including:

- physical failure,
- active measurement failure or unavailability,
- degradation,
- instability,
- recovery evidence,
- endpoint or path identity changes,
- repeated unsuccessful recovery attempts.

It must respond by scheduling or retrying exact-path work. It must not manufacture a new health state or replace the intelligence model.

Repeated failures should remain visible through durable attempt count, last error, trigger snapshot, and retry timing. The orchestrator must not silently suppress a persistently failing path.

## Interfaces

The implementation should expose a small orchestration surface around the existing inventory primitives.

Expected responsibilities:

- discover/enqueue triggered recovery actions,
- list due actions,
- claim an action,
- execute one leased recovery attempt,
- persist transition or retry state,
- report durable action state.

Existing `ComputeInventory` persistence remains the source of truth for recovery action durability unless a narrowly scoped separate orchestration module is required by the current code structure.

## Data flow

`physical path state + exact-path intelligence`
-> `recovery trigger`
-> `durable action`
-> `lease claim`
-> `physical reverification`
-> `fresh exact-path active measurement`
-> `active-path intelligence`
-> `routing eligibility`
-> `SUCCEEDED or RETRY_WAIT`

The action record is the control-plane record. Physical verification, active measurement, and routing eligibility remain authoritative data-plane decisions.

## Error handling

- Missing exact path: reject the action without inventing a path.
- Stale generation: cancel the stale action and do not mutate the current path.
- Incomplete physical evidence: remain non-routable and retry according to durable retry policy.
- Unverified active measurement: remain non-routable and retry.
- Unstable or degrading intelligence: remain non-routable and retry.
- Lease conflict: do not execute; leave the existing owner untouched.
- Expired lease: allow a new worker to reclaim according to the durable lease rules.
- Unexpected execution failure: persist the error and enter the existing retry policy unless the condition is explicitly terminal.

Routing must default to false whenever the recovery gates are not satisfied.

## Testing strategy

Use the existing TDD pattern and exact-path fixtures.

Required behavioral coverage:

1. Discovery creates one action for each independently triggered path.
2. Repeated discovery is idempotent.
3. Discovery has no artificial backlog cap.
4. Only one worker can hold a live action lease.
5. Expired leases can be reclaimed.
6. A stale generation is cancelled and cannot change the newer path.
7. Physical reverification alone never enables routing.
8. A fresh but unverified active measurement never enables routing.
9. A fresh verified measurement with insufficient intelligence remains in retry state.
10. Stable exact-path recovery closes the action and enables routing through existing gates.
11. A failure on one path does not change another path.
12. Endpoint or path identity changes require fresh exact-path evidence.
13. Repeated failed attempts remain durable and visible.
14. Recovery actions survive inventory object recreation because state is stored in SQLite.
15. Concurrent discovery and claiming do not create duplicate active work.

Tests must use real production interfaces and real durable SQLite behavior. No fake URLs, placeholder tests, or synthetic shortcuts that bypass the authoritative verification methods.

## Verification gates

Before declaring the layer complete:

- focused recovery-orchestrator tests must pass,
- the existing physical fabric and active-path recovery tests must still pass,
- the full relevant repository test suite must pass,
- the GPU Fabric Validation workflow must be run on `feature/gpu-fabric-foundation`,
- workflow success must be verified from the actual GitHub Actions result, not inferred from an empty combined-status response,
- the resulting commit must remain on `feature/gpu-fabric-foundation` and must not modify `main`.

## Boundary of completion

This layer is complete only when durable recovery work can be discovered, leased, executed, retried, and closed using the existing exact-path evidence gates, while preserving strict isolation between path generations and between different physical paths.

The orchestrator is not allowed to declare physical truth. It only coordinates evidence collection and consumes the authoritative result.
