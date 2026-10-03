from __future__ import annotations

import json
import subprocess

import pytest

from .kaggle_free_compute import (
    KaggleFreeComputeConfig,
    KaggleFreeComputeError,
    KaggleFreeComputeProvider,
)


def _runner_factory(quota_remaining: str = "20.00h"):
    calls: list[list[str]] = []
    status_calls = 0

    def runner(command, *, timeout, cwd=None):
        calls.append(list(command))
        if command[1:3] == ["quota", "--format"]:
            payload = [
                {
                    "resource": "GPU",
                    "used": "10.00h",
                    "remaining": quota_remaining,
                    "total": "30.00h",
                    "refreshAt": "2099-01-01T00:00:00+00:00",
                }
            ]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[1:3] == ["kernels", "status"]:
            nonlocal status_calls
            status_calls += 1
            if status_calls <= 2:
                return subprocess.CompletedProcess(command, 1, "", "Kernel not found")
            return subprocess.CompletedProcess(command, 0, "Status: Running", "")
        if command[1:3] == ["kernels", "push"]:
            return subprocess.CompletedProcess(command, 0, "Kernel pushed", "")
        if command[1:3] == ["kernels", "delete"]:
            return subprocess.CompletedProcess(command, 0, "Deleted", "")
        raise AssertionError(f"unexpected Kaggle command: {command}")

    return runner, calls


def _provider(runner):
    return KaggleFreeComputeProvider(
        KaggleFreeComputeConfig(
            username="example-user",
            kernel_slug="thorio-free-gpu-worker",
            repository_ref="feature/gpu-fabric-foundation",
        ),
        runner=runner,
        clock=lambda: 1_700_000_000.0,
    )


def test_discover_free_requires_observed_gpu_quota_and_returns_evidence():
    runner, calls = _runner_factory()
    provider = _provider(runner)

    offers = provider.discover_free()

    assert len(offers) == 1
    offer = offers[0]
    assert offer.provider_id == "kaggle"
    assert offer.no_cost is True
    assert offer.gpu_capable is True
    assert offer.capacity_evidence["gpu_quota_remaining_hours"] == 20.0
    assert offer.capacity_evidence["accelerator_requested"] == "NvidiaTeslaT4"
    assert offer.capacity_evidence["kernel_status"] == "not_found"
    assert "THORIO_COMPUTE_AUTH_TOKEN" not in json.dumps(offer.capacity_evidence)
    assert any(command[1:3] == ["quota", "--format"] for command in calls)


def test_discover_free_treats_kaggle_private_kernel_permission_error_as_absent():
    calls: list[list[str]] = []

    def runner(command, *, timeout, cwd=None):
        calls.append(list(command))
        if command[1:3] == ["quota", "--format"]:
            payload = [{
                "resource": "GPU",
                "used": "1.00h",
                "remaining": "20.00h",
                "total": "30.00h",
                "refreshAt": "2099-01-01T00:00:00+00:00",
            }]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[1:3] == ["kernels", "status"]:
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "Cannot access kernel 'example-user/thorio-free-gpu-worker' "
                "(Permission 'kernels.get' was denied).",
            )
        raise AssertionError(f"unexpected command: {command}")

    provider = _provider(runner)
    offers = provider.discover_free()

    assert len(offers) == 1
    assert offers[0].capacity_evidence["kernel_status"] == "not_found"
    assert any(command[1:3] == ["kernels", "status"] for command in calls)


def test_discover_free_fails_closed_when_quota_is_exhausted():
    runner, _ = _runner_factory("0.00h")
    provider = _provider(runner)

    with pytest.raises(KaggleFreeComputeError, match="quota is exhausted"):
        provider.discover_free()


def test_discover_free_does_not_offer_a_running_kernel():
    calls: list[list[str]] = []

    def runner(command, *, timeout, cwd=None):
        calls.append(list(command))
        if command[1:3] == ["quota", "--format"]:
            payload = [{
                "resource": "GPU",
                "used": "1.00h",
                "remaining": "20.00h",
                "total": "30.00h",
                "refreshAt": "2099-01-01T00:00:00+00:00",
            }]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[1:3] == ["kernels", "status"]:
            return subprocess.CompletedProcess(command, 0, "Status: Running", "")
        raise AssertionError(f"unexpected command: {command}")

    provider = _provider(runner)
    assert provider.discover_free() == ()


