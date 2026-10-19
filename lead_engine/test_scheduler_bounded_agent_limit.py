from unittest.mock import MagicMock, patch

from .agent_registry import ALL_AGENT_ROLES
from .scheduler import LeadScheduler
from .sources import StaticLeadSource


def test_bounded_scheduler_uses_configured_agent_drain_rounds(monkeypatch):
    runner = MagicMock()
    runner.run_source.return_value = {
        "discovered_count": 0,
        "accepted_count": 0,
        "duplicate_count": 0,
        "failed_count": 0,
    }
    monkeypatch.setenv("THORIO_AGENT_DRAIN_ROUNDS", "4")
    scheduler = LeadScheduler(runner=runner)
    source = StaticLeadSource([])

    with patch.object(scheduler.agent_orchestrator, "run_all_once", return_value={}) as run_agents:
        scheduler.run_bounded([source], interval_seconds=0, max_cycles=1)

    run_agents.assert_called_once_with(
        limit_per_agent=max(role.max_concurrency for role in ALL_AGENT_ROLES),
        max_rounds=4,
    )


def test_bounded_scheduler_caps_agent_drain_rounds(monkeypatch):
    runner = MagicMock()
    runner.run_source.return_value = {
        "discovered_count": 0,
        "accepted_count": 0,
        "duplicate_count": 0,
        "failed_count": 0,
    }
    monkeypatch.setenv("THORIO_AGENT_DRAIN_ROUNDS", "9999")
    scheduler = LeadScheduler(runner=runner)
    source = StaticLeadSource([])

    with patch.object(scheduler.agent_orchestrator, "run_all_once", return_value={}) as run_agents:
        scheduler.run_bounded([source], interval_seconds=0, max_cycles=1)

    run_agents.assert_called_once_with(
        limit_per_agent=max(role.max_concurrency for role in ALL_AGENT_ROLES),
        max_rounds=32,
    )


def test_collection_backpressure_pauses_at_configured_queue_threshold(monkeypatch):
    scheduler = LeadScheduler.__new__(LeadScheduler)
    scheduler.agent_orchestrator = MagicMock()
    scheduler.agent_orchestrator._queue_health.return_value = {
        "queued_count": 4990,
        "running_count": 10,
        "failed_count": 0,
    }
    monkeypatch.setenv("THORIO_AGENT_BACKLOG_COLLECTION_PAUSE_THRESHOLD", "5000")

    state = scheduler._source_collection_backlog_state()

    assert state == {"paused": True, "threshold": 5000, "pending_count": 5000}


def test_collection_backpressure_is_disabled_without_positive_threshold(monkeypatch):
    scheduler = LeadScheduler.__new__(LeadScheduler)
    scheduler.agent_orchestrator = MagicMock()
    monkeypatch.setenv("THORIO_AGENT_BACKLOG_COLLECTION_PAUSE_THRESHOLD", "0")

    state = scheduler._source_collection_backlog_state()

    assert state == {"paused": False, "threshold": 0, "pending_count": 0}
    scheduler.agent_orchestrator._queue_health.assert_not_called()
