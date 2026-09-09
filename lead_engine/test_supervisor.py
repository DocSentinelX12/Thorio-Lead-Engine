from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from .supervisor import SupervisorConfig, SupervisorConfigurationError, WorkerSupervisor


def test_supervisor_requires_worker_command():
    with pytest.raises(SupervisorConfigurationError):
        SupervisorConfig(command=(), heartbeat_file=Path("heartbeat"))


def test_supervisor_requires_positive_heartbeat_interval():
    with pytest.raises(SupervisorConfigurationError):
        SupervisorConfig(command=("python", "-c", "pass"), heartbeat_file=Path("heartbeat"), heartbeat_interval_seconds=0)


def test_supervisor_restarts_worker_after_exit(tmp_path):
    config = SupervisorConfig(
        command=("worker",),
        heartbeat_file=tmp_path / "heartbeat",
        heartbeat_interval_seconds=0.01,
        restart_delay_seconds=0,
        max_restart_delay_seconds=0,
    )
    supervisor = WorkerSupervisor(config)

    first = MagicMock()
    first.poll.side_effect = [None, 17]
    second = MagicMock()
    second.poll.side_effect = [None]

    supervisor._stopping = False

    def fake_popen(_command):
        if not hasattr(fake_popen, "calls"):
            fake_popen.calls = 0
        fake_popen.calls += 1
        if fake_popen.calls == 1:
            return first
        supervisor._stopping = True
        return second

    with patch("lead_engine.supervisor.subprocess.Popen", side_effect=fake_popen), patch("lead_engine.supervisor.time.sleep"):
        assert supervisor.run() == 0

    assert fake_popen.calls == 2
    assert first.poll.call_count >= 1
    assert (tmp_path / "heartbeat").exists()
    assert "restart_count=1" in (tmp_path / "heartbeat").read_text(encoding="utf-8")


def test_supervisor_heartbeat_is_atomic(tmp_path):
    config = SupervisorConfig(command=("worker",), heartbeat_file=tmp_path / "nested" / "heartbeat")
    supervisor = WorkerSupervisor(config)

    supervisor._heartbeat("running", 3)

    assert config.heartbeat_file.exists()
    assert not config.heartbeat_file.with_suffix(".tmp").exists()
    text = config.heartbeat_file.read_text(encoding="utf-8")
    assert "state=running" in text
    assert "restart_count=3" in text
