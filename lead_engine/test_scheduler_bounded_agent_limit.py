from unittest.mock import MagicMock, patch

from .scheduler import LeadScheduler
from .sources import StaticLeadSource


def test_bounded_scheduler_uses_one_agent_drain_round():
    runner = MagicMock()
    runner.run_source.return_value = {
        "discovered_count": 0,
        "accepted_count": 0,
        "duplicate_count": 0,
        "failed_count": 0,
    }
    scheduler = LeadScheduler(runner=runner)
    source = StaticLeadSource([])

    with patch.object(scheduler.agent_orchestrator, "run_all_once", return_value={}) as run_agents:
        scheduler.run_bounded([source], interval_seconds=0, max_cycles=1)

    run_agents.assert_called_once_with(limit_per_agent=5, max_rounds=1)
