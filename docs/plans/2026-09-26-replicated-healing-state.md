# Replicated Healing State and Quorum Hardening

Date: 2026-09-26
Branch: feature/gpu-fabric-foundation

## Objective

Make autonomous healing state resilient to controller loss, replica loss, stale-controller execution, and split-brain conditions without replacing authoritative physical, placement, execution, or inventory state.

## Architecture

The layer provides:

- fixed odd-sized replica sets with majority quorum;
- hash-chained durable replication log;
- monotonic controller generations;
- durable fencing tokens;
- quorum-gated leadership;
- quorum-gated healing mutations;
- crash-safe replay of committed entries;
- replica reconciliation from a quorum-agreed canonical log;
- explicit checksum conflict detection;
- explicit replica repair by rebuilding the healing projection from committed history;
- replicated control-plane projections;
- conservative control-plane restoration that always returns through reconciliation before activation.

The replicated layer remains a durability and coordination authority for healing state. It does not establish physical truth.

## Connected Components

- `lead_engine/healing_replication.py`
- `lead_engine/healing_actions.py`
- `lead_engine/healing_control_plane.py`
- `lead_engine/test_healing_replication.py`
- `lead_engine/test_healing_actions.py`
- `lead_engine/test_healing_control_plane.py`
- `.github/workflows/gpu-fabric-validation.yml`

## Safety Properties

1. Fewer than a majority of replicas cannot commit healing mutations.
2. A stale controller cannot mutate state after a newer fencing token is established.
3. Controller generations are strictly monotonic.
4. Replication entries are hash chained and conflicting committed histories are rejected.
5. A committed log entry may remain unapplied after a crash, but reconciliation replays it before state is considered converged.
6. A lagging replica is repaired from a quorum-agreed canonical history.
7. Control-plane restoration is conservative and returns to fenced-pending-reconciliation rather than automatically becoming active.
8. Transactional healing checkpoints can use quorum-replicated healing state.
9. Existing `HealingState` remains the lifecycle schema and does not become a physical-state authority.
10. No protected standby, physical path, placement, or execution authority is bypassed.

## Verification

The production GPU Fabric Validation workflow covers:

- quorum commit;
- minority refusal;
- fencing after takeover;
- monotonic generations;
- checksum conflict detection;
- restart persistence;
- lagging replica reconciliation;
- replicated control-plane projections;
- conservative control-plane restoration;
- transactional healing through replicated state;
- the complete existing GPU fabric regression suite.

Final verification must pass on `feature/gpu-fabric-foundation` before this layer is considered complete.
