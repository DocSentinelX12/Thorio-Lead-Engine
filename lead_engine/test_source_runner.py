from unittest.mock import Mock

from .source_runner import SourceRunner


def test_source_runner_processes_all_records_independently():
    pipeline = Mock()

    pipeline.process.side_effect = [
        {"accepted": True, "status": "accepted"},
        {"accepted": False, "status": "duplicate"},
        Exception("record failed"),
        {"accepted": True, "status": "accepted"},
    ]

    runner = SourceRunner(pipeline)

    result = runner.process(
        [
            {"source": "test", "source_id": "1"},
            {"source": "test", "source_id": "2"},
            {"source": "test", "source_id": "3"},
            {"source": "test", "source_id": "4"},
        ]
    )

    assert result == {
        "discovered_count": 4,
        "accepted_count": 2,
        "duplicate_count": 1,
        "failed_count": 1,
    }

    assert pipeline.process.call_count == 4


def test_source_runner_runs_source_collection():
    pipeline = Mock()
    pipeline.process.return_value = {
        "accepted": True,
        "status": "accepted",
    }

    source = Mock()
    source.collect.return_value = [
        {
            "source": "web",
            "source_id": "001",
        },
        {
            "source": "web",
            "source_id": "002",
        },
    ]

    runner = SourceRunner(pipeline)

    result = runner.run_source(source)

    assert result == {
        "discovered_count": 2,
        "accepted_count": 2,
        "duplicate_count": 0,
        "failed_count": 0,
    }

    source.collect.assert_called_once()
    assert pipeline.process.call_count == 2


def test_source_runner_continues_after_pipeline_failure():
    pipeline = Mock()

    pipeline.process.side_effect = [
        Exception("temporary failure"),
        {"accepted": True, "status": "accepted"},
    ]

    runner = SourceRunner(pipeline)

    result = runner.process(
        [
            {"source": "test", "source_id": "failed"},
            {"source": "test", "source_id": "successful"},
        ]
    )

    assert result["failed_count"] == 1
    assert result["accepted_count"] == 1
    assert result["duplicate_count"] == 0


def test_source_runner_run_source_collects_and_processes_records():
    pipeline = Mock()

    pipeline.process.side_effect = [
        {
            "accepted": True,
            "status": "accepted",
        },
        {
            "accepted": False,
            "status": "duplicate",
        },
    ]

    source = Mock()

    source.collect.return_value = [
        {
            "source": "web",
            "source_id": "runner-001",
        },
        {
            "source": "web",
            "source_id": "runner-002",
        },
    ]

    runner = SourceRunner(pipeline)

    result = runner.run_source(
        source
    )

    assert result == {
        "discovered_count": 2,
        "accepted_count": 1,
        "duplicate_count": 1,
        "failed_count": 0,
    }

    source.collect.assert_called_once()

    assert pipeline.process.call_count == 2


def test_source_runner_does_not_hide_internal_type_error():
    pipeline = Mock()

    source = Mock()

    source.collect.side_effect = TypeError(
        "checkpoint data has invalid type"
    )

    runner = SourceRunner(pipeline)

    try:
        runner.run_source(
            source,
            checkpoint="123",
        )
    except TypeError as exc:
        assert str(exc) == (
            "checkpoint data has invalid type"
        )
    else:
        raise AssertionError(
            "Internal TypeError was incorrectly swallowed."
        )

    assert source.collect.call_count == 1
