from __future__ import annotations

import json

import pytest

from lead_engine.free_compute_acquisition import FreeComputeAcquisitionManager, FreeComputeAcquisitionStore
from lead_engine.lightning_free_compute import (
    LightningFreeComputeConfig,
    LightningFreeComputeError,
    LightningFreeComputeProvider,
)


def _config(**overrides):
    values = {
        "studio_name": "thorio-gpu-test",
        "machine": "T4",
        "teamspace": "default",
        "repo": "https://github.com/DocSentinelX12/Thorio-Lead-Engine.git",
        "ref": "feature/gpu-fabric-foundation",
        "free_hours_remaining": 2.0,
        "offer_ttl_seconds": 1200,
    }
    values.update(overrides)
    return LightningFreeComputeConfig(**values)


def test_lightning_provider_is_strictly_zero_cost():
    provider = LightningFreeComputeProvider(_config())
    offer = provider.discover_free()[0]
    assert offer.provider_id == "lightning_ai"
    assert offer.no_cost is True
    assert offer.gpu_capable is True
    assert offer.capacity_evidence["free_only_enforcement"] == "no_purchase_no_upgrade_no_paid_fallback"


def test_lightning_provider_refuses_unattested_free_budget():
    provider = LightningFreeComputeProvider(_config(free_hours_remaining=None))
    with pytest.raises(LightningFreeComputeError, match="free GPU budget is not attested"):
        provider.discover_free()


def test_lightning_provider_registers_through_existing_acquisition_boundary(tmp_path):
    manager = FreeComputeAcquisitionManager(FreeComputeAcquisitionStore(str(tmp_path / "acq.sqlite3")))
    provider = LightningFreeComputeProvider(_config())
    manager.register(provider)
    status = manager.status()
    assert status["provider_ids"] == ("lightning_ai",)
    discovery = manager.discover()
    assert discovery["provider_ids"] == ("lightning_ai",)
    assert len(discovery["offers"]) == 1


def test_lightning_domain_identity_is_stable_and_provider_scoped():
    first = LightningFreeComputeProvider(_config())._domain_id()
    second = LightningFreeComputeProvider(_config())._domain_id()
    assert first == second == "lightning_ai:default:thorio-gpu-test"


def test_lightning_bootstrap_evidence_requires_physical_cuda_execution():
    valid = {
        "gpu_discovery_state": "healthy",
        "physical_gpu_execution": [{"verified": True, "execution_backend": "cuda", "gpu_uuid": "GPU-1"}],
        "coordinator_enrollment": {"attempted": True, "status": "registered"},
    }
    assert LightningFreeComputeProvider._parse_bootstrap_evidence(
        "THORIO_LIGHTNING_WORKER_EVIDENCE " + json.dumps(valid)
    ) == valid
    with pytest.raises(LightningFreeComputeError, match="physical CUDA execution"):
        LightningFreeComputeProvider._parse_bootstrap_evidence(
            "THORIO_LIGHTNING_WORKER_EVIDENCE " + json.dumps({"gpu_discovery_state": "healthy"})
        )
    with pytest.raises(LightningFreeComputeError, match="coordinator enrollment"):
        LightningFreeComputeProvider._parse_bootstrap_evidence(
            "THORIO_LIGHTNING_WORKER_EVIDENCE " + json.dumps({
                "gpu_discovery_state": "healthy",
                "physical_gpu_execution": [{"verified": True, "execution_backend": "cuda", "gpu_uuid": "GPU-1"}],
            })
        )


def test_lightning_failed_bootstrap_stops_started_studio(monkeypatch):
    class FakeMachine:
        T4 = "T4"

    class FakeStudio:
        started = False
        stopped = False

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self, machine):
            self.started = True
            type(self).started = True

        def run_with_exit_code(self, command):
            return ("", "bootstrap failed", 1)

        def stop(self):
            self.stopped = True
            type(self).stopped = True

    provider = LightningFreeComputeProvider(_config())
    monkeypatch.setattr(provider, "_sdk", lambda: (FakeMachine, FakeStudio))
    monkeypatch.setattr(
        provider,
        "_ssh_bootstrap",
        lambda acquisition_id: (_ for _ in ()).throw(
            LightningFreeComputeError("Lightning authenticated SSH bootstrap exited 1")
        ),
    )
    offer = provider.discover_free()[0]

    with pytest.raises(LightningFreeComputeError, match="authenticated SSH bootstrap exited 1"):
        provider.acquire_free(offer)

    assert FakeStudio.started is True
    assert FakeStudio.stopped is True


