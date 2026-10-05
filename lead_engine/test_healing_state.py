from __future__ import annotations

import sqlite3

import pytest

from lead_engine.healing_state import HealingState, HealingStateError


def test_healing_state_persists_action_lease_checkpoint_and_reconciliation(tmp_path):
    db_path = str(tmp_path / "healing.sqlite3")
    state = HealingState(db_path)
    action = state.ensure_action(
        scope_id="path-a",
        failure_fingerprint="failure-1",
        generation=1,
        strategy="known_good_recovery",
    )
    claimed = state.claim_action(action["action_id"], owner="controller-a", now=10.0, lease_seconds=5.0)
    assert claimed["owner"] == "controller-a"
    assert claimed["fencing_token"] == 1

    state.checkpoint(
        action_id=action["action_id"],
        owner="controller-a",
        checkpoint="physical_reverify",
        payload={"path_id": "path-a"},
        now=11.0,
    )
    state.record_reconciliation(
        action_id=action["action_id"],
        authoritative_state={"physical_state": "FAILED"},
        observed_at=11.0,
    )

    restored = HealingState(db_path)
    snapshot = restored.action(action["action_id"])
    assert snapshot["checkpoint"] == "physical_reverify"
    assert snapshot["reconciliation"]["authoritative_state"]["physical_state"] == "FAILED"


def test_healing_state_rejects_stale_generation_and_fenced_owner(tmp_path):
    state = HealingState(str(tmp_path / "healing.sqlite3"))
    old = state.ensure_action(scope_id="scope", failure_fingerprint="f1", generation=1, strategy="r1")
    state.ensure_action(scope_id="scope", failure_fingerprint="f2", generation=2, strategy="r2")
    with pytest.raises(HealingStateError, match="stale generation"):
        state.claim_action(old["action_id"], owner="old", now=1.0, lease_seconds=10.0)

    fresh = state.ensure_action(scope_id="scope-2", failure_fingerprint="f3", generation=1, strategy="r1")
    state.claim_action(fresh["action_id"], owner="a", now=1.0, lease_seconds=1.0)
    takeover = state.claim_action(fresh["action_id"], owner="b", now=3.0, lease_seconds=10.0)
    assert takeover["owner"] == "b"
    assert takeover["fencing_token"] == 2
    with pytest.raises(HealingStateError, match="fenced"):
        state.checkpoint(action_id=fresh["action_id"], owner="a", checkpoint="stale", payload={})


def test_healing_state_is_idempotent_and_preserves_all_actions(tmp_path):
    state = HealingState(str(tmp_path / "healing.sqlite3"))
    first = state.ensure_action(scope_id="s", failure_fingerprint="f", generation=1, strategy="r")
    again = state.ensure_action(scope_id="s", failure_fingerprint="f", generation=1, strategy="r")
    assert again["action_id"] == first["action_id"]
    for index in range(10):
        state.ensure_action(scope_id=f"s-{index}", failure_fingerprint=f"f-{index}", generation=1, strategy="r")
    assert len(state.list_actions()) == 11


def test_healing_state_degraded_mode_is_durable(tmp_path):
    path = str(tmp_path / "healing.sqlite3")
    state = HealingState(path)
    state.enter_degraded(scope_id="scope-a", reason="no-safe-recovery", now=5.0)
    restored = HealingState(path)
    assert restored.degraded_scope("scope-a")["reason"] == "no-safe-recovery"
