import pytest

from lead_engine.status import (
    _failed_sync_details,
    _pending_details,
    _safe_state,
    get_engine_status,
)


class BrokenStateDB:
    def get_state(self, key):
        raise RuntimeError("state read failed")

    class Connection:
        def execute(self, query):
            raise RuntimeError("query read failed")

    conn = Connection()

    def stats(self):
        return 0, 0, 0


def test_safe_state_does_not_convert_database_failure_to_empty_state():
    with pytest.raises(
        RuntimeError,
        match="Unable to read database state for key 'source_observability'",
    ):
        _safe_state(BrokenStateDB(), "source_observability")


def test_pending_details_does_not_convert_database_failure_to_zero_counts():
    with pytest.raises(
        RuntimeError,
        match="Unable to read pending lead details from the database",
    ):
        _pending_details(BrokenStateDB())


def test_failed_sync_details_does_not_convert_database_failure_to_zero_counts():
    with pytest.raises(
        RuntimeError,
        match="Unable to read failed synchronization details from the database",
    ):
        _failed_sync_details(BrokenStateDB())


def test_engine_status_surfaces_database_read_failure():
    with pytest.raises(
        RuntimeError,
        match="Unable to read pending lead details from the database",
    ):
        get_engine_status(BrokenStateDB())

    
def test_engine_status_does_not_remain_unhealthy_after_historical_sync_failure(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    db.set_state(
        "sync_observability",
        {
            "sync_runs": 3,
            "successful_sync_runs": 2,
            "failed_sync_runs": 1,
            "last_sync_failure": "2026-09-27T00:00:00+00:00",
            "last_successful_sync": "2026-09-27T00:05:00+00:00",
        },
    )

    status = get_engine_status(db)

    assert status["healthy"] is True
    assert status["failed_sync_runs"] == 1
    assert status["successful_sync_runs"] == 2
