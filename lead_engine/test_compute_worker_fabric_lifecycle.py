        stop_event=stop_event,
    )

    assert client.fabric_seen is True
    assert client.claimed is False
    assert serviced == [(client, {"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"}, "10.0.0.5:29400")]


def test_run_worker_survives_fabric_runtime_failure(monkeypatch):
    from lead_engine.compute_worker import run_worker
    from lead_engine.nvidia_runtime import NvidiaRuntimeError

    class Stop:
        def __init__(self):
            self.done = False
        def is_set(self):
            return self.done
        def wait(self, seconds):
            self.done = True
            return True

    class Client:
        def __init__(self):
            self._registered = True
            self.worker_id = "worker-1"
            self.claimed = False
        def heartbeat(self, current_load=0):
            return {"ok": True}
        def fabric_assignments(self):
            return [{"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"}]
        def claim(self):
            self.claimed = True
            return None

    client = Client()
    stop = Stop()

    def failing_verify(*args, **kwargs):
        stop.done = True
        raise NvidiaRuntimeError("real NCCL runtime unavailable")

    monkeypatch.setattr("lead_engine.compute_worker.run_fabric_verification", failing_verify)

    run_worker(
        client,
        idle_seconds=1,
        heartbeat_seconds=15,
        fabric_rendezvous_endpoint="10.0.0.5:29400",
        stop_event=stop,
    )

    assert client.claimed is False


def test_running_fabric_participant_heartbeat_renews_lease(tmp_path: Path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    coordinator = ComputeCoordinator(