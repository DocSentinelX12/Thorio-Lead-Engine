import pytest

from lead_engine.distributed_execution_contract import (
    DistributedExecutionContractError,
    validate_launch_plan,
)


def _plan():
    return {
        "world_size": 3,
        "nnodes": 2,
        "rendezvous_endpoint": "node-a:29500",
        "workers": [
            {
                "worker_id": "worker-a",
                "node_id": "node-a",
                "process_count": 2,
                "rendezvous_endpoint": "node-a:29500",
                "gpu_bindings": [
                    {"gpu_id": "0", "gpu_uuid": "GPU-a0", "rank": 0, "local_rank": 0},
                    {"gpu_id": "1", "gpu_uuid": "GPU-a1", "rank": 1, "local_rank": 1},
                ],
            },
            {
                "worker_id": "worker-b",
                "node_id": "node-b",
                "process_count": 1,
                "rendezvous_endpoint": "node-a:29500",
                "gpu_bindings": [
                    {"gpu_id": "0", "gpu_uuid": "GPU-b0", "rank": 2, "local_rank": 0},
                ],
            },
        ],
    }


def test_valid_multi_node_plan_has_contiguous_global_ranks():
    evidence = validate_launch_plan(_plan())
    assert evidence == {
        "verified": True,
        "world_size": 3,
        "nnodes": 2,
        "worker_count": 2,
        "binding_count": 3,
        "rendezvous_endpoint": "node-a:29500",
    }


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p.update(world_size=4), "world_size does not match total process bindings"),
        (lambda p: p.update(nnodes=3), "nnodes does not match participant nodes"),
        (lambda p: p["workers"][1]["gpu_bindings"][0].update(rank=1), "global rank set is invalid or duplicated"),
        (lambda p: p["workers"][1].update(node_id="node-a"), "duplicate node_id"),
        (lambda p: p["workers"][1].update(rendezvous_endpoint="node-b:29500"), "rendezvous endpoint mismatch"),
        (lambda p: p["workers"][0].update(process_count=1), "GPU/process binding count mismatch"),
        (lambda p: p["workers"][0]["gpu_bindings"][0].update(local_rank=1), "local rank set is invalid or duplicated"),
        (lambda p: p["workers"][0]["gpu_bindings"][0].update(gpu_uuid=""), "GPU binding requires gpu_uuid and gpu_id"),
    ],
)
def test_invalid_global_launch_contract_is_rejected(mutate, message):
    plan = _plan()
    mutate(plan)
    with pytest.raises(DistributedExecutionContractError, match=message):
        validate_launch_plan(plan)


def test_expected_endpoint_can_supply_missing_plan_endpoint():
    plan = _plan()
    plan.pop("rendezvous_endpoint")
    for worker in plan["workers"]:
        worker.pop("rendezvous_endpoint")
    evidence = validate_launch_plan(plan, expected_endpoint="node-a:29500")
    assert evidence["rendezvous_endpoint"] == "node-a:29500"

def test_coordinator_launch_boundary_persists_verified_contract(tmp_path):
    from lead_engine.compute_coordinator import ComputeCoordinator

    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "token")
    now = 1_000.0
    attempt_id = "attempt-verified"
    with coordinator._connect() as connection:
        connection.execute(
            """INSERT INTO compute_tasks(
                   task_id,payload,status,worker_id,lease_token,lease_until,
                   attempt_id,generation,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("task-verified", "{}", "leased", "fabric:" + attempt_id, "lease",
             now + 300, attempt_id, 1, now, now),
        )
        connection.execute(
            """INSERT INTO compute_execution_attempts(
                   attempt_id,task_id,generation,worker_id,status,
                   lease_token_digest,started_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (attempt_id, "task-verified", 1, "fabric:" + attempt_id, "leased",
             __import__("hashlib").sha256(b"lease").hexdigest(), now),
        )
        connection.commit()

    plan = {
        "attempt_id": attempt_id,
        "world_size": 2,
        "nnodes": 2,
        "rendezvous_endpoint": "node-a:29500",
        "workers": [
            {"worker_id": "worker-a", "node_id": "node-a", "process_count": 1,
             "gpu_bindings": [{"gpu_id": "0", "gpu_uuid": "GPU-a", "rank": 0, "local_rank": 0}]},
            {"worker_id": "worker-b", "node_id": "node-b", "process_count": 1,
             "gpu_bindings": [{"gpu_id": "0", "gpu_uuid": "GPU-b", "rank": 1, "local_rank": 0}]},
        ],
    }

    evidence = coordinator._validate_and_persist_launch_plan(plan)

    assert evidence["verified"] is True
    attempt = coordinator.execution_attempt(attempt_id)
    assert attempt["launch_plan_verification"] == evidence


def test_coordinator_launch_boundary_rejects_invalid_contract_before_persistence(tmp_path):
    from lead_engine.compute_coordinator import ComputeCoordinator

    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), "token")
    attempt_id = "attempt-invalid"
    with coordinator._connect() as connection:
        connection.execute(
            """INSERT INTO compute_tasks(
                   task_id,payload,status,worker_id,lease_token,lease_until,
                   attempt_id,generation,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("task-invalid", "{}", "leased", "fabric:" + attempt_id, "lease",
             2_000.0, attempt_id, 1, 1_000.0, 1_000.0),
        )
        connection.execute(
            """INSERT INTO compute_execution_attempts(
                   attempt_id,task_id,generation,worker_id,status,
                   lease_token_digest,started_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (attempt_id, "task-invalid", 1, "fabric:" + attempt_id, "leased",
             __import__("hashlib").sha256(b"lease").hexdigest(), 1_000.0),
        )
        connection.commit()

    invalid_plan = {
        "attempt_id": attempt_id,
        "world_size": 3,
        "nnodes": 2,
        "rendezvous_endpoint": "node-a:29500",
        "workers": [
            {"worker_id": "worker-a", "node_id": "node-a", "process_count": 1,
             "gpu_bindings": [{"gpu_id": "0", "gpu_uuid": "GPU-a", "rank": 0, "local_rank": 0}]},
            {"worker_id": "worker-b", "node_id": "node-b", "process_count": 1,
             "gpu_bindings": [{"gpu_id": "0", "gpu_uuid": "GPU-b", "rank": 1, "local_rank": 0}]},
        ],
    }

    with pytest.raises(DistributedExecutionContractError, match="world_size does not match total process bindings"):
        coordinator._validate_and_persist_launch_plan(invalid_plan)

    attempt = coordinator.execution_attempt(attempt_id)
    assert attempt["launch_plan_verification"] is None

