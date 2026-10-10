"""Readiness markers are emitted only after successful worker lifecycle calls."""
from lead_engine.compute_worker import ComputeWorkerError, run_worker


class StopAfterFirstWait:
    def __init__(self):
        self.waits = 0

    def is_set(self):
        return self.waits > 0

    def wait(self, _seconds):
        self.waits += 1
        return True


class ReadyClient:
    def __init__(self):
        self.worker_id = "github-test"
        self._registered = False
        self._active_task = None

    def register(self):
        self._registered = True
        return {"ok": True}

    def heartbeat(self, _load=0):
        return {"ok": True}

    def fabric_assignments(self):
        return []

    def claim(self):
        return None


def test_worker_emits_registration_and_heartbeat_markers_after_success(capsys):
    run_worker(ReadyClient(), idle_seconds=0.01, heartbeat_seconds=0.01, stop_event=StopAfterFirstWait())
    output = capsys.readouterr().out
    assert "THORIO_WORKER_REGISTERED worker_id=github-test" in output
    assert "THORIO_WORKER_HEARTBEAT_OK worker_id=github-test" in output


def test_failed_heartbeat_never_emits_success_marker(capsys):
    class FailedHeartbeatClient(ReadyClient):
        def heartbeat(self, _load=0):
            raise ComputeWorkerError("coordinator heartbeat failed")

    run_worker(FailedHeartbeatClient(), idle_seconds=0.01, heartbeat_seconds=0.01, stop_event=StopAfterFirstWait())
    output = capsys.readouterr().out
    assert "THORIO_WORKER_REGISTERED worker_id=github-test" in output
    assert "THORIO_WORKER_HEARTBEAT_OK" not in output
