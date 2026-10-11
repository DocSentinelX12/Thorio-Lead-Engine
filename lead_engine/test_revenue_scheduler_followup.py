from unittest.mock import MagicMock, patch

from .scheduler import LeadScheduler
from .sources import StaticLeadSource


def test_scheduler_enqueues_due_revenue_followups_before_specialist_drain():
    runner = MagicMock()
    runner.run_source.return_value = {"discovered_count": 0, "accepted_count": 0, "duplicate_count": 0, "failed_count": 0}
    scheduler = LeadScheduler(runner=runner)
    source = StaticLeadSource([])
    with patch("lead_engine.scheduler.enqueue_due_followups", return_value=3) as enqueue_due, patch.object(scheduler.agent_orchestrator, "run_all_once", return_value={"failed_count": 0}) as run_agents:
        result = scheduler.run_bounded([source], interval_seconds=0, max_cycles=1)
    enqueue_due.assert_called_once_with(runner.pipeline.db)
    run_agents.assert_called_once()
    assert result["due_followups_enqueued"] == 3


def test_inbound_observation_failure_blocks_followup_enqueue_and_persists_health(monkeypatch):
    from datetime import datetime, timezone
    from lead_engine.revenue_conversation import enqueue_due_followups

    class DB:
        def __init__(self):
            self.state = {}
            self.enqueued = []

        def all_leads(self):
            return [{
                "fingerprint": "lead-1",
                "follow_up_due": True,
                "outreach_state": "awaiting_response",
                "next_follow_up_at": datetime.now(timezone.utc).isoformat(),
            }]

        def set_state(self, key, value):
            self.state[key] = value

        def get_state(self, key):
            return self.state.get(key)

    db = DB()
    monkeypatch.setattr(
        "lead_engine.browser_revenue_inbound.poll_browser_revenue_inbound",
        lambda db, limit=100: {
            "status": "completed",
            "observed_count": 0,
            "recorded_count": 0,
            "failed_count": 1,
            "failures": [{"opportunity_id": "lead-1", "channel": "linkedin", "error": "inbox unavailable"}],
        },
    )
    monkeypatch.setattr("lead_engine.revenue_conversation.enqueue", lambda *args, **kwargs: db.enqueued.append((args, kwargs)))

    assert enqueue_due_followups(db) == 0
    assert db.enqueued == []
    health = db.get_state("revenue_inbound_health")
    assert health["status"] == "failed"
    assert health["failed_count"] == 1
    assert health["failures"][0]["opportunity_id"] == "lead-1"


def test_followup_blocks_when_due_conversation_was_not_in_observer_batch(monkeypatch):
    from datetime import datetime, timezone
    from lead_engine.revenue_conversation import enqueue_due_followups

    class DB:
        def __init__(self):
            self.state = {}
            self.enqueued = []

        def all_leads(self):
            return [{
                "fingerprint": "lead-unobserved",
                "conversation_id": "conversation-unobserved",
                "outreach_channel": "linkedin",
                "outreach_state": "awaiting_response",
                "follow_up_due": True,
                "next_follow_up_at": datetime.now(timezone.utc).isoformat(),
                "outreach_history": [{
                    "provider_result": {"thread_url": "https://example.invalid/thread/lead-unobserved"}
                }],
            }]

        def set_state(self, key, value):
            self.state[key] = value

        def get_state(self, key):
            return self.state.get(key)

    monkeypatch.delenv("THORIO_ACCOUNT_GMAIL_USERNAME", raising=False)
    monkeypatch.delenv("THORIO_ACCOUNT_GMAIL_PASSWORD", raising=False)
    monkeypatch.delenv("THORIO_REVENUE_BROWSER_INBOUND_TARGETS", raising=False)
    monkeypatch.setattr(
        "lead_engine.browser_revenue_inbound.poll_browser_revenue_inbound",
        lambda db, limit=100: {
            "status": "completed", "observed_count": 0, "recorded_count": 0,
            "failed_count": 0, "failures": [], "observed_opportunity_ids": [],
        },
    )
    db = DB()
    monkeypatch.setattr(
        "lead_engine.revenue_conversation.enqueue",
        lambda *args, **kwargs: db.enqueued.append((args, kwargs)),
    )

    assert enqueue_due_followups(db) == 0
    assert db.enqueued == []
    assert db.get_state("revenue_inbound_health")["status"] == "blocked_unobserved"


def test_followup_queues_only_when_browser_observer_checked_that_lead(monkeypatch):
    import json
    from datetime import datetime, timezone
    from lead_engine.revenue_conversation import enqueue_due_followups

    target = {
        "channel": "linkedin", "account": "linkedin",
        "inbox_url": "https://example.invalid/inbox",
        "message_selector": ".message", "message_author_selector": ".author",
        "message_id_selector": ".id", "timestamp_selector": ".time",
        "body_selector": ".body", "self_marker": "Thorio",
    }
    monkeypatch.setenv("THORIO_REVENUE_BROWSER_INBOUND_TARGETS", json.dumps([target]))
    monkeypatch.delenv("THORIO_ACCOUNT_GMAIL_USERNAME", raising=False)
    monkeypatch.delenv("THORIO_ACCOUNT_GMAIL_PASSWORD", raising=False)

    class DB:
        def __init__(self):
            self.state = {}
            self.enqueued = []

        def all_leads(self):
            return [{
                "fingerprint": "lead-observed",
                "conversation_id": "conversation-observed",
                "outreach_channel": "linkedin",
                "outreach_state": "awaiting_response",
                "follow_up_due": True,
                "next_follow_up_at": datetime.now(timezone.utc).isoformat(),
                "outreach_history": [{
                    "provider_result": {"thread_url": "https://example.invalid/thread/lead-observed"}
                }],
            }]

        def set_state(self, key, value):
            self.state[key] = value

        def get_state(self, key):
            return self.state.get(key)

    monkeypatch.setattr(
        "lead_engine.browser_revenue_inbound.poll_browser_revenue_inbound",
        lambda db, limit=100: {
            "status": "completed", "observed_count": 1, "recorded_count": 0,
            "failed_count": 0, "failures": [],
            "observed_opportunity_ids": ["lead-observed"],
        },
    )
    db = DB()
    monkeypatch.setattr(
        "lead_engine.revenue_conversation.enqueue",
        lambda *args, **kwargs: db.enqueued.append((args, kwargs)),
    )

    assert enqueue_due_followups(db) == 1
    assert len(db.enqueued) == 1
    assert db.get_state("revenue_inbound_health")["status"] == "completed"
