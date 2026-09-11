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