def test_acquire_free_creates_bounded_private_gpu_kernel_without_persisting_secrets():
    runner, calls = _runner_factory()
    provider = _provider(runner)
    offer = provider.discover_free()[0]

    acquired = provider.acquire_free(offer)

    assert acquired.provider_id == "kaggle"
    assert acquired.gpu_capable is True
    assert acquired.enrollment["kernel_ref"] == "example-user/thorio-free-gpu-worker"
    assert acquired.enrollment["free_only"] is True
    assert acquired.enrollment["physical_verification_required"] is True
    assert acquired.enrollment["provider_submission_accepted"] is True
    assert acquired.enrollment["provider_run_status"] == "running"
    assert acquired.enrollment["external_capacity_acquired"] is True

    push = next(command for command in calls if command[1:3] == ["kernels", "push"])
    assert "--accelerator" in push
    assert "NvidiaTeslaT4" in push
    assert "--timeout" in push

    assert "secret-value" not in json.dumps(acquired.enrollment)
    assert "THORIO_COMPUTE_AUTH_TOKEN" not in json.dumps(acquired.enrollment)


def test_acquire_free_builds_jit_runner_handoff_without_persisting_jit_token():
    runner, calls = _runner_factory()
    captured_script = {}

    def capturing_runner(command, *, timeout, cwd=None):
        if command[1:3] == ["kernels", "push"]:
            from pathlib import Path

            script_path = Path(command[command.index("-p") + 1]) / "thorio_worker.py"
            captured_script["content"] = script_path.read_text(encoding="utf-8")
        return runner(command, timeout=timeout, cwd=cwd)

    provider = KaggleFreeComputeProvider(
        KaggleFreeComputeConfig(
            username="example-user",
            kernel_slug="thorio-free-gpu-worker",
            repository_ref="feature/gpu-fabric-foundation",
            github_runner_jit_token_secret_label="THORIO_GITHUB_RUNNER_JIT_TOKEN",
            github_repository="DocSentinelX12/Thorio-Lead-Engine",
            github_runner_labels="thorio-free-gpu,cuda",
        ),
        runner=capturing_runner,
        clock=lambda: 1_700_000_000.0,
    )
    offer = provider.discover_free()[0]

    provider.acquire_free(offer)

    script = captured_script["content"]
    assert "get_secret(CONFIG[\"github_runner_jit_token_secret\"])" in script
    assert "GITHUB_RUNNER_JIT_TOKEN" in script
    assert "register-ephemeral-gpu-runner.sh" in script
    assert "thorio-free-gpu,cuda" in script
    assert "secret-value" not in script
    assert "jit-token-value" not in script


def test_acquire_free_passes_the_durable_acquisition_id_to_worker(tmp_path):
    runner, calls = _runner_factory()
    captured_script = {}

    def capturing_runner(command, *, timeout, cwd=None):
        if command[1:3] == ["kernels", "push"]:
            from pathlib import Path

            script_path = Path(command[command.index("-p") + 1]) / "thorio_worker.py"
            captured_script["content"] = script_path.read_text(encoding="utf-8")
        return runner(command, timeout=timeout, cwd=cwd)

    provider = _provider(capturing_runner)
    offer = provider.discover_free()[0]
    acquired = provider.acquire_free(offer)

    from .free_compute_acquisition import FreeComputeAcquisitionStore

    expected = FreeComputeAcquisitionStore.acquisition_id(offer)
    assert f'"acquisition_id": "{expected}"' in captured_script["content"]
    assert acquired.acquisition_id == expected



def test_acquire_free_rejects_stale_offer_identity():
    runner, _ = _runner_factory()
    provider = _provider(runner)
    offer = provider.discover_free()
    stale = offer[0].__class__(
        provider_id=offer[0].provider_id,
        domain_id=offer[0].domain_id,
        offer_id="stale",
        observed_at=offer[0].observed_at,
        expires_at=offer[0].expires_at,
        gpu_capable=True,
        no_cost=True,
        capacity_evidence=offer[0].capacity_evidence,
    )

    with pytest.raises(KaggleFreeComputeError, match="stale"):
        provider.acquire_free(stale)


