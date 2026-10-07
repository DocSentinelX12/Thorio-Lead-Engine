import os
import socket
import subprocess
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
