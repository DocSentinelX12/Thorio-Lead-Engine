from __future__ import annotations

from lead_engine.fabric_topology import PhysicalFabricTopology


def test_locality_graph_requires_explicit_identity_correlation() -> None:
    graph = PhysicalFabricTopology.build_locality_graph(
        components=[
            {"component_type": "gpu", "identity": "gpu:GPU-0", "node_id": "node-a"},
            {"component_type": "nic", "identity": "nic:mlx5_0", "node_id": "node-a"},
        ],
        relationships=[
            {
                "relationship_type": "gpu_to_nic",
                "source": "gpu:GPU-0",
                "target": "nic:mlx5_0",
                "evidence": {"source": "nvidia-smi topo -nic", "distance": "PIX"},
            }
        ],
    )

    assert graph["edges"][0]["source"] == "gpu:GPU-0"
    assert graph["edges"][0]["target"] == "nic:mlx5_0"
    assert graph["edges"][0]["state"] == "known"
    assert graph["edges"][0]["evidence"][0]["distance"] == "PIX"


def test_missing_pcie_and_numa_relationships_remain_unknown() -> None:
    graph = PhysicalFabricTopology.build_locality_graph(
        components=[
            {"component_type": "gpu", "identity": "gpu:GPU-0", "node_id": "node-a"},
            {"component_type": "pci", "identity": "pci:0000:3b:00.0", "node_id": "node-a"},
            {"component_type": "numa", "identity": "numa:0", "node_id": "node-a"},
        ],
        relationships=[],
    )

    unknown = {(edge["source"], edge["target"], edge["relationship_type"]) for edge in graph["edges"] if edge["state"] == "unknown"}
    assert ("gpu:GPU-0", "pci:0000:3b:00.0", "gpu_to_pci") in unknown
    assert ("gpu:GPU-0", "numa:0", "gpu_to_numa") in unknown


def test_same_node_coexistence_does_not_create_locality() -> None:
    graph = PhysicalFabricTopology.build_locality_graph(
        components=[
            {"component_type": "gpu", "identity": "gpu:GPU-0", "node_id": "node-a"},
            {"component_type": "nic", "identity": "nic:mlx5_0", "node_id": "node-a"},
        ],
        relationships=[],
    )

    assert not any(
        edge["source"] == "gpu:GPU-0"
        and edge["target"] == "nic:mlx5_0"
        and edge["state"] == "known"
        for edge in graph["edges"]
    )


def test_multiple_nics_and_rdma_ports_are_all_preserved() -> None:
    graph = PhysicalFabricTopology.build_locality_graph(
        components=[
            {"component_type": "gpu", "identity": "gpu:GPU-0", "node_id": "node-a"},
            {"component_type": "nic", "identity": "nic:mlx5_0", "node_id": "node-a"},
            {"component_type": "nic", "identity": "nic:mlx5_1", "node_id": "node-a"},
            {"component_type": "rdma_device", "identity": "rdma:mlx5_0", "node_id": "node-a"},
            {"component_type": "rdma_device", "identity": "rdma:mlx5_1", "node_id": "node-a"},
            {"component_type": "rdma_port", "identity": "rdma:mlx5_0:1", "node_id": "node-a"},
            {"component_type": "rdma_port", "identity": "rdma:mlx5_1:1", "node_id": "node-a"},
        ],
        relationships=[
            {"relationship_type": "gpu_to_nic", "source": "gpu:GPU-0", "target": "nic:mlx5_0"},
            {"relationship_type": "gpu_to_nic", "source": "gpu:GPU-0", "target": "nic:mlx5_1"},
            {"relationship_type": "nic_to_rdma_device", "source": "nic:mlx5_0", "target": "rdma:mlx5_0"},
            {"relationship_type": "nic_to_rdma_device", "source": "nic:mlx5_1", "target": "rdma:mlx5_1"},
            {"relationship_type": "rdma_device_to_port", "source": "rdma:mlx5_0", "target": "rdma:mlx5_0:1"},
            {"relationship_type": "rdma_device_to_port", "source": "rdma:mlx5_1", "target": "rdma:mlx5_1:1"},
        ],
    )

    known = [edge for edge in graph["edges"] if edge["state"] == "known"]
    assert len(known) == 6
    assert {edge["target"] for edge in known} >= {
        "nic:mlx5_0", "nic:mlx5_1", "rdma:mlx5_0", "rdma:mlx5_1",
        "rdma:mlx5_0:1", "rdma:mlx5_1:1",
    }


