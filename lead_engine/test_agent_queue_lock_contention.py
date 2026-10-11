from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from .agent_queue import claim, enqueue_many
from .database import LeadDB


def test_concurrent_claimers_do_not_fail_on_sqlite_lock(tmp_path):
    seed = LeadDB(data_dir=tmp_path)
    enqueue_many(
        seed,
        [
            {"agent": "x_signal", "payload": {"source_id": str(index)}}
            for index in range(64)
        ],
    )
    seed.close()

    start = Barrier(16)

    def claim_once(index):
        db = LeadDB(data_dir=tmp_path)
        try:
            start.wait(timeout=10)
            return claim(db, "x_signal", worker_id=f"lock-stress-{index}", limit=1)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(claim_once, range(16)))

    claimed = [task[0]["task_id"] for task in results if task]
    assert len(claimed) == 8
    assert len(set(claimed)) == len(claimed)

def test_concurrent_completion_and_payload_writes_are_serialized(tmp_path):
    from .agent_queue import claim_task, complete, enqueue_many
    from .worker_database import WorkerLeadDB

    worker_count = 8
    seed = LeadDB(data_dir=tmp_path)
    fingerprint = "concurrent-completion-payload"
    assert seed.insert_if_new({
        "fingerprint": fingerprint,
        "company": "Concurrent Writes Co",
        "signal": "Verified test signal",
    })
    tasks = enqueue_many(
        seed,
        [
            {"agent": "x_signal", "payload": {"source_id": str(index)}}
            for index in range(worker_count)
        ],
    )
    seed.close()
    start = Barrier(worker_count)
    claimed = Barrier(worker_count)

    def finish_once(index):
        db = WorkerLeadDB(data_dir=tmp_path)
        worker_id = f"completion-lock-{index}"
        try:
            start.wait(timeout=10)
            task = claim_task(db, tasks[index]["task_id"], worker_id=worker_id)
            claimed.wait(timeout=10)
            completed = complete(
                db,
                task["task_id"],
                worker_id=worker_id,
                lease_token=task["lease_token"],
                result={"completed_by": worker_id},
            )
            updated = db.update_payload(
                fingerprint,
                {f"writer_{index}": True},
            )
            assert completed["status"] == "complete"
            assert updated is not None
            return task["task_id"]
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        completed_ids = list(executor.map(finish_once, range(worker_count)))

    check = LeadDB(data_dir=tmp_path)
    try:
        assert len(set(completed_ids)) == worker_count
        assert all(check.queue_get(task["task_id"])[3] == "complete" for task in tasks)
        stored = check.get(fingerprint)
        assert all(stored.get(f"writer_{index}") is True for index in range(worker_count))
    finally:
        check.close()


def test_enqueue_retries_transient_sqlite_writer_contention(tmp_path):
    import sqlite3
    from .agent_queue import enqueue

    db = LeadDB(data_dir=tmp_path)

    class BusyOnceConnection:
        def __init__(self, connection):
            self._connection = connection
            self._busy_once = True

        def execute(self, sql, *args):
            if sql == "BEGIN IMMEDIATE" and self._busy_once:
                self._busy_once = False
                raise sqlite3.OperationalError("database is locked")
            return self._connection.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._connection, name)

    db.conn = BusyOnceConnection(db.conn)
    task = enqueue(db, "x_signal", {"source_id": "enqueue-busy-once"})
    assert task["status"] == "queued"
    assert db.queue_get(task["task_id"]) is not None
    db.close()

