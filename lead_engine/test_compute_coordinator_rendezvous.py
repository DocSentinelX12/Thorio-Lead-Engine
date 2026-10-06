from __future__ import annotations

from pathlib import Path

from lead_engine.compute_coordinator import ComputeCoordinator


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
