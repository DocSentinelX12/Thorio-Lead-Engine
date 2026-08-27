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
