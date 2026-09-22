import os
import signal
import subprocess


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

    def fabric_record_verification(self, *args):
        return {"ok": True}

    def fabric_converge(self, *args):
        return {"converged": True}


class Runtime:
    timeout_seconds = 1

    def verify_local(self):
        return {"cuda": True, "nccl": True}

    def distributed_command(self, **kwargs):
        return ["torchrun"]


def test_fabric_subprocess_starts_in_its_own_process_group(monkeypatch):
    from lead_engine.compute_worker import run_fabric_verification

    class Process:
        pid = 4242
        returncode = 0

        def poll(self):
            return 0

        def communicate(self, timeout=None):
            return "", ""

        def wait(self, timeout=None):
            return 0

    captured = {}
    process = Process()

    def popen(*args, **kwargs):
        captured.update(kwargs)
        return process

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(os, "killpg", lambda *args: (_ for _ in ()).throw(ProcessLookupError()))

    run_fabric_verification(
        Client(),
        {"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"},
        rendezvous_endpoint="10.0.0.5:29400",
        heartbeat_seconds=1,
        runtime=Runtime(),
    )

    if os.name == "posix":
        assert captured["start_new_session"] is True
    elif os.name == "nt":
        assert captured["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP


def test_fabric_timeout_escalates_to_process_group_kill(monkeypatch):
    from lead_engine.compute_worker import run_fabric_verification

    class Process:
        pid = 4343
        returncode = None

        def poll(self):
            return None

        def communicate(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired(["torchrun"], timeout)
            return "", ""

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(["torchrun"], timeout)

    signals = []
    process = Process()

    def killpg(pgid, sig):
        signals.append((pgid, sig))

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(os, "killpg", killpg)

    try:
        run_fabric_verification(
            Client(),
            {"attempt_id": "attempt-1", "generation": 1, "lease_token": "lease-1"},
            rendezvous_endpoint="10.0.0.5:29400",
            heartbeat_seconds=1,
            runtime=Runtime(),
        )
    except Exception as error:
        assert "timed out" in str(error)
    else:
        raise AssertionError("expected distributed launch timeout")

    if os.name == "posix":
        assert (4343, signal.SIGTERM) in signals
        assert (4343, signal.SIGKILL) in signals


def test_fabric_rank_failure_terminates_other_ranks_without_waiting_for_timeout(monkeypatch):
    from lead_engine.compute_worker import ComputeWorkerError, run_fabric_verification
    import subprocess
    import time

    class MultiClient:
        worker_id = "worker-1"
        def fabric_launch_plan(self, *args):
            return {"workers": [
                {"worker_id":"worker-1","node_rank":0,"process_count":2,"gpu_bindings":[
                    {"resource_id":"worker-1/gpu-0","gpu_id":"0","gpu_uuid":"GPU-0","rank":0,"local_rank":0},
                    {"resource_id":"worker-1/gpu-1","gpu_id":"1","gpu_uuid":"GPU-1","rank":1,"local_rank":1},
                ]},
                {"worker_id":"worker-2","node_rank":1,"process_count":1,"gpu_bindings":[
                    {"resource_id":"worker-2/gpu-0","gpu_id":"0","gpu_uuid":"GPU-2","rank":2,"local_rank":0},
                ]},
            ],"world_size":3,"nnodes":2,"rendezvous_endpoint":"10.0.0.5:29400","rendezvous_id":"fabric:attempt-1:1"}
        def fabric_state(self, *args): return {"ok": True}
        def fabric_heartbeat(self, *args): return {"ok": True}

    class Runtime:
        timeout_seconds = 30
        def verify_local(self): return {"cuda": True, "nccl": True}
        def verify_gpu_bindings(self, bindings): return {"verified": True}
        def distributed_process_command(self): return ["probe"]
        def validate_distributed_probe_output(self, *args, **kwargs):
            raise AssertionError("failed rank must abort before probe validation")

    class Process:
        def __init__(self, rank):
            self.rank=rank; self.terminated=False; self.killed=False
            self.returncode=1 if rank == 0 else None
        def poll(self): return self.returncode
        def communicate(self, timeout=None):
            if self.rank == 0: return "", "rank 0 failed"
            while not self.terminated and not self.killed: time.sleep(0.01)
            return "", "terminated"
        def wait(self, timeout=None):
            if self.rank != 0 and not self.terminated and not self.killed:
                raise subprocess.TimeoutExpired(["probe"], timeout)
            return self.returncode if self.returncode is not None else 143
        def terminate(self): self.terminated=True; self.returncode=143
        def kill(self): self.killed=True; self.returncode=137

    processes=[]
    def popen(*args, **kwargs):
        process=Process(len(processes)); processes.append(process); return process
    monkeypatch.setattr(subprocess, "Popen", popen)

    try:
        run_fabric_verification(
            MultiClient(),
            {"attempt_id":"attempt-1","generation":1,"lease_token":"lease-1"},
            rendezvous_endpoint="10.0.0.5:29400", heartbeat_seconds=1, runtime=Runtime(),
        )
    except ComputeWorkerError:
        pass
    else:
        raise AssertionError("distributed rank failure was not surfaced")

    assert len(processes) == 2
    assert processes[1].terminated is True or processes[1].killed is True
