from __future__ import annotations

from lead_engine.nvidia_provider import NvidiaProvider
from lead_engine.compute_resources import GpuResource, ResourceState


def _gpus() -> tuple[GpuResource, ...]:
    return (
        GpuResource(
            node_id="node-a",
            gpu_id="0",
            gpu_uuid="GPU-0",
            vram_bytes=80 * 1024**3,
            pci_bus_id="0000:3b:00.0",
            numa_node=0,
            health_state=ResourceState.HEALTHY,
            availability_state=ResourceState.AVAILABLE,
        ),
        GpuResource(
            node_id="node-a",
            gpu_id="1",
            gpu_uuid="GPU-1",
            vram_bytes=80 * 1024**3,
            pci_bus_id="0000:5e:00.0",
            numa_node=0,
            health_state=ResourceState.HEALTHY,
            availability_state=ResourceState.AVAILABLE,
        ),
    )


def test_nvlink_status_parser_preserves_current_per_link_state_and_bandwidth() -> None:
    output = """GPU 0: NVIDIA H100 (UUID: GPU-0)
 Link 0: 26.562 GB/s
 Link 1: <inactive>
GPU 1: NVIDIA H100 (UUID: GPU-1)
 Link 0: 26.562 GB/s
 Link 1: 25 GB/s
"""
    parsed = NvidiaProvider._parse_nvlink_status(output, _gpus())

    assert parsed["source"] == "nvidia-smi nvlink --status"
    assert parsed["available"] is True
    assert parsed["links"] == [
        {"gpu_id": "0", "gpu_uuid": "GPU-0", "link_id": 0, "state": "active", "bandwidth_gbps": 26.562},
        {"gpu_id": "0", "gpu_uuid": "GPU-0", "link_id": 1, "state": "inactive", "bandwidth_gbps": None},
        {"gpu_id": "1", "gpu_uuid": "GPU-1", "link_id": 0, "state": "active", "bandwidth_gbps": 26.562},
        {"gpu_id": "1", "gpu_uuid": "GPU-1", "link_id": 1, "state": "active", "bandwidth_gbps": 25.0},
    ]


def test_physical_fabric_evidence_records_provenance_and_conflicts_without_overwriting_truth() -> None:
    network = {
        "link_capabilities": {
            "eth0": {"bus_info": "0000:3b:00.1", "speed_mbps": 400000},
        },
        "gpu_nic_locality": [
            {
                "gpu_uuid": "GPU-0",
                "gpu_pci_bus_id": "0000:3b:00.0",
                "nic": "eth0",
                "nic_pci_bus_id": "0000:3b:00.1",
                "gpu_numa_node": 0,
                "nic_numa_node": 0,
                "same_numa_node": True,
                "shared_pci_ancestor": "0000:3b:00.0",
                "source": "sysfs",
            }
        ],
        "rdma": {
            "devices": [{"device": "mlx5_0", "pci_bus_id": "0000:3b:00.1", "state": "ACTIVE"}],
            "links": [
                {
                    "rdma_device": "mlx5_0",
                    "port": 1,
                    "netdev": "eth0",
                    "pci_bus_id": "0000:3b:00.1",
                    "state": "ACTIVE",
                    "physical_state": "LINK_UP",
                    "link_layer": "Ethernet",
                    "gids": ["fe80::1"],
                }
            ],
        },
        "physical_fabric": {},
    }
    host_physical = {
        "pci": {
            "devices": [
                {"bus_id": "0000:3b:00.0", "numa_node": 1},
                {"bus_id": "0000:3b:00.1", "numa_node": 0},
            ]
        }
    }
    nvlink_status = {
        "source": "nvidia-smi nvlink --status",
        "available": True,
        "links": [
            {"gpu_id": "0", "gpu_uuid": "GPU-0", "link_id": 0, "state": "active", "bandwidth_gbps": 26.562}
        ],
    }

    evidence = NvidiaProvider._physical_fabric_evidence(
        node_id="node-a",
        gpus=_gpus(),
        network=network,
        observed_at=123.0,
        host_physical=host_physical,
        nvlink_status=nvlink_status,
    )

    gpu = next(item for item in evidence["components"] if item["identity"] == "gpu:GPU-0")
    assert gpu["evidence"]["source"] == "nvidia-smi"
    assert gpu["evidence"]["observed_at"] == 123.0
    assert gpu["evidence"]["confidence"] == "direct_observation"

    assert any(item["relationship_type"] == "gpu_to_nic" for item in evidence["relationships"])
    assert any(item["relationship_type"] == "gpu_nvlink" for item in evidence["relationships"])
    assert any(item["relationship_type"] == "nic_to_rdma_device" for item in evidence["relationships"])

    assert evidence["contradictions"] == [
        {
            "identity": "gpu:GPU-0",
            "field": "numa_node",
            "values": [
                {"source": "nvidia-smi", "value": 0},
                {"source": "sysfs", "value": 1},
            ],
        }
    ]
