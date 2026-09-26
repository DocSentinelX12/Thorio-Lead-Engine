from __future__ import annotations

import sqlite3

import pytest

from lead_engine.healing_replication import (
    HealingReplicationError,
    ReplicatedHealingState,
)


def _paths(tmp_path):
    return tuple(str(tmp_path / f"replica-{index}.sqlite3") for index in range(3))


def test_quorum_commits_healing_action_and_replica_catches_up(tmp_path):
    state = ReplicatedHealingState(_paths(tmp_path))
    leader = state.acquire_leadership("controller-a", generation=1, now=10.0)
    action = state.ensure_action(
        scope_id="path-a",
        failure_fingerprint="failure-1",
        generation=1,
        strategy="known_good_recovery",
        controller_id="controller-a",
        fencing_token=leader["fencing_token"],
        now=11.0,
    )
    assert action["action_id"].startswith("heal:")
    assert state.commit_index() == 1
    state.claim_action(
        action["action_id"],
        owner="controller-a",
        controller_id="controller-a",
        fencing_token=leader["fencing_token"],
        now=11.5,
        lease_seconds=5.0,
    )

    state.set_replica_available(2, False)
    state.checkpoint(
        action_id=action["action_id"],
        owner="controller-a",
        checkpoint="physical_reverify",
        payload={"path_id": "path-a"},
        controller_id="controller-a",
        fencing_token=leader["fencing_token"],
        now=12.0,
    )
    assert state.commit_index() == 2

    state.set_replica_available(2, True)
    repaired = state.reconcile()
    assert repaired["commit_index"] == 2
    assert repaired["replicas"][2]["commit_index"] == 2

    restored = ReplicatedHealingState(_paths(tmp_path))
    assert restored.action(action["action_id"])["checkpoint"] == "physical_reverify"


def test_minority_cannot_mutate_or_claim_authority(tmp_path):
    state = ReplicatedHealingState(_paths(tmp_path))
    state.acquire_leadership("controller-a", generation=1, now=10.0)
    state.set_replica_available(0, False)
    state.set_replica_available(1, False)

    with pytest.raises(HealingReplicationError, match="quorum"):
        state.ensure_action(
            scope_id="scope",
            failure_fingerprint="failure",
            generation=1,
            strategy="recovery",
            controller_id="controller-a",
            fencing_token=1,
            now=11.0,
        )
    with pytest.raises(HealingReplicationError, match="quorum"):
        state.acquire_leadership("controller-b", generation=2, now=12.0)


def test_fencing_prevents_stale_controller_after_takeover(tmp_path):
    state = ReplicatedHealingState(_paths(tmp_path))
    first = state.acquire_leadership("controller-a", generation=1, now=10.0)
    second = state.acquire_leadership("controller-b", generation=2, now=20.0)
    assert second["fencing_token"] > first["fencing_token"]

    with pytest.raises(HealingReplicationError, match="fenced"):
        state.ensure_action(
            scope_id="scope",
            failure_fingerprint="failure",
            generation=2,
            strategy="recovery",
            controller_id="controller-a",
            fencing_token=first["fencing_token"],
            now=21.0,
        )


def test_leadership_requires_monotonic_generation(tmp_path):
    state = ReplicatedHealingState(_paths(tmp_path))
    state.acquire_leadership("controller-a", generation=3, now=10.0)
    with pytest.raises(HealingReplicationError, match="generation"):
        state.acquire_leadership("controller-b", generation=3, now=11.0)


def test_replicated_state_rejects_conflicting_replica_log(tmp_path):
    paths = _paths(tmp_path)
    state = ReplicatedHealingState(paths)
    leader = state.acquire_leadership("controller-a", generation=1, now=10.0)
    state.ensure_action(
        scope_id="scope",
        failure_fingerprint="failure",
        generation=1,
        strategy="recovery",
        controller_id="controller-a",
        fencing_token=leader["fencing_token"],
        now=11.0,
    )

    with sqlite3.connect(paths[1]) as db:
        db.execute(
            "UPDATE healing_replication_log SET checksum=? WHERE log_index=1",
            ("corrupted",),
        )

    with pytest.raises(HealingReplicationError, match="checksum"):
        state.reconcile()


def test_restart_preserves_committed_index_and_fencing(tmp_path):
    paths = _paths(tmp_path)
    state = ReplicatedHealingState(paths)
    leader = state.acquire_leadership("controller-a", generation=1, now=10.0)
    action = state.ensure_action(
        scope_id="scope",
        failure_fingerprint="failure",
        generation=1,
        strategy="recovery",
        controller_id="controller-a",
        fencing_token=leader["fencing_token"],
        now=11.0,
    )

    restored = ReplicatedHealingState(paths)
    assert restored.commit_index() == 1
    assert restored.leadership()["fencing_token"] == leader["fencing_token"]
    assert restored.action(action["action_id"])["scope_id"] == "scope"


def test_quorum_requires_majority_of_configured_replicas(tmp_path):
    with pytest.raises(ValueError, match="odd"):
        ReplicatedHealingState(_paths(tmp_path)[:2])

    with pytest.raises(ValueError, match="replica"):
        ReplicatedHealingState(("", "", ""))


def test_reconciliation_never_rolls_back_a_higher_committed_index(tmp_path):
    paths = _paths(tmp_path)
    state = ReplicatedHealingState(paths)
    leader = state.acquire_leadership("controller-a", generation=1, now=10.0)
    action = state.ensure_action(
        scope_id="scope",
        failure_fingerprint="failure",
        generation=1,
        strategy="recovery",
        controller_id="controller-a",
        fencing_token=leader["fencing_token"],
        now=11.0,
    )
    state.claim_action(
        action["action_id"],
        owner="controller-a",
        controller_id="controller-a",
        fencing_token=leader["fencing_token"],
        now=11.5,
        lease_seconds=5.0,
    )
    state.set_replica_available(2, False)
    state.checkpoint(
        action_id=state.list_actions()[0]["action_id"],
        owner="controller-a",
        checkpoint="verify",
        payload={},
        controller_id="controller-a",
        fencing_token=leader["fencing_token"],
        now=12.0,
    )
    state.set_replica_available(2, True)
    result = state.reconcile()
    assert result["commit_index"] == 2
    assert all(replica["commit_index"] == 2 for replica in result["replicas"])


def test_replicated_projection_survives_restart_and_quorum_loss(tmp_path):
    paths = _paths(tmp_path)
    state = ReplicatedHealingState(paths)
    leader = state.acquire_leadership("controller-a", generation=1, now=10.0)
    state.record_projection(
        name="control-plane",
        value={"state": "ACTIVE", "generation": 1},
        controller_id="controller-a",
        fencing_token=leader["fencing_token"],
        now=11.0,
    )
    restored = ReplicatedHealingState(paths)
    assert restored.projection("control-plane")["value"]["state"] == "ACTIVE"

    restored.set_replica_available(0, False)
    restored.set_replica_available(1, False)
    with pytest.raises(HealingReplicationError, match="quorum"):
        restored.record_projection(
            name="control-plane",
            value={"state": "FENCED_PENDING_RECONCILIATION"},
            controller_id="controller-a",
            fencing_token=leader["fencing_token"],
            now=12.0,
        )