def test_release_free_terminates_provider_kernel():
    runner, calls = _runner_factory()
    provider = _provider(runner)
    offer = provider.discover_free()[0]
    acquired = provider.acquire_free(offer)

    provider.release_free(acquired)

    assert any(
        command[1:3] == ["kernels", "delete"]
        and "example-user/thorio-free-gpu-worker" in command
        for command in calls
    )


def test_configuration_rejects_invalid_kernel_slug():
    with pytest.raises(ValueError, match="kernel_slug"):
        KaggleFreeComputeConfig(username="user", kernel_slug="Not Valid")


def test_configuration_rejects_paid_or_unknown_accelerator():
    with pytest.raises(ValueError, match="accelerator"):
        KaggleFreeComputeConfig(username="user", accelerator="A100-paid")



def test_acquire_free_waits_for_queued_provider_run_then_confirms_external_capacity():
    now = [1_700_000_000.0]
    status_calls = 0
    commands: list[list[str]] = []

    def runner(command, *, timeout, cwd=None):
        nonlocal status_calls
        commands.append(list(command))
        if command[1:3] == ["quota", "--format"]:
            payload = [{
                "resource": "GPU",
                "used": "10.00h",
                "remaining": "20.00h",
                "total": "30.00h",
                "refreshAt": "2099-01-01T00:00:00+00:00",
            }]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[1:3] == ["kernels", "status"]:
            status_calls += 1
            if status_calls <= 2:
                return subprocess.CompletedProcess(command, 1, "", "Kernel not found")
            if status_calls == 3:
                return subprocess.CompletedProcess(command, 0, "Status: Queued", "")
            return subprocess.CompletedProcess(command, 0, "Status: Running", "")
        if command[1:3] == ["kernels", "push"]:
            return subprocess.CompletedProcess(command, 0, "Kernel pushed", "")
        if command[1:3] == ["kernels", "delete"]:
            return subprocess.CompletedProcess(command, 0, "Deleted", "")
        raise AssertionError(f"unexpected Kaggle command: {command}")

    def sleeper(seconds):
        now[0] += seconds

    provider = KaggleFreeComputeProvider(
        KaggleFreeComputeConfig(
            username="example-user",
            kernel_slug="thorio-free-gpu-worker",
            repository_ref="feature/gpu-fabric-foundation",
            acquisition_ready_timeout_seconds=10,
            acquisition_ready_poll_interval_seconds=5,
        ),
        runner=runner,
        clock=lambda: now[0],
        sleeper=sleeper,
    )
    offer = provider.discover_free()[0]

    acquired = provider.acquire_free(offer)

    assert acquired.enrollment["provider_run_status"] == "running"
    assert acquired.enrollment["external_capacity_acquired"] is True
    assert not any(command[1:3] == ["kernels", "delete"] for command in commands)


def test_acquire_free_rejects_provider_run_that_does_not_reach_running_state():
    status_calls = 0
    commands: list[list[str]] = []

    def runner(command, *, timeout, cwd=None):
        nonlocal status_calls
        commands.append(list(command))
        if command[1:3] == ["quota", "--format"]:
            payload = [{
                "resource": "GPU",
                "used": "10.00h",
                "remaining": "20.00h",
                "total": "30.00h",
                "refreshAt": "2099-01-01T00:00:00+00:00",
            }]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[1:3] == ["kernels", "status"]:
            status_calls += 1
            if status_calls <= 2:
                return subprocess.CompletedProcess(command, 1, "", "Kernel not found")
            return subprocess.CompletedProcess(command, 0, "Status: Error", "")
        if command[1:3] == ["kernels", "push"]:
            return subprocess.CompletedProcess(command, 0, "Kernel pushed", "")
        if command[1:3] == ["kernels", "delete"]:
            return subprocess.CompletedProcess(command, 0, "Deleted", "")
        raise AssertionError(f"unexpected Kaggle command: {command}")

    provider = _provider(runner)
    offer = provider.discover_free()

    with pytest.raises(KaggleFreeComputeError, match="did not reach running state"):
        provider.acquire_free(offer[0])

    assert any(command[1:3] == ["kernels", "delete"] for command in commands)
