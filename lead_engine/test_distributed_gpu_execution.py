import json

import pytest

from lead_engine.compute_worker import ComputeWorkerError, run_fabric_verification
from lead_engine.nvidia_runtime import NvidiaRuntime, NvidiaRuntimeError
from lead_engine.nccl_all_reduce_probe import build_probe_evidence


class FakeRuntime(NvidiaRuntime):
    def __init__(self):
        super().__init__(runner=lambda args, timeout: (0, "", ""), which=lambda name: "/usr/bin/" + name)
        self.environments = []

    def verify_local(self):
        return {"verified": True, "gpu_count": 1, "evidence_source": ("test",)}

    def verify_gpu_bindings(self, gpu_bindings):
        return {"verified": True, "gpu_bindings": [dict(item) for item in gpu_bindings]}

    def distributed_process_command(self):
        return ("python", "-m", "lead_engine.nccl_all_reduce_probe")

    def validate_distributed_probe_output(self, stdout, world_size, *, expected_rank=None, expected_gpu_uuid=None, log_output=None):
        return {
            "backend": "nccl",
            "collective": "all_reduce",
            "verified_on_gpu": True,
            "world_size": world_size,
            "rank": expected_rank,
            "gpu_uuid": expected_gpu_uuid,
            "nnodes": 2,
            "network_transport": "Socket",
            "network_evidence_lines": ("NCCL INFO Using network Socket",),
            "peer_connections": (),
            "gpu_direct_rdma": False,
        }

    def validate_nccl_transport_against_rdma(self, log_output, rdma_evidence, *, gpu_uuid=None, gpu_nic_locality=None, require_gpu_direct_rdma=False):
        return {"rdma_devices": (), "verified_rdma_devices": (), "verified_hca_selections": (), "verified_rdma_links": (), "gpu_direct_rdma": False, "data_path_verified": False}


class FakeClient:
    worker_id = "worker-a"

    def __init__(self):
        self.states = []
        self.heartbeats = 0
        self.recorded = None
        self.converge_calls = 0

    def fabric_launch_plan(self, attempt_id, generation, lease_token, rendezvous_endpoint):
        return {
            "attempt_id": attempt_id,
            "rendezvous_endpoint": rendezvous_endpoint,
            "world_size": 2,
            "nnodes": 2,
            "rendezvous_id": "rv-1",
            "workers": [
                {
                    "worker_id": "worker-a",
                    "node_id": "node-a",
                    "node_rank": 0,
                    "process_count": 1,
                    "gpu_resource_ids": ["node-a/0"],
                    "gpu_bindings": [{
                        "resource_id": "node-a/0",
                        "gpu_id": "0",
                        "gpu_uuid": "GPU-a",
                        "rank": 0,
                        "local_rank": 0,
                    }],
                    "rendezvous_ref": "rv-1",
                    "rendezvous_endpoint": rendezvous_endpoint,
                },
                {
                    "worker_id": "worker-b",
                    "node_id": "node-b",
                    "node_rank": 1,
                    "process_count": 1,
                    "gpu_resource_ids": ["node-b/0"],
                    "gpu_bindings": [{
                        "resource_id": "node-b/0",
                        "gpu_id": "0",
                        "gpu_uuid": "GPU-b",
                        "rank": 1,
                        "local_rank": 0,
                    }],
                    "rendezvous_ref": "rv-1",
                    "rendezvous_endpoint": rendezvous_endpoint,
                },
            ],
        }

    def fabric_state(self, attempt_id, generation, lease_token, status, error=""):
        self.states.append((status, error))
        return {"ok": True}

    def fabric_heartbeat(self, attempt_id, generation, lease_token):
        self.heartbeats += 1
        return {"ok": True}

    def fabric_record_verification(self, attempt_id, generation, lease_token, verification):
        self.recorded = verification
        return {"ok": True}

    def fabric_converge(self, attempt_id, generation, lease_token):
        self.converge_calls += 1
        return {"converged": True, "status": "completed"}


def test_ib_gpu_direct_execution_requires_explicit_gdrdma_evidence():
    rdma = {
        "devices": [{"device": "mlx5_0"}],
        "links": [{"rdma_device": "mlx5_0", "port": 1, "netdev": "ib0", "pci_bus_id": "0000:41:00.0", "state": "ACTIVE", "physical_state": "LINK_UP", "link_layer": "InfiniBand"}],
    }
    log = "NCCL INFO NET/IB : Using [0]mlx5_0:1/IB\n"
    with pytest.raises(NvidiaRuntimeError, match="GPU Direct RDMA"):
        NvidiaRuntime.validate_nccl_transport_against_rdma(
            log, rdma, gpu_uuid="GPU-a",
            gpu_nic_locality=({"gpu_uuid": "GPU-a", "nic": "ib0", "nic_pci_bus_id": "0000:41:00.0"},),
            require_gpu_direct_rdma=True,
        )


