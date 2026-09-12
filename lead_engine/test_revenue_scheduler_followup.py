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
