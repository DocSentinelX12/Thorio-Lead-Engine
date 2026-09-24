import json

import pytest

from lead_engine.gpu_execution_runtime import (
    GpuExecutionError,
    execute_gpu_workload,
    verify_allocated_nvidia_gpus,
)


class Client:
    worker_id = "worker-1"

    def __init__(self):
        self.states = []
        self.heartbeats = 0
        self.verification = None
        self.converged = 0

    def fabric_state(self, attempt_id, generation, lease_token, status, error=""):
        self.states.append((status, error))
        return {"ok": True}

    def fabric_heartbeat(self, attempt_id, generation, lease_token):
        self.heartbeats += 1
        return {"ok": True}

    def fabric_record_verification(self, attempt_id, generation, lease_token, verification):
        self.verification = verification
        return {"ok": True}

    def gpu_record_verification(self, attempt_id, generation, lease_token, verification):
        self.verification = verification
        return {"ok": True}


def task():
    return {
        "task_id": "task-1",
        "attempt_id": "attempt-1",
        "generation": 3,
        "lease_token": "lease-1",
        "payload": {
            "kind": "gpu_workload",
            "command": ["python", "-c", "print('gpu')"],
        },
        "physical_allocation": {
            "allocation_id": "alloc-1",
            "capability_evidence": [
                {"resource_id": "node-1/0", "gpu_id": "0", "gpu_uuid": "GPU-1"}
            ],
        },
    }


def test_gpu_identity_verification_uses_exact_uuid():
    calls = []

    def runner(args):
        calls.append(tuple(args))
        return 0, "0, GPU-1\n", ""

    result = verify_allocated_nvidia_gpus(
        [{"resource_id": "node-1/0", "gpu_id": "0", "gpu_uuid": "GPU-1"}],
        runner=runner,
    )

    assert result["verified"] is True
    assert result["gpu_bindings"][0]["gpu_uuid"] == "GPU-1"
    assert calls == [("nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits")]


def test_gpu_workload_runs_only_after_exact_identity_verification():
    client = Client()
    calls = []

    def runner(args, env, timeout):
        calls.append((tuple(args), dict(env or {}), timeout))
        if args[0] == "nvidia-smi":
            return 0, "0, GPU-1\n", ""
        return 0, "result", ""

    result = execute_gpu_workload(client, task(), runner=runner)

    assert result["verified"] is True
    assert result["gpu_bindings"][0]["gpu_uuid"] == "GPU-1"
    assert calls[1][1]["CUDA_VISIBLE_DEVICES"] == "0"
    assert calls[1][1]["THORIO_EXPECTED_GPU_UUIDS"] == json.dumps(["GPU-1"])
    assert client.states[:2] == [("launching", ""), ("active", "")]
    assert client.verification["execution_kind"] == "gpu_workload"


def test_gpu_workload_rejects_identity_mismatch_before_launch():
    client = Client()
    launched = []

    def runner(args, env, timeout):
        if args[0] == "nvidia-smi":
            return 0, "0, GPU-DIFFERENT\n", ""
        launched.append(args)
        return 0, "unexpected", ""

    with pytest.raises(GpuExecutionError, match="identity mismatch"):
        execute_gpu_workload(client, task(), runner=runner)

    assert launched == []


def test_gpu_workload_failure_is_not_reported_as_success():
    client = Client()

    def runner(args, env, timeout):
        if args[0] == "nvidia-smi":
            return 0, "0, GPU-1\n", ""
        return 17, "", "workload failed"

    with pytest.raises(GpuExecutionError, match="exited with code 17"):
        execute_gpu_workload(client, task(), runner=runner)

    assert client.verification is None
    assert client.states[-1][0] == "failed"


