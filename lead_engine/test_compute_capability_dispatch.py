import threading

from lead_engine.compute_coordinator import ComputeCoordinator
from lead_engine.compute_pool import WorkerIdentity


def _worker(worker_id, capabilities, cpu_count=4, memory_mb=8192):
    return WorkerIdentity(worker_id, "host", "x86_64", cpu_count, memory_mb, tuple(capabilities))


def test_claim_skips_incompatible_oldest_task_and_matches_specialist(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "secret", lease_seconds=30)
    coordinator.register_worker(_worker("ai-worker", ["ai_demand_discovery", "lead_prepare"]))
    coordinator.enqueue({"kind": "agent_task", "agent": "social_decision_maker_research"}, task_id="social-task")
    coordinator.enqueue({"kind": "agent_task", "agent": "ai_demand_discovery"}, task_id="ai-task")

    claimed = coordinator.claim("ai-worker")

    assert claimed is not None
    assert claimed["task_id"] == "ai-task"
    assert coordinator.task("social-task")["status"] == "queued"


def test_generic_task_remains_claimable_by_processing_worker(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "secret", lease_seconds=30)
    coordinator.register_worker(_worker("generic-worker", ["lead-processing"]))
    task_id = coordinator.enqueue({"fingerprint": "generic"}, task_id="generic-task")

    claimed = coordinator.claim("generic-worker")

    assert claimed is not None
    assert claimed["task_id"] == task_id


def test_explicit_required_capabilities_are_all_required(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "secret", lease_seconds=30)
    coordinator.register_worker(_worker("partial-worker", ["research", "lead_prepare"]))
    coordinator.enqueue({"required_capabilities": ["research", "verification"], "payload": {}}, task_id="strict-task")

    assert coordinator.claim("partial-worker") is None
    assert coordinator.task("strict-task")["status"] == "queued"


def test_specialist_task_can_use_role_alias_from_existing_payloads(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "secret", lease_seconds=30)
    coordinator.register_worker(_worker("social-worker", ["social_intelligence"]))
    coordinator.enqueue({"kind": "agent_task", "role": "social_intelligence", "lead_id": "lead-1"}, task_id="social-task")

    claimed = coordinator.claim("social-worker")

    assert claimed is not None
    assert claimed["task_id"] == "social-task"


def test_claim_is_capacity_aware_and_exposes_available_slots(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "secret", lease_seconds=30)
    coordinator.register_worker(_worker("small", ["lead-processing"], cpu_count=2, memory_mb=4096))
    coordinator.enqueue({"fingerprint": "one"}, task_id="one")
    coordinator.enqueue({"fingerprint": "two"}, task_id="two")

    first = coordinator.claim("small")
    second = coordinator.claim("small")

    assert first is not None
    assert second is None
    snapshot = coordinator.health()["capacity"]
    worker = snapshot["workers"][0]
    assert worker["worker_id"] == "small"
    assert worker["recommended_slots"] == 1
    assert worker["active_load"] == 1
    assert worker["available_slots"] == 0


def test_capacity_is_released_on_completion_and_expiry(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "secret", lease_seconds=30)
    coordinator.register_worker(_worker("worker", ["lead-processing"], cpu_count=2, memory_mb=4096))
    coordinator.enqueue({"fingerprint": "one"}, task_id="one")
    claimed = coordinator.claim("worker")
    assert coordinator.health()["capacity"]["workers"][0]["active_load"] == 1

    assert coordinator.complete("worker", "one", claimed["lease_token"], {"ok": True})
    assert coordinator.health()["capacity"]["workers"][0]["active_load"] == 0

    coordinator.enqueue({"fingerprint": "two"}, task_id="two")
    claimed = coordinator.claim("worker")
    assert claimed is not None
    with coordinator._connect() as connection:
        connection.execute("UPDATE compute_tasks SET lease_until=0 WHERE task_id='two'")
        connection.commit()
    assert coordinator.recover_expired_tasks() == 1
    assert coordinator.health()["capacity"]["workers"][0]["active_load"] == 0


def test_capacity_snapshot_accounts_for_eighty_logical_slots(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "secret", lease_seconds=30)
    for index in range(80):
        coordinator.register_worker(_worker(f"worker-{index:02d}", ["lead-processing"], cpu_count=4, memory_mb=8192))

    capacity = coordinator.health()["capacity"]

    assert capacity["logical_slots"] == 80
    assert capacity["ready_workers"] == 80
    assert capacity["available_slots"] == 80
    assert capacity["worker_count"] == 80


def test_workers_balance_pull_workload_without_exceeding_one_slot(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "secret", lease_seconds=30)
    coordinator.register_worker(_worker("provider-a-worker", ["research"]))
    coordinator.register_worker(_worker("provider-b-worker", ["research"]))
    for index in range(10):
        coordinator.enqueue({"required_capabilities": ["research"], "index": index}, task_id=f"balanced-{index}")

    counts = {"provider-a-worker": 0, "provider-b-worker": 0}
    for index in range(10):
        worker_id = "provider-a-worker" if index % 2 == 0 else "provider-b-worker"
        claimed = coordinator.claim(worker_id)
        assert claimed is not None
        counts[worker_id] += 1
        assert coordinator.complete(worker_id, claimed["task_id"], claimed["lease_token"], {"ok": True})

    assert counts == {"provider-a-worker": 5, "provider-b-worker": 5}
    assert coordinator.health()["queued"] == 0
    assert coordinator.health()["capacity"]["available_slots"] == 2


def test_stale_provider_worker_releases_capacity_after_lease_reclamation(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "secret", lease_seconds=30)
    coordinator.register_worker(_worker("failed-provider-worker", ["research"]))
    coordinator.register_worker(_worker("replacement-provider-worker", ["research"]))
    coordinator.enqueue({"required_capabilities": ["research"]}, task_id="recoverable")

    claimed = coordinator.claim("failed-provider-worker")
    assert claimed is not None
    with coordinator._connect() as connection:
        connection.execute("UPDATE compute_tasks SET lease_until=0 WHERE task_id='recoverable'")
        connection.execute("UPDATE compute_workers SET last_heartbeat=0 WHERE worker_id='failed-provider-worker'")
        connection.commit()

    coordinator.pool.reap_stale_workers(stale_after_seconds=1)
    assert coordinator.recover_expired_tasks() == 1
    assert coordinator.task("recoverable")["status"] == "queued"
    assert coordinator.health()["capacity"]["stale_workers"] == 1
    assert coordinator.health()["capacity"]["available_slots"] == 1

    replacement = coordinator.claim("replacement-provider-worker")
    assert replacement is not None
    assert replacement["task_id"] == "recoverable"


def test_concurrent_workers_never_double_claim_the_same_task(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "secret", lease_seconds=30)
    worker_ids = [f"worker-{index:02d}" for index in range(40)]
    for worker_id in worker_ids:
        coordinator.register_worker(_worker(worker_id, ["research"], cpu_count=2, memory_mb=4096))
    coordinator.enqueue({"required_capabilities": ["research"]}, task_id="single-task")

    claims = []
    lock = threading.Lock()

    def attempt(worker_id):
        result = coordinator.claim(worker_id)
        if result is not None:
            with lock:
                claims.append((worker_id, result["task_id"], result["lease_token"]))

    threads = [threading.Thread(target=attempt, args=(worker_id,)) for worker_id in worker_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert len(claims) == 1
    assert claims[0][1] == "single-task"
    assert coordinator.task("single-task")["attempts"] == 1
