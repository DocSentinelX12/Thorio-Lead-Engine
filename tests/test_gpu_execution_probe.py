from __future__ import annotations

from lead_engine.gpu_execution_probe import normalize_gpu_uuid


def test_normalize_gpu_uuid_accepts_nvidia_prefix_variants() -> None:
    assert normalize_gpu_uuid("GPU-2ce092c4-2296-7960-6ef1-623ff44057fb") == "GPU-2ce092c4-2296-7960-6ef1-623ff44057fb"
    assert normalize_gpu_uuid("2ce092c4-2296-7960-6ef1-623ff44057fb") == "GPU-2ce092c4-2296-7960-6ef1-623ff44057fb"
    assert normalize_gpu_uuid(" gpu-2ce092c4-2296-7960-6ef1-623ff44057fb ") == "GPU-2ce092c4-2296-7960-6ef1-623ff44057fb"


def test_normalize_gpu_uuid_preserves_distinct_physical_identities() -> None:
    assert normalize_gpu_uuid("GPU-aaa") != normalize_gpu_uuid("GPU-bbb")
    assert normalize_gpu_uuid("") == ""
