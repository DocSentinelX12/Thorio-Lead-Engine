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
