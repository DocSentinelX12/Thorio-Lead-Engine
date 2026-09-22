                "probe": probe,
                "network_transport": probe.get("network_transport"),
                "gpu_direct_rdma": probe.get("gpu_direct_rdma"),
                "network_evidence_lines": list(probe.get("network_evidence_lines") or ()),
                "peer_connections": list(probe.get("peer_connections") or ()),
                "rdma_devices": list(path_evidence.get("rdma_devices") or ()),
                "verified_rdma_devices": list(path_evidence.get("verified_rdma_devices") or ()),
                "hca_selections": list(path_evidence.get("hca_selections") or ()),
                "verified_hca_selections": list(path_evidence.get("verified_hca_selections") or ()),
                "verified_rdma_links": list(path_evidence.get("verified_rdma_links") or ()),
                "gpu_nic_locality": path_evidence.get("gpu_nic_locality"),
                "stdout": stdout[-4000:],
            })

        if failures:
            raise NvidiaRuntimeError("distributed NCCL launch failed: " + "; ".join(failures))

        if len(process_evidence) != len(normalized_bindings):
            raise NvidiaRuntimeError(
                f"distributed NCCL execution produced {len(process_evidence)} verified local ranks; expected {len(normalized_bindings)}"
            )

        evidence = {
            "verified": True,
            "backend": "nccl",
            "collective": "all_reduce",
            "local_runtime": local,
            "gpu_identity": gpu_identity,
            "gpu_bindings": normalized_bindings,
            "process_evidence": process_evidence,
            "attempt_id": attempt_id,
            "generation": generation,
            "worker_id": client.worker_id,
            "node_rank": int(participant["node_rank"]),
            "world_size": world_size,
            "nnodes": int(plan["nnodes"]),
            "command": list(command),
            "rendezvous_endpoint": plan["rendezvous_endpoint"],
        }
