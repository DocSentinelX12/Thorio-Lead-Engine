"""Physical GPU-to-NIC topology evidence.

This module builds a host-local topology graph from independent kernel/NVIDIA
observations. It deliberately distinguishes physical locality evidence from
network-domain membership and never treats NUMA or subnet membership as proof
of a usable GPU-to-RDMA path.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


class FabricTopologyError(RuntimeError):
    """Raised when physical topology evidence is missing or contradictory."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], float], CommandResult]


_PCI_BDF = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\\.[0-7]$", re.I)


class PhysicalFabricTopology:
    """Discover and reconcile physical GPU, PCIe, NIC and RDMA relationships."""

    def __init__(self, *, timeout_seconds: float = 10.0, runner: Runner | None = None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self._runner = runner or self._run

    @staticmethod
    def _run(args: Sequence[str], timeout_seconds: float) -> CommandResult:
        try:
            result = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout_seconds, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FabricTopologyError(f"physical topology probe failed for {args[0]}: {exc}") from exc
        return CommandResult(result.returncode, result.stdout, result.stderr)

    def _exec(self, args: Sequence[str]) -> str:
        result = self._runner(args, self.timeout_seconds)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().replace("\\n", " ")
            raise FabricTopologyError(f"{' '.join(args)} failed ({result.returncode}): {detail[:1000]}")
        return result.stdout

    @staticmethod
    def _normalize_bdf(value: object) -> str:
        text = str(value or "").strip().lower()
        if not _PCI_BDF.fullmatch(text):
            raise FabricTopologyError(f"invalid PCI BDF: {value!r}")
        return text

    @classmethod
    def pci_hierarchy(cls, pci_bus_id: str, *, sysfs_root: str = "/sys/bus/pci/devices") -> tuple[str, ...]:
        bdf = cls._normalize_bdf(pci_bus_id)
        device = Path(sysfs_root) / bdf
        try:
            resolved = device.resolve(strict=True)
        except OSError as exc:
            raise FabricTopologyError(f"PCI device {bdf} is not present in sysfs") from exc
        hierarchy: list[str] = []
        current = resolved
        while current != current.parent:
            if _PCI_BDF.fullmatch(current.name.lower()):
                hierarchy.append(current.name.lower())
            current = current.parent
        if not hierarchy or hierarchy[0] != bdf:
            raise FabricTopologyError(f"PCI hierarchy for {bdf} is incomplete")
        return tuple(hierarchy)

    @classmethod
    def common_pci_ancestor(cls, left: str, right: str, *, sysfs_root: str = "/sys/bus/pci/devices") -> str:
        left_path = cls.pci_hierarchy(left, sysfs_root=sysfs_root)
        right_set = set(cls.pci_hierarchy(right, sysfs_root=sysfs_root))
        for bdf in left_path:
            if bdf in right_set:
                return bdf
        raise FabricTopologyError(f"GPU/NIC PCI paths {left} and {right} have no common PCI ancestor")

    @staticmethod
    def parse_gpu_nic_matrix(text: str) -> dict[str, object]:
        """Parse ``nvidia-smi topo -nic`` without turning affinity into connectivity.

        NVIDIA documents this matrix as the GPU-NIC connectivity view and
        exposes NIC identity as ibdev/netdev/PCI/SLOT in the enhanced legend.
        The parser requires every GPU row and every declared NIC column.
        """
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        if not lines:
            raise FabricTopologyError("GPU-NIC topology output is empty")
        header_index = next((i for i, line in enumerate(lines) if re.search(r"\\bGPU\\d+\\b", line)), None)
        if header_index is None:
            raise FabricTopologyError("GPU-NIC topology header is missing")
        header = lines[header_index].split()
        gpu_columns = [token[3:] for token in header if re.fullmatch(r"GPU\\d+", token)]
        if not gpu_columns:
            raise FabricTopologyError("GPU-NIC topology contains no GPU columns")
        rows: dict[str, list[str]] = {}
        for line in lines[header_index + 1:]:
            tokens = line.split()
            if not tokens or not re.fullmatch(r"GPU\\d+", tokens[0]):
                continue
            gpu_id = tokens[0][3:]
            if gpu_id in rows:
                raise FabricTopologyError(f"duplicate GPU-NIC row: GPU{gpu_id}")
            rows[gpu_id] = tokens[1:]
        if set(rows) != set(gpu_columns):
            raise FabricTopologyError(f"GPU-NIC topology rows are incomplete: expected {gpu_columns}, got {sorted(rows)}")
        if any(len(values) < len(gpu_columns) for values in rows.values()):
            raise FabricTopologyError("GPU-NIC topology row is shorter than the GPU matrix")
        matrix = {gpu: dict(zip(gpu_columns, rows[gpu][:len(gpu_columns)], strict=True)) for gpu in gpu_columns}
        legend = []
        for line in lines[header_index + 1:]:
            if re.search(r"\\bibdev\\b", line, re.I) or re.search(r"\\bnetdev\\b", line, re.I):
                legend.append(line.strip())
        return {"source": "nvidia-smi topo -nic", "gpu_ids": gpu_columns, "matrix": matrix, "legend": tuple(legend)}

    @staticmethod
    def parse_pci_inventory(text: str) -> list[dict[str, str]]:
        """Parse ``lspci -D -nn`` into stable PCI endpoint identities."""
        inventory: list[dict[str, str]] = []
        pattern = re.compile(r"^([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\\.[0-7])\\s+(.+)$")
        for line in text.splitlines():
            match = pattern.match(line.strip())
            if not match:
                continue
            bdf, description = match.groups()
            inventory.append({"pci_bus_id": bdf.lower(), "description": description.strip()})
        return inventory

    @staticmethod
    def reconcile(
        *,
        gpus: Sequence[Mapping[str, object]],
        nics: Sequence[Mapping[str, object]],
        rdma_devices: Sequence[Mapping[str, object]],
        rdma_links: Sequence[Mapping[str, object]],
        gpu_nic_matrix: Mapping[str, object],
        sysfs_root: str = "/sys/bus/pci/devices",
    ) -> dict[str, object]:
        if not gpus:
            raise FabricTopologyError("physical topology requires at least one GPU")
        if not nics:
            raise FabricTopologyError("physical topology requires at least one NIC")
        matrix = gpu_nic_matrix.get("matrix")
        if not isinstance(matrix, Mapping):
            raise FabricTopologyError("GPU-NIC topology matrix is missing")
        nic_by_name = {str(item.get("netdev") or item.get("name") or "").strip(): item for item in nics if isinstance(item, Mapping)}
        if not nic_by_name or "" in nic_by_name:
            raise FabricTopologyError("NIC inventory contains an invalid identity")
        rdma_by_device = {str(item.get("device") or "").strip(): item for item in rdma_devices if isinstance(item, Mapping)}
        if len(rdma_by_device) != len([item for item in rdma_devices if isinstance(item, Mapping)]):
            raise FabricTopologyError("RDMA inventory contains duplicate device identities")
        links_by_device: dict[str, list[Mapping[str, object]]] = {}
        for link in rdma_links:
            if not isinstance(link, Mapping):
                continue
            device = str(link.get("rdma_device") or "").strip()
            if device:
                links_by_device.setdefault(device, []).append(link)

        paths: list[dict[str, object]] = []
        for gpu in gpus:
            gpu_uuid = str(gpu.get("gpu_uuid") or "").strip()
            gpu_bdf = PhysicalFabricTopology._normalize_bdf(gpu.get("pci_bus_id"))
            gpu_id = str(gpu.get("gpu_id") or "").strip()
            if not gpu_uuid or not gpu_id:
                raise FabricTopologyError("GPU inventory is missing immutable identity")
            row = matrix.get(gpu_id)
            if not isinstance(row, Mapping):
                raise FabricTopologyError(f"GPU-NIC topology has no row for GPU {gpu_id}")
            gpu_paths: list[dict[str, object]] = []
            for nic_name, nic in sorted(nic_by_name.items()):
                nic_bdf = PhysicalFabricTopology._normalize_bdf(nic.get("pci_bus_id"))
                relationship = str(row.get(nic_name) or "").strip()
                if not relationship:
                    continue
                ancestor = PhysicalFabricTopology.common_pci_ancestor(gpu_bdf, nic_bdf, sysfs_root=sysfs_root)
                nic_rdma = []
                for device, device_links in links_by_device.items():
                    if device not in rdma_by_device:
                        continue
                    device_pci = str(rdma_by_device[device].get("pci_bus_id") or "").strip().lower()
                    if device_pci and device_pci == nic_bdf:
                        nic_rdma.extend(device_links)
                gpu_paths.append({
                    "gpu_uuid": gpu_uuid,
                    "gpu_pci_bus_id": gpu_bdf,
                    "nic": nic_name,
                    "nic_pci_bus_id": nic_bdf,
                    "gpu_nic_distance": relationship,
                    "shared_pci_ancestor": ancestor,
                    "rdma_links": [dict(link) for link in nic_rdma],
                    "physical_evidence": ("nvidia-smi topo -nic", "sysfs-pci"),
                })
            if not gpu_paths:
                raise FabricTopologyError(f"GPU {gpu_uuid} has no verified NIC relationship")
            paths.extend(gpu_paths)

        return {
            "verified": True,
            "evidence_class": "physical_gpu_nic_rdma_topology",
            "gpu_count": len(gpus),
            "nic_count": len(nic_by_name),
            "rdma_device_count": len(rdma_by_device),
            "paths": paths,
            "network_domain_membership_not_used_as_physical_proof": True,
        }

    @staticmethod
    def build_locality_graph(
        *,
        components: Sequence[Mapping[str, object]],
        relationships: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        """Build a deterministic evidence-backed physical locality graph."""
        component_records: dict[str, dict[str, object]] = {}
        for raw in components:
            if not isinstance(raw, Mapping):
                continue
            identity = str(raw.get("identity") or "").strip()
            component_type = str(raw.get("component_type") or "").strip()
            node_id = str(raw.get("node_id") or "").strip()
            if not identity or not component_type or not node_id:
                continue
            candidate = {
                "identity": identity,
                "component_type": component_type,
                "node_id": node_id,
            }
            existing = component_records.get(identity)
            if existing is None:
                component_records[identity] = candidate
            elif existing != candidate:
                component_records[identity] = {
                    "identity": identity,
                    "component_type": "conflict",
                    "node_id": "",
                }

        observations: dict[tuple[str, str, str], list[dict[str, object]]] = {}
        for raw in relationships:
            if not isinstance(raw, Mapping):
                continue
            relationship_type = str(raw.get("relationship_type") or "").strip()
            source = str(raw.get("source") or "").strip()
            target = str(raw.get("target") or "").strip()
            if not relationship_type or not source or not target:
                continue
            source_record = component_records.get(source)
            target_record = component_records.get(target)
            if source_record is None or target_record is None:
                state = "unknown"
                reason = "endpoint identity is not present in canonical physical inventory"
            elif source_record["component_type"] == "conflict" or target_record["component_type"] == "conflict":
                state = "conflict"
                reason = "component identity has contradictory physical observations"
            else:
                requested_state = str(raw.get("state") or "known").strip().lower()
                state = requested_state if requested_state in {"known", "unknown", "conflict"} else "unknown"
                reason = str(raw.get("reason") or "").strip()
            evidence = raw.get("evidence")
            evidence_record = dict(evidence) if isinstance(evidence, Mapping) else {}
            if reason:
                evidence_record.setdefault("reason", reason)
            key = (relationship_type, source, target)
            observations.setdefault(key, []).append({
                "state": state,
                "evidence": evidence_record,
            })

        edges: list[dict[str, object]] = []
        component_types = {
            identity: record["component_type"]
            for identity, record in component_records.items()
            if record["component_type"] != "conflict"
        }
        for (relationship_type, source, target), items in observations.items():
            known = [item for item in items if item["state"] == "known"]
            unique_evidence = {
                json.dumps(item["evidence"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for item in known
            }
            if any(item["state"] == "conflict" for item in items) or len(unique_evidence) > 1:
                state = "conflict"
            elif known:
                state = "known"
            else:
                state = "unknown"
            evidence = []
            seen_evidence: set[str] = set()
            for item in sorted(
                items,
                key=lambda item: json.dumps(item["evidence"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ):
                encoded = json.dumps(item["evidence"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if encoded in seen_evidence:
                    continue
                seen_evidence.add(encoded)
                evidence.append(dict(item["evidence"]))
            edges.append({
                "relationship_type": relationship_type,
                "source": source,
                "target": target,
                "source_component_type": component_types.get(source),
                "target_component_type": component_types.get(target),
                "state": state,
                "evidence": evidence,
            })

        expected_relationships = (
            ("gpu", "pci", "gpu_to_pci"),
            ("gpu", "numa", "gpu_to_numa"),
            ("gpu", "nic", "gpu_to_nic"),
            ("nic", "pci", "nic_to_pci"),
            ("nic", "rdma_device", "nic_to_rdma_device"),
            ("rdma_device", "rdma_port", "rdma_device_to_port"),
        )
        known_keys = {(edge["relationship_type"], edge["source"], edge["target"]) for edge in edges}
        identities = sorted(component_records)
        for source_type, target_type, relationship_type in expected_relationships:
            sources = [identity for identity in identities if component_records[identity]["component_type"] == source_type]
            targets = [identity for identity in identities if component_records[identity]["component_type"] == target_type]
            for source in sources:
                for target in targets:
                    if source == target:
                        continue
                    key = (relationship_type, source, target)
                    if key in known_keys:
                        continue
                    if component_records[source]["node_id"] != component_records[target]["node_id"]:
                        continue
                    edges.append({
                        "relationship_type": relationship_type,
                        "source": source,
                        "target": target,
                        "source_component_type": source_type,
                        "target_component_type": target_type,
                        "state": "unknown",
                        "evidence": [],
                    })

        edges.sort(key=lambda edge: (
            str(edge["relationship_type"]),
            str(edge["source"]),
            str(edge["target"]),
        ))
        return {
            "schema_version": 1,
            "provider_neutral": True,
            "components": [component_records[identity] for identity in sorted(component_records)],
            "edges": edges,
        }

    def discover(self) -> dict[str, object]:
        gpu_nic = self._exec(("nvidia-smi", "topo", "-nic"))
        pci_inventory = self.parse_pci_inventory(self._exec(("lspci", "-D", "-nn")))
        return {
            "gpu_nic_topology": self.parse_gpu_nic_matrix(gpu_nic),
            "pci_inventory": pci_inventory,
            "evidence_sources": ("nvidia-smi topo -nic", "lspci -D -nn", "sysfs-pci"),
        }
