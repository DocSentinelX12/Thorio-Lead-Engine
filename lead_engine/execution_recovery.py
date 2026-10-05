"""Checkpoint and elastic recovery planning primitives."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Sequence


@dataclass(frozen=True)
class CheckpointManifest:
    workload_id: str
    execution_plan_id: str
    checkpoint_id: str
    completed_unit_ids: tuple[str, ...]
    partition_state: tuple[tuple[str, str], ...]
    digest: str

    @classmethod
    def create(cls, *, workload_id: str, execution_plan_id: str, checkpoint_id: str,
               completed_unit_ids: Sequence[str],
               partition_state: Sequence[tuple[str, str]]) -> "CheckpointManifest":
        units = tuple(dict.fromkeys(str(item).strip() for item in completed_unit_ids if str(item).strip()))
        state = tuple(sorted((str(k).strip(), str(v).strip()) for k, v in partition_state
                             if str(k).strip() and str(v).strip()))
        if not workload_id.strip() or not execution_plan_id.strip() or not checkpoint_id.strip():
            raise ValueError("checkpoint identity fields are required")
        material = {
            "workload_id": workload_id,
            "execution_plan_id": execution_plan_id,
            "checkpoint_id": checkpoint_id,
            "completed_unit_ids": units,
            "partition_state": state,
        }
        digest = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return cls(workload_id, execution_plan_id, checkpoint_id, units, state, digest)


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    checkpoint_id: str
    checkpoint_digest: str
    unavailable_node_ids: tuple[str, ...]
    replacement_node_ids: tuple[str, ...]
    rank_reassignments: tuple[tuple[str, str], ...]


class ExecutionRecoveryPlanner:
    def decide(self, *, checkpoint: CheckpointManifest,
               active_node_ids: Sequence[str],
               unavailable_node_ids: Sequence[str],
               candidate_node_ids: Sequence[str],
               elastic: bool) -> RecoveryDecision:
        active = tuple(dict.fromkeys(str(x).strip() for x in active_node_ids if str(x).strip()))
        unavailable = tuple(dict.fromkeys(str(x).strip() for x in unavailable_node_ids if str(x).strip()))
        candidates = tuple(dict.fromkeys(str(x).strip() for x in candidate_node_ids if str(x).strip()))
        if not checkpoint.digest:
            raise ValueError("checkpoint digest is required")
        if not unavailable:
            return RecoveryDecision("resume", checkpoint.checkpoint_id, checkpoint.digest, (), (), ())
        if not elastic:
            return RecoveryDecision("restore", checkpoint.checkpoint_id, checkpoint.digest, unavailable, (), ())
        replacements = tuple(x for x in candidates if x not in active and x not in unavailable)
        if len(replacements) < len(unavailable):
            return RecoveryDecision("restore", checkpoint.checkpoint_id, checkpoint.digest, unavailable, (), ())
        replacement_tuple = replacements[:len(unavailable)]
        reassignments = tuple(zip(unavailable, replacement_tuple))
        return RecoveryDecision(
            "restore_and_rebalance",
            checkpoint.checkpoint_id,
            checkpoint.digest,
            unavailable,
            replacement_tuple,
            reassignments,
        )
