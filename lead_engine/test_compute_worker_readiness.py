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



def test_worker_logs_coordinator_errors_before_retry(capsys):
    class FailedClaimClient(ReadyClient):
        def claim(self):
            raise ComputeWorkerError("coordinator HTTP 503: temporary outage")

    run_worker(FailedClaimClient(), idle_seconds=0.01, heartbeat_seconds=0.01, stop_event=StopAfterFirstWait())
    output = capsys.readouterr().out
    assert "THORIO_WORKER_COORDINATOR_ERROR worker_id=github-test" in output
    assert "coordinator HTTP 503: temporary outage" in output


def test_worker_logs_task_failure_and_failed_release(capsys):
    class FailedTaskClient(ReadyClient):
        def __init__(self):
            super().__init__()
            self.claimed = False

        def claim(self):
            if self.claimed:
                return None
            self.claimed = True
            return {
                "task_id": "task-failed",
                "lease_token": "lease-token",
                "payload": {"kind": "unsupported-kind"},
            }

        def release(self, task_id, lease_token, error):
            raise ComputeWorkerError("coordinator rejected release")

    run_worker(FailedTaskClient(), idle_seconds=0.01, heartbeat_seconds=999, stop_event=StopAfterFirstWait())
    output = capsys.readouterr().out
    assert "THORIO_WORKER_TASK_FAILED worker_id=github-test task_id=task-failed" in output
    assert "unsupported-kind" in output
    assert "THORIO_WORKER_TASK_RELEASE_FAILED worker_id=github-test task_id=task-failed" in output