def test_ib_gpu_direct_execution_records_verified_gdrdma_evidence():
    rdma = {
        "devices": [{"device": "mlx5_0"}],
        "links": [{"rdma_device": "mlx5_0", "port": 1, "netdev": "ib0", "pci_bus_id": "0000:41:00.0", "state": "ACTIVE", "physical_state": "LINK_UP", "link_layer": "InfiniBand"}],
    }
    log = "NCCL INFO NET/IB : Using [0]mlx5_0:1/IB\nNCCL INFO GPU Direct RDMA Enabled\n"
    result = NvidiaRuntime.validate_nccl_transport_against_rdma(
        log, rdma, gpu_uuid="GPU-a",
        gpu_nic_locality=({"gpu_uuid": "GPU-a", "nic": "ib0", "nic_pci_bus_id": "0000:41:00.0"},),
        require_gpu_direct_rdma=True,
    )
    assert result["gpu_direct_rdma"] is True
    assert result["data_path_verified"] is True
    assert result["verified_rdma_links"][0]["rdma_device"] == "mlx5_0"



def test_active_gdrdma_client_requires_explicit_trusted_remote_and_cuda_mode():
    runtime = NvidiaRuntime(
        runner=lambda args, timeout: (0, "RDMA_Write BW Test\\nDevice : mlx5_0\\n", ""),
        which=lambda name: "/usr/bin/" + name,
    )
    with pytest.raises(NvidiaRuntimeError, match="trusted remote"):
        runtime.verify_active_gpu_direct_rdma(
            gpu_index=0,
            rdma_device="mlx5_0",
            trusted_remote=None,
        )


def test_active_gdrdma_client_uses_cuda_dmabuf_and_records_only_observed_result():
    captured = []

    def runner(args, timeout):
        captured.append(tuple(args))
        return 0, "RDMA_Write BW Test\\nDevice : mlx5_0\\nBandwidth: 123.4 Gbps\\n", ""

    runtime = NvidiaRuntime(
        runner=runner,
        which=lambda name: "/usr/bin/" + name,
    )
    result = runtime.verify_active_gpu_direct_rdma(
        gpu_index=0,
        rdma_device="mlx5_0",
        trusted_remote={"endpoint": "198.51.100.10", "verified": True, "remote_test_server_verified": True, "fabric_path_id": "path-1"},
        mode="cuda_dmabuf",
    )

    assert result["verified"] is True
    assert result["gpu_index"] == 0
    assert result["rdma_device"] == "mlx5_0"
    assert result["mode"] == "cuda_dmabuf"
    assert result["remote_endpoint"] == "198.51.100.10"
    assert result["observed_output"].startswith("RDMA_Write BW Test")
    assert captured == [(
        "/usr/bin/ib_write_bw",
        "--use_cuda=0",
        "--use_cuda_dmabuf",
        "-d", "mlx5_0",
        "-a", "-F",
        "--report_gbits",
        "-q", "1",
        "198.51.100.10",
    )]


def test_active_gdrdma_client_rejects_nonzero_perftest_result():
    runtime = NvidiaRuntime(
        runner=lambda args, timeout: (1, "", "GPU memory registration failed"),
        which=lambda name: "/usr/bin/" + name,
    )
    with pytest.raises(NvidiaRuntimeError, match="active GPU Direct RDMA"):
        runtime.verify_active_gpu_direct_rdma(
            gpu_index=0,
            rdma_device="mlx5_0",
            trusted_remote={"endpoint": "198.51.100.10", "verified": True, "remote_test_server_verified": True, "fabric_path_id": "path-1"},
        )


def test_active_gdrdma_measurement_parses_only_explicit_bandwidth_and_latency():
    runtime = NvidiaRuntime(
        runner=lambda args, timeout: (
            0,
            "RDMA_Write BW Test\\n"
            "Device : mlx5_0\\n"
            "#bytes     #iterations    BW peak[Gb/sec]    BW average[Gb/sec]   MsgRate[Mpps]\\n"
            "64         5000             201.0               187.5               7.02\\n",
            "",
        ),
        which=lambda name: "/usr/bin/" + name,
    )
    result = runtime.verify_active_gpu_direct_rdma(
        gpu_index=0,
        rdma_device="mlx5_0",
        trusted_remote={
            "endpoint": "198.51.100.10",
            "verified": True,
            "remote_test_server_verified": True,
            "fabric_path_id": "path-1",
        },
    )

    assert result["measurement_status"] == "measured"
    assert result["bandwidth_samples"] == ({"message_size_bytes": 64, "iterations": 5000, "peak_bandwidth_gbps": 201.0, "bandwidth_gbps": 187.5, "message_rate_mpps": 7.02},)
    assert result["bandwidth_gbps"] is None
    assert result["latency_us"] is None
    assert result["raw_measurement_evidence"]["bandwidth_lines"] == ("64         5000             201.0               187.5               7.02",)

