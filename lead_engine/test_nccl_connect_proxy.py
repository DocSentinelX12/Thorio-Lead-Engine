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
    assert 'client.sendall(b"\x00")' in relay
    assert 'client.sendall(b"\x01")' in relay
    assert "acknowledgement_sent" in relay


def test_connect_proxy_requires_upstream_acknowledgement():
    source = Path("lead_engine/nccl_connect_proxy.c").read_text()
    assert "#include <poll.h>" in source
    assert "THORIO_CONNECT_PROXY_UPSTREAM_REJECTED" in source
    assert "poll(&ack_poll, 1, 15000)" in source


def test_tcpstore_forwarder_consumes_relay_acknowledgement():
    source = Path("lead_engine/nccl_all_reduce_probe.py").read_text()
    assert 'acknowledgement = upstream.recv(1)' in source
    assert 'acknowledgement != b"\x00"' in source
