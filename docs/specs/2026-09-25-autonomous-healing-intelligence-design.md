# Autonomous Healing Intelligence and Dependency-Aware Recovery Design

## Goal

Extend the existing Autonomous Healing Plane into a durable, dependency-aware recovery intelligence layer that reasons across authoritative physical, active-path, execution, placement, workload, control-plane, closure, and learning systems without creating competing sources of truth.

## Architecture

The layer adds a durable evidence graph, dependency and blast-radius analysis, failure correlation, adaptive containment and dependency-aware recovery planning above the existing authorities. SQLite remains the durable mechanism, and authoritative systems remain responsible for physical reality, capacity, execution reality, and recovery execution.

## Invariants

- Exact fabric_path_id identity is preserved end to end.
- Healing may coordinate and reason but may not synthesize physical, capacity, allocation, or execution truth.
- Existing ComputeInventory, RecoveryOrchestrator, FabricCoordinator, WorkloadRecoveryPlanner, ControlPlaneRecovery, HealingClosureValidator, and HealingLearning remain authoritative within their domains.
- Protected standby capacity remains a hard safety floor.
- Durable state must permit restart reconciliation without blind replay.
- Every derived relationship carries provenance and evidence references.
- Independent failure domains may recover concurrently; conflicting operations are ordered.
- A healing episode closes only after authoritative verification and no secondary damage.
- main is not modified.

## Components

### Durable Evidence Graph

Stores immutable evidence observations and explicit relationships. Evidence records include scope, entity, relation, source authority, generation, timestamp, confidence, and payload. Relationships are derived only from supplied authoritative identities.

### Dependency and Blast-Radius Analyzer

Traverses persisted relationships to identify directly and transitively affected workloads, paths, nodes, allocations, and control-plane scopes. It reports dependency paths and failure-domain impact without declaring physical health itself.

### Failure Correlator

Groups observations into recovery episodes using exact identity, temporal overlap, shared failure domains, and explicit dependency relationships. It preserves independent failures when evidence does not support correlation.

### Adaptive Healing Planner

Consumes the evidence graph and existing healing policy constraints to produce an ordered plan. It chooses containment, recovery, migration, degraded operation, or observation based on confidence, criticality, blast radius, cascade risk, redundancy, reversibility, and protected capacity.

### Recovery Reconciler

Persists intended steps and observed authoritative outcomes. After restart it compares durable intent with authoritative current state and returns resume, compensate, or replan without blindly replaying completed actions.

### Learning Closure

Records complete episode evidence and outcome in the existing learning authority, including provenance and secondary effects.

## Data Flow

Authoritative observations -> durable evidence graph -> dependency/blast-radius analysis -> failure correlation -> adaptive plan -> existing authoritative executors -> authoritative verification -> reconciliation -> closure -> learning.

## Testing

Focused behavioral tests cover graph persistence, dependency traversal, failure correlation, protected standby behavior, recovery ordering, concurrent independent recovery, conflict serialization, restart reconciliation, secondary-failure replanning, closure, learning, and exact path identity. The GPU fabric workflow remains the final integration gate.
