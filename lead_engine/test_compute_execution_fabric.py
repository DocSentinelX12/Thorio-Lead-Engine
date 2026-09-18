import tempfile
from pathlib import Path

from lead_engine.compute_bridge import REMOTE_SAFE_AGENTS
from lead_engine.compute_coordinator import ComputeCoordinator
from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_pool import WorkerIdentity
from lead_engine.compute_resources import ResourceState


def _worker():
    return WorkerIdentity(
        "worker-1",
        "host",
        "x86_64",
        4,
        8192,
        ("lead-processing", "engineering_demand_discovery"),
    )


def test_claim_creates_and_binds_physical_allocation_to_worker_node():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        inventory = ComputeInventory(str(root / "inventory.sqlite3"))
        coordinator = ComputeCoordinator(
            str(root / "coordinator.sqlite3"),
            auth_token="token",
            lease_seconds=30,
            inventory=inventory,
        )
        coordinator.register_worker(_worker())
        task_id = coordinator.enqueue({
            "kind": "agent_task",
            "agent": "engineering_demand_discovery",
            "payload": {
                "lead": {"fingerprint": "lead-1"},
                "evidence_events": [{"signal": "Hiring a backend engineer"}],
                "compute_requirements": {
                    "workload_class": "cpu_bound",
                    "min_cpu_count": 1,
                    "min_memory_bytes": 1,
                },
            },
        })

        claimed = coordinator.claim("worker-1")

        assert claimed is not None
        allocation = claimed["physical_allocation"]
        assert allocation["node_ids"] == ["worker-1"]
        assert allocation["provider_id"] == "worker_pool"
        assert allocation["domain_id"] == "worker-1"
        stored = inventory.allocation(allocation["allocation_id"])
        assert stored["state"] == "bound"
        assert stored["task_id"] == task_id
        assert stored["attempt_id"] == claimed["attempt_id"]
        assert stored["generation"] == claimed["generation"]
        attempt = coordinator.execution_attempt(claimed["attempt_id"])
        assert attempt["allocation_id"] == allocation["allocation_id"]
        assert attempt["resource_ids"] == allocation["resource_ids"]


def test_completion_releases_physical_allocation():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        inventory = ComputeInventory(str(root / "inventory.sqlite3"))
        coordinator = ComputeCoordinator(
            str(root / "coordinator.sqlite3"),
            auth_token="token",
            lease_seconds=30,
            inventory=inventory,
        )
        coordinator.register_worker(_worker())
        task_id = coordinator.enqueue({
            "kind": "agent_task",
            "agent": "engineering_demand_discovery",
            "payload": {
                "compute_requirements": {
                    "workload_class": "cpu_bound",
                    "min_cpu_count": 1,
                    "min_memory_bytes": 1,
                }
            },
        })
        claimed = coordinator.claim("worker-1")
        allocation_id = claimed["physical_allocation"]["allocation_id"]
        resource_key = claimed["physical_allocation"]["resource_keys"][0]

        assert coordinator.complete("worker-1", task_id, claimed["lease_token"], {"ok": True})

        assert inventory.allocation(allocation_id)["state"] == "released"
        assert inventory.get(resource_key)["state"] == ResourceState.AVAILABLE.value


def test_claim_without_physical_capacity_never_leases_work():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        inventory = ComputeInventory(str(root / "inventory.sqlite3"))
        coordinator = ComputeCoordinator(
            str(root / "coordinator.sqlite3"),
            auth_token="token",
            lease_seconds=30,
            inventory=inventory,
        )
        coordinator.register_worker(_worker())
        task_id = coordinator.enqueue({
            "kind": "agent_task",
            "agent": "engineering_demand_discovery",
            "payload": {
                "compute_requirements": {
                    "workload_class": "gpu_required",
                    "gpu": {"gpu_count": 1},
                }
            },
        })

        assert coordinator.claim("worker-1") is None
        task = coordinator.task(task_id)
        assert task["status"] == "queued"
        assert task["worker_id"] is None
        assert coordinator.pool.worker("worker-1")["current_load"] == 0


def test_remote_safe_set_matches_only_stateless_worker_implementations():
    assert "engineering_demand_discovery" in REMOTE_SAFE_AGENTS
    assert "social_hiring_research" in REMOTE_SAFE_AGENTS
    assert "company_research" not in REMOTE_SAFE_AGENTS
    assert "qualification_a" not in REMOTE_SAFE_AGENTS
    assert "outreach_closer" not in REMOTE_SAFE_AGENTS
    assert "follow_up" not in REMOTE_SAFE_AGENTS
