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
    kernel_exists = False
    kernel_ref = "example-user/thorio-free-gpu-worker"

    def runner(command, *, timeout, cwd=None):
        nonlocal status_calls, kernel_exists
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
        if command[1:3] == ["kernels", "list"]:
            rows = f"{kernel_ref},Thorio,test-user,2026-10-07T00:00:00Z,0\n" if kernel_exists else ""
            return subprocess.CompletedProcess(command, 0, "ref,title,author,lastRunTime,totalVotes\n" + rows, "")
        if command[1:3] == ["datasets", "list"]:
            return subprocess.CompletedProcess(command, 0, "ref,title\n", "")
        if command[1:3] == ["kernels", "status"]:
            status_calls += 1
            if status_calls <= 2:
                return subprocess.CompletedProcess(command, 1, "", "Kernel not found")
            return subprocess.CompletedProcess(command, 0, "Status: Running", "")
        if command[1:3] == ["kernels", "push"]:
            kernel_exists = True
            return subprocess.CompletedProcess(command, 0, "Kernel version 1 successfully pushed.", "")
        if command[1:3] == ["kernels", "delete"]:
            kernel_exists = False
            return subprocess.CompletedProcess(command, 0, "Deleted", "")
        if command[1:3] == ["datasets", "delete"]:
            return subprocess.CompletedProcess(command, 0, "Deleted", "")
        raise AssertionError(f"unexpected Kaggle command: {command}")

    return runner, calls

def _provider(runner):
    return KaggleFreeComputeProvider(
        KaggleFreeComputeConfig(
            username="example-user",
            kernel_slug="thorio-free-gpu-worker",
            repository_ref="main",
            github_runner_jit_token_dataset_slug="thorio-runner-credentials-test",
        ),
        runner=runner,
        clock=lambda: 1_700_000_000.0,
    )


