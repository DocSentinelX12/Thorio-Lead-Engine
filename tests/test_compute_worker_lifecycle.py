from lead_engine.compute_pool import ComputePool, WorkerIdentity


def identity():
    return WorkerIdentity(
        worker_id="worker-1",
        hostname="host",
        architecture="x86_64",
        cpu_count=4,
        memory_mb=8192,
        capabilities=("lead-processing",),
    )


def test_worker_lifecycle_blocks_work_until_explicit_readmission(tmp_path):
    pool = ComputePool(str(tmp_path / "pool.sqlite3"), lease_seconds=30)
    pool.register(identity())

    assert pool.drain_worker("worker-1", "maintenance") is True
    assert pool.worker("worker-1")["status"] == "draining"
    assert pool.heartbeat("worker-1", 0) is True
    assert pool.worker("worker-1")["status"] == "draining"
    assert pool.reserve_task_slot("worker-1") is False

    assert pool.readmit_worker("worker-1", "maintenance complete") is True
    assert pool.worker("worker-1")["status"] == "ready"
    assert pool.reserve_task_slot("worker-1") is True
    pool.release_task_slot("worker-1")


def test_quarantine_and_revocation_survive_worker_reregistration(tmp_path):
    pool = ComputePool(str(tmp_path / "pool.sqlite3"), lease_seconds=30)
    pool.register(identity())

    assert pool.quarantine_worker("worker-1", "GPU evidence mismatch") is True
    pool.register(identity())
    assert pool.worker("worker-1")["status"] == "quarantined"
    assert pool.reserve_task_slot("worker-1") is False

    assert pool.revoke_worker("worker-1", "credential revoked") is True
    pool.register(identity())
    assert pool.worker("worker-1")["status"] == "revoked"
    assert pool.reserve_task_slot("worker-1") is False

    assert pool.readmit_worker("worker-1", "new credential verified") is True
    assert pool.worker("worker-1")["status"] == "ready"
