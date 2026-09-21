import json
import threading
import time
from pathlib import Path

from lead_engine.compute_coordinator import ComputeCoordinator, ComputeCoordinatorServer
from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_pool import WorkerIdentity
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState
from lead_engine.compute_worker import ComputeWorkerClient, run_fabric_verification


def _fabric_worker(node_id: str) -> WorkerIdentity:
    return WorkerIdentity(
        node_id,
        f"{node_id}.host",
        "x86_64",
        8,
        16384,
        ("lead-processing",),
        (GpuResource(node_id=node_id, gpu_id="gpu-0", availability_state=ResourceState.AVAILABLE),),
        "550.1",
        "12.4",
        "2.20",
    )


def _register_inventory(coordinator: ComputeCoordinator, inventory: ComputeInventory) -> None:
    for node_id in ("worker-1", "worker-2"):
        coordinator.pool.register(_fabric_worker(node_id))
        inventory.observe(ProviderResourceSnapshot(
            provider_id="fabric-provider",
            domain_id="fabric-domain",
            observed_at=time.time(),
            expires_at=time.time() + 300,
            ephemeral=True,
            authentication_state="authenticated",
            evidence={"source": "test"},
            nodes=(NodeResource(
                node_id=node_id,
                architecture="x86_64",
                cpu=CpuResource(node_id, 8, 16384),
                gpus=(GpuResource(
                    node_id=node_id, gpu_id="gpu-0",
                    availability_state=ResourceState.AVAILABLE,
                ),),
                driver_version="550.1",
                cuda_version="12.4",
                nccl_version="2.20",
                state=ResourceState.AVAILABLE,
            ),),
        ))


class _FakeRuntime:
    timeout_seconds = 2.0

    def verify_local(self):
        return {"verified": True, "gpu_count": 1, "cuda_toolkit_version": "12.4", "nccl_library": "test"}

    def distributed_command(self, **kwargs):
        return (
            "torchrun",
            f"--nproc-per-node={kwargs['process_count']}",
            f"--nnodes={kwargs['nnodes']}",
            f"--node-rank={kwargs['node_rank']}",
            f"--master-addr={kwargs['master_addr']}",
            f"--master-port={kwargs['master_port']}",
            "--rdzv-id",
            kwargs["rendezvous_id"],
            "-m",
            "lead_engine.nccl_all_reduce_probe",
        )


def test_worker_receives_durable_participant_and_runs_launch_heartbeat_lifecycle(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
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
    assert claimed["task_id"] == task_id

    server = ComputeCoordinatorServer(coordinator, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ComputeWorkerClient(
            f"http://127.0.0.1:{server.server_port}",
            "test-token",
            "worker-1",
            timeout_seconds=2,
        )
        assignments = client.fabric_assignments()
        assert len(assignments) == 1
        assignment = assignments[0]
        assert assignment["attempt_id"] == claimed["attempt_id"]
        assert assignment["generation"] == claimed["generation"]
        assert assignment["worker_id"] == "worker-1"
        assert assignment["lease_token"] == claimed["lease_token"]

        calls = []
        def runner(command, timeout):
            calls.append((tuple(command), timeout))
            time.sleep(0.05)
            return 0, "THORIO_NCCL_PROBE_OK {\"verified_on_gpu\":true}", ""

        evidence = run_fabric_verification(
            client,
            assignment,
            rendezvous_endpoint="10.0.0.5:29400",
            heartbeat_seconds=0.01,
            runtime=_FakeRuntime(),
            runner=runner,
        )

        assert evidence["verified"] is True
        assert calls
        assert "--node-rank=0" in calls[0][0]
        attempt = coordinator.execution_attempt(claimed["attempt_id"])
        assert json.loads(attempt["verification"])["verified"] is True
        participant = coordinator.execution_participants(claimed["attempt_id"])[0]
        assert participant["status"] == "running"
        assert participant["heartbeat_at"] >= participant["bound_at"]
        assert coordinator.task(task_id)["status"] == "leased"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_fabric_launch_requires_explicit_rendezvous_endpoint(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        auth_token="test-token",
        lease_seconds=30,
        inventory=inventory,
    )
    _register_inventory(coordinator, inventory)
    task_id = coordinator.enqueue({
        "compute_requirements": {
            "workload_class": "multi_node_gpu",
            "gpu": {"gpu_count": 2},
            "min_cpu_count": 1,
            "min_memory_bytes": 1,
            "same_node": False,
        },
    })
    claimed = coordinator.claim_physical()
    assert claimed["task_id"] == task_id
    try:
        coordinator.fabric_launch_plan_for_worker(
            attempt_id=claimed["attempt_id"],
            generation=claimed["generation"],
            worker_id="worker-1",
            lease_token=claimed["lease_token"],
            rendezvous_endpoint="",
        )
    except ValueError as error:
        assert "host:port" in str(error)
    else:
        raise AssertionError("fabric launch accepted a missing rendezvous endpoint")
