import json
import threading
import urllib.error
import urllib.request

from lead_engine.compute_coordinator import ComputeCoordinator, ComputeCoordinatorServer


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


def _start_server(coordinator):
    server = ComputeCoordinatorServer(coordinator, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _register(base_url, worker_id="worker-1"):
    status, registered = _request(base_url, "/workers/register", "POST", {
        "worker_id": worker_id,
        "hostname": "host",
        "architecture": "x86_64",
        "cpu_count": 2,
        "memory_mb": 4096,
        "capabilities": ["lead-processing"],
    })
    assert status == 200
    assert registered["worker_id"] == worker_id


def test_coordinator_register_claim_complete_round_trip(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token", lease_seconds=30)
    server, thread = _start_server(coordinator)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        _register(base_url)
        task_id = coordinator.enqueue({"fingerprint": "abc", "payload": {"company": "Example"}})
        status, claimed = _request(base_url, "/work/claim", "POST", {"worker_id": "worker-1"})
        assert status == 200
        assert claimed["task_id"] == task_id
        assert claimed["payload"]["fingerprint"] == "abc"

        status, second_claim = _request(base_url, "/work/claim", "POST", {"worker_id": "worker-1"})
        assert status == 200
        assert second_claim == {"task": None}

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
        _stop_server(server, thread)


def test_remote_enqueue_claim_complete_round_trip(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token", lease_seconds=30)
    server, thread = _start_server(coordinator)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        _register(base_url)
        status, queued = _request(base_url, "/work/enqueue", "POST", {
            "task_id": "remote-task-1",
            "payload": {"kind": "agent_task", "role": "social_intelligence", "lead_id": "lead-1"},
        })
        assert status == 201
        assert queued["task_id"] == "remote-task-1"

        status, claimed = _request(base_url, "/work/claim", "POST", {"worker_id": "worker-1"})
        assert status == 200
        assert claimed["task_id"] == "remote-task-1"
        assert claimed["payload"]["role"] == "social_intelligence"

        status, completed = _request(base_url, "/work/complete", "POST", {
            "worker_id": "worker-1",
            "task_id": "remote-task-1",
            "lease_token": claimed["lease_token"],
            "result": {"status": "processed", "lead_id": "lead-1"},
        })
        assert status == 200
        assert completed["completed"] is True
        assert coordinator.task("remote-task-1")["result"]["lead_id"] == "lead-1"
    finally:
        _stop_server(server, thread)


def test_remote_enqueue_requires_object_payload(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token")
    server, thread = _start_server(coordinator)
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        try:
            _request(base_url, "/work/enqueue", "POST", {"payload": []})
        except urllib.error.HTTPError as error:
            assert error.code == 400
            body = json.loads(error.read().decode("utf-8"))
            assert "payload must be an object" in body["error"]
        else:
            raise AssertionError("invalid coordinator task payload was accepted")
    finally:
        _stop_server(server, thread)


def test_expired_lease_is_requeued_and_claimable(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token", lease_seconds=30)
    coordinator.register_worker(__import__("lead_engine.compute_pool", fromlist=["WorkerIdentity"]).WorkerIdentity("worker-1", "host", "x86_64", 2, 4096))
    task_id = coordinator.enqueue({"kind": "lead_prepare", "leads": []})
    claimed = coordinator.claim("worker-1")
    assert claimed["task_id"] == task_id
    with coordinator._connect() as connection:
        connection.execute("UPDATE compute_tasks SET lease_until=? WHERE task_id=?", (0, task_id))
        connection.commit()
    assert coordinator.recover_expired_tasks() == 1
    assert coordinator.task(task_id)["status"] == "queued"
    assert coordinator.claim("worker-1")["task_id"] == task_id


def test_coordinator_rejects_invalid_auth(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token")
    server, thread = _start_server(coordinator)
    request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/health")
    try:
        try:
            urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("unauthenticated coordinator request was accepted")
    finally:
        _stop_server(server, thread)
