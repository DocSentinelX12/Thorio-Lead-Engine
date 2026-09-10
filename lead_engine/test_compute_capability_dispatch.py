from lead_engine.compute_coordinator import ComputeCoordinator
from lead_engine.compute_pool import WorkerIdentity


def _worker(worker_id, capabilities):
    return WorkerIdentity(worker_id, "host", "x86_64", 4, 8192, tuple(capabilities))


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
