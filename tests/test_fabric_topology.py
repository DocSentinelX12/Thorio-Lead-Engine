from __future__ import annotations

from pathlib import Path

import pytest

from lead_engine.fabric_topology import FabricTopologyError, PhysicalFabricTopology


def _pci_tree(root: Path, bdf: str, parents: list[str]) -> None:
    target = root / bdf
    target.mkdir(parents=True, exist_ok=True)
    current = target
    for parent in parents:
        parent_path = root / parent
        parent_path.mkdir(parents=True, exist_ok=True)
        current = current.parent


def test_gpu_nic_matrix_requires_complete_gpu_rows() -> None:
    text = """GPU0 GPU1
GPU0 X PIX
"""
    with pytest.raises(FabricTopologyError, match="rows are incomplete"):
        PhysicalFabricTopology.parse_gpu_nic_matrix(text)


def test_gpu_nic_matrix_preserves_physical_distance() -> None:
    text = """GPU0 GPU1 mlx5_0 mlx5_1
GPU0 X NV1 PIX PXB
GPU1 NV1 X PXB PIX
"""
    evidence = PhysicalFabricTopology.parse_gpu_nic_matrix(text)
    assert evidence["gpu_ids"] == ["0", "1"]
    assert evidence["matrix"]["0"]["mlx5_0"] == "PIX"
    assert evidence["matrix"]["1"]["mlx5_1"] == "PIX"


def test_reconcile_requires_real_pci_ancestry(tmp_path: Path) -> None:
    root = tmp_path / "pci"
    root.mkdir()
    # GPU and NIC share a PCI switch. The endpoint symlinks mirror the Linux
    # sysfs shape used by pci_hierarchy().
    switch = root / "0000:00:01.0"
    switch.mkdir()
    gpu_target = root / "0000:01:00.0"
    nic_target = root / "0000:01:00.1"
    gpu_target.mkdir()
    nic_target.mkdir()
    (gpu_target / "parent").symlink_to(switch, target_is_directory=True)
    (nic_target / "parent").symlink_to(switch, target_is_directory=True)

    # The test helper uses a normal temporary tree, so patch the hierarchy
    # traversal to the explicit fixture paths by making endpoint paths resolve
    # through a parent directory chain.
    gpu_parent = gpu_target / "device"
    nic_parent = nic_target / "device"
    gpu_parent.symlink_to(switch, target_is_directory=True)
    nic_parent.symlink_to(switch, target_is_directory=True)

    # A disconnected endpoint must not be accepted merely because it is on
    # the same NUMA/network domain.
    other = root / "0000:02:00.0"
    other.mkdir()
    with pytest.raises(FabricTopologyError):
        PhysicalFabricTopology.common_pci_ancestor("0000:01:00.0", "0000:02:00.0", sysfs_root=str(root))


def test_reconcile_produces_explicit_gpu_to_nic_to_rdma_paths(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "pci"
    root.mkdir()
    gpu = root / "0000:01:00.0"
    nic = root / "0000:01:00.1"
    switch = root / "0000:00:01.0"
    gpu.mkdir()
    nic.mkdir()
    switch.mkdir()

    # Linux sysfs resolves the PCI endpoint's device symlink to its PCI
    # hierarchy. Build that exact shape for the deterministic fixture.
    (gpu / "device").symlink_to(switch, target_is_directory=True)
    (nic / "device").symlink_to(switch, target_is_directory=True)

    original = PhysicalFabricTopology.pci_hierarchy
    monkeypatch.setattr(
        PhysicalFabricTopology,
        "pci_hierarchy",
        classmethod(lambda cls, bdf, sysfs_root="/sys/bus/pci/devices": (bdf.lower(), "0000:00:01.0", "0000:00:00.0")),
    )
    try:
        result = PhysicalFabricTopology.reconcile(
            gpus=[{"gpu_id": "0", "gpu_uuid": "GPU-0", "pci_bus_id": "0000:01:00.0"}],
            nics=[{"netdev": "eth0", "pci_bus_id": "0000:01:00.1"}],
            rdma_devices=[{"device": "mlx5_0", "pci_bus_id": "0000:01:00.1"}],
            rdma_links=[{"rdma_device": "mlx5_0", "port": 1, "netdev": "eth0", "link_layer": "InfiniBand"}],
            gpu_nic_matrix={"matrix": {"0": {"eth0": "PIX"}}},
            sysfs_root=str(root),
        )
    finally:
        monkeypatch.setattr(PhysicalFabricTopology, "pci_hierarchy", original)

    assert result["verified"] is True
    assert result["network_domain_membership_not_used_as_physical_proof"] is True
    path = result["paths"][0]
    assert path["gpu_uuid"] == "GPU-0"
    assert path["nic"] == "eth0"
    assert path["rdma_links"][0]["rdma_device"] == "mlx5_0"
