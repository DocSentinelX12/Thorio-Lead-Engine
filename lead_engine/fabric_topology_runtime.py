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
    return {
        "verified": True,
        "graph": graph,
        "gpu_nic_topology": gpu_nic_topology,
        "pci_inventory": topology.get("pci_inventory", ()),
        "evidence_sources": topology.get("evidence_sources", ()),
    }
