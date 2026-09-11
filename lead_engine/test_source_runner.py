from unittest.mock import Mock

from .source_runner import SourceRunner, _queue_priority


def test_queue_priority_normalizes_numeric_and_named_values():
    assert _queue_priority(3) == 3
    assert _queue_priority("2") == 2
    assert _queue_priority("High") == 2
    assert _queue_priority("critical") == 3
    assert _queue_priority("Medium") == 1
    assert _queue_priority("unknown") == 0
    assert _queue_priority(None) == 0


def _record(source, source_id):
    return {
        "source": source,
        "source_id": source_id,
        "url": f"https://example.com/{source_id}",
        "company": "Example Company",
        "signal": "remote software engineer",
        "evidence": "Observed remote software engineer hiring signal.",
    }


def test_source_runner_processes_all_records_independently():
    pipeline = Mock()
    pipeline.process.side_effect = [
        {"accepted": True, "status": "accepted"},
        {"accepted": False, "status": "duplicate"},
        Exception("record failed"),
        {"accepted": True, "status": "accepted"},
    ]
    runner = SourceRunner(pipeline)
    result = runner.process([_record("test", str(i)) for i in range(1, 5)])
    assert result == {"discovered_count": 4, "accepted_count": 2, "duplicate_count": 1, "failed_count": 1}
    assert pipeline.process.call_count == 4


def test_source_runner_runs_source_collection():
    pipeline = Mock()
    pipeline.process.return_value = {"accepted": True, "status": "accepted"}
    source = Mock()
    source.collect.return_value = [_record("web", "001"), _record("web", "002")]
    runner = SourceRunner(pipeline)
    result = runner.run_source(source)
    assert result == {"discovered_count": 2, "accepted_count": 2, "duplicate_count": 0, "failed_count": 0}
    source.collect.assert_called_once()
    assert pipeline.process.call_count == 2


def test_source_runner_continues_after_pipeline_failure():
    pipeline = Mock()
    pipeline.process.side_effect = [Exception("temporary failure"), {"accepted": True, "status": "accepted"}]
    runner = SourceRunner(pipeline)
    result = runner.process([_record("test", "failed"), _record("test", "successful")])
    assert result["failed_count"] == 1
    assert result["accepted_count"] == 1
    assert result["duplicate_count"] == 0


def test_source_runner_run_source_collects_and_processes_records():
    pipeline = Mock()
    pipeline.process.side_effect = [
        {"accepted": True, "status": "accepted"},
        {"accepted": False, "status": "duplicate"},
    ]
    source = Mock()
    source.collect.return_value = [_record("web", "runner-001"), _record("web", "runner-002")]
    runner = SourceRunner(pipeline)
    result = runner.run_source(source)
    assert result == {"discovered_count": 2, "accepted_count": 1, "duplicate_count": 1, "failed_count": 0}
    source.collect.assert_called_once()
    assert pipeline.process.call_count == 2


def test_source_runner_batches_database_writes_for_one_source():
    pipeline = Mock()
    pipeline.process.return_value = {"accepted": True, "status": "accepted"}
    batch = pipeline.db.batch_writes.return_value
    runner = SourceRunner(pipeline)

    result = runner.process([_record("web", "batch-001"), _record("web", "batch-002")])

    assert result["accepted_count"] == 2
    pipeline.db.batch_writes.assert_called_once_with()
    assert batch.__enter__.call_count == 1
    assert batch.__exit__.call_count == 1


def test_source_runner_does_not_hide_internal_type_error():
    pipeline = Mock()
    source = Mock()
    source.collect.side_effect = TypeError("checkpoint data has invalid type")
    runner = SourceRunner(pipeline)
    try:
        runner.run_source(source, checkpoint="123")
    except TypeError as exc:
        assert str(exc) == "checkpoint data has invalid type"
    else:
        raise AssertionError("Internal TypeError was incorrectly swallowed.")
    assert source.collect.call_count == 1
