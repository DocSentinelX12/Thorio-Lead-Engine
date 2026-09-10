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
    assert capacity["available_slots"] == 80 * 3
    assert capacity["worker_count"] == 80
