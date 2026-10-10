import os
import socket
import subprocess
import struct
from pathlib import Path

def test_relay_header_constant():
    source = Path("lead_engine/nccl_connect_proxy.c").read_text()
    assert 'memcpy(header, "THORIO1", 7)' in source
    assert "THORIO_PEER_TUNNEL_HOST" in source
    assert "THORIO_PEER_TUNNEL_PORT" in source

def test_private_ranges():
    source = Path("lead_engine/nccl_connect_proxy.c").read_text()
    assert "(host_order >> 24) == 10" in source
    assert "(host_order >> 20) == 0xAC1" in source
    assert "(host_order >> 16) == 0xC0A8" in source


def test_relay_is_authenticated_and_framed():
    relay = Path("lead_engine/nccl_tcp_relay.py").read_text()
    assert 'HEADER = struct.Struct("!7s32s4sH")' in relay
    assert 'THORIO_RELAY_TOKEN' in relay
    assert 'THORIO1' in relay
    assert 'def _recv_exact' in relay


def test_relay_acknowledges_only_after_upstream_connect():
    relay = Path("lead_engine/nccl_tcp_relay.py").read_text()
    assert r'client.sendall(b"\x00")' in relay
    assert r'client.sendall(b"\x01")' in relay
    assert "acknowledgement_sent" in relay


def test_connect_proxy_requires_upstream_acknowledgement():
    source = Path("lead_engine/nccl_connect_proxy.c").read_text()
    assert "#include <poll.h>" in source
    assert "THORIO_CONNECT_PROXY_UPSTREAM_REJECTED" in source
    assert "poll(&ack_poll, 1, 15000)" in source


def test_tcpstore_forwarder_consumes_relay_acknowledgement():
    source = Path("lead_engine/nccl_all_reduce_probe.py").read_text()
    assert 'acknowledgement = upstream.recv(1)' in source
    assert r'acknowledgement != b"\x00"' in source


def test_proxy_keeps_local_listening_connections_local(tmp_path):
    import ipaddress
    import shutil
    import sys

    import pytest

    compiler = shutil.which("gcc")
    if not compiler:
        pytest.skip("gcc is required for the connect-proxy integration test")

    route = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        route.connect(("1.1.1.1", 80))
        local_ip = route.getsockname()[0]
    finally:
        route.close()

    address = ipaddress.ip_address(local_ip)
    if not any(
        address in ipaddress.ip_network(network)
        for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    ):
        pytest.skip("runner has no RFC1918 interface address to exercise the proxy")

    library = tmp_path / "libthorio-connect-proxy.so"
    subprocess.run(
        [
            compiler,
            "-shared",
            "-fPIC",
            "-O2",
            "-Wall",
            "-Wextra",
            "lead_engine/nccl_connect_proxy.c",
            "-o",
            str(library),
            "-ldl",
            "-pthread",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((local_ip, 0))
        listener.listen(1)
        listener.settimeout(3)
        port = listener.getsockname()[1]

        env = os.environ.copy()
        env.update(
            {
                "LD_PRELOAD": str(library),
                # If the proxy incorrectly redirects this local connection,
                # this deliberately closed local endpoint makes the test fail.
                "THORIO_PEER_TUNNEL_HOST": "127.0.0.1",
                "THORIO_PEER_TUNNEL_PORT": "1",
                "THORIO_PEER_RELAY_TOKEN": "a" * 32,
            }
        )
        script = (
            "import socket; "
            f"sock=socket.create_connection(({local_ip!r}, {port}), timeout=3); "
            "sock.close()"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=6,
        )
        assert completed.returncode == 0, (
            "a connection to a local listening NCCL socket was incorrectly "
            f"sent through the peer relay: {completed.stderr}"
        )
        accepted, _ = listener.accept()
        accepted.close()
