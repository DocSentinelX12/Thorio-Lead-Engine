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
