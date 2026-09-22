from concurrent.futures import ThreadPoolExecutor

from .database import LeadDB
from .worker_database import WorkerLeadDB


def test_worker_database_reuses_initialized_schema_without_recovery_probe(tmp_path, monkeypatch):
    db = LeadDB(data_dir=tmp_path)
    lead = {
        "fingerprint": "worker-db-test",
        "company": "Acme",
        "signal": "Acme is hiring",
    }
    db.insert_if_new(lead)

    def fail_if_recovery_is_called(*_args, **_kwargs):
        raise AssertionError("worker connections must not repeat database recovery/integrity startup")

    monkeypatch.setattr(LeadDB, "_connect_with_recovery", fail_if_recovery_is_called)
    worker_db = WorkerLeadDB(data_dir=tmp_path)
    try:
        assert worker_db.get("worker-db-test") == lead
        assert worker_db.conn.execute("SELECT COUNT(*) FROM agent_queue").fetchone()[0] == 0
    finally:
        worker_db.close()
        monkeypatch.undo()
        db.close()


def test_worker_database_supports_independent_concurrent_connections(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    db.insert_if_new({"fingerprint": "concurrent-worker-db-test", "company": "Acme"})
    db.close()

    def read_from_worker(_: int) -> dict:
        worker_db = WorkerLeadDB(data_dir=tmp_path)
        try:
            row = worker_db.conn.execute(
                "SELECT fingerprint FROM leads WHERE fingerprint = ?",
                ("concurrent-worker-db-test",),
            ).fetchone()
            return {"fingerprint": row[0] if row else None}
        finally:
            worker_db.close()

    with ThreadPoolExecutor(max_workers=32) as executor:
        results = list(executor.map(read_from_worker, range(32)))

    assert all(result["fingerprint"] == "concurrent-worker-db-test" for result in results)
