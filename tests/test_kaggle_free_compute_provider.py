import json
import subprocess

from lead_engine.free_compute_acquisition import (
    FreeComputeAcquisitionManager,
    FreeComputeAcquisitionStore,
)
from lead_engine.kaggle_free_compute_provider import KaggleFreeGPUProvider


def _runner_factory():
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["kaggle", "quota", "--format"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    [
                        {
                            "resource": "GPU",
                            "used": "5.00h",
                            "remaining": "25.00h",
                            "total": "30.00h",
                            "refreshAt": "2026-10-01T00:00:00+00:00",
                        }
                    ]
                ),
                stderr="",
            )
        if command[:3] == ["kaggle", "kernels", "push"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Kernel pushed successfully.",
                stderr="",
            )
        if command[:3] == ["kaggle", "kernels", "delete"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Kernel deleted.",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command}")

    return runner, calls


def _kernel_dir(tmp_path):
    directory = tmp_path / "kaggle-kernel"
    directory.mkdir()
    (directory / "kernel-metadata.json").write_text(
        json.dumps(
            {
                "id": "test-owner/thorio-gpu-smoke",
                "title": "Thorio GPU Smoke",
                "code_file": "run.py",
                "language": "python",
                "kernel_type": "script",
                "is_private": "true",
                "enable_gpu": "true",
                "enable_internet": "true",
            }
        ),
        encoding="utf-8",
    )
    (directory / "run.py").write_text(
        "print('thorio kaggle gpu adapter smoke')\n",
        encoding="utf-8",
    )
    return directory


def test_kaggle_adapter_discovers_only_when_gpu_quota_is_available(tmp_path):
    runner, calls = _runner_factory()
    provider = KaggleFreeGPUProvider(
        kernel_dir=_kernel_dir(tmp_path),
        runner=runner,
        clock=lambda: 100.0,
    )

    offers = provider.discover_free()

    assert len(offers) == 1
    offer = offers[0]
    assert offer.provider_id == "kaggle"
    assert offer.domain_id == "kaggle-free-gpu"
    assert offer.offer_id == "test-owner/thorio-gpu-smoke:NvidiaTeslaT4"
    assert offer.no_cost is True
    assert offer.gpu_capable is True
    assert offer.capacity_evidence["remaining_gpu_hours"] == 25.0
    assert calls == [["kaggle", "quota", "--format", "json"]]


def test_kaggle_adapter_acquires_through_official_kernel_push(tmp_path):
    runner, calls = _runner_factory()
    provider = KaggleFreeGPUProvider(
        kernel_dir=_kernel_dir(tmp_path),
        runner=runner,
        timeout_seconds=1800,
        clock=lambda: 100.0,
    )
    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store)
    manager.register(provider)

    offer = provider.discover_free()[0]
    acquired = manager.acquire(offer)

    assert acquired.provider_id == "kaggle"
    assert acquired.gpu_capable is True
    assert acquired.enrollment["provider_submission_accepted"] is True
    assert acquired.enrollment["kernel_ref"] == "test-owner/thorio-gpu-smoke"
    assert acquired.expires_at == 1900.0
    assert calls[-1] == [
        "kaggle",
        "kernels",
        "push",
        "--path",
        str(_kernel_dir(tmp_path)),
        "--accelerator",
        "NvidiaTeslaT4",
        "--timeout",
        "1800",
    ]
    assert store.records()[0]["status"] == "acquired"


def test_kaggle_adapter_release_deletes_only_the_acquired_kernel(tmp_path):
    runner, calls = _runner_factory()
    provider = KaggleFreeGPUProvider(
        kernel_dir=_kernel_dir(tmp_path),
        runner=runner,
        clock=lambda: 100.0,
    )
    offer = provider.discover_free()[0]
    store = FreeComputeAcquisitionStore(str(tmp_path / "acquisition.sqlite3"))
    manager = FreeComputeAcquisitionManager(store)
    manager.register(provider)
    acquired = manager.acquire(offer)

    manager.release(acquired)

    assert calls[-1] == [
        "kaggle",
        "kernels",
        "delete",
        "test-owner/thorio-gpu-smoke",
        "--yes",
    ]
    assert store.records()[0]["status"] == "released"


def test_kaggle_adapter_does_not_claim_capacity_when_gpu_quota_is_exhausted(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                [
                    {
                        "resource": "GPU",
                        "used": "30.00h",
                        "remaining": "0.00h",
                        "total": "30.00h",
                        "refreshAt": "2026-10-01T00:00:00+00:00",
                    }
                ]
            ),
            stderr="",
        )

    provider = KaggleFreeGPUProvider(
        kernel_dir=_kernel_dir(tmp_path),
        runner=runner,
        clock=lambda: 100.0,
    )

    assert provider.discover_free() == ()
    assert calls == [["kaggle", "quota", "--format", "json"]]
