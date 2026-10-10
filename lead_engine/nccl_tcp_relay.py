#!/usr/bin/env python3
"""Tiny authenticated-by-rank TCP fan-out relay for the physical NCCL proof.

Pinggy exposes this one local port. Each incoming tunnel connection begins with
a fixed binary destination header, then the relay connects to that destination
inside the same Kaggle network namespace and shuttles bytes both ways.
"""
from __future__ import annotations
import ipaddress
import json
import os
import socket
import struct
import sys
import threading

MAGIC = b"THORIO1"
HEADER = struct.Struct("!7s32s4sH")
MAX_HEADER = HEADER.size

def _copy(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                return
            dst.sendall(data)
    except OSError:
        return
    finally:
        for sock in (src, dst):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

def _allowed_destination(raw_ip: str) -> bool:
    ip = ipaddress.ip_address(raw_ip)
    return ip.is_private and not ip.is_loopback and not ip.is_link_local

def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        data = sock.recv(remaining)
        if not data:
            return b""
        chunks.append(data)
        remaining -= len(data)
    return b"".join(chunks)

def _handle(client: socket.socket) -> None:
    destination = "<unparsed>"
    port = 0
    header_valid = False
    acknowledgement_sent = False
    try:
        header = _recv_exact(client, MAX_HEADER)
        if len(header) != MAX_HEADER:
            return
        magic, token, packed_ip, port = HEADER.unpack(header)
        expected = os.environ.get("THORIO_RELAY_TOKEN", "").encode("ascii")
        if magic != MAGIC or token.rstrip(b"\x00") != expected or not (1 <= port <= 65535):
            return
        destination = socket.inet_ntoa(packed_ip)
        if not _allowed_destination(destination):
            return
        header_valid = True
        print(
            "THORIO_RELAY_INCOMING "
            + json.dumps({"destination": destination, "port": port}, sort_keys=True),
            flush=True,
        )
        # A tunnel TCP connection is not proof that the NCCL peer socket accepted.
        # Acknowledge only after the final destination connection succeeds.
        upstream = socket.create_connection((destination, port), timeout=10)
        client.sendall(b"\\x00")
        acknowledgement_sent = True
        print(
            "THORIO_RELAY_UPSTREAM_CONNECTED "
            + json.dumps({"destination": destination, "port": port}, sort_keys=True),
            flush=True,
        )
        client.settimeout(None)
        upstream.settimeout(None)
        t = threading.Thread(target=_copy, args=(client, upstream), daemon=True)
        t.start()
        _copy(upstream, client)
    except OSError as exc:
        if header_valid and not acknowledgement_sent:
            try:
                client.sendall(b"\\x01")
            except OSError:
                pass
        print(
            "THORIO_RELAY_UPSTREAM_CONNECT_FAILED "
            + json.dumps(
                {
                    "destination": destination,
                    "port": port,
                    "error_type": type(exc).__name__,
                    "errno": exc.errno,
                    "detail": str(exc)[:200],
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return
    finally:
        try:
            client.close()
        except OSError:
            pass

def main() -> None:
    requested = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", requested))
    server.listen(128)
    port = server.getsockname()[1]
    print(f"THORIO_RELAY_LISTEN_PORT={port}", flush=True)
    while True:
        client, _ = server.accept()
        threading.Thread(target=_handle, args=(client,), daemon=True).start()

if __name__ == "__main__":
    main()
