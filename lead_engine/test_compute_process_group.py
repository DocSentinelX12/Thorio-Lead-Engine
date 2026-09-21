import subprocess


def test_fabric_subprocess_starts_in_its_own_process_group(monkeypatch):
    from lead_engine.compute_worker import run_fabric_verification

    class Client:
        worker_id = "worker-1"
        def fabric_launch_plan(self, *args):
            return {
                "workers": [{"worker_id": "worker-1", "node_rank": 0, "process_count": 1}],
                "world_size": 2,
                "nnodes": 1,
                "rendezvous_endpoint": "10.0.0.5:29400",
                "rendezvous_id": "fabric:attempt-1:1",
            }
        def fabric_state(self, *args):
            return {"ok": True}
        def fabric_heartbeat(self, *args):
            return {"ok": True}

    class Runtime:
        timeout_seconds = 1
        def verify_local(self):
            return {"cuda": True, "nccl": True}
        def distributed_command(self, **kwargs):
            return ["torchrun"]

    class Process:
        returncode = 0
        def poll(self):
            return 0
        def communicate(self, timeout=None):
            return "", ""
        def terminate(self):
            pass
        def kill(self):
            pass
        def wait(self, timeout=None):
            return 0

    captured = {}
    process = Process()

    def popen(*args, **kwargs):
        captured.update(kwargs)
        return process

    monkeypatch.setattr(subprocess, "Popen", popen)

    run_fabric_verification(
        Client(),
        {"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"},
        rendezvous_endpoint="10.0.0.5:29400",
        heartbeat_seconds=1,
        runtime=Runtime(),
    )

    assert captured["start_new_session"] is True
