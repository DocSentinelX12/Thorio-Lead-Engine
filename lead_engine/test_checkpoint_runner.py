from unittest.mock import MagicMock

from .checkpoint_runner import CheckpointRunner
from .database import LeadDB
from .sources import StaticLeadSource


def test_checkpoint_runner_persists_checkpoint(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    runner = MagicMock()

    runner.run_source.return_value = {
        "processed_count": 2,
        "failed_count": 0,
        "total": 2,
    }

    source = StaticLeadSource([])

    checkpoint_runner = CheckpointRunner(
        db=db,
        runner=runner,
    )

    result = checkpoint_runner.run(
        source=source,
        checkpoint="checkpoint-001",
    )

    assert result["previous_checkpoint"] == ""
    assert result["checkpoint"] == "checkpoint-001"

    assert db.get_checkpoint(
        source.name
    ) == "checkpoint-001"


def test_checkpoint_runner_does_not_advance_after_failure(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    db.set_checkpoint(
        "static",
        "checkpoint-old",
    )

    runner = MagicMock()

    runner.run_source.return_value = {
        "processed_count": 1,
        "failed_count": 1,
        "total": 2,
    }

    source = StaticLeadSource([])

    checkpoint_runner = CheckpointRunner(
        db=db,
        runner=runner,
    )

    result = checkpoint_runner.run(
        source=source,
        checkpoint="checkpoint-new",
    )

    assert result["previous_checkpoint"] == "checkpoint-old"
    assert result["checkpoint"] == "checkpoint-old"

    assert db.get_checkpoint(
        source.name
    ) == "checkpoint-old"


from unittest.mock import Mock


def test_checkpoint_is_passed_into_source_and_saved_after_success():
    source = Mock()
    source.name = "cursor-source"
    source.last_checkpoint = "next-cursor"

    source.collect.return_value = [
        {
            "source": "cursor-source",
            "source_id": "1",
            "url": "https://example.com/job/1",
            "company": "Example Corp",
            "signal": "Software Engineer",
            "evidence": "real job evidence",
            "signal_type": "hiring",
            "source_url": "https://example.com/jobs",
            "job_title": "Software Engineer",
        }
    ]

    db = Mock()
    db.get_checkpoint.return_value = "previous-cursor"

    runner = Mock()

    runner.run_source.return_value = {
        "discovered_count": 1,
        "accepted_count": 1,
        "duplicate_count": 0,
        "failed_count": 0,
        "checkpoint": "next-cursor",
    }

    from .checkpoint_runner import CheckpointRunner

    checkpoint_runner = CheckpointRunner(
        db=db,
        runner=runner,
    )

    result = checkpoint_runner.run(
        source=source,
        checkpoint="ignored-by-design",
    )

    runner.run_source.assert_called_once_with(
        source,
        checkpoint="previous-cursor",
    )

    db.set_checkpoint.assert_called_once_with(
        "cursor-source",
        "next-cursor",
    )

    assert (
        result["checkpoint"]
        == "next-cursor"
    )


def test_checkpoint_does_not_advance_after_processing_failure():
    source = Mock()
    source.name = "failing-source"

    db = Mock()
    db.get_checkpoint.return_value = "previous-cursor"

    runner = Mock()

    runner.run_source.return_value = {
        "discovered_count": 1,
        "accepted_count": 0,
        "duplicate_count": 0,
        "failed_count": 1,
        "checkpoint": "bad-next-cursor",
    }

    from .checkpoint_runner import CheckpointRunner

    checkpoint_runner = CheckpointRunner(
        db=db,
        runner=runner,
    )

    result = checkpoint_runner.run(
        source=source,
        checkpoint="ignored",
    )

    db.set_checkpoint.assert_not_called()

    assert (
        result["checkpoint"]
        == "previous-cursor"
    )
