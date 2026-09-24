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