def test_acquire_free_publishes_private_dataset_when_no_slug_is_configured(monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("GITHUB_RUNNER_JIT_TOKEN", "jit-token-value")
    calls = []
    captured = {}

    def runner(command, *, timeout, cwd=None):
        calls.append(list(command))
        if command[1:3] == ["quota", "--format"]:
            payload = [{
                "resource": "GPU",
                "used": "10.00h",
                "remaining": "20.00h",
                "total": "30.00h",
                "refreshAt": "2099-01-01T00:00:00+00:00",
            }]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[1:3] == ["datasets", "create"]:
            dataset_dir = Path(command[command.index("-p") + 1])
            captured["dataset_metadata"] = json.loads(
                (dataset_dir / "dataset-metadata.json").read_text(encoding="utf-8")
            )
            captured["dataset_token"] = (dataset_dir / "runner-token").read_text(encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "Upload successful: runner-token (32B)\nDataset created", "")
        if command[1:3] == ["kernels", "list"]:
            return subprocess.CompletedProcess(command, 0, "ref,title,author,lastRunTime,totalVotes\nexample-user/thorio-free-gpu-worker,Thorio,test-user,2026-10-07T00:00:00Z,0\n", "")
        if command[1:3] == ["datasets", "list"]:
            dataset_ref = captured["dataset_metadata"]["id"]
            return subprocess.CompletedProcess(command, 0, "ref,title\n" + dataset_ref + ",Thorio credential\n", "")
        if command[1:3] == ["kernels", "push"]:
            kernel_dir = Path(command[command.index("-p") + 1])
            captured["kernel_metadata"] = json.loads(
                (kernel_dir / "kernel-metadata.json").read_text(encoding="utf-8")
            )
            captured["worker_script"] = (kernel_dir / "thorio_worker.py").read_text(encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "Kernel version 1 successfully pushed.", "")
        if command[1:3] == ["kernels", "delete"]:
            return subprocess.CompletedProcess(command, 0, "Deleted", "")
        if command[1:3] == ["datasets", "delete"]:
            return subprocess.CompletedProcess(command, 0, "Deleted", "")
        raise AssertionError(f"unexpected Kaggle command: {command}")

    provider = KaggleFreeComputeProvider(
        KaggleFreeComputeConfig(
            username="example-user",
            kernel_slug="thorio-free-gpu-worker",
            github_runner_jit_token_dataset_slug="",
        ),
        runner=runner,
        clock=lambda: 1_700_000_000.0,
    )
    provider._kernel_status = lambda kernel_ref: "not_found"
    provider._runner_bootstrap_script = lambda: "echo runner"
    offer = provider.discover_free()[0]
    provider._kernel_status = lambda kernel_ref: "running"

    acquired = provider.acquire_free(offer)

    dataset_slug = acquired.enrollment["runner_credential_dataset_slug"]
    assert "isPrivate" not in captured["dataset_metadata"]
    assert captured["dataset_token"] == "jit-token-value"
    assert captured["kernel_metadata"]["dataset_sources"] == [f"example-user/{dataset_slug}"]
    assert acquired.enrollment["runner_credential_dataset_owned"] is True
    assert "jit-token-value" not in captured["worker_script"]
    assert "UserSecretsClient" not in captured["worker_script"]
    assert "thorio-worker.log" in captured["worker_script"]
    assert "sys.excepthook" in captured["worker_script"]
    assert "stdout=log" in captured["worker_script"]
    compile(captured["worker_script"], "thorio_worker.py", "exec")

    provider.release_free(acquired)

    assert any(command[1:3] == ["datasets", "delete"] for command in calls)
    assert any(command[1:3] == ["kernels", "delete"] for command in calls)



def test_kernel_cleanup_skips_delete_when_owner_inventory_proves_absent():
    runner, calls = _runner_factory()
    provider = _provider(runner)

    deleted = provider._delete_kernel_if_listed("example-user/thorio-free-gpu-worker")

    assert deleted is False
    assert not any(command[1:3] == ["kernels", "delete"] for command in calls)
    assert any(command[1:3] == ["kernels", "list"] and "--search" not in command for command in calls)


def test_dataset_cleanup_skips_delete_when_owner_inventory_proves_absent():
    runner, calls = _runner_factory()
    provider = _provider(runner)

    provider._delete_private_runner_credential_dataset("thorio-runner-credentials-12345-1")

    assert not any(command[1:3] == ["datasets", "delete"] for command in calls)
    assert any(command[1:3] == ["datasets", "list"] and "--search" not in command for command in calls)


def test_failed_kernel_output_is_captured_before_cleanup_and_secrets_are_redacted(monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("GITHUB_RUNNER_JIT_TOKEN", "do-not-log-this-token")
    calls = []
    base_runner, _ = _runner_factory()

    def runner(command, *, timeout, cwd=None):
        calls.append(list(command))
        if command[1:3] == ["kernels", "output"]:
            output_dir = Path(command[command.index("-p") + 1])
            (output_dir / "thorio-worker.log").write_text(
                "KAGGLE WORKER ROOT CAUSE: JIT configuration rejected\ndo-not-log-this-token",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "Output downloaded", "")
        return base_runner(command, timeout=timeout, cwd=cwd)

    provider = _provider(runner)
    offer = provider.discover_free()[0]
    provider._runner_bootstrap_script = lambda: "echo runner"
    provider._kernel_status = lambda kernel_ref: "failed"

    with pytest.raises(KaggleFreeComputeError, match="KAGGLE WORKER ROOT CAUSE") as error:
        provider.acquire_free(offer)

    message = str(error.value)
    assert "[REDACTED]" in message
    assert "do-not-log-this-token" not in message
    output_index = next(i for i, command in enumerate(calls) if command[1:3] == ["kernels", "output"])
    delete_index = next(i for i, command in enumerate(calls) if command[1:3] == ["kernels", "delete"])
    assert output_index < delete_index


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
        if command[1:3] == ["kernels", "list"]:
            return subprocess.CompletedProcess(command, 0, "ref,title,author,lastRunTime,totalVotes\n", "")
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
    listing_commands = [command for command in calls if command[1:3] == ["kernels", "list"]]
    assert listing_commands
    assert "--mine" in listing_commands[0]
    assert "--search" not in listing_commands[0]
    assert "--page" in listing_commands[0]
    assert "--page-size" in listing_commands[0]


def test_discover_free_fails_closed_when_permission_denied_kernel_is_listed():
    def runner(command, *, timeout, cwd=None):
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
        if command[1:3] == ["kernels", "list"]:
            return subprocess.CompletedProcess(
                command,
                0,
                "ref,title,author,lastRunTime,totalVotes\n"
                "example-user/thorio-free-gpu-worker,thorio-free-gpu-worker,example-user,2026-10-08,0\n",
                "",
            )
        raise AssertionError(f"unexpected command: {command}")

    provider = _provider(runner)
    with pytest.raises(KaggleFreeComputeError, match="refusing to treat a permission error as absence"):
        provider.discover_free()


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
        if command[1:3] == ["kernels", "list"]:
            return subprocess.CompletedProcess(command, 0, "ref,title,author,lastRunTime,totalVotes\n", "")
        if command[1:3] == ["kernels", "status"]:
            return subprocess.CompletedProcess(command, 0, "Status: Running", "")
        raise AssertionError(f"unexpected command: {command}")

    provider = _provider(runner)
    assert provider.discover_free() == ()


def test_acquire_free_creates_bounded_gpu_kernel_without_persisting_secrets():
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

            kernel_dir = Path(command[command.index("-p") + 1])
            script_path = kernel_dir / "thorio_worker.py"
            metadata_path = kernel_dir / "kernel-metadata.json"
            captured_script["content"] = script_path.read_text(encoding="utf-8")
            captured_script["metadata"] = json.loads(metadata_path.read_text(encoding="utf-8"))
        return runner(command, timeout=timeout, cwd=cwd)

    provider = KaggleFreeComputeProvider(
        KaggleFreeComputeConfig(
            username="example-user",
            kernel_slug="thorio-free-gpu-worker",
            repository_ref="main",
            github_runner_jit_token_dataset_slug="thorio-runner-credentials-test",
            github_repository="DocSentinelX12/Thorio-Lead-Engine",
            github_runner_name="thorio-free-gpu-worker-123",
            github_runner_labels="self-hosted,thorio-free-gpu,cuda",
        ),
        runner=capturing_runner,
        clock=lambda: 1_700_000_000.0,
    )
    offer = provider.discover_free()[0]

    provider.acquire_free(offer)

    script = captured_script["content"]
    assert "def get_runner_token():" in script
    assert 'input_root = Path("/kaggle/input")' in script
    assert 'secret_file = input_root / dataset_slug / "runner-token"' in script
    assert "UserSecretsClient" not in script
    assert "GITHUB_RUNNER_JIT_TOKEN" in script
    assert 'RUNNER_ROOT"] = "/kaggle/working/actions-runner"' in script
    assert "register-ephemeral-gpu-runner.sh" in script
    assert "self-hosted,thorio-free-gpu,cuda" in script
    assert 'git", "clone"' not in script
    assert "GITHUB_RUNNER_JIT_TOKEN" in script
    assert "KAGGLE WORKER PHASE: reading the run-scoped private credential dataset." in script
    assert "mounted_input_directories=" in script
    assert "traceback.print_exception(exc_type, exc, tb, file=sys.stderr)" in script
    assert "KAGGLE WORKER PHASE: invoking ephemeral runner bootstrap." in script
    assert "GPU RUNNER PHASE: requesting GitHub JIT runner configuration." in script
    assert "GPU RUNNER JIT CREATED:" in script
    assert "GPU RUNNER PHASE: launching Actions runner with JIT configuration." in script
    assert '"github_runner_name": "thorio-free-gpu-worker-123"' in script
    assert 'os.environ["RUNNER_NAME"] = CONFIG["github_runner_name"] or' in script
    assert 'os.environ.pop("GITHUB_RUNNER_JIT_TOKEN", None)' in script
    assert "secret-value" not in script
    assert "jit-token-value" not in script


def test_acquire_free_never_embeds_provisioner_credentials_in_public_kernel(monkeypatch):
    runner, calls = _runner_factory()
    captured_script = {}
    monkeypatch.setenv("THORIO_KAGGLE_ENABLED", "1")
    monkeypatch.setenv("THORIO_KAGGLE_USERNAME", "example-user")
    monkeypatch.setenv("THORIO_KAGGLE_KERNEL_SLUG", "thorio-free-gpu-worker")
    monkeypatch.setenv("THORIO_KAGGLE_SECRET_DATASET_SLUG", "thorio-runner-credentials-test")
    monkeypatch.setenv("THORIO_KAGGLE_REPOSITORY_REF", "main")
    monkeypatch.setenv("THORIO_KAGGLE_GITHUB_RUNNER_NAME", "thorio-free-gpu-worker-123")
    monkeypatch.setenv("THORIO_COMPUTE_AUTH_TOKEN", "coordinator-token-value")
    monkeypatch.setenv("THORIO_COMPUTE_COORDINATOR_URL", "https://coordinator.example.test")
    monkeypatch.setenv("GITHUB_RUNNER_JIT_TOKEN", "jit-token-value")

    def capturing_runner(command, *, timeout, cwd=None):
        if command[1:3] == ["kernels", "push"]:
            from pathlib import Path

            kernel_dir = Path(command[command.index("-p") + 1])
            script_path = kernel_dir / "thorio_worker.py"
            metadata_path = kernel_dir / "kernel-metadata.json"
            captured_script["content"] = script_path.read_text(encoding="utf-8")
            captured_script["metadata"] = json.loads(metadata_path.read_text(encoding="utf-8"))
        return runner(command, timeout=timeout, cwd=cwd)

    provider = KaggleFreeComputeProvider.from_environment()
    provider._runner = capturing_runner
    provider._clock = lambda: 1_700_000_000.0
    provider._sleeper = lambda _: None
    offer = provider.discover_free()[0]

    provider.acquire_free(offer)

    script = captured_script["content"]
    metadata = captured_script["metadata"]
    assert metadata["id"] == "example-user/thorio-free-gpu-worker"
    assert metadata["title"] == "thorio-free-gpu-worker"
    assert metadata["is_private"] is False
    assert metadata["dataset_sources"] == ["example-user/thorio-runner-credentials-test"]
    assert '"github_runner_jit_token_dataset_slug": "thorio-runner-credentials-test"' in script
    assert '"coordinator_token":' not in script
    assert '"coordinator_url":' not in script
    assert '"github_runner_jit_token":' not in script
    assert "coordinator-token-value" not in script
    assert "https://coordinator.example.test" not in script
    assert "jit-token-value" not in script
    assert 'credential("coordinator_token", "coordinator_token_secret")' not in script
    assert 'credential("coordinator_url", "coordinator_url_secret")' not in script
    assert "get_runner_token()" in script
    assert "UserSecretsClient" not in script
    assert "runner-token" in script


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



def test_acquire_free_waits_for_running_provider_status():
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
        if command[1:3] == ["kernels", "list"]:
            return subprocess.CompletedProcess(command, 0, "ref,title,author,lastRunTime,totalVotes\nexample-user/thorio-free-gpu-worker,Thorio,test-user,2026-10-07T00:00:00Z,0\n", "")
        if command[1:3] == ["kernels", "status"]:
            status_calls += 1
            if status_calls <= 2:
                return subprocess.CompletedProcess(command, 1, "", "Kernel not found")
            if status_calls == 3:
                return subprocess.CompletedProcess(command, 0, "Status: Queued", "")
            return subprocess.CompletedProcess(command, 0, "Status: Running", "")
        if command[1:3] == ["kernels", "push"]:
            return subprocess.CompletedProcess(command, 0, "Kernel version 1 successfully pushed.", "")
        if command[1:3] == ["kernels", "delete"]:
            return subprocess.CompletedProcess(command, 0, "Deleted", "")
        raise AssertionError(f"unexpected Kaggle command: {command}")

    def sleeper(seconds):
        now[0] += seconds

    provider = KaggleFreeComputeProvider(
        KaggleFreeComputeConfig(
            username="example-user",
            kernel_slug="thorio-free-gpu-worker",
            repository_ref="main",
            github_runner_jit_token_dataset_slug="thorio-runner-credentials-test",
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
    assert any(command[1:3] == ["kernels", "status"] for command in commands)


def test_acquire_free_fails_when_provider_never_reaches_running():
    now = [1_700_000_000.0]
    commands: list[list[str]] = []

    def runner(command, *, timeout, cwd=None):
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
        if command[1:3] == ["kernels", "list"]:
            return subprocess.CompletedProcess(command, 0, "ref,title,author,lastRunTime,totalVotes\nexample-user/thorio-free-gpu-worker,Thorio,test-user,2026-10-07T00:00:00Z,0\n", "")
        if command[1:3] == ["kernels", "status"]:
            if sum(command[1:3] == ["kernels", "status"] for command in commands) == 1:
                return subprocess.CompletedProcess(command, 1, "", "Kernel not found")
            return subprocess.CompletedProcess(command, 0, "Status: Queued", "")
        if command[1:3] == ["kernels", "push"]:
            return subprocess.CompletedProcess(command, 0, "Kernel version 1 successfully pushed.", "")
        if command[1:3] == ["kernels", "delete"]:
            return subprocess.CompletedProcess(command, 0, "Deleted", "")
        raise AssertionError(f"unexpected Kaggle command: {command}")

    def sleeper(seconds):
        now[0] += seconds

    provider = KaggleFreeComputeProvider(
        KaggleFreeComputeConfig(
            username="example-user",
            kernel_slug="thorio-free-gpu-worker",
            repository_ref="main",
            github_runner_jit_token_dataset_slug="thorio-runner-credentials-test",
            acquisition_ready_timeout_seconds=10,
            acquisition_ready_poll_interval_seconds=5,
        ),
        runner=runner,
        clock=lambda: now[0],
        sleeper=sleeper,
    )
    offer = provider.discover_free()[0]

    with pytest.raises(KaggleFreeComputeError, match="did not reach running state before timeout"):
        provider.acquire_free(offer)

    assert any(command[1:3] == ["kernels", "delete"] for command in commands)

def test_acquire_free_retries_transient_kaggle_batch_session_limit():
    push_calls = 0

    status_calls = 0
    now = [1_700_000_000.0]
    def runner(command, *, timeout, cwd=None):
        nonlocal push_calls, status_calls
        if command[1:3] == ["quota", "--format"]:
            payload = [{
                "resource": "GPU",
                "used": "10.00h",
                "remaining": "20.00h",
                "total": "30.00h",
                "refreshAt": "2099-01-01T00:00:00+00:00",
            }]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[1:3] == ["kernels", "list"]:
            return subprocess.CompletedProcess(command, 0, "ref,title,author,lastRunTime,totalVotes\n", "")
        if command[1:3] == ["kernels", "status"]:
            status_calls += 1
            if status_calls == 1:
                return subprocess.CompletedProcess(command, 1, "", "Kernel not found")
            return subprocess.CompletedProcess(command, 0, "Status: Running", "")
        if command[1:3] == ["kernels", "push"]:
            push_calls += 1
            if push_calls == 1:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    "Kernel push error: Maximum batch GPU session count of 2 reached.",
                    "",
                )
            return subprocess.CompletedProcess(command, 0, "Kernel version 1 successfully pushed.", "")
        if command[1:3] == ["kernels", "delete"]:
            return subprocess.CompletedProcess(command, 0, "Deleted", "")
        raise AssertionError(f"unexpected Kaggle command: {command}")

    provider = KaggleFreeComputeProvider(
        KaggleFreeComputeConfig(
            username="example-user",
            kernel_slug="thorio-free-gpu-worker",
            github_runner_jit_token_dataset_slug="thorio-runner-credentials-test",
            acquisition_ready_timeout_seconds=5,
            acquisition_ready_poll_interval_seconds=0.01,
        ),
        runner=runner,
        clock=lambda: now[0],
        sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )
    acquired = provider.acquire_free(provider.discover_free()[0])

    assert push_calls == 2
    assert acquired.enrollment["provider_run_status"] == "running"
    assert status_calls == 2


def test_acquire_free_rejects_provider_push_without_success_marker():
    commands: list[list[str]] = []

    def runner(command, *, timeout, cwd=None):
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
        if command[1:3] == ["kernels", "list"]:
            return subprocess.CompletedProcess(command, 0, "ref,title,author,lastRunTime,totalVotes\n", "")
        if command[1:3] == ["kernels", "status"]:
            return subprocess.CompletedProcess(command, 1, "", "Kernel not found")
        if command[1:3] == ["kernels", "push"]:
            return subprocess.CompletedProcess(command, 0, "Kernel push error: simulated failure", "")
        if command[1:3] == ["kernels", "delete"]:
            return subprocess.CompletedProcess(command, 0, "Deleted", "")
        raise AssertionError(f"unexpected Kaggle command: {command}")

    provider = _provider(runner)
    offer = provider.discover_free()[0]

    with pytest.raises(KaggleFreeComputeError, match="accepted submission"):
        provider.acquire_free(offer)

    assert not any(command[1:3] == ["kernels", "delete"] for command in commands)


def test_embedded_runner_bootstrap_tracks_current_actions_runner_release():
    from pathlib import Path

    script = (Path(__file__).parents[1] / "infra" / "free-compute" / "register-ephemeral-gpu-runner.sh").read_text(encoding="utf-8")
    assert 'RUNNER_VERSION="${RUNNER_VERSION:-latest}"' in script
    assert 'GITHUB_API_URL}/repos/actions/runner/releases/latest' in script


@pytest.mark.parametrize("resource_type,empty_output", [
    ("kernels", "No kernels found"),
    ("datasets", "No datasets found"),
])
def test_inventory_plain_text_empty_sentinel_is_treated_as_absent(resource_type, empty_output):
    def runner(command, *, timeout, cwd=None):
        if command[1:3] == [resource_type, "list"]:
            return subprocess.CompletedProcess(command, 0, empty_output + "\n", "")
        raise AssertionError(f"unexpected Kaggle command: {command}")

    provider = _provider(runner)
    if resource_type == "kernels":
        assert provider._kernel_is_listed("example-user/thorio-free-gpu-worker") is False
    else:
        assert provider._dataset_is_listed("example-user/thorio-runner-credentials-12345-1") is False


def test_inventory_unrecognized_headerless_response_still_fails_closed():
    def runner(command, *, timeout, cwd=None):
        if command[1:3] == ["datasets", "list"]:
            return subprocess.CompletedProcess(command, 0, "Unexpected API response\n", "")
        raise AssertionError(f"unexpected Kaggle command: {command}")

    provider = _provider(runner)
    with pytest.raises(KaggleFreeComputeError, match="no CSV header"):
        provider._dataset_is_listed("example-user/thorio-runner-credentials-12345-1")
