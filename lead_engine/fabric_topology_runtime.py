"""Runtime integration for physical GPU/NIC/RDMA topology evidence.

This adapter consumes the existing NVIDIA provider snapshot and upgrades it
with an independently observed physical topology graph. It never treats an
IP subnet, NUMA node, or software allocation as physical fabric proof.
"""
from __future__ import annotations

from typing import Any, Mapping

from .fabric_topology import FabricTopologyError, PhysicalFabricTopology


class FabricTopologyRuntimeError(RuntimeError):
    """Raised when runtime topology evidence cannot be reconciled."""


def verify_provider_snapshot(snapshot: Any, *, runner=None) -> dict[str, object]:
    evidence = getattr(snapshot, "evidence", None)
    nodes = getattr(snapshot, "nodes", None)
    if not isinstance(evidence, Mapping) or not isinstance(nodes, tuple) or not nodes:
        raise FabricTopologyRuntimeError("NVIDIA provider snapshot is missing node/evidence data")
    network = evidence.get("network")
    if not isinstance(network, Mapping):
        raise FabricTopologyRuntimeError("NVIDIA provider snapshot is missing network evidence")
    node = nodes[0]
    gpus = []
    for gpu in getattr(node, "gpus", ()):
        gpus.append({
            "gpu_id": getattr(gpu, "gpu_id", None),
            "gpu_uuid": getattr(gpu, "gpu_uuid", None),
            "pci_bus_id": getattr(gpu, "pci_bus_id", None),
        })
    if not gpus:
        raise FabricTopologyRuntimeError("NVIDIA provider snapshot contains no physical GPUs")
    link_capabilities = network.get("link_capabilities")
    if not isinstance(link_capabilities, Mapping):
        raise FabricTopologyRuntimeError("network evidence contains no NIC physical inventory")
    nics = []
    for name, raw in sorted(link_capabilities.items(), key=lambda item: str(item[0])):
        if not isinstance(raw, Mapping):
            continue
        pci_bus_id = str(raw.get("bus_info") or "").strip()
        if not pci_bus_id:
            continue
        nics.append({"netdev": str(name), "pci_bus_id": pci_bus_id})
    rdma = network.get("rdma")
    if not isinstance(rdma, Mapping):
        raise FabricTopologyRuntimeError("network evidence contains no RDMA inventory")
    rdma_devices = rdma.get("devices")
    rdma_links = rdma.get("links")
    if not isinstance(rdma_devices, list) or not isinstance(rdma_links, list):
        raise FabricTopologyRuntimeError("RDMA evidence is incomplete")

    topology = PhysicalFabricTopology(runner=runner).discover()
    gpu_nic_topology = topology.get("gpu_nic_topology")
    if not isinstance(gpu_nic_topology, Mapping):
        raise FabricTopologyRuntimeError("physical GPU-NIC topology discovery returned no matrix")
    try:
        graph = PhysicalFabricTopology.reconcile(
            gpus=gpus,
            nics=nics,
            rdma_devices=rdma_devices,
            rdma_links=rdma_links,
            gpu_nic_matrix=gpu_nic_topology,
        )
    except FabricTopologyError as exc:
        raise FabricTopologyRuntimeError(str(exc)) from exc

    physical_fabric = evidence.get("physical_fabric")
    if isinstance(physical_fabric, Mapping):
        components = physical_fabric.get("components")
        relationships = physical_fabric.get("relationships")
        if not isinstance(components, list):
            components = []
        if not isinstance(relationships, list):
            relationships = []
    else:
        components = []
        relationships = []

    if not components:
        component_by_identity: dict[str, dict[str, object]] = {}

        def add_component(component_type: str, identity: str, node_id: str) -> None:
            if not identity or not node_id:
                return
            component_by_identity.setdefault(
                identity,
                {
                    "component_type": component_type,
                    "identity": identity,
                    "node_id": node_id,
                },
            )

        for gpu in gpus:
            add_component("gpu", f"gpu:{gpu['gpu_uuid']}", str(node.node_id))
            add_component("pci", f"pci:{gpu['pci_bus_id']}", str(node.node_id))
            relationships.append({
                "relationship_type": "gpu_to_pci",
                "source": f"gpu:{gpu['gpu_uuid']}",
                "target": f"pci:{gpu['pci_bus_id']}",
                "evidence": {"source": "provider_gpu_pci_identity"},
            })
        for nic in nics:
            add_component("nic", f"nic:{nic['netdev']}", str(node.node_id))
            add_component("pci", f"pci:{nic['pci_bus_id']}", str(node.node_id))
            relationships.append({
                "relationship_type": "nic_to_pci",
                "source": f"nic:{nic['netdev']}",
                "target": f"pci:{nic['pci_bus_id']}",
                "evidence": {"source": "provider_nic_pci_identity"},
            })
        for device in rdma_devices:
            rdma_name = str(device.get("device") or "").strip()
            if not rdma_name:
                continue
            add_component("rdma_device", f"rdma:{rdma_name}", str(node.node_id))
            pci_bus_id = str(device.get("pci_bus_id") or "").strip()
            if pci_bus_id:
                add_component("pci", f"pci:{pci_bus_id}", str(node.node_id))
                relationships.append({
                    "relationship_type": "rdma_device_to_pci",
                    "source": f"rdma:{rdma_name}",
                    "target": f"pci:{pci_bus_id}",
                    "evidence": {"source": "provider_rdma_pci_identity"},
                })
        for link in rdma_links:
            rdma_name = str(link.get("rdma_device") or "").strip()
            port = link.get("port")
            if not rdma_name or port is None:
                continue
            port_identity = f"rdma:{rdma_name}:{port}"
            add_component("rdma_port", port_identity, str(node.node_id))
            relationships.append({
                "relationship_type": "rdma_device_to_port",
                "source": f"rdma:{rdma_name}",
                "target": port_identity,
                "evidence": {
                    "source": "provider_rdma_link",
                    "link_layer": link.get("link_layer"),
                },
            })

        for path in graph["paths"]:
            gpu_identity = f"gpu:{path['gpu_uuid']}"
            nic_identity = f"nic:{path['nic']}"
            relationships.append({
                "relationship_type": "gpu_to_nic",
                "source": gpu_identity,
                "target": nic_identity,
                "evidence": {
                    "source": "nvidia-smi topo -nic",
                    "distance": path["gpu_nic_distance"],
                },
            })
            for link in path["rdma_links"]:
                rdma_name = str(link.get("rdma_device") or "").strip()
                if not rdma_name:
                    continue
                relationships.append({
                    "relationship_type": "nic_to_rdma_device",
                    "source": nic_identity,
                    "target": f"rdma:{rdma_name}",
                    "evidence": {
                        "source": "rdma-pci-identity",
                        "pci_bus_id": path["nic_pci_bus_id"],
                    },
                })
        components = list(component_by_identity.values())

    locality_graph = PhysicalFabricTopology.build_locality_graph(
        components=components,
        relationships=relationships,
    )
    return {
        "verified": True,
        "graph": graph,
        "locality_graph": locality_graph,
        "gpu_nic_topology": gpu_nic_topology,
        "pci_inventory": topology.get("pci_inventory", ()),
        "evidence_sources": topology.get("evidence_sources", ()),
    }
