import json
import threading
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


def _register(base_url):
    status, result = _request(base_url, "/workers/register", "POST", {
        "worker_id": "worker-1",
        "hostname": "host",
        "architecture": "x86_64",
        "cpu_count": 2,
        "memory_mb": 4096,
        "capabilities": ["lead-processing", "lead_prepare"],
    })
    assert status == 200
    assert result["worker_id"] == "worker-1"


def test_lead_prepare_checkpoint_survives_lease_expiry_and_is_excluded_from_retry(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token", lease_seconds=30)
    server, thread = _start_server(coordinator)
    base_url = f"http://127.0.0.1:{server.server_port}"
    payload = {
        "kind": "lead_prepare",
        "leads": [
            {"company": "Alpha", "url": "https://alpha.example"},
            {"company": "Beta", "url": "https://beta.example"},
        ],
    }
    try:
        _register(base_url)
        task_id = coordinator.enqueue(payload)
        _, claimed = _request(base_url, "/work/claim", "POST", {"worker_id": "worker-1"})
        assert claimed["task_id"] == task_id
        first_key = claimed["payload"]["leads"][0]["__checkpoint_item_key"]

        status, checkpointed = _request(base_url, "/work/checkpoint", "POST", {
            "worker_id": "worker-1",
            "task_id": task_id,
            "lease_token": claimed["lease_token"],
            "items": [{"item_key": first_key, "result": {"company": "Alpha", "score": 5}}],
        })
        assert status == 200
        assert checkpointed["checkpointed"] == 1

        with coordinator._connect() as connection:
            connection.execute("UPDATE compute_tasks SET lease_until=? WHERE task_id=?", (0, task_id))
            connection.commit()
        assert coordinator.recover_expired_tasks() == 1

        _, retry = _request(base_url, "/work/claim", "POST", {"worker_id": "worker-1"})
        assert retry["task_id"] == task_id
        assert len(retry["payload"]["leads"]) == 1
        assert retry["payload"]["leads"][0]["company"] == "Beta"

        status, stored = _request(base_url, f"/work/checkpoints/{task_id}")
        assert status == 200
        assert stored["completed"] == 1
        assert stored["results"][0]["company"] == "Alpha"
    finally:
        _stop_server(server, thread)



def test_lead_prepare_checkpoint_is_idempotent_and_rejects_conflicting_result(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token", lease_seconds=30)
    coordinator.register_worker(__import__("lead_engine.compute_pool", fromlist=["WorkerIdentity"]).WorkerIdentity(
        "worker-1", "host", "x86_64", 2, 4096, ("lead-processing", "lead_prepare")
    ))
    task_id = coordinator.enqueue({"kind": "lead_prepare", "leads": [{"company": "Alpha"}]})
    claimed = coordinator.claim("worker-1")
    key = claimed["payload"]["leads"][0]["__checkpoint_item_key"]
    assert coordinator.checkpoint_lead_prepare(
        "worker-1", task_id, claimed["lease_token"], [{"item_key": key, "result": {"company": "Alpha"}}]
    ) == {"checkpointed": 1, "already_checkpointed": 0}
    assert coordinator.checkpoint_lead_prepare(
        "worker-1", task_id, claimed["lease_token"], [{"item_key": key, "result": {"company": "Alpha"}}]
    ) == {"checkpointed": 0, "already_checkpointed": 1}
    try:
        coordinator.checkpoint_lead_prepare(
            "worker-1", task_id, claimed["lease_token"], [{"item_key": key, "result": {"company": "Changed"}}]
        )
    except ValueError as error:
        assert "checkpoint conflict" in str(error)
    else:
        raise AssertionError("conflicting checkpoint was accepted")


def test_checkpointed_worker_preserves_lead_without_preexisting_fingerprint():
    from lead_engine.compute_worker import execute_checkpointed_lead_prepare

    class FakeClient:
        def __init__(self):
            self.items = []
        def checkpoint_lead_prepare(self, task_id, lease_token, items):
            self.items.extend(items)
            return {"checkpointed": len(items), "already_checkpointed": 0}
        def checkpoint_results(self, task_id):
            return {"completed": len(self.items), "results": [item["result"] for item in self.items if item["result"] is not None]}

    client = FakeClient()
    result = execute_checkpointed_lead_prepare(
        client,
        "task-1",
        "lease-1",
        {"kind": "lead_prepare", "leads": [{"company": "Example", "signal": "hiring", "url": "https://example.com"}]},
    )
    assert result["count"] == 1
    assert result["leads"][0]["company"] == "Example"
    assert "__checkpoint_item_key" not in result["leads"][0]
    assert client.items[0]["item_key"]
