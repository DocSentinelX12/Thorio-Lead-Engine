import json
import sqlite3
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
        "capabilities": ["lead-processing", "social_intelligence", "lead_prepare"],
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
    coordinator.register_worker(__import__("lead_engine.compute_pool", fromlist=["WorkerIdentity"]).WorkerIdentity(
        "worker-1", "host", "x86_64", 2, 4096, ("lead-processing", "lead_prepare")
    ))
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


def test_claim_finds_compatible_work_beyond_oldest_scan_window(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token", lease_seconds=30)
    coordinator.register_worker(__import__("lead_engine.compute_pool", fromlist=["WorkerIdentity"]).WorkerIdentity(
        "specialist-worker", "host", "x86_64", 2, 4096, ("lead-processing", "target-capability")
    ))
    for index in range(100):
        coordinator.enqueue({"kind": "agent_task", "agent": "incompatible", "required_capabilities": ["other-capability"], "index": index})
    target_id = coordinator.enqueue({
        "kind": "agent_task",
        "agent": "target",
        "required_capabilities": ["target-capability"],
    })
    claimed = coordinator.claim("specialist-worker")
    assert claimed is not None
    assert claimed["task_id"] == target_id


def test_completion_is_idempotent_and_attempt_is_durable(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token", lease_seconds=30)
    coordinator.register_worker(__import__("lead_engine.compute_pool", fromlist=["WorkerIdentity"]).WorkerIdentity(
        "worker-1", "host", "x86_64", 2, 4096, ("lead-processing", "lead_prepare")
    ))
    task_id = coordinator.enqueue({"kind": "lead_prepare", "leads": []})
    claimed = coordinator.claim("worker-1")
    assert claimed["task_id"] == task_id
    assert claimed["attempt_id"]
    assert claimed["generation"] == 1

    result = {"status": "processed"}
    assert coordinator.complete("worker-1", task_id, claimed["lease_token"], result) is True
    assert coordinator.complete("worker-1", task_id, claimed["lease_token"], result) is True

    with coordinator._connect() as connection:
        attempt = connection.execute(
            "SELECT status,generation,worker_id,authoritative_acceptance FROM compute_execution_attempts WHERE attempt_id=?",
            (claimed["attempt_id"],),
        ).fetchone()
    assert attempt["status"] == "completed"
    assert attempt["generation"] == 1
    assert attempt["worker_id"] == "worker-1"
    assert attempt["authoritative_acceptance"] == "pending"


def test_expired_attempt_is_recoverable_without_completion(tmp_path):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token", lease_seconds=30)
    coordinator.register_worker(__import__("lead_engine.compute_pool", fromlist=["WorkerIdentity"]).WorkerIdentity(
        "worker-1", "host", "x86_64", 2, 4096, ("lead-processing", "lead_prepare")
    ))
    task_id = coordinator.enqueue({"kind": "lead_prepare", "leads": []})
    claimed = coordinator.claim("worker-1")
    with coordinator._connect() as connection:
        connection.execute("UPDATE compute_tasks SET lease_until=? WHERE task_id=?", (0, task_id))
        connection.commit()
    assert coordinator.recover_expired_tasks() == 1
    with coordinator._connect() as connection:
        attempt = connection.execute(
            "SELECT status,finished_at,error FROM compute_execution_attempts WHERE attempt_id=?",
            (claimed["attempt_id"],),
        ).fetchone()
    assert attempt["status"] == "expired"
    assert attempt["finished_at"] is not None
    assert "lease expired" in attempt["error"]
    assert coordinator.task(task_id)["status"] == "queued"


def test_reconcile_fabric_rolls_back_requeue_if_attempt_was_retired_concurrently(tmp_path, monkeypatch):
    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token", lease_seconds=30)
    coordinator.register_worker(__import__("lead_engine.compute_pool", fromlist=["WorkerIdentity"]).WorkerIdentity(
        "worker-1", "host", "x86_64", 2, 4096, ("lead-processing",)
    ))
    task_id = coordinator.enqueue({"kind": "lead_prepare", "leads": []})
    claimed = coordinator.claim("worker-1")
    attempt_id = claimed["attempt_id"]
    generation = claimed["generation"]
    now = 1.0
    with coordinator._connect() as connection:
        connection.execute(
            "INSERT INTO compute_execution_participants("
            "attempt_id,task_id,generation,allocation_id,worker_id,node_id,rank,world_size,"
            "rendezvous_ref,status,resource_ids,bound_at,heartbeat_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (attempt_id, task_id, generation, "allocation-1", "worker-1", "worker-1", 0, 1,
             "rendezvous-1", "running", "[]", now, now),
        )
        connection.commit()

    real_connect = coordinator._connect

    class RacingConnection:
        def __init__(self, connection):
            self._connection = connection
            self._retired = False

        def execute(self, sql, params=()):
            if not self._retired and "UPDATE compute_execution_attempts" in sql and "SET status='failed'" in sql:
                self._retired = True
                with sqlite3.connect(coordinator.db_path) as race:
                    race.execute(
                        "UPDATE compute_execution_attempts SET status='failed' WHERE attempt_id=? AND generation=? AND status='leased'",
                        (attempt_id, generation),
                    )
                    race.commit()
            return self._connection.execute(sql, params)

        def commit(self):
            return self._connection.commit()

        def rollback(self):
            return self._connection.rollback()

        def __enter__(self):
            self._connection.__enter__()
            return self

        def __exit__(self, *args):
            return self._connection.__exit__(*args)

    monkeypatch.setattr(coordinator, "_connect", lambda: RacingConnection(real_connect()))

    result = coordinator.reconcile_fabric(participant_timeout_seconds=1)
    assert result == {"reconciled": 0, "requeued": 0}

    with real_connect() as connection:
        task = connection.execute(
            "SELECT status,attempt_id FROM compute_tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        attempt = connection.execute(
            "SELECT status FROM compute_execution_attempts WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
    assert task["status"] == "leased"
    assert task["attempt_id"] == attempt_id
    assert attempt["status"] == "failed"


def test_physical_allocation_binding_is_idempotent_and_generation_specific(tmp_path):
    from lead_engine.compute_pool import WorkerIdentity

    coordinator = ComputeCoordinator(str(tmp_path / "coordinator.sqlite3"), auth_token="test-token", lease_seconds=30)
    coordinator.register_worker(WorkerIdentity(
        "worker-1", "host", "x86_64", 2, 4096, ("lead-processing", "lead_prepare")
    ))
    task_id = coordinator.enqueue({"kind": "lead_prepare", "leads": []})
    claimed = coordinator.claim("worker-1")
    assert claimed["task_id"] == task_id
    assert coordinator.bind_physical_allocation(
        task_id=task_id,
        attempt_id=claimed["attempt_id"],
        generation=claimed["generation"],
        allocation_id="allocation-1",
        provider_id="provider-a",
        domain_id="domain-a",
        resource_ids=("node-a/cpu", "node-a/gpu-0"),
        lease_token=claimed["lease_token"],
    )
    assert coordinator.bind_physical_allocation(
        task_id=task_id,
        attempt_id=claimed["attempt_id"],
        generation=claimed["generation"],
        allocation_id="allocation-1",
        provider_id="provider-a",
        domain_id="domain-a",
        resource_ids=("node-a/cpu", "node-a/gpu-0"),
        lease_token=claimed["lease_token"],
    )
    assert not coordinator.bind_physical_allocation(
        task_id=task_id,
        attempt_id=claimed["attempt_id"],
        generation=claimed["generation"] + 1,
        allocation_id="allocation-2",
        provider_id="provider-a",
        domain_id="domain-a",
        resource_ids=("node-a/cpu", "node-a/gpu-1"),
        lease_token=claimed["lease_token"],
    )
    with coordinator._connect() as connection:
        row = connection.execute(
            "SELECT allocation_id,provider_id,domain_id,resource_ids FROM compute_execution_attempts WHERE attempt_id=?",
            (claimed["attempt_id"],),
        ).fetchone()
    assert row["allocation_id"] == "allocation-1"
    assert row["provider_id"] == "provider-a"
    assert row["domain_id"] == "domain-a"
    assert row["resource_ids"] == '["node-a/cpu", "node-a/gpu-0"]'
