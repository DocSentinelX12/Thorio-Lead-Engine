from __future__ import annotations

from lead_engine.compute_fabric_telemetry import (
    workload_performance_key,
    summarize_route_health,
)


def test_workload_performance_key_separates_collective_workloads():
    path = {
        "node_id": "node-a",
        "gpu_uuid": "gpu-0",
        "nic": "eth0",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    first = workload_performance_key(
        path,
        {
            "workload_class": "multi_gpu",
            "collective": "all_reduce",
            "world_size": 8,
            "message_size_bytes": 1048576,
            "dtype": "bf16",
        },
    )
    second = workload_performance_key(
        path,
        {
            "workload_class": "multi_gpu",
            "collective": "all_reduce",
            "world_size": 8,
            "message_size_bytes": 16777216,
            "dtype": "bf16",
        },
    )
    assert first
    assert first != second


def test_workload_performance_key_is_order_independent():
    path = {
        "node_id": "node-a",
        "gpu_uuid": "gpu-0",
        "nic": "eth0",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    a = workload_performance_key(path, {"world_size": 8, "collective": "all_reduce", "dtype": "bf16"})
    b = workload_performance_key(path, {"dtype": "bf16", "collective": "all_reduce", "world_size": 8})
    assert a == b


def test_route_health_summary_exposes_observed_regression_without_threshold_policy():
    samples = [
        {"observed_at": 10.0, "latency_ms": 4.0, "success": True},
        {"observed_at": 20.0, "latency_ms": 5.0, "success": True},
        {"observed_at": 30.0, "latency_ms": 9.0, "success": True},
        {"observed_at": 40.0, "latency_ms": 9.0, "success": False},
    ]
    summary = summarize_route_health(samples)
    assert summary["sample_count"] == 4
    assert summary["success_count"] == 3
    assert summary["failure_count"] == 1
    assert summary["latest_latency_ms"] == 9.0
    assert summary["historical_mean_latency_ms"] == 6.75
    assert summary["latency_delta_from_mean_ms"] == 2.25
    assert summary["failure_rate"] == 0.25


def test_route_health_summary_preserves_unknown_evidence():
    summary = summarize_route_health([])
    assert summary == {"sample_count": 0, "success_count": 0, "failure_count": 0}


def test_scheduler_uses_workload_specific_history_before_legacy_path_history(tmp_path):
    from lead_engine.compute_inventory import ComputeInventory
    from lead_engine.compute_provider import ProviderResourceSnapshot
    from lead_engine.compute_resources import ComputeRequirements, GpuRequirements, WorkloadClass, CpuResource, GpuResource, NodeResource, ResourceState
    from lead_engine.compute_scheduler import ComputeScheduler
    import time

    def gpu(node, gid, uuid):
        return GpuResource(
            node_id=node, gpu_id=gid, gpu_uuid=uuid, vram_bytes=24 * 1024**3,
            compute_capability="8.0", health_state=ResourceState.HEALTHY, availability_state=ResourceState.AVAILABLE,
        )

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(ProviderResourceSnapshot(
        provider_id="p", domain_id="d", observed_at=time.time(),
        nodes=(NodeResource(
            node_id="n", architecture="x86_64",
            cpu=CpuResource(node_id="n", cpu_count=8, memory_bytes=64 * 1024**3),
            gpus=(gpu("n", "g0", "u0"), gpu("n", "g1", "u1")),
            state=ResourceState.HEALTHY,
        ),),
        authentication_state="authenticated",
        evidence={"network": {
            "source": "test",
            "gpu_nic_locality": [
                {"gpu_uuid": "u0", "nic": "e0", "rdma_device": "r0", "rdma_port": 1, "link_layer": "ib"},
                {"gpu_uuid": "u1", "nic": "e1", "rdma_device": "r1", "rdma_port": 1, "link_layer": "ib"},
            ],
            "rdma": {"devices": [{"device": "r0"}, {"device": "r1"}], "links": [
                {"rdma_device": "r0", "port": 1, "link_layer": "ib", "state": "ACTIVE", "physical_state": "LINK_UP"},
                {"rdma_device": "r1", "port": 1, "link_layer": "ib", "state": "ACTIVE", "physical_state": "LINK_UP"},
            ]},
        }},
    ))
    from lead_engine.compute_fabric_telemetry import workload_performance_key, physical_path_key
    paths = {
        "u0": {"node_id": "n", "gpu_uuid": "u0", "nic": "e0", "rdma_device": "r0", "rdma_port": 1, "link_layer": "ib"},
        "u1": {"node_id": "n", "gpu_uuid": "u1", "nic": "e1", "rdma_device": "r1", "rdma_port": 1, "link_layer": "ib"},
    }
    workload = {"workload_class": "multi_gpu", "collective": "all_reduce", "world_size": 2, "message_size_bytes": 1048576}
    history = {
        workload_performance_key(paths["u0"], workload): {"avg_all_reduce_elapsed_ms": 2.0, "sample_count": 5},
        workload_performance_key(paths["u1"], workload): {"avg_all_reduce_elapsed_ms": 8.0, "sample_count": 5},
        physical_path_key(paths["u0"]): {"avg_all_reduce_elapsed_ms": 99.0, "sample_count": 100},
        physical_path_key(paths["u1"]): {"avg_all_reduce_elapsed_ms": 1.0, "sample_count": 100},
    }
    scheduler = ComputeScheduler(inventory, performance_history_provider=lambda: history)
    allocation = scheduler.allocate(
        ComputeRequirements(
            WorkloadClass.MULTI_GPU,
            GpuRequirements(gpu_count=1),
            performance_signature=tuple(workload.items()),
        ),
        "workload-specific",
    )
    assert allocation.resource_ids[-1] == "n/g0"


def test_route_health_observations_are_durable_and_idempotent(tmp_path):
    from lead_engine.compute_inventory import ComputeInventory

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = {
        "node_id": "node-a",
        "gpu_uuid": "gpu-0",
        "nic": "eth0",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    first = inventory.record_fabric_route_observation(
        path, latency_ms=4.0, success=True, observed_at=10.0,
    )
    second = inventory.record_fabric_route_observation(
        path, latency_ms=4.0, success=True, observed_at=10.0,
    )
    inventory.record_fabric_route_observation(
        path, latency_ms=9.0, success=False, observed_at=20.0,
    )
    assert first == second
    health = inventory.fabric_route_health_index()[inventory.fabric_path_key(path)]
    assert health["sample_count"] == 2
    assert health["failure_count"] == 1
    assert health["latest_latency_ms"] == 9.0


def test_execution_metrics_carry_explicit_workload_identity():
    from lead_engine.compute_fabric_telemetry import extract_execution_metrics

    verification = {
        "workload": {
            "workload_class": "multi_gpu",
            "collective": "all_reduce",
            "world_size": 4,
            "message_size_bytes": 4096,
            "dtype": "fp16",
        },
        "process_evidence": [{
            "rank": 0,
            "gpu_binding": {
                "node_id": "node-a",
                "planned_physical_path": {
                    "node_id": "node-a",
                    "gpu_uuid": "gpu-0",
                    "nic": "eth0",
                    "rdma_device": "mlx5_0",
                    "rdma_port": 1,
                    "link_layer": "InfiniBand",
                },
            },
            "probe": {
                "rank": 0,
                "gpu_uuid": "gpu-0",
                "network_transport": "nccl",
                "all_reduce_elapsed_ms": 3.5,
            },
        }],
    }
    metric = extract_execution_metrics(verification)[0]
    assert metric["workload_signature"]["message_size_bytes"] == 4096
    assert metric["workload_key"]


def test_inventory_route_health_exposes_predictive_failure_degradation_without_new_storage(tmp_path):
    from lead_engine.compute_inventory import ComputeInventory

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    path = {
        "node_id": "node-a",
        "gpu_uuid": "gpu-0",
        "nic": "eth0",
        "rdma_device": "mlx5_0",
        "rdma_port": 1,
        "link_layer": "InfiniBand",
    }
    workload_key = "workload-a"
    for observed_at, success in ((1.0, True), (2.0, True), (3.0, False), (4.0, False)):
        inventory.record_fabric_route_observation(
            path,
            latency_ms=3.0,
            success=success,
            observed_at=observed_at,
            evidence={"workload_key": workload_key, "fabric_path_id": "path-a"},
            fabric_path_id="path-a",
        )

    health = inventory.fabric_route_health_index()["path-a"]
    assert health["failure_count"] == 2
    assert health["predictive_failure_degradation"]["state"] == "failure_pattern"
    assert health["predictive_failure_by_workload_key"][workload_key]["state"] == "failure_pattern"


def test_fleet_resource_intelligence_aggregates_capacity_by_provider_domain_and_state(tmp_path):
    from lead_engine.compute_inventory import ComputeInventory
    from lead_engine.compute_provider import ProviderResourceSnapshot
    from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState
    import time

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))

    def gpu(node, gpu_id, uuid, state=ResourceState.HEALTHY):
        return GpuResource(
            node_id=node,
            gpu_id=gpu_id,
            gpu_uuid=uuid,
            model="Test-A",
            vram_bytes=24 * 1024**3,
            compute_capability="8.0",
            cuda_version="12.4",
            driver_version="550",
            health_state=state,
            availability_state=state,
        )

    observed = time.time()
    inventory.observe(ProviderResourceSnapshot(
        provider_id="provider-a",
        domain_id="domain-a",
        observed_at=observed,
        nodes=(
            NodeResource(
                node_id="node-a",
                architecture="x86_64",
                cpu=CpuResource("node-a", 16, 64 * 1024**3),
                gpus=(gpu("node-a", "0", "uuid-a0"), gpu("node-a", "1", "uuid-a1", ResourceState.AVAILABLE), gpu("node-a", "2", "uuid-a2")),
                state=ResourceState.HEALTHY,
            ),
            NodeResource(
                node_id="node-b",
                architecture="x86_64",
                cpu=CpuResource("node-b", 16, 64 * 1024**3),
                gpus=(gpu("node-b", "0", "uuid-b0", ResourceState.DEGRADED),),
                state=ResourceState.DEGRADED,
            ),
        ),
        authentication_state="authenticated",
    ))
    inventory.mark_state("provider-a/domain-a/node-a/gpu/uuid-a2", ResourceState.RESERVED)
    inventory.mark_state("provider-a/domain-a/node-b/gpu/uuid-b0", ResourceState.QUARANTINED)

    summary = inventory.fleet_resource_intelligence(now=observed + 1)

    assert summary["totals"]["gpu"]["TOTAL"] == 4
    assert summary["totals"]["gpu"]["HEALTHY"] == 1
    assert summary["totals"]["gpu"]["AVAILABLE"] == 1
    assert summary["totals"]["gpu"]["RESERVED"] == 1
    assert summary["totals"]["gpu"]["LEASED"] == 0
    assert summary["totals"]["gpu"]["DEGRADED"] == 0
    assert summary["totals"]["gpu"]["QUARANTINED"] == 1
    assert summary["provider_domains"]["provider-a/domain-a"]["gpu"]["AVAILABLE"] == 1
    assert summary["provider_domains"]["provider-a/domain-a"]["nodes"]["TOTAL"] == 2
    assert summary["provider_domains"]["provider-a/domain-a"]["gpu"]["known_vram_bytes"] == 4 * 24 * 1024**3


def test_fleet_resource_intelligence_reconciles_bound_allocations_as_leased(tmp_path):
    from lead_engine.compute_inventory import ComputeInventory
    from lead_engine.compute_provider import ProviderResourceSnapshot
    from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState
    import time

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(ProviderResourceSnapshot(
        provider_id="p",
        domain_id="d",
        observed_at=10.0,
        nodes=(NodeResource(
            node_id="n",
            architecture="x86_64",
            cpu=CpuResource("n", 8, 32 * 1024**3),
            gpus=(GpuResource(
                node_id="n", gpu_id="0", gpu_uuid="u0", model="Test",
                vram_bytes=16 * 1024**3,
                health_state=ResourceState.HEALTHY,
                availability_state=ResourceState.AVAILABLE,
            ),),
            state=ResourceState.HEALTHY,
        ),),
        authentication_state="authenticated",
    ))
    key = "p/d/n/gpu/u0"
    inventory.reserve_allocation("allocation-1", "p", "d", [key])
    assert inventory.bind_allocation(
        "allocation-1",
        task_id="task-1",
        attempt_id="attempt-1",
        generation=1,
        lease_token_digest="digest",
    )

    summary = inventory.fleet_resource_intelligence(now=20.0)

    assert summary["totals"]["gpu"]["AVAILABLE"] == 0
    assert summary["totals"]["gpu"]["RESERVED"] == 0
    assert summary["totals"]["gpu"]["LEASED"] == 1
    assert summary["provider_domains"]["p/d"]["gpu"]["LEASED"] == 1


def test_fleet_resource_intelligence_preserves_capability_unknowns_and_no_synthetic_capacity(tmp_path):
    from lead_engine.compute_inventory import ComputeInventory
    from lead_engine.compute_provider import ProviderResourceSnapshot
    from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(ProviderResourceSnapshot(
        provider_id="p",
        domain_id="d",
        observed_at=10.0,
        nodes=(NodeResource(
            node_id="n",
            architecture="x86_64",
            cpu=CpuResource("n", 4, 16 * 1024**3),
            gpus=(GpuResource(
                node_id="n", gpu_id="0", gpu_uuid="u0", model=None,
                vram_bytes=None, compute_capability=None, cuda_version=None,
                driver_version=None, health_state=ResourceState.AVAILABLE,
                availability_state=ResourceState.AVAILABLE,
            ),),
        ),),
        authentication_state="authenticated",
    ))

    summary = inventory.fleet_resource_intelligence(now=11.0)

    gpu = summary["totals"]["gpu"]
    assert gpu["TOTAL"] == 1
    assert gpu["AVAILABLE"] == 1
    assert gpu["known_vram_bytes"] == 0
    assert gpu["unknown_vram_count"] == 1
    assert gpu["capability_families"]["model"] == {}
    assert gpu["capability_families"]["compute_capability"] == {}
    assert summary["provider_domains"]["p/d"]["gpu"]["AVAILABLE"] == 1


def test_scheduler_exposes_the_same_fleet_intelligence_without_owning_capacity_state(tmp_path):
    from lead_engine.compute_inventory import ComputeInventory
    from lead_engine.compute_scheduler import ComputeScheduler

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    scheduler = ComputeScheduler(inventory)

    direct = inventory.fleet_resource_intelligence(now=100.0)
    exposed = scheduler.fleet_resource_intelligence(now=100.0)

    assert exposed == direct


def test_fleet_resource_intelligence_keeps_expired_resources_out_of_eligible_capacity(tmp_path):
    from lead_engine.compute_inventory import ComputeInventory
    from lead_engine.compute_provider import ProviderResourceSnapshot
    from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState

    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(ProviderResourceSnapshot(
        provider_id="p",
        domain_id="d",
        observed_at=10.0,
        expires_at=20.0,
        ephemeral=True,
        nodes=(NodeResource(
            node_id="n",
            architecture="x86_64",
            cpu=CpuResource("n", 4, 16 * 1024**3),
            gpus=(GpuResource(
                node_id="n", gpu_id="0", gpu_uuid="u0",
                vram_bytes=8 * 1024**3,
                availability_state=ResourceState.AVAILABLE,
            ),),
        ),),
        authentication_state="authenticated",
    ))

    summary = inventory.fleet_resource_intelligence(now=20.0)

    assert summary["totals"]["gpu"]["AVAILABLE"] == 1
    assert summary["totals"]["eligible"] == 0
    assert summary["totals"]["gpu"]["available_known_vram_bytes"] == 0


def test_continuous_self_optimization_preserves_future_single_node_flexibility():
    from lead_engine.compute_placement import PlacementEvaluator
    from lead_engine.compute_resources import ComputeRequirements, GpuRequirements, WorkloadClass

    requirements = ComputeRequirements(
        workload_class=WorkloadClass.GPU_REQUIRED,
        performance_signature=(),
        gpu=GpuRequirements(gpu_count=1),
    )
    def gpu(key, node):
        return {
            "resource_key": key,
            "provider_id": "p",
            "domain_id": "d",
            "node_id": node,
            "resource_type": "gpu",
            "payload_json": json.dumps({"gpu_uuid": key, "gpu_id": key}),
            "evidence_json": "{}",
            "state": "available",
            "expires_at": None,
        }

    rows = [
        gpu("a0", "node-a"),
        gpu("a1", "node-a"),
        gpu("b0", "node-b"),
    ]
    evaluator = object.__new__(PlacementEvaluator)
    evaluator.scheduler = type("Scheduler", (), {"_gpu_matches": staticmethod(lambda row, _req: True)})()
    evaluator.requirements = requirements
    evaluator.rows = rows
    evaluator.performance_history = {}
    evaluator.route_health = {}
    evaluator.physical_paths = ()

    records = evaluator._continuous_optimization_records([
        (rows[0],),
        (rows[2],),
    ])

    first = next(item for item in records if item["candidate_key"] == "a0")
    second = next(item for item in records if item["candidate_key"] == "b0")

    assert first["future_single_node_count"] == 2
    assert second["future_single_node_count"] == 1
    assert first["preferred"] is True
    assert second["preferred"] is False


def test_continuous_self_optimization_is_final_and_cannot_override_observed_performance():
    from lead_engine.compute_placement import PlacementEvaluator

    evaluator = object.__new__(PlacementEvaluator)
    candidate_a = ({"resource_key": "a"},)
    candidate_b = ({"resource_key": "b"},)
    evaluator._candidate_performance = lambda candidate: (
        (0, 2.0, -8) if candidate == candidate_a else (0, 1.0, -8)
    )

    records = (
        {
            "candidate_key": "a",
            "preferred": True,
            "future_feasible_domain_count": 10,
            "future_single_node_count": 10,
        },
        {
            "candidate_key": "b",
            "preferred": False,
            "future_feasible_domain_count": 1,
            "future_single_node_count": 1,
        },
    )

    ranked = sorted(
        (candidate_a, candidate_b),
        key=lambda candidate: (
            evaluator._candidate_performance(candidate),
            evaluator._candidate_continuous_optimization(candidate, records),
            tuple(row["resource_key"] for row in candidate),
        ),
    )

    assert ranked[0] == candidate_b


def test_fabric_cycle_exposes_read_only_continuous_optimization_snapshot(tmp_path):
    from lead_engine.compute_fabric import ComputeFabricOrchestrator

    inventory = __import__("lead_engine.compute_inventory", fromlist=["ComputeInventory"]).ComputeInventory(
        str(tmp_path / "inventory.sqlite3")
    )
    fabric = ComputeFabricOrchestrator(inventory)

    snapshot = fabric.continuous_optimization()

    assert snapshot["state"] == "insufficient_evidence"
    assert snapshot["policy"]["placement_recomputed_from_current_inventory"] is True
    assert snapshot["policy"]["observed_execution_feedback_is_reused"] is True
    assert snapshot["policy"]["hard_validation_remains_authoritative"] is True
    assert snapshot["policy"]["compute_allocation_remains_authoritative"] is True
    assert snapshot["policy"]["synthetic_performance_values"] is False
    assert snapshot["policy"]["synthetic_capacity_values"] is False
    assert inventory.fleet_resource_intelligence()["totals"]["eligible"] == 0