def test_lightning_bootstrap_command_contains_exact_branch_and_acquisition_identity():
    provider = LightningFreeComputeProvider(_config())
    command = provider._bootstrap_command("acq-123")
    assert "--branch feature/gpu-fabric-foundation" in command
    assert "--acquisition-id acq-123" in command
    assert "lead_engine.lightning_worker_bootstrap" in command

def test_lightning_ssh_target_parsing(monkeypatch):
    class Result:
        returncode = 0
        stdout = (
            "host studio-alias\n"
            "hostname 203.0.113.10\n"
            "user lightning\n"
            "port 2222\n"
            "identityfile /home/runner/.ssh/lightning\n"
            "identityfile none\n"
        )
        stderr = ""

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr("lead_engine.lightning_free_compute.subprocess.run", fake_run)
    target = LightningFreeComputeProvider._ssh_connection_target("studio-alias")

    assert target == {
        "alias": "studio-alias",
        "hostname": "203.0.113.10",
        "user": "lightning",
        "port": "2222",
        "identity_files": ("/home/runner/.ssh/lightning",),
        "authentication_mode": "identity_file",
    }
    assert captured["command"] == ["ssh", "-G", "studio-alias"]


def test_lightning_ssh_bootstrap_requires_an_actual_authenticated_session(monkeypatch):
    provider = LightningFreeComputeProvider(_config())
    offer = provider.discover_free()[0]
    acquisition_id = provider._acquisition_id(offer)
    calls = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    evidence = {
        "provider_id": "lightning_ai",
        "acquisition_id": acquisition_id,
        "worker_id": "worker-1",
        "gpu_discovery_state": "healthy",
        "gpu_resources": [{"gpu_uuid": "GPU-1"}],
        "physical_gpu_execution": [
            {"verified": True, "execution_backend": "cuda", "gpu_uuid": "GPU-1"}
        ],
        "coordinator_enrollment": {"attempted": True, "status": "registered"},
    }

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[:3] == ["lightning", "ssh", "configure"]:
            return Result()
        if command[:2] == ["ssh", "-G"]:
            return Result(
                stdout="hostname 203.0.113.10\nuser lightning\nport 2222\nidentityfile /tmp/key\n"
            )
        return Result(
            stdout="THORIO_LIGHTNING_WORKER_EVIDENCE "
            + json.dumps(evidence)
            + "\n"
        )

    monkeypatch.setattr("lead_engine.lightning_free_compute.subprocess.run", fake_run)
    payload = provider._ssh_bootstrap(acquisition_id)

    assert payload["ssh"]["verification"] == "authenticated_ssh_session"
    assert payload["ssh"]["session_executed"] is True
    assert payload["ssh"]["worker_id"] == "worker-1"
    assert payload["ssh"]["gpu_uuids"] == ["GPU-1"]
    assert calls[0][0][:3] == ["lightning", "ssh", "configure"]
    assert calls[1][0] == ["ssh", "-G", "thorio-gpu-test"]
    assert calls[2][0][0] == "ssh"
    assert "BatchMode=yes" in calls[2][0]
    assert "thorio-gpu-test" in calls[2][0]
    assert "--acquisition-id" in calls[2][0][-1]


def test_lightning_worker_evidence_no_longer_claims_ssh_from_provider_documentation():
    provider = LightningFreeComputeProvider(_config())
    valid = {
        "provider_id": "lightning_ai",
        "acquisition_id": "acq-123",
        "worker_id": "worker-1",
        "gpu_discovery_state": "healthy",
        "gpu_resources": [{"gpu_uuid": "GPU-1"}],
        "physical_gpu_execution": [
            {"verified": True, "execution_backend": "cuda", "gpu_uuid": "GPU-1"}
        ],
        "coordinator_enrollment": {"attempted": True, "status": "registered"},
    }
    parsed = provider._parse_bootstrap_evidence(
        "THORIO_LIGHTNING_WORKER_EVIDENCE " + json.dumps(valid)
    )
    assert "ssh" not in parsed