def test_probe_evidence_contains_only_observed_execution_identity():
    evidence = build_probe_evidence(
        rank=1,
        world_size=2,
        nnodes=2,
        expected_sum=3,
        gpu_uuid="GPU-b",
        hostname="node-b",
    )
    assert evidence == {
        "backend": "nccl",
        "rank": 1,
        "world_size": 2,
        "nnodes": 2,
        "local_rank": 0,
        "collective": "all_reduce",
        "expected_sum": 3,
        "verified_on_gpu": True,
        "gpu_uuid": "GPU-b",
        "hostname": "node-b",
    }
    assert "network_transport" not in evidence
    assert "gpu_direct_rdma" not in evidence


def test_distributed_execution_launches_exact_gpu_with_deterministic_rank_and_cuda_isolation():
    client = FakeClient()
    runtime = FakeRuntime()
    assignment = {"attempt_id": "attempt-1", "generation": 4, "lease_token": "lease-1"}
    captured = []

    def runner(command, timeout, environment):
        captured.append(dict(environment))
        probe = build_probe_evidence(
            rank=int(environment["RANK"]),
            world_size=int(environment["WORLD_SIZE"]),
            nnodes=int(environment["THORIO_EXPECTED_NNODES"]),
            expected_sum=3,
            gpu_uuid=environment["THORIO_EXPECTED_GPU_UUID"],
            hostname="node-a",
        )
        return 0, "THORIO_NCCL_PROBE_OK " + json.dumps(probe), "NCCL INFO Using network Socket"

    result = run_fabric_verification(
        client,
        assignment,
        rendezvous_endpoint="node-a:29500",
        heartbeat_seconds=10,
        runtime=runtime,
        runner=runner,
    )

    assert result["verified"] is True
    assert result["backend"] == "nccl"
    assert result["world_size"] == 2
    assert result["nnodes"] == 2
    assert len(captured) == 1
    assert captured[0]["CUDA_VISIBLE_DEVICES"] == "0"
    assert captured[0]["RANK"] == "0"
    assert captured[0]["WORLD_SIZE"] == "2"
    assert captured[0]["LOCAL_RANK"] == "0"
    assert captured[0]["THORIO_EXPECTED_GPU_UUID"] == "GPU-a"
    assert [state for state, _ in client.states] == ["launching", "active"]
    assert client.recorded["generation"] == 4
    assert client.recorded["process_evidence"][0]["rank"] == 0
    assert client.converge_calls == 1


def test_distributed_rank_failure_transitions_attempt_to_failed_and_never_reports_verification():
    client = FakeClient()
    runtime = FakeRuntime()
    assignment = {"attempt_id": "attempt-2", "generation": 7, "lease_token": "lease-2"}

    def runner(command, timeout, environment):
        return 1, "", "NCCL rank failure"

    with pytest.raises(NvidiaRuntimeError, match="distributed NCCL launch failed"):
        run_fabric_verification(
            client,
            assignment,
            rendezvous_endpoint="node-a:29501",
            heartbeat_seconds=10,
            runtime=runtime,
            runner=runner,
        )

    assert [state for state, _ in client.states] == ["launching", "active", "failed"]
    assert client.recorded is None
    assert client.converge_calls == 0


def test_distributed_execution_rejects_invalid_heartbeat_configuration_before_launch():
    client = FakeClient()
    with pytest.raises(ValueError, match="heartbeat_seconds must be positive"):
        run_fabric_verification(
            client,
            {"attempt_id": "attempt-3", "generation": 1, "lease_token": "lease"},
            rendezvous_endpoint="node-a:29502",
            heartbeat_seconds=0,
            runtime=FakeRuntime(),
            runner=lambda *_: (0, "", ""),
        )


def test_distributed_execution_requires_worker_in_durable_launch_plan():
    class MissingWorkerClient(FakeClient):
        worker_id = "worker-missing"

    with pytest.raises(ComputeWorkerError, match="not present in the durable launch plan"):
        run_fabric_verification(
            MissingWorkerClient(),
            {"attempt_id": "attempt-4", "generation": 1, "lease_token": "lease"},
            rendezvous_endpoint="node-a:29503",
            runtime=FakeRuntime(),
            runner=lambda *_: (0, "", ""),
        )