def test_conflicting_locality_is_not_promoted_to_known() -> None:
    graph = PhysicalFabricTopology.build_locality_graph(
        components=[
            {"component_type": "gpu", "identity": "gpu:GPU-0", "node_id": "node-a"},
            {"component_type": "nic", "identity": "nic:mlx5_0", "node_id": "node-a"},
        ],
        relationships=[
            {
                "relationship_type": "gpu_to_nic",
                "source": "gpu:GPU-0",
                "target": "nic:mlx5_0",
                "state": "known",
                "evidence": {"source": "probe-a", "distance": "PIX"},
            },
            {
                "relationship_type": "gpu_to_nic",
                "source": "gpu:GPU-0",
                "target": "nic:mlx5_0",
                "state": "known",
                "evidence": {"source": "probe-b", "distance": "SYS"},
            },
        ],
    )

    edge = graph["edges"][0]
    assert edge["state"] == "conflict"
    assert len(edge["evidence"]) == 2


def test_reconciliation_is_deterministic() -> None:
    components = [
        {"component_type": "nic", "identity": "nic:mlx5_1", "node_id": "node-a"},
        {"component_type": "gpu", "identity": "gpu:GPU-0", "node_id": "node-a"},
        {"component_type": "rdma_device", "identity": "rdma:mlx5_1", "node_id": "node-a"},
    ]
    relationships = [
        {"relationship_type": "nic_to_rdma_device", "source": "nic:mlx5_1", "target": "rdma:mlx5_1"},
        {"relationship_type": "gpu_to_nic", "source": "gpu:GPU-0", "target": "nic:mlx5_1"},
    ]

    first = PhysicalFabricTopology.build_locality_graph(
        components=components, relationships=relationships
    )
    second = PhysicalFabricTopology.build_locality_graph(
        components=list(reversed(components)),
        relationships=list(reversed(relationships)),
    )

    assert first == second


def test_runtime_exposes_the_same_canonical_locality_graph(monkeypatch) -> None:
    from types import SimpleNamespace

    from lead_engine.fabric_topology import PhysicalFabricTopology
    from lead_engine.fabric_topology_runtime import verify_provider_snapshot

    node = SimpleNamespace(
        node_id="node-a",
        gpus=(
            SimpleNamespace(
                gpu_id="0",
                gpu_uuid="GPU-0",
                pci_bus_id="0000:01:00.0",
            ),
        ),
    )
    snapshot = SimpleNamespace(
        nodes=(node,),
        evidence={
            "network": {
                "link_capabilities": {
                    "eth0": {"bus_info": "0000:01:00.1"},
                },
                "rdma": {
                    "devices": [{"device": "mlx5_0", "pci_bus_id": "0000:01:00.1"}],
                    "links": [
                        {
                            "rdma_device": "mlx5_0",
                            "port": 1,
                            "netdev": "eth0",
                            "link_layer": "InfiniBand",
                        }
                    ],
                },
            }
        },
    )

    monkeypatch.setattr(
        PhysicalFabricTopology,
        "discover",
        lambda self: {
            "gpu_nic_topology": {
                "matrix": {"0": {"eth0": "PIX"}},
            },
            "pci_inventory": (),
            "evidence_sources": (),
        },
    )
    monkeypatch.setattr(
        PhysicalFabricTopology,
        "reconcile",
        staticmethod(
            lambda **kwargs: {
                "paths": [
                    {
                        "gpu_uuid": "GPU-0",
                        "nic": "eth0",
                        "gpu_nic_distance": "PIX",
                        "nic_pci_bus_id": "0000:01:00.1",
                        "rdma_links": [
                            {
                                "rdma_device": "mlx5_0",
                                "port": 1,
                                "link_layer": "InfiniBand",
                            }
                        ],
                    }
                ]
            }
        ),
    )

    result = verify_provider_snapshot(snapshot)
    edges = result["locality_graph"]["edges"]

    assert any(
        edge["relationship_type"] == "gpu_to_nic"
        and edge["state"] == "known"
        for edge in edges
    )
    assert any(
        edge["relationship_type"] == "rdma_device_to_port"
        and edge["state"] == "known"
        for edge in edges
    )
