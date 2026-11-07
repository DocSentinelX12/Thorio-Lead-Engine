from __future__ import annotations

from lead_engine.agent_queue import (
    FAILED,
    QUEUED,
    claim,
    enqueue,
    fail,
    pending,
    requeue_failed_matching,
)
from lead_engine.database import LeadDB


ROUTE_SCOPE_ERROR = "Route-specific evidence must remain in route_research."


def _db(tmp_path):
    return LeadDB(data_dir=tmp_path)


def test_requeue_failed_matching_is_exact_bounded_and_idempotent(tmp_path):
    db = _db(tmp_path)
    target = enqueue(
        db,
        "company_research",
        {"lead": {"fingerprint": "recover-route-evidence"}},
    )
    claimed = claim(db, "company_research", worker_id="recovery-test", limit=1)[0]
    fail(db, target["task_id"], worker_id="recovery-test", error=ROUTE_SCOPE_ERROR)

    unrelated_error = enqueue(
        db,
        "company_research",
        {"lead": {"fingerprint": "keep-unrelated-error"}},
    )
    claim(db, "company_research", worker_id="unrelated-error-test", limit=1)
    fail(db, unrelated_error["task_id"], worker_id="unrelated-error-test", error="different failure")

    unrelated_agent = enqueue(db, "paxus_research", {"fingerprint": "keep-other-agent"})
    claim(db, "paxus_research", worker_id="other-agent-test", limit=1)
    fail(db, unrelated_agent["task_id"], worker_id="other-agent-test", error=ROUTE_SCOPE_ERROR)

    over_attempted = enqueue(
        db,
        "company_research",
        {"lead": {"fingerprint": "keep-over-attempted"}},
    )
    claim(db, "company_research", worker_id="over-attempted-test", limit=1)
    db.queue_update(over_attempted["task_id"], attempts=2)
    fail(db, over_attempted["task_id"], worker_id="over-attempted-test", error=ROUTE_SCOPE_ERROR)

    recovered = requeue_failed_matching(
        db,
        agent="company_research",
        error_substring=ROUTE_SCOPE_ERROR,
        max_attempts=1,
        limit=1,
    )

    assert recovered == [target["task_id"]]
    queued = next(item for item in pending(db, "company_research") if item["task_id"] == target["task_id"])
    assert queued["status"] == QUEUED
    assert queued["attempts"] == claimed["attempts"]
    assert queued["last_error"] == ROUTE_SCOPE_ERROR
    assert queued["worker_id"] is None
    assert queued["lease_until"] is None
    assert queued["lease_token"] is None
    assert requeue_failed_matching(
        db,
        agent="company_research",
        error_substring=ROUTE_SCOPE_ERROR,
        max_attempts=1,
        limit=250,
    ) == []

    assert db.queue_get(unrelated_error["task_id"])[3] == FAILED
    assert db.queue_get(unrelated_agent["task_id"])[3] == FAILED
    assert db.queue_get(over_attempted["task_id"])[3] == FAILED
    db.close()
