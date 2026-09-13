import json

from .agent_queue import pending
from .database import LeadDB


def test_persisted_follow_up_task_migrates_to_outreach_closer(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    db.conn.execute(
        "INSERT INTO agent_queue (task_id, agent, queue, status, priority, payload, dedupe_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "legacy-follow-up-task",
            "follow_up",
            "revenue.follow_up",
            "queued",
            10,
            json.dumps({"lead": {"fingerprint": "legacy-lead"}, "outcome": "no_response", "execute": True}),
            "legacy-follow-up-dedupe",
            "2026-09-13T00:00:00+00:00",
            "2026-09-13T00:00:00+00:00",
        ),
    )
    db.conn.commit()
    db.close()

    migrated = LeadDB(data_dir=tmp_path)
    tasks = pending(migrated, "outreach_closer")

    assert len(tasks) == 1
    assert tasks[0]["agent"] == "outreach_closer"
    assert tasks[0]["queue"] == "revenue.outreach"
    assert tasks[0]["payload"]["revenue_action"] == "follow_up"
    assert pending(migrated, "follow_up") == []
