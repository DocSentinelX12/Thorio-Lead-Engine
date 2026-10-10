import pytest

from lead_engine.nvidia_runtime import NvidiaRuntime, NvidiaRuntimeError


def test_nccl_oob_interface_is_not_misclassified_as_selected_ib_transport():
    log = "\n".join(
        (
            "NCCL INFO NET/IB : No device found.",
            "NCCL INFO NET/IB : Using [RO]; OOB eth0:172.19.2.2<0>",
            "NCCL INFO Failed to initialize NET plugin IB",
            "NCCL INFO NET/Socket : Using [0]eth0:172.19.2.2<0>",
            "NCCL INFO Using network Socket",
            "NCCL INFO Channel 00/0 : 0[0] -> 1[0] [send] via NET/Socket/0",
        )
    )

    evidence = NvidiaRuntime.parse_nccl_network_evidence(log)

    assert evidence["network_transport"] == "Socket"
    assert evidence["peer_connections"] == (
        {
            "channel": "00/0",
            "local_rank": 0,
            "peer_rank": 1,
            "direction": "send",
            "transport": "Socket/0",
        },
    )


def test_nccl_selected_ib_transport_retains_rdma_device_evidence():
    log = "\n".join(
        (
            "NCCL INFO NET/IB : Using [0]mlx5_0:1/IB",
            "NCCL INFO Using network IB",
        )
    )

    evidence = NvidiaRuntime.parse_nccl_network_evidence(log)

    assert evidence["network_transport"] == "IB"
    assert evidence["hca_selections"] == (
        {"device": "mlx5_0", "port": 1, "transport": "IB"},
    )
