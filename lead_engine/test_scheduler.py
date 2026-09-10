from unittest.mock import MagicMock, patch

from .database import LeadDB
from .pipeline import LeadPipeline
from .scheduler import LeadScheduler
from .source_definition import SourceDefinition
from .source_adapters import create_adapter
from .sources import StaticLeadSource


def test_scheduler_runs_multiple_sources():
    runner = MagicMock()
    runner.run_source.side_effect = [
        {"processed_count": 2, "failed_count": 0, "total": 2},
        {"processed_count": 1, "failed_count": 0, "total": 1},
    ]
    scheduler = LeadScheduler(runner=runner)
    sources = [StaticLeadSource([]), StaticLeadSource([])]
    result = scheduler.run(sources)
    assert result["source_count"] == 2
    assert result["failed_count"] == 0
    assert runner.run_source.call_count == 2


def test_scheduler_keeps_running_after_source_failure():
    runner = MagicMock()
    runner.run_source.side_effect = [
        RuntimeError("source unavailable"),
        {"processed_count": 1, "failed_count": 0, "total": 1},
    ]
    scheduler = LeadScheduler(runner=runner)
    sources = [StaticLeadSource([]), StaticLeadSource([])]
    result = scheduler.run(sources)
    assert result["source_count"] == 2
    assert result["successful_source_count"] == 1
    assert result["failed_count"] == 1
    assert result["failed"][0]["error"] == "source unavailable"
    assert runner.run_source.call_count == 2


def test_scheduler_parallelizes_collection_but_keeps_processing_sequential(monkeypatch):
    class CollectingSource:
        def __init__(self, name):
            self.name = name
            self.last_checkpoint = None

        def collect(self, checkpoint=None):
            self.last_checkpoint = f"next-{self.name}"
            return [{"company": self.name, "source": self.name}]

    runner = MagicMock()
    runner.process.return_value = {"discovered_count": 1, "accepted_count": 1, "duplicate_count": 0, "failed_count": 0}
    monkeypatch.setenv("THORIO_SOURCE_COLLECTION_WORKERS", "2")
    scheduler = LeadScheduler(runner=runner)
    sources = [CollectingSource("one"), CollectingSource("two")]
    result = scheduler.run(sources)
    assert result["source_count"] == 2
    assert result["successful_source_count"] == 2
    assert result["failed_count"] == 0
    assert runner.run_source.call_count == 0
    assert runner.process.call_count == 2
    assert runner.process.call_args_list[0].args[0] == [{"company": "one", "source": "one"}]
    assert runner.process.call_args_list[1].args[0] == [{"company": "two", "source": "two"}]
    assert sources[0].last_checkpoint == "next-one"
    assert sources[1].last_checkpoint == "next-two"


def test_scheduler_parallel_collection_does_not_advance_failed_source_checkpoint(monkeypatch, tmp_path):
    class CollectingSource:
        def __init__(self, name):
            self.name = name
            self.last_checkpoint = None

        def collect(self, checkpoint=None):
            self.last_checkpoint = f"next-{self.name}"
            return [{"company": self.name, "source": self.name}]

    runner = MagicMock()
    db = LeadDB(data_dir=str(tmp_path))
    pipeline = LeadPipeline(db=db)
    runner.pipeline = pipeline
    runner.process.side_effect = [
        {"discovered_count": 1, "accepted_count": 0, "duplicate_count": 0, "failed_count": 1},
        {"discovered_count": 1, "accepted_count": 1, "duplicate_count": 0, "failed_count": 0},
    ]
    monkeypatch.setenv("THORIO_SOURCE_COLLECTION_WORKERS", "2")
    scheduler = LeadScheduler(runner=runner)
    sources = [CollectingSource("one"), CollectingSource("two")]
    scheduler.checkpoint_runner.save_checkpoint(sources[0], "old-one")
    scheduler.checkpoint_runner.save_checkpoint(sources[1], "old-two")
    result = scheduler.run(sources)
    assert result["failed_count"] == 0
    assert scheduler.checkpoint_runner.get_checkpoint(sources[0]) == "old-one"
    assert scheduler.checkpoint_runner.get_checkpoint(sources[1]) == "next-two"
    db.close()


def test_scheduler_respects_source_poll_interval():
    runner = MagicMock()
    runner.run_source.return_value = {"processed_count": 1, "failed_count": 0, "total": 1}
    definition = SourceDefinition(
        name="Hourly API", provider="Example", collector_type="json", url="https://example.com/api",
        pagination_type="none", poll_interval_seconds=3600,
    )
    source = create_adapter(definition=definition)
    scheduler = LeadScheduler(runner=runner)
    first = scheduler.run([source])
    second = scheduler.run([source])
    assert first["successful_source_count"] == 1
    assert second["successful_source_count"] == 0
    assert second["skipped_count"] == 1
    assert second["skipped"][0]["reason"] == "not_due"
    assert runner.run_source.call_count == 1


def test_scheduler_runs_source_again_when_poll_interval_expires():
    runner = MagicMock()
    runner.run_source.return_value = {"processed_count": 1, "failed_count": 0, "total": 1}
    definition = SourceDefinition(
        name="Short Poll API", provider="Example", collector_type="json", url="https://example.com/api",
        pagination_type="none", poll_interval_seconds=60,
    )
    source = create_adapter(definition=definition)
    scheduler = LeadScheduler(runner=runner)
    scheduler.run([source])
    with patch("lead_engine.scheduler.time.monotonic", side_effect=[1061.0, 1061.0]):
        scheduler._next_run_at[scheduler._source_key(source)] = 1060.0
        result = scheduler.run([source])
    assert result["successful_source_count"] == 1
    assert result["skipped_count"] == 0
    assert runner.run_source.call_count == 2


