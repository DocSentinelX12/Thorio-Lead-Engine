        routes = evidence.get("adaptive_routes") if isinstance(evidence, dict) else None
        if not isinstance(routes, (list, tuple)):
            return ()
        source, destination = (str(value).strip() for value in gpu_pair)
        return tuple(
            str(route.get("path_id")).strip()
            for route in routes
            if isinstance(route, dict)
            and str(route.get("source_gpu") or "").strip() == source
            and str(route.get("destination_gpu") or "").strip() == destination
            and str(route.get("path_id") or "").strip()
        )

    @staticmethod
    def _planned_physical_path(resource: dict[str, Any], gpu_uuid: str) -> dict[str, Any] | None:
        paths = ComputeScheduler._verified_gpu_nic_rdma_path(resource, gpu_uuid)
        if not paths:
            return None
        path = dict(paths[0])
        link = path.pop("verified_rdma_link", None)
        if isinstance(link, dict):
            path.update({
                "rdma_pci_bus_id": link.get("pci_bus_id"),
                "rdma_link_state": link.get("state"),
                "rdma_physical_state": link.get("physical_state"),
            })
        return {
            "node_id": str(resource.get("node_id") or "").strip(),
            "gpu_uuid": gpu_uuid,
            "nic": path.get("nic"),
            "nic_pci_bus_id": path.get("nic_pci_bus_id"),
            "rdma_device": path.get("rdma_device"),
            "rdma_port": path.get("rdma_port"),
            "rdma_pci_bus_id": path.get("rdma_pci_bus_id"),
            "link_layer": path.get("link_layer"),
            "gpu_nic_distance": path.get("gpu_nic_distance"),
            "shared_pci_ancestor": path.get("shared_pci_ancestor"),
            "rdma_link_state": path.get("rdma_link_state"),
            "rdma_physical_state": path.get("rdma_physical_state"),
            "physical_evidence": path.get("physical_evidence"),
        }
    def fabric_launch_plan(self, attempt_id: str, rendezvous_endpoint: str) -> Dict[str, Any]:
        """Build the exact per-process launch contract from durable physical participants.

        Each allocated GPU becomes exactly one distributed process. Global ranks
        are assigned deterministically from the durable participant order, so