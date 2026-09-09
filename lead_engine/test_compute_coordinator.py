import json
import threading
import urllib.error
import urllib.request

from lead_engine.compute_coordinator import ComputeCoordinator, ComputeCoordinatorServer
from lead_engine.compute_pool import WorkerIdentity


def _request(base_url, path, method="GET", body=None, token="test-token"):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        base_url + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_coordinator_register_claim_complete_round_trip(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token", lease_seconds=30)
    server = ComputeCoordinatorServer(coordinator, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        status, registered = _request(base_url, "/workers/register", "POST", {
            "worker_id": "worker-1",
            "hostname": "host",
            "architecture": "x86_64",
            "cpu_count": 2,
            "memory_mb": 4096,
            "capabilities": ["lead-processing"],
        })
        assert status == 200
        assert registered["worker_id"] == "worker-1"

        task_id = coordinator.enqueue({"fingerprint": "abc", "payload": {"company": "Example"}})
        status, claimed = _request(base_url, "/work/claim", "POST", {"worker_id": "worker-1"})
        assert status == 200
        assert claimed["task_id"] == task_id
        assert claimed["payload"]["fingerprint"] == "abc"

        status, completed = _request(base_url, "/work/complete", "POST", {
            "worker_id": "worker-1",
            "task_id": task_id,
            "lease_token": claimed["lease_token"],
            "result": {"status": "processed"},
        })
        assert status == 200
        assert completed["completed"] is True
        assert coordinator.task(task_id)["status"] == "completed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_coordinator_rejects_invalid_auth(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token")
    server = ComputeCoordinatorServer(coordinator, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/health")
    try:
        try:
            urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("unauthenticated coordinator request was accepted")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