def test_scheduler_static_source_runs_without_poll_interval():
    runner = MagicMock()
    runner.run_source.return_value = {"processed_count": 1, "failed_count": 0, "total": 1}
    source = StaticLeadSource([])
    scheduler = LeadScheduler(runner=runner)
    scheduler.run([source])
    scheduler.run([source])
    assert runner.run_source.call_count == 2


def test_scheduler_persists_source_poll_interval(tmp_path):
    runner = MagicMock()
    db = LeadDB(data_dir=str(tmp_path))
    pipeline = LeadPipeline(db=db)
    runner.pipeline = pipeline
    runner.run_source.return_value = {"processed_count": 1, "failed_count": 0, "total": 1}
    definition = SourceDefinition(
        name="Persistent Poll API", provider="Example", collector_type="json", url="https://example.com/api",
        pagination_type="none", poll_interval_seconds=3600,
    )
    source = create_adapter(definition=definition)
    scheduler = LeadScheduler(runner=runner)
    with patch("lead_engine.scheduler.time.time", return_value=1000.0):
        first = scheduler.run([source])
    assert first["successful_source_count"] == 1
    runner.run_source.reset_mock()
    second_scheduler = LeadScheduler(runner=runner)
    with patch("lead_engine.scheduler.time.time", return_value=1001.0):
        second = second_scheduler.run([source])
    assert second["successful_source_count"] == 0
    assert second["skipped_count"] == 1
    assert second["skipped"][0]["reason"] == "not_due"
    assert runner.run_source.call_count == 0
    db.close()


def test_scheduler_persisted_poll_interval_expires():
    runner = MagicMock()
    runner.run_source.return_value = {"processed_count": 1, "failed_count": 0, "total": 1}
    definition = SourceDefinition(
        name="Expiring Persistent Poll API", provider="Example", collector_type="json", url="https://example.com/api",
        pagination_type="none", poll_interval_seconds=60,
    )
    source = create_adapter(definition=definition)
    scheduler = LeadScheduler(runner=runner)
    with patch("lead_engine.scheduler.time.time", return_value=1000.0):
        first = scheduler.run([source])
    assert first["successful_source_count"] == 1
    runner.run_source.reset_mock()
    second_scheduler = LeadScheduler(runner=runner)
    with patch("lead_engine.scheduler.time.time", return_value=1061.0):
        second = second_scheduler.run([source])
    assert second["successful_source_count"] == 1
    assert second["skipped_count"] == 0
    assert runner.run_source.call_count == 1


def test_scheduler_persisted_poll_interval_uses_wall_clock_after_restart(tmp_path):
    runner = MagicMock()
    db = LeadDB(data_dir=str(tmp_path))
    pipeline = LeadPipeline(db=db)
    runner.pipeline = pipeline
    runner.run_source.return_value = {"processed_count": 1, "failed_count": 0, "total": 1}
    definition = SourceDefinition(
        name="Restart Poll API", provider="Example", collector_type="json", url="https://example.com/api",
        pagination_type="none", poll_interval_seconds=60,
    )
    source = create_adapter(definition=definition)
    first_scheduler = LeadScheduler(runner=runner)
    with patch("lead_engine.scheduler.time.time", return_value=1000.0), patch("lead_engine.scheduler.time.monotonic", return_value=5000.0):
        first = first_scheduler.run([source])
    assert first["successful_source_count"] == 1
    runner.run_source.reset_mock()
    second_scheduler = LeadScheduler(runner=runner)
    with patch("lead_engine.scheduler.time.time", return_value=1059.0), patch("lead_engine.scheduler.time.monotonic", return_value=1.0):
        before_expiry = second_scheduler.run([source])
    assert before_expiry["successful_source_count"] == 0
    assert runner.run_source.call_count == 0
    with patch("lead_engine.scheduler.time.time", return_value=1061.0), patch("lead_engine.scheduler.time.monotonic", return_value=1.0):
        after_expiry = second_scheduler.run([source])
    assert after_expiry["successful_source_count"] == 1
    assert runner.run_source.call_count == 1
    db.close()


def test_scheduler_bounded_run_collects_even_when_persisted_deadlines_are_future(tmp_path, monkeypatch):
    runner = MagicMock()
    db = LeadDB(data_dir=str(tmp_path))
    pipeline = LeadPipeline(db=db)
    runner.pipeline = pipeline
    runner.process.return_value = {"discovered_count": 1, "accepted_count": 1, "duplicate_count": 0, "failed_count": 0}
    monkeypatch.setenv("THORIO_SOURCE_COLLECTION_WORKERS", "2")
    definition = SourceDefinition(
        name="Bounded Acceptance API", provider="Example", collector_type="json", url="https://example.com/api",
        pagination_type="none", poll_interval_seconds=3600,
    )
    source = create_adapter(definition=definition)
    scheduler = LeadScheduler(runner=runner)
    with patch("lead_engine.scheduler.time.time", return_value=1000.0):
        first = scheduler.run([source])
    assert first["successful_source_count"] == 1
    runner.process.reset_mock()
    second_scheduler = LeadScheduler(runner=runner)
    with patch("lead_engine.scheduler.time.time", return_value=1001.0):
        result = second_scheduler.run_bounded([source], interval_seconds=0, max_cycles=1)
    assert result["successful_source_count"] == 1
    assert result["failed_count"] == 0
    assert result["discovered_count"] == 1
    assert runner.process.call_count == 1
    db.close()
