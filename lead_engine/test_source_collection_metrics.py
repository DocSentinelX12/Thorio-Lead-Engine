from lead_engine.source_collection_metrics import record_source_collection_metrics, source_collection_metrics


class FakeDB:
    def __init__(self):
        self.state = {}

    def get_state(self, key):
        return self.state.get(key)

    def set_state(self, key, value):
        self.state[key] = value


def test_source_collection_metrics_persist_yield_and_failure_counts():
    db = FakeDB()
    first = record_source_collection_metrics(db, "Example Source", {"discovered_count": 10, "accepted_count": 6, "duplicate_count": 3, "failed_count": 1})
    assert first["runs"] == 1
    assert first["discovered"] == 10
    assert first["accepted"] == 6
    assert first["duplicates"] == 3
    assert first["failed"] == 1
    assert first["acceptance_rate"] == 0.6
    assert first["failure_rate"] == 0.1


def test_source_collection_metrics_accumulate_across_runs():
    db = FakeDB()
    record_source_collection_metrics(db, "Example Source", {"discovered_count": 10, "accepted_count": 5, "duplicate_count": 2, "failed_count": 3})
    result = record_source_collection_metrics(db, "Example Source", {"discovered_count": 20, "accepted_count": 14, "duplicate_count": 4, "failed_count": 2})
    assert result["runs"] == 2
    assert result["discovered"] == 30
    assert result["accepted"] == 19
    assert result["duplicates"] == 6
    assert result["failed"] == 5
    assert result["acceptance_rate"] == 19 / 30
    assert result["failure_rate"] == 5 / 30


def test_source_collection_metrics_keep_sources_separate():
    db = FakeDB()
    record_source_collection_metrics(db, "Source A", {"discovered_count": 10, "accepted_count": 4, "duplicate_count": 0, "failed_count": 0})
    record_source_collection_metrics(db, "Source B", {"discovered_count": 5, "accepted_count": 1, "duplicate_count": 1, "failed_count": 3})
    metrics = source_collection_metrics(db)
    assert set(metrics) == {"Source A", "Source B"}
    assert metrics["Source A"]["accepted"] == 4
    assert metrics["Source B"]["failed"] == 3


def test_source_collection_metrics_rejects_invalid_result():
    db = FakeDB()
    try:
        record_source_collection_metrics(db, "Example Source", {"accepted_count": 1})
    except ValueError as exc:
        assert "discovered_count" in str(exc)
    else:
        raise AssertionError("invalid collection result was accepted")
