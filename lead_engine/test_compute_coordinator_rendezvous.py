from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from lead_engine.compute_coordinator import ComputeCoordinator, ComputeCoordinatorServer


def test_fabric_rendezvous_round_trip(tmp_path: Path):
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        "test-token",
    )

    published = coordinator.publish_fabric_rendezvous(
        session_id="nccl-test-1",
        address="10.0.0.10",
        port=29500,
        interface_name="eth0",
    )

    assert published["ok"] is True
    assert published["address"] == "10.0.0.10"
    assert published["port"] == 29500
    assert published["interface_name"] == "eth0"

    observed = coordinator.get_fabric_rendezvous("nccl-test-1")
    assert observed["ok"] is True
    assert observed["status"] == "published"
    assert observed["address"] == "10.0.0.10"
    assert observed["port"] == 29500
    assert observed["interface_name"] == "eth0"

    assert coordinator.clear_fabric_rendezvous("nccl-test-1") is True
    assert coordinator.get_fabric_rendezvous("nccl-test-1") == {
        "ok": False,
        "session_id": "nccl-test-1",
        "status": "not_published",
    }


def test_fabric_rendezvous_http_publish_and_read(tmp_path: Path):
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        "test-token",
    )
    server = ComputeCoordinatorServer(coordinator, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        publish_request = urllib.request.Request(
            base + "/fabric/acquisition/rendezvous",
            data=json.dumps(
                {
                    "action": "publish",
                    "session_id": "nccl-http-test",
                    "address": "10.0.0.20",
                    "port": 29501,
                    "interface_name": "eth1",
                    "ttl_seconds": 60,
                }
            ).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(publish_request, timeout=5) as response:
            published = json.loads(response.read().decode("utf-8"))

        assert published["ok"] is True
        assert published["session_id"] == "nccl-http-test"

        read_request = urllib.request.Request(
            base + "/fabric/acquisition/rendezvous?session_id=nccl-http-test",
            headers={"Authorization": "Bearer test-token"},
        )
        with urllib.request.urlopen(read_request, timeout=5) as response:
            observed = json.loads(response.read().decode("utf-8"))

        assert observed["ok"] is True
        assert observed["address"] == "10.0.0.20"
        assert observed["port"] == 29501
        assert observed["interface_name"] == "eth1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_fabric_rendezvous_rejects_invalid_endpoint(tmp_path: Path):
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        "test-token",
    )

    try:
        coordinator.publish_fabric_rendezvous(
            session_id="nccl-test-2",
            address="",
            port=29500,
            interface_name="eth0",
        )
    except ValueError as exc:
        assert "address" in str(exc)
    else:
        raise AssertionError("empty rendezvous address must be rejected")

    try:
        coordinator.publish_fabric_rendezvous(
            session_id="nccl-test-3",
            address="10.0.0.10",
            port=70000,
            interface_name="eth0",
        )
    except ValueError as exc:
        assert "port" in str(exc)
    else:
        raise AssertionError("invalid rendezvous port must be rejected")
