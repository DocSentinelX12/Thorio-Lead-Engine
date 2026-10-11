from unittest.mock import MagicMock, patch

from .database import LeadDB
from .pipeline import LeadPipeline
from .scheduler import LeadScheduler
from .sources import StaticLeadSource
from .runner import LeadEngineRunner


def test_scheduler_defers_airtable_until_after_bounded_specialist_pass(tmp_path):
    events = []
    db = LeadDB(data_dir=str(tmp_path))
    pipeline = LeadPipeline(db=db, sync_enabled=True)
    runner = LeadEngineRunner(pipeline=pipeline)

    def run_source(source, checkpoint=None):
        events.append(("collect_persist", pipeline.sync_enabled))
        return {"discovered_count": 0, "accepted_count": 0, "duplicate_count": 0, "failed_count": 0}

    runner.run_source = run_source
    scheduler = LeadScheduler(runner=runner)

    scheduler.agent_orchestrator = MagicMock()
    scheduler.agent_orchestrator.run_all_once.side_effect = lambda **kwargs: events.append(("specialists", pipeline.sync_enabled)) or {"processed_count": 0}
    scheduler._bridge_remote = lambda **kwargs: {"status": "disabled", "published_count": 0, "completed_count": 0, "retried_count": 0}

    with patch("lead_engine.scheduler.process_paxus_research_queue", side_effect=lambda db: events.append(("paxus_research", pipeline.sync_enabled)) or {"processed": 0, "failed": 0}), patch("lead_engine.scheduler.sync_pending", side_effect=lambda db: events.append(("airtable_sync", pipeline.sync_enabled)) or {"synced": [], "already_exists": [], "failed": [], "synced_count": 0, "already_exists_count": 0, "failed_count": 0}):
        scheduler.run([StaticLeadSource([])], agent_max_rounds=1)

    assert events == [
        ("collect_persist", False),
        ("specialists", True),
        ("paxus_research", True),
        ("airtable_sync", True),
    ]
    assert pipeline.sync_enabled is True
    db.close()


def test_scheduler_skips_airtable_drain_when_sync_is_disabled(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    pipeline = LeadPipeline(db=db, sync_enabled=False)
    runner = LeadEngineRunner(pipeline=pipeline)
    scheduler = LeadScheduler(runner=runner)
    scheduler.agent_orchestrator = MagicMock()
    scheduler.agent_orchestrator._queue_health.return_value = {
        "queued_count": 0,
        "running_count": 0,
        "failed_count": 0,
    }
    bridge_calls = []
    scheduler._bridge_remote = lambda **kwargs: bridge_calls.append(True) or {
        "status": "disabled",
        "published_count": 0,
        "completed_count": 0,
        "retried_count": 0,
    }

    with patch("lead_engine.scheduler.drain_pending", side_effect=AssertionError("Airtable drain must not run while sync is disabled")), patch(
        "lead_engine.scheduler.process_paxus_research_queue",
        side_effect=AssertionError("Paxus research must be deferred while sync is disabled"),
    ):
        result = scheduler.run([StaticLeadSource([])], agent_max_rounds=1)
        bounded = scheduler.run_bounded([StaticLeadSource([])], interval_seconds=0, max_cycles=1)

    assert result["sync"]["status"] == "disabled"
    assert result["sync"]["failed_count"] == 0
    assert result["agents"]["status"] == "deferred"
    assert result["agents"]["drain_complete"] is True
    assert scheduler.agent_orchestrator.run_all_once.call_count == 0
    assert bridge_calls == []
    assert bounded["status"] == "sync_disabled"
    observability = db.get_state("sync_observability")
    assert observability["successful_sync_runs"] == 0
    assert observability["last_successful_sync"] is None
    db.close()
