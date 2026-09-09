import json
import tempfile
import threading
from pathlib import Path

import pytest

from .compute_coordinator import ComputeCoordinator, ComputeCoordinatorServer
from .compute_pool import WorkerIdentity
from .compute_worker import ComputeWorkerClient, ComputeWorkerError, execute_compute_task


def _identity(worker_id="test-worker"):
    return WorkerIdentity(worker_id, "test-host", "x86_64", 2, 1024, ("lead-processing",))


def test_coordinator_enqueue_is_idempotent_and_rejects_payload_drift():
    with tempfile.TemporaryDirectory() as directory:
        coordinator = ComputeCoordinator(str(Path(directory) / "coordinator.sqlite3"), "secret")
        task_id = coordinator.enqueue({"kind": "agent_task", "agent": "ai_demand_discovery"}, task_id="stable-task")
        assert coordinator.enqueue({"kind": "agent_task", "agent": "ai_demand_discovery"}, task_id=task_id) == task_id
        with pytest.raises(ValueError, match="different payload"):
            coordinator.enqueue({"kind": "agent_task", "agent": "engineering_demand_discovery"}, task_id=task_id)


def test_http_enqueue_claim_complete_and_status_are_connected():
    with tempfile.TemporaryDirectory() as directory:
        coordinator = ComputeCoordinator(str(Path(directory) / "coordinator.sqlite3"), "secret")
        coordinator.register_worker(_identity())
        server = ComputeCoordinatorServer(coordinator, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            client = ComputeWorkerClient(url, "secret", "test-worker")
            created = client.enqueue({"kind": "agent_task", "agent": "ai_demand_discovery", "payload": {"events": []}}, task_id="remote-task")
            assert created["task_id"] == "remote-task"
            task = client.claim()
            assert task is not None
            assert task["task_id"] == "remote-task"
            result = {"kind": "agent_task", "agent": "ai_demand_discovery", "result": {"matched_event_count": 0}}
            assert client.complete(task["task_id"], task["lease_token"], result)["completed"] is True
            status = client.status("remote-task")
            assert status["status"] == "completed"
            assert status["result"] == result
            assert status["attempts"] == 1
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def test_execute_compute_task_rejects_stateful_or_unknown_agent_work():
    with pytest.raises(ComputeWorkerError, match="not supported"):
        execute_compute_task({"kind": "agent_task", "agent": "identity_resolution", "payload": {}})


def test_compute_worker_rejects_failed_completion_ack():
    class FakeClient(ComputeWorkerClient):
        def request(self, path, payload=None):
            return {"completed": False}

    client = FakeClient("http://example.test", "secret", "worker")
    with pytest.raises(ComputeWorkerError, match="rejected completion"):
        client.complete("task", "lease", {})
