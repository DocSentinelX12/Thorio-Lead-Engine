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
            return subprocess.CompletedProcess(command, 1, "", "Kernel not found")
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

    push = next(command for command in calls if command[1:3] == ["kernels", "push"])
    assert "--accelerator" in push
    assert "NvidiaTeslaT4" in push
    assert "--timeout" in push

    assert "secret-value" not in json.dumps(acquired.enrollment)
    assert "THORIO_COMPUTE_AUTH_TOKEN" not in json.dumps(acquired.enrollment)


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

