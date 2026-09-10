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

    with patch("lead_engine.scheduler.sync_pending", side_effect=lambda db: events.append(("airtable_sync", pipeline.sync_enabled)) or {"synced": [], "already_exists": [], "failed": [], "synced_count": 0, "already_exists_count": 0, "failed_count": 0}):
        scheduler.run([StaticLeadSource([])], agent_max_rounds=1)

    assert events == [
        ("collect_persist", False),
        ("specialists", True),
        ("airtable_sync", True),
    ]
    assert pipeline.sync_enabled is True
    db.close()