def test_declared_artifact_and_checkpoint_are_content_addressed(tmp_path):
    client = Client()
    output = tmp_path / "output.bin"
    checkpoint = tmp_path / "checkpoint.bin"
    output.write_bytes(b"output")
    checkpoint.write_bytes(b"checkpoint")
    payload = task()
    payload["payload"]["output_artifacts"] = [str(output)]
    payload["payload"]["checkpoint_path"] = str(checkpoint)

    def runner(args, env, timeout):
        if args[0] == "nvidia-smi":
            return 0, "0, GPU-1\n", ""
        return 0, "done", ""

    result = execute_gpu_workload(client, payload, runner=runner)

    refs = {item["kind"]: item for item in result["artifact_refs"]}
    assert refs["output"]["immutable"] is True
    assert refs["checkpoint"]["immutable"] is True
    assert len(refs["output"]["sha256"]) == 64
    assert len(refs["checkpoint"]["sha256"]) == 64

def test_gpu_verification_persists_immutable_artifact_and_checkpoint_refs(tmp_path):
    from lead_engine.compute_coordinator import ComputeCoordinator
    import hashlib
    import time

    db_path = str(tmp_path / "coordinator.sqlite3")
    coordinator = ComputeCoordinator(db_path, "token")
    now = time.time()
    lease_token = "lease-1"
    lease_digest = hashlib.sha256(lease_token.encode()).hexdigest()
    task_id = "task-1"
    attempt_id = "attempt-1"
    generation = 1
    allocation_id = "alloc-1"

    with coordinator._connect() as connection:
        connection.execute(
            "INSERT INTO compute_tasks(task_id,payload,status,worker_id,lease_token,lease_until,attempt_id,generation,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (task_id, '{"kind":"gpu_workload"}', "leased", "fabric:"+attempt_id, lease_token, now + 300, attempt_id, generation, now, now),
        )
        connection.execute(
            "INSERT INTO compute_execution_attempts(attempt_id,task_id,generation,worker_id,status,lease_token_digest,started_at,allocation_id,resource_ids) VALUES(?,?,?,?,?,?,?,?,?)",
            (attempt_id, task_id, generation, "fabric:"+attempt_id, "leased", lease_digest, now, allocation_id, '["node-1/gpu-0"]'),
        )
        connection.execute(
            "INSERT INTO compute_execution_participants(attempt_id,task_id,generation,allocation_id,worker_id,node_id,rank,world_size,rendezvous_ref,status,resource_ids,bound_at,heartbeat_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (attempt_id, task_id, generation, allocation_id, "worker-1", "node-1", 0, 1, "fabric:attempt-1:1", "active", '["node-1/gpu-0"]', now, now),
        )
        connection.commit()

    coordinator.inventory.allocation = lambda _allocation_id: {
        "state": "bound",
        "attempt_id": attempt_id,
        "generation": generation,
        "resource_keys": ["node-1/gpu-0"],
        "resource_ids": ["node-1/gpu-0"],
    }

    verification = {
        "verified": True,
        "execution_kind": "gpu_workload",
        "worker_id": "worker-1",
        "gpu_bindings": [{"resource_id": "node-1/gpu-0", "gpu_id": "0", "gpu_uuid": "GPU-1"}],
        "artifact_refs": [
            {"kind": "output", "sha256": "a" * 64, "size_bytes": 12, "immutable": True, "attempt_id": attempt_id, "generation": generation}
        ],
        "checkpoint_ref": {
            "kind": "checkpoint",
            "sha256": "b" * 64,
            "size_bytes": 34,
            "immutable": True,
            "attempt_id": attempt_id,
            "generation": generation,
        },
    }

    assert coordinator.record_gpu_execution_verification(
        attempt_id=attempt_id,
        generation=generation,
        worker_id="worker-1",
        lease_token=lease_token,
        verification=verification,
    )

    attempt = coordinator.execution_attempt(attempt_id)
    assert attempt["artifact_refs"] == verification["artifact_refs"]
    assert json.loads(attempt["checkpoint_ref"]) == verification["checkpoint_ref"]
\n