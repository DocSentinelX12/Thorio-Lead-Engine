# Continuous Autonomous Fabric Recovery Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable continuous recovery controller that discovers, schedules, executes, reconciles, and verifies autonomous recovery work across the existing GPU fabric authorities.

**Architecture:** The controller owns recovery episodes and scheduling intent. Existing physical fabric, inventory, active-path intelligence, recovery orchestration, placement, workload, control-plane, and closure systems remain authoritative for their domains. Controlled fault scenarios exercise the same production seams.

**Tech Stack:** Python 3.10, SQLite, pytest, GitHub Actions.

## Global Constraints

- Work only on `feature/gpu-fabric-foundation` and never modify `main`.
- Preserve exact authoritative `fabric_path_id` identity.
- Do not bypass authoritative verification, capacity, lease, fencing, or closure gates.
- Preserve durable recovery work with no arbitrary backlog discard.
- Independent failures remain independent unless evidence establishes a dependency.
- Conflicting work is serialized.
- Interrupted work is reconciled against authoritative state.
- Fault injection uses production controller and durable authority seams.

### Task 1: Durable episodes and scheduler

**Files:** `lead_engine/continuous_recovery.py`, `lead_engine/test_continuous_recovery.py`

- [x] Durable episode identity, event history, controller lease, fencing, and restart state.
- [x] Exact-path observation and idempotent episode creation.
- [x] Dependency/failure-domain aware scheduling with concurrent independent episodes and serialized conflicts.
- [x] Focused tests for idempotency, fencing, concurrency, and restart.

### Task 2: Authoritative execution and reconciliation

**Files:** `lead_engine/continuous_recovery.py`, `lead_engine/test_continuous_recovery.py`

- [x] Execute only through `HealingAuthorityGateway.recover_path()`.
- [x] Preserve incomplete evidence as retryable state.
- [x] Reconcile unfinished episodes after controller restart from authoritative path/action state.
- [x] Verify complete recovery through the existing authoritative recovery result.

### Task 3: Controlled fault validation

**Files:** `lead_engine/healing_fault_injection.py`, `lead_engine/test_healing_fault_injection.py`

- [x] Explicit catalog for isolated failure, independent failure, controller restart, verification failure, and protected-capacity scenarios.
- [x] Reject unknown physical paths through the production gateway.
- [x] Keep fault scenarios attached to the production controller rather than creating a parallel recovery implementation.

### Task 4: Production workflow gate

**Files:** `.github/workflows/gpu-fabric-validation.yml`

- [x] Run continuous recovery and fault-injection tests in GPU Fabric Validation.
- [ ] Verify the complete workflow green on `feature/gpu-fabric-foundation` after implementation.
