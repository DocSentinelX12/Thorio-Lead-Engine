from lead_engine.compute_pool import ComputeCapacity, local_capacity, pool_snapshot, worker_budget


def test_recommended_workers_is_bounded_by_cpu_and_memory():
    capacity = ComputeCapacity("node", cpu_count=8, memory_mb=4096, architecture="x86_64")
    assert capacity.recommended_workers == 2


def test_worker_budget_respects_requested_limit(monkeypatch):
    capacity = ComputeCapacity("node", cpu_count=8, memory_mb=16384, architecture="x86_64")
    monkeypatch.delenv("THORIO_MAX_LOCAL_WORKERS", raising=False)
    assert worker_budget(capacity, requested=3) == 3
    assert worker_budget(capacity, requested=99) == 7


def test_worker_budget_respects_free_only_local_cap(monkeypatch):
    capacity = ComputeCapacity("node", cpu_count=16, memory_mb=32768, architecture="x86_64")
    monkeypatch.setenv("THORIO_MAX_LOCAL_WORKERS", "4")
    assert worker_budget(capacity) == 4


def test_worker_budget_rejects_invalid_requests():
    capacity = ComputeCapacity("node", cpu_count=4, memory_mb=8192, architecture="x86_64")
    for value in (0, -1, True):
        try:
            worker_budget(capacity, requested=value)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid worker request was accepted")


def test_pool_snapshot_is_auditable():
    first = ComputeCapacity("a", 4, 8192, "x86_64", persistent=True)
    second = ComputeCapacity("b", 2, 4096, "aarch64")
    snapshot = pool_snapshot({"a": first, "b": second})
    assert snapshot["free_only"] is True
    assert snapshot["node_count"] == 2
    assert snapshot["total_cpu"] == 6
    assert snapshot["total_memory_mb"] == 12288
    assert snapshot["total_recommended_workers"] == 5


def test_local_capacity_has_positive_resources():
    capacity = local_capacity(node_id="test-node")
    assert capacity.node_id == "test-node"
    assert capacity.cpu_count >= 1
    assert capacity.memory_mb >= 1
    assert capacity.architecture
