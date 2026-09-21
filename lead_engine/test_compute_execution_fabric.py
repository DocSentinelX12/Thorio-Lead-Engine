import tempfile
from pathlib import Path

from lead_engine.compute_bridge import REMOTE_SAFE_AGENTS
from lead_engine.compute_coordinator import ComputeCoordinator
from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_pool import WorkerIdentity
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState
from lead_engine.nvidia_runtime import NvidiaRuntime, NvidiaRuntimeError


def _worker():
    return WorkerIdentity(
        "worker-1",
        "host",
        "x86_64",
        4,
        8192,
        ("lead-processing", "engineering_demand_discovery"),
    )


def test_physical_fabric_requirements_do_not_bind_to_claiming_worker():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        coordinator = ComputeCoordinator(
            str(root / "coordinator.sqlite3"),
            auth_token="token",
            inventory=ComputeInventory(str(root / "inventory.sqlite3")),
        )
        requirements = coordinator.physical_requirements({
            "compute_requirements": {
                "workload_class": "multi_node_gpu",
                "gpu": {"gpu_count": 2, "require_nccl": True},
                "min_cpu_count": 2,
                "min_memory_bytes": 1024,
                "same_node": False,
            },
        })

        assert requirements.allowed_node_ids == ()
        assert requirements.workload_class.value == "multi_node_gpu"
        assert requirements.gpu.gpu_count == 2
        assert requirements.gpu.require_nccl is True


def test_global_physical_claim_allocates_across_registered_nodes_without_worker_pinning():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        inventory = ComputeInventory(str(root / "inventory.sqlite3"))
        coordinator = ComputeCoordinator(
            str(root / "coordinator.sqlite3"),
            auth_token="token",
            lease_seconds=30,
            inventory=inventory,
        )
        for node_id in ("worker-1", "worker-2"):
            coordinator.pool.register(WorkerIdentity(
                node_id,
                f"{node_id}.host",
                "x86_64",
                4,
                8192,
                ("lead-processing",),
                (GpuResource(
                    node_id=node_id,
                    gpu_id="gpu-0",
                    availability_state=ResourceState.AVAILABLE,
                ),),
                "550.1",
                "12.4",
                "2.20",
            ))
            inventory.observe(ProviderResourceSnapshot(
                provider_id="fabric-provider",
                domain_id="fabric-domain",
                observed_at=1.0,
                expires_at=9999999999.0,
                ephemeral=True,
                authentication_state="authenticated",
                evidence={"source": "test"},
                nodes=(NodeResource(
                    node_id=node_id,
                    architecture="x86_64",
                    cpu=CpuResource(node_id, 4, 8192),
                    gpus=(GpuResource(node_id=node_id, gpu_id="gpu-0", availability_state=ResourceState.AVAILABLE),),
                    driver_version="550.1",
                    cuda_version="12.4",
                    nccl_version="2.20",
                    state=ResourceState.AVAILABLE,
                ),),
            ))
        task_id = coordinator.enqueue({
            "compute_requirements": {
                "workload_class": "multi_node_gpu",
                "gpu": {"gpu_count": 2, "require_nccl": True},
                "min_cpu_count": 1,
                "min_memory_bytes": 1,
                "same_node": False,
            },
        })

        claimed = coordinator.claim_physical()

        assert claimed is not None
        assert claimed["task_id"] == task_id
        assert claimed["physical_allocation"]["node_ids"] == ["worker-1", "worker-2"]
        assert claimed["physical_allocation"]["resource_ids"] == ["worker-1/cpu", "worker-2/cpu", "worker-1/gpu-0", "worker-2/gpu-0"]
        stored = inventory.allocation(claimed["physical_allocation"]["allocation_id"])
        assert stored["state"] == "bound"
        assert stored["task_id"] == task_id
        assert stored["attempt_id"] == claimed["attempt_id"]
        assert stored["generation"] == claimed["generation"]

        participants = coordinator.execution_participants(claimed["attempt_id"])
        assert [item["worker_id"] for item in participants] == ["worker-1", "worker-2"]
        assert [item["node_id"] for item in participants] == ["worker-1", "worker-2"]
        assert [item["rank"] for item in participants] == [0, 1]
        assert [item["world_size"] for item in participants] == [2, 2]
        assert len({item["rendezvous_ref"] for item in participants}) == 1
        assert participants[0]["status"] == "bound"


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
            },
            "compute_requirements": {
                "workload_class": "cpu_bound",
                "min_cpu_count": 1,
                "min_memory_bytes": 1,
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
            "payload": {},
            "compute_requirements": {
                "workload_class": "cpu_bound",
                "min_cpu_count": 1,
                "min_memory_bytes": 1,
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
            "payload": {},
            "compute_requirements": {
                "workload_class": "gpu_required",
                "gpu": {"gpu_count": 1},
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


def test_nvidia_runtime_requires_real_cuda_and_nccl_evidence():
    calls = []

    def runner(args, timeout):
        calls.append(tuple(args))
        if args[0] == "nvidia-smi" and args[1:] == ("-L",):
            return 0, "GPU 0: NVIDIA H100 (UUID: GPU-aaa)\\nGPU 1: NVIDIA H100 (UUID: GPU-bbb)\\n", ""
        if args[0] == "nvcc":
            return 0, "Cuda compilation tools, release 12.4, V12.4.131\\n", ""
        if args[0] == "ldconfig":
            return 0, "libnccl.so.2 => /usr/lib/x86_64-linux-gnu/libnccl.so.2\\n", ""
        raise AssertionError(args)

    runtime = NvidiaRuntime(runner=runner, which=lambda name: name)
    evidence = runtime.verify_local()
    assert evidence["gpu_count"] == 2
    assert evidence["cuda_toolkit_version"] == "12.4"
    assert evidence["nccl_library"] == "/usr/lib/x86_64-linux-gnu/libnccl.so.2"
    assert any(call[:2] == ("nvidia-smi", "-L") for call in calls)


def test_nvidia_runtime_refuses_missing_nccl_instead_of_claiming_distributed_capability():
    def runner(args, timeout):
        if args[0] == "nvidia-smi":
            return 0, "GPU 0: NVIDIA H100 (UUID: GPU-aaa)\\n", ""
        if args[0] == "nvcc":
            return 0, "Cuda compilation tools, release 12.4, V12.4.131\\n", ""
        if args[0] == "ldconfig":
            return 0, "", ""
        raise AssertionError(args)

    runtime = NvidiaRuntime(runner=runner, which=lambda name: name)
    with pytest.raises(NvidiaRuntimeError, match="NCCL"):
        runtime.verify_local()
