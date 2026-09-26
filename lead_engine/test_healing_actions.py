from __future__ import annotations

import pytest

from lead_engine.healing_actions import HealingActionExecutor, HealingActionError
from lead_engine.healing_state import HealingState


def test_transactional_action_checkpoints_and_closes(tmp_path):
    state = HealingState(str(tmp_path / "healing.sqlite3"))
    action = state.ensure_action(scope_id="scope", failure_fingerprint="f", generation=1, strategy="known_good")
    state.claim_action(action["action_id"], owner="worker", now=1.0, lease_seconds=100)
    executor = HealingActionExecutor(state)
    seen = []
    result = executor.execute(
        action_id=action["action_id"], owner="worker",
        steps=(
            ("isolate", lambda: seen.append("isolated")),
            ("reinitialize", lambda: seen.append("reinitialized")),
        ),
        now=2.0,
    )
    assert result["state"] == "SUCCEEDED"
    assert seen == ["isolated", "reinitialized"]
    assert result["checkpoint"] == "reinitialize"


def test_transactional_action_compensates_after_failed_step(tmp_path):
    state = HealingState(str(tmp_path / "healing.sqlite3"))
    action = state.ensure_action(scope_id="scope", failure_fingerprint="f", generation=1, strategy="known_good")
    state.claim_action(action["action_id"], owner="worker", now=1.0, lease_seconds=100)
    executor = HealingActionExecutor(state)
    events = []
    result = executor.execute(
        action_id=action["action_id"], owner="worker",
        steps=(
            ("isolate", lambda: events.append("isolate")),
            ("reinitialize", lambda: (_ for _ in ()).throw(RuntimeError("device unavailable"))),
        ),
        compensations=(("isolate", lambda: events.append("restore")),),
        now=2.0,
    )
    assert result["state"] == "ROLLED_BACK"
    assert events == ["isolate", "restore"]


def test_transactional_action_rejects_stale_owner(tmp_path):
    state = HealingState(str(tmp_path / "healing.sqlite3"))
    action = state.ensure_action(scope_id="scope", failure_fingerprint="f", generation=1, strategy="known_good")
    state.claim_action(action["action_id"], owner="worker", now=1.0, lease_seconds=1)
    executor = HealingActionExecutor(state)
    with pytest.raises(HealingActionError, match="fenced"):
        executor.execute(action_id=action["action_id"], owner="other", steps=(), now=2.0)


def test_transactional_action_can_use_quorum_replicated_healing_state(tmp_path):
    from lead_engine.healing_replication import ReplicatedHealingState

    paths = tuple(str(tmp_path / f"replica-{index}.sqlite3") for index in range(3))
    state = ReplicatedHealingState(paths)
    leader = state.acquire_leadership("worker", generation=1, now=1.0)
    action = state.ensure_action(
        scope_id="scope",
        failure_fingerprint="f",
        generation=1,
        strategy="known_good",
        controller_id="worker",
        fencing_token=leader["fencing_token"],
        now=1.0,
    )
    state.claim_action(
        action["action_id"],
        owner="worker",
        controller_id="worker",
        fencing_token=leader["fencing_token"],
        now=1.0,
        lease_seconds=100,
    )
    executor = HealingActionExecutor(state)
    result = executor.execute(
        action_id=action["action_id"],
        owner="worker",
        steps=(("isolate", lambda: None), ("reinitialize", lambda: None)),
        now=2.0,
    )
    assert result["state"] == "SUCCEEDED"
    assert all(replica["applied_index"] == state.commit_index() for replica in state.snapshot()["replicas"])
    assert state.action(action["action_id"])["checkpoint"] == "reinitialize"
