"""Concrete zero-cost Kaggle GPU provider adapter.

Kaggle Notebooks expose free GPU compute with a provider-enforced weekly GPU
quota. This adapter treats that quota as the only acquisition budget. It never
uses a paid fallback, never stores Kaggle credentials in durable acquisition
records, and hands acquired workers to the existing authenticated worker
registration and physical GPU discovery path.

The adapter intentionally uses the Kaggle CLI as an external process. The
repository remains Python 3.10 compatible while current Kaggle CLI releases
may require a newer Python runtime.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .compute_fabric import ProviderCapabilities
from .free_compute_acquisition import (
    AcquiredCompute,
    FreeComputeAcquisitionError,
    FreeComputeOffer,
    FreeComputeProvider,
)


class KaggleFreeComputeError(FreeComputeAcquisitionError):
    """Raised when Kaggle cannot satisfy the zero-cost acquisition contract."""


@dataclass(frozen=True)
class KaggleFreeComputeConfig:
    username: str
    kernel_slug: str = "thorio-free-gpu-worker"
    accelerator: str = "NvidiaTeslaT4"
    repository_url: str = "https://github.com/DocSentinelX12/Thorio-Lead-Engine.git"
    repository_ref: str = "main"
    # The JIT token is delivered through a run-scoped private Kaggle dataset.
    github_runner_jit_token_dataset_slug: str = ""
    github_repository: str = "DocSentinelX12/Thorio-Lead-Engine"
    github_runner_name: str = ""
    github_runner_labels: str = "self-hosted,thorio-free-gpu,cuda"
    minimum_remaining_hours: float = 1.0
    maximum_runtime_hours: float = 6.0
    command_timeout_seconds: int = 120
    acquisition_ready_timeout_seconds: int = 60
    acquisition_ready_poll_interval_seconds: float = 5.0
    kaggle_binary: str = "kaggle"

    def __post_init__(self) -> None:
        if not self.username.strip():
            raise ValueError("Kaggle username is required")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}", self.kernel_slug):
            raise ValueError("kernel_slug must be a valid Kaggle kernel slug")
        if self.accelerator not in {
            "NvidiaTeslaT4",
            "NvidiaL4",
            "NvidiaTeslaA100",
            "NvidiaH100",
            "NvidiaRtxPro6000",
        }:
            raise ValueError("accelerator is not an allowed non-competition Kaggle GPU")
        if not self.repository_url.startswith("https://"):
            raise ValueError("repository_url must use HTTPS")
        if not self.repository_ref.strip():
            raise ValueError("repository_ref is required")
        if self.github_runner_jit_token_dataset_slug and not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{0,49}", self.github_runner_jit_token_dataset_slug
        ):
            raise ValueError("GitHub runner JIT token dataset slug must be a valid Kaggle dataset slug")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.github_repository):
            raise ValueError("github_repository must use owner/repository form")
        if self.github_runner_name and not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", self.github_runner_name):
            raise ValueError("github_runner_name must be a valid 1-64 character runner name")
        if not any(item.strip() for item in self.github_runner_labels.split(",")):
            raise ValueError("github_runner_labels must contain at least one label")
        if self.minimum_remaining_hours <= 0:
            raise ValueError("minimum_remaining_hours must be positive")
        if self.maximum_runtime_hours <= 0:
            raise ValueError("maximum_runtime_hours must be positive")
        if self.command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")
        if self.acquisition_ready_timeout_seconds <= 0:
            raise ValueError("acquisition_ready_timeout_seconds must be positive")
        if self.acquisition_ready_poll_interval_seconds <= 0:
            raise ValueError("acquisition_ready_poll_interval_seconds must be positive")


class KaggleFreeComputeProvider(FreeComputeProvider):
    """Acquire one bounded Kaggle GPU kernel as a free external worker."""

    provider_id = "kaggle"

    def capabilities(self) -> ProviderCapabilities:
        """Declare Kaggle adapter capabilities; worker-local evidence remains authoritative."""
        return ProviderCapabilities(
            gpu_acquisition=True,
            cuda_execution=True,
            arbitrary_process=True,
            ephemeral_runner=True,
            github_jit_runner=True,
            provider_api=True,
            explicit_release=True,
        )

    def __init__(
        self,
        config: KaggleFreeComputeConfig,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        clock=time.time,
        sleeper=time.sleep,
    ):
        self.config = config
        self._runner = runner or self._subprocess_runner
        self._clock = clock
        self._sleeper = sleeper

    @classmethod
    def from_environment(cls) -> "KaggleFreeComputeProvider":
        enabled = os.environ.get("THORIO_KAGGLE_ENABLED", "0").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            raise KaggleFreeComputeError("THORIO_KAGGLE_ENABLED must be enabled to register Kaggle")
        username = os.environ.get("THORIO_KAGGLE_USERNAME", "").strip()
        if not username:
            raise KaggleFreeComputeError("THORIO_KAGGLE_USERNAME is required")
        return cls(
            KaggleFreeComputeConfig(
                username=username,
                kernel_slug=os.environ.get("THORIO_KAGGLE_KERNEL_SLUG", "thorio-free-gpu-worker").strip(),
                accelerator=os.environ.get("THORIO_KAGGLE_ACCELERATOR", "NvidiaTeslaT4").strip(),
                repository_url=os.environ.get(
                    "THORIO_KAGGLE_REPOSITORY_URL",
                    "https://github.com/DocSentinelX12/Thorio-Lead-Engine.git",
                ).strip(),
                repository_ref=os.environ.get(
                    "THORIO_KAGGLE_REPOSITORY_REF",
                    "main",
                ).strip(),
                github_runner_jit_token_dataset_slug=os.environ.get(
                    "THORIO_KAGGLE_SECRET_DATASET_SLUG",
                    "",
                ).strip(),
                github_repository=os.environ.get(
                    "THORIO_KAGGLE_GITHUB_REPOSITORY",
                    "DocSentinelX12/Thorio-Lead-Engine",
                ).strip(),
                github_runner_name=os.environ.get("THORIO_KAGGLE_GITHUB_RUNNER_NAME", "").strip(),
                github_runner_labels=os.environ.get(
                    "THORIO_KAGGLE_GITHUB_RUNNER_LABELS",
                    "self-hosted,thorio-free-gpu,cuda",
                ).strip(),
                minimum_remaining_hours=float(
                    os.environ.get("THORIO_KAGGLE_MINIMUM_REMAINING_HOURS", "1")
                ),
                maximum_runtime_hours=float(
                    os.environ.get("THORIO_KAGGLE_MAXIMUM_RUNTIME_HOURS", "6")
                ),
                command_timeout_seconds=int(
                    os.environ.get("THORIO_KAGGLE_COMMAND_TIMEOUT_SECONDS", "120")
                ),
                acquisition_ready_timeout_seconds=int(
                    os.environ.get("THORIO_KAGGLE_ACQUISITION_READY_TIMEOUT_SECONDS", "60")
                ),
                acquisition_ready_poll_interval_seconds=float(
                    os.environ.get("THORIO_KAGGLE_ACQUISITION_READY_POLL_INTERVAL_SECONDS", "5")
                ),
                kaggle_binary=os.environ.get("THORIO_KAGGLE_BINARY", "kaggle").strip(),
            )
        )

    @staticmethod
    def _subprocess_runner(
        command: list[str],
        *,
        timeout: int,
        cwd: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def _run(self, args: list[str], *, cwd: str | None = None) -> str:
        command = [self.config.kaggle_binary, *args]
        try:
            result = self._runner(command, timeout=self.config.command_timeout_seconds, cwd=cwd)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise KaggleFreeComputeError(f"Kaggle CLI execution failed: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-4000:]
            raise KaggleFreeComputeError(
                f"Kaggle CLI command failed with exit code {result.returncode}: {detail}"
            )
        return result.stdout

    @staticmethod
    def _hours(value: Any) -> float:
        text = str(value or "").strip()
        if not text:
            raise KaggleFreeComputeError("Kaggle quota response omitted a time value")
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)h", text, re.IGNORECASE)
        if not match:
            raise KaggleFreeComputeError(f"unrecognized Kaggle quota time value: {text!r}")
        return float(match.group(1))

    def _quota(self) -> dict[str, Any]:
        raw = self._run(["quota", "--format", "json"])
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise KaggleFreeComputeError("Kaggle quota command returned invalid JSON") from exc
        if isinstance(payload, dict):
            rows = payload.get("rows") if isinstance(payload.get("rows"), list) else payload.get("data")
            if rows is None and all(key in payload for key in ("resource", "remaining")):
                rows = [payload]
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = None
        if not isinstance(rows, list):
            raise KaggleFreeComputeError("Kaggle quota response contains no structured quota rows")
        gpu = next(
            (row for row in rows if isinstance(row, Mapping) and str(row.get("resource", "")).strip().upper() == "GPU"),
            None,
        )
        if gpu is None:
            raise KaggleFreeComputeError("Kaggle account has no reported GPU quota")
        remaining = self._hours(gpu.get("remaining"))
        total = self._hours(gpu.get("total"))
        used = self._hours(gpu.get("used"))
        refresh_at = str(gpu.get("refreshAt") or "").strip()
        if remaining <= 0:
            raise KaggleFreeComputeError("Kaggle GPU quota is exhausted")
        return {
            "resource": "GPU",
            "remaining_hours": remaining,
            "total_hours": total,
            "used_hours": used,
            "refresh_at": refresh_at,
        }

    def _kernel_is_listed(self, kernel_ref: str) -> bool:
        """Check Kaggle's owner-scoped kernel inventory before interpreting a 403."""
        import csv
        import io

        # Use the complete owner-scoped inventory, not --search: Kaggle's
        # search endpoint can omit the CSV header when a newly pushed slug is
        # not indexed yet. Compare exact refs and fail closed on malformed output.
        page = 1
        while True:
            try:
                output = self._run(
                    [
                        "kernels",
                        "list",
                        "--mine",
                        "--page",
                        str(page),
                        "--page-size",
                        "100",
                        "--csv",
                    ]
                )
            except KaggleFreeComputeError as exc:
                raise KaggleFreeComputeError(
                    "Cannot safely classify Kaggle status permission denial because "
                    f"owner-scoped kernel listing failed: {exc}"
                ) from exc

            lines = [line for line in output.splitlines() if line.strip()]
            header = next(
                (index for index, line in enumerate(lines) if line.strip().lower().startswith("ref,")),
                None,
            )
            if header is None:
                raise KaggleFreeComputeError(
                    "Cannot safely classify Kaggle status permission denial because "
                    f"kernel listing page {page} returned no CSV header"
                )
            rows = list(csv.DictReader(io.StringIO("\n".join(lines[header:]))))
            if any(str(row.get("ref") or "").strip() == kernel_ref for row in rows):
                return True
            if len(rows) < 100:
                return False
            page += 1

    def _kernel_status(self, kernel_ref: str) -> str:
        try:
            output = self._run(["kernels", "status", kernel_ref])
        except KaggleFreeComputeError as exc:
            message = str(exc).lower()
            if "not found" in message or "404" in message:
                return "not_found"
            if "permission 'kernels.get' was denied" in message:
                if self._kernel_is_listed(kernel_ref):
                    raise KaggleFreeComputeError(
                        f"Kaggle denied status access for listed kernel {kernel_ref}; "
                        "refusing to treat a permission error as absence"
                    ) from exc
                return "not_found"
            raise
        lowered = output.lower()
        if "running" in lowered:
            return "running"
        if "queued" in lowered or "pending" in lowered:
            return "queued"
        if "complete" in lowered or "completed" in lowered:
            return "complete"
        if "error" in lowered or "failed" in lowered:
            return "failed"
        if "cancel" in lowered:
            return "cancelled"
        return "unknown"

    def _kernel_ref(self) -> str:
        return f"{self.config.username}/{self.config.kernel_slug}"

    def _domain_id(self) -> str:
        return f"kaggle:{self.config.username}:{self.config.kernel_slug}"

    def _offer_id(self, quota: Mapping[str, Any]) -> str:
        refresh_at = quota.get("refresh_at") or quota.get("gpu_quota_refresh_at") or None
        material = {
            "provider": self.provider_id,
            "domain": self._domain_id(),
            "accelerator": self.config.accelerator,
            "refresh_at": refresh_at,
        }
        return hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def discover_free(self) -> tuple[FreeComputeOffer, ...]:
        quota = self._quota()
        if quota["remaining_hours"] < self.config.minimum_remaining_hours:
            return ()
        status = self._kernel_status(self._kernel_ref())
        if status in {"running", "queued"}:
            return ()
        observed_at = self._clock()
        expires_at = None
        if quota["refresh_at"]:
            try:
                from datetime import datetime
                expires_at = datetime.fromisoformat(quota["refresh_at"].replace("Z", "+00:00")).timestamp()
                if expires_at <= observed_at:
                    expires_at = None
            except (TypeError, ValueError, OverflowError):
                expires_at = None
        return (
            FreeComputeOffer(
                provider_id=self.provider_id,
                domain_id=self._domain_id(),
                offer_id=self._offer_id(quota),
                observed_at=observed_at,
                expires_at=expires_at,
                gpu_capable=True,
                no_cost=True,
                capacity_evidence={
                    "provider": "Kaggle",
                    "provider_account": self.config.username,
                    "resource": quota["resource"],
                    "accelerator_requested": self.config.accelerator,
                    "gpu_quota_remaining_hours": quota["remaining_hours"],
                    "gpu_quota_total_hours": quota["total_hours"],
                    "gpu_quota_used_hours": quota["used_hours"],
                    "gpu_quota_refresh_at": quota["refresh_at"],
                    "kernel_ref": self._kernel_ref(),
                    "kernel_status": status,
                    "quota_source": "kaggle quota",
                    "no_cost_source": "Kaggle free GPU notebook quota",
                },
            ),
        )

    @staticmethod
    def _worker_script(
        *,
        repository_url: str,
        repository_ref: str,
        acquisition_id: str,
        domain_id: str,
        worker_id: str,
        github_runner_jit_token_dataset_slug: str,
        github_repository: str,
        github_runner_name: str,
        github_runner_labels: str,
        runner_bootstrap_script: str,
    ) -> str:
        values = {
            "repository_url": repository_url,
            "repository_ref": repository_ref,
            "acquisition_id": acquisition_id,
            "domain_id": domain_id,
            "worker_id": worker_id,
            # The dataset contains the token, but the dataset itself is private
            # and the value is never serialized into the public kernel source.
            "github_runner_jit_token_dataset_slug": github_runner_jit_token_dataset_slug,
            "github_repository": github_repository,
            "github_runner_name": github_runner_name,
            "github_runner_labels": github_runner_labels,
            "runner_bootstrap_script": runner_bootstrap_script,
        }
        encoded = json.dumps(values, sort_keys=True)
        return f'''import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

CONFIG = json.loads({encoded!r})
ROOT = Path("/kaggle/working/thorio-lead-engine")

LOG_PATH = Path("/kaggle/working/thorio-worker.log")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def _log_uncaught_exception(exc_type, exc, tb):
    with LOG_PATH.open("a", encoding="utf-8") as log:
        traceback.print_exception(exc_type, exc, tb, file=log)

sys.excepthook = _log_uncaught_exception

def run(*args):
    with LOG_PATH.open("a", encoding="utf-8") as log:
        result = subprocess.run(
            list(args), stdout=log, stderr=subprocess.STDOUT, check=False
        )
    if result.returncode != 0:
        try:
            print(LOG_PATH.read_text(encoding="utf-8", errors="replace")[-12000:], file=sys.stderr, flush=True)
        except OSError:
            pass
        raise subprocess.CalledProcessError(result.returncode, list(args))

def get_runner_token():
    dataset_slug = CONFIG["github_runner_jit_token_dataset_slug"]
    secret_file = Path("/kaggle/input") / dataset_slug / "runner-token"
    if not secret_file.is_file():
        raise RuntimeError(
            "Run-scoped private runner credential dataset is not mounted at "
            f"{{secret_file}}; refusing to start an unauthenticated GPU worker"
        )
    value = secret_file.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("Run-scoped private runner credential file is empty")
    return value

print("KAGGLE WORKER PHASE: reading the run-scoped private credential dataset.", flush=True)
jit_token = get_runner_token()
print("KAGGLE WORKER PHASE: GitHub JIT token retrieved.", flush=True)
if not jit_token:
    raise RuntimeError("Kaggle GitHub runner JIT token secret is empty")

if ROOT.exists():
    shutil.rmtree(ROOT)
ROOT.mkdir(parents=True, exist_ok=True)
runner_script = ROOT / "register-ephemeral-gpu-runner.sh"
runner_script.write_text(CONFIG["runner_bootstrap_script"], encoding="utf-8")
print("KAGGLE WORKER PHASE: embedded runner bootstrap written.", flush=True)
runner_script.chmod(0o700)

os.environ["THORIO_COMPUTE_ACQUISITION_ID"] = CONFIG["acquisition_id"]
os.environ["THORIO_COMPUTE_DOMAIN"] = CONFIG["domain_id"]
os.environ["THORIO_WORKER_ID"] = CONFIG["worker_id"]
os.environ["THORIO_FREE_ONLY"] = "1"
os.environ["PYTHONUNBUFFERED"] = "1"
os.environ["GITHUB_REPOSITORY"] = CONFIG["github_repository"]
os.environ["RUNNER_NAME"] = CONFIG["github_runner_name"] or ("thorio-free-gpu-" + CONFIG["acquisition_id"][:12])
os.environ["RUNNER_LABELS"] = CONFIG["github_runner_labels"]
jit_token_file = ROOT / "github-runner-jit-token"
jit_token_file.write_text(jit_token, encoding="utf-8")
jit_token_file.chmod(0o600)
os.environ.pop("GITHUB_RUNNER_JIT_TOKEN", None)
os.environ["GITHUB_RUNNER_JIT_TOKEN_FILE"] = str(jit_token_file)
os.environ["RUNNER_ROOT"] = "/kaggle/working/actions-runner"

runner_script = ROOT / "register-ephemeral-gpu-runner.sh"
if not runner_script.is_file():
    raise RuntimeError("ephemeral GPU runner bootstrap script is missing")
print("KAGGLE WORKER PHASE: invoking ephemeral runner bootstrap.", flush=True)
run("bash", str(runner_script))
'''

    @staticmethod
    def _runner_bootstrap_script() -> str:
        path = Path(__file__).resolve().parents[1] / "infra" / "free-compute" / "register-ephemeral-gpu-runner.sh"
        if not path.is_file():
            raise KaggleFreeComputeError(
                f"ephemeral GPU runner bootstrap script is missing: {path}"
            )
        return path.read_text(encoding="utf-8")

    def _capture_kernel_failure_output(self, kernel_ref: str) -> str:
        """Retrieve the remote worker log before failed kernels are deleted."""
        try:
            with tempfile.TemporaryDirectory(prefix="thorio-kaggle-failure-") as directory:
                command_output = self._run(
                    ["kernels", "output", kernel_ref, "-p", directory, "--force"]
                )
                candidates = [
                    path for path in Path(directory).rglob("*")
                    if path.is_file() and (path.name == "thorio-worker.log" or path.suffix.lower() in {".log", ".txt"})
                ]
                chunks = []
                for path in sorted(candidates):
                    try:
                        text = path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    if text.strip():
                        chunks.append(f"--- {path.name} ---\n{text[-12000:]}")
                if not chunks and command_output.strip():
                    chunks.append(command_output[-4000:])
                detail = "\n".join(chunks).strip()
        except Exception as exc:
            detail = f"Remote Kaggle output retrieval failed: {type(exc).__name__}: {exc}"
        for name in (
            "GITHUB_RUNNER_JIT_TOKEN",
            "THORIO_GITHUB_RUNNER_JIT_TOKEN",
            "KAGGLE_API_TOKEN",
            "THORIO_COMPUTE_AUTH_TOKEN",
        ):
            secret = os.environ.get(name, "").strip()
            if secret:
                detail = detail.replace(secret, "[REDACTED]")
        return detail[-16000:]

    def _wait_for_running(self, kernel_ref: str) -> str:
        """Wait for Kaggle to report the actual latest run as running.
        
        Kernel visibility, last-run timestamps, or successful submission are
        not equivalent to an active compute session. The provider status
        endpoint is therefore the only signal that can promote acquisition
        to the running state.
        """
        deadline = self._clock() + self.config.acquisition_ready_timeout_seconds
        last_status = "unknown"
        while True:
            last_status = self._kernel_status(kernel_ref)
            if last_status == "running":
                return last_status
            if last_status in {"failed", "cancelled", "complete", "unknown"}:
                raise KaggleFreeComputeError(
                    f"Kaggle provider run did not reach running state: {last_status}"
                )
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise KaggleFreeComputeError(
                    f"Kaggle provider run did not reach running state before timeout: {last_status}"
                )
            self._sleeper(min(self.config.acquisition_ready_poll_interval_seconds, remaining))

    def acquisition_status(self, acquisition: AcquiredCompute) -> str | None:
        if acquisition.provider_id != self.provider_id:
            raise KaggleFreeComputeError("acquisition belongs to a different provider")
        if acquisition.domain_id != self._domain_id():
            raise KaggleFreeComputeError("acquisition domain does not match the configured Kaggle worker")
        return self._kernel_status(self._kernel_ref())

    def _delete_private_runner_credential_dataset(self, dataset_slug: str) -> None:
        dataset_ref = f"{self.config.username}/{dataset_slug}"
        try:
            self._run(["datasets", "delete", dataset_ref, "--yes"])
        except KaggleFreeComputeError as exc:
            message = str(exc).lower()
            if "not found" in message or "404" in message:
                return
            raise

    def _publish_private_runner_credential_dataset(self, dataset_slug: str) -> None:
        token = (
            os.environ.get("GITHUB_RUNNER_JIT_TOKEN", "").strip()
            or os.environ.get("THORIO_GITHUB_RUNNER_JIT_TOKEN", "").strip()
        )
        if not token:
            raise KaggleFreeComputeError(
                "GITHUB_RUNNER_JIT_TOKEN or THORIO_GITHUB_RUNNER_JIT_TOKEN is required "
                "to publish a private runner credential dataset"
            )
        dataset_ref = f"{self.config.username}/{dataset_slug}"
        created = False
        try:
            with tempfile.TemporaryDirectory(prefix="thorio-kaggle-credential-") as directory:
                path = Path(directory)
                token_path = path / "runner-token"
                token_path.write_text(token, encoding="utf-8")
                token_path.chmod(0o600)
                (path / "dataset-metadata.json").write_text(
                    json.dumps(
                        {
                            "id": dataset_ref,
                            "title": dataset_slug,
                            "licenses": [{"name": "other"}],
                        },
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                self._run(["datasets", "create", "-p", str(path)], cwd=str(path))
                created = True

            with tempfile.TemporaryDirectory(prefix="thorio-kaggle-credential-verify-") as directory:
                self._run(["datasets", "metadata", dataset_ref, "-p", directory], cwd=directory)
                metadata_path = Path(directory) / "dataset-metadata.json"
                if not metadata_path.is_file():
                    raise KaggleFreeComputeError(
                        "Kaggle returned no metadata for the private runner credential dataset"
                    )
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if str(metadata.get("id") or "").strip() != dataset_ref:
                    raise KaggleFreeComputeError(
                        "Kaggle returned metadata for a different runner credential dataset"
                    )
                if metadata.get("isPrivate") is False:
                    raise KaggleFreeComputeError(
                        "Kaggle reports the runner credential dataset is public; refusing GPU acquisition"
                    )
                files_csv = self._run(["datasets", "files", dataset_ref, "--csv"])
                lines = [line for line in files_csv.splitlines() if line.strip()]
                header = next(
                    (index for index, line in enumerate(lines) if line.strip().lower().startswith("name,")),
                    None,
                )
                if header is None:
                    raise KaggleFreeComputeError(
                        "Kaggle runner credential dataset file listing returned no CSV header"
                    )
                rows = list(csv.DictReader(io.StringIO("\n".join(lines[header:]))))
                if not any(
                    Path(str(value or "")).name == "runner-token"
                    for row in rows
                    for value in row.values()
                ):
                    raise KaggleFreeComputeError(
                        "Private runner credential dataset does not contain runner-token"
                    )
            print(
                f"THORIO_PRIVATE_RUNNER_CREDENTIAL_DATASET_READY ref={dataset_ref} privacy=private-by-default",
                flush=True,
            )
        except Exception as exc:
            if created:
                try:
                    self._delete_private_runner_credential_dataset(dataset_slug)
                except Exception as cleanup_exc:
                    raise KaggleFreeComputeError(
                        f"Private runner credential dataset setup failed: {exc}; "
                        f"dataset cleanup also failed: {cleanup_exc}"
                    ) from exc
            if isinstance(exc, KaggleFreeComputeError):
                raise
            raise KaggleFreeComputeError(
                f"Private runner credential dataset setup failed: {type(exc).__name__}: {exc}"
            ) from exc

    def _push_kernel_with_retry(self, path: Path, timeout_seconds: int) -> str:
        deadline = self._clock() + self.config.acquisition_ready_timeout_seconds
        while True:
            try:
                output = self._run(
                    [
                        "kernels",
                        "push",
                        "-p",
                        str(path),
                        "--accelerator",
                        self.config.accelerator,
                        "--timeout",
                        str(timeout_seconds),
                    ]
                )
            except KaggleFreeComputeError as exc:
                if "maximum batch gpu session count" not in str(exc).lower():
                    raise
                output = str(exc)
            if "maximum batch gpu session count" not in output.lower():
                return output
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise KaggleFreeComputeError(
                    "Kaggle free GPU batch session limit remained exhausted before acquisition retry timeout"
                )
            self._sleeper(
                min(self.config.acquisition_ready_poll_interval_seconds, remaining)
            )


    def acquire_free(self, offer: FreeComputeOffer) -> AcquiredCompute:
        if offer.provider_id != self.provider_id:
            raise KaggleFreeComputeError("offer belongs to a different provider")
        if not offer.no_cost:
            raise KaggleFreeComputeError("Kaggle paid capacity is outside the free provider boundary")
        if offer.domain_id != self._domain_id():
            raise KaggleFreeComputeError("offer domain does not match the configured Kaggle worker")
        if offer.offer_id != self._offer_id(offer.capacity_evidence):
            raise KaggleFreeComputeError("offer identity is stale or was not issued by this adapter")

        quota = self._quota()
        if quota["remaining_hours"] < self.config.minimum_remaining_hours:
            raise KaggleFreeComputeError("Kaggle GPU quota no longer satisfies the minimum acquisition budget")

        kernel_ref = self._kernel_ref()
        now = self._clock()
        max_seconds = int(self.config.maximum_runtime_hours * 3600)
        quota_seconds = int(quota["remaining_hours"] * 3600)
        timeout_seconds = min(max_seconds, quota_seconds, 12 * 3600)
        if timeout_seconds < int(self.config.minimum_remaining_hours * 3600):
            raise KaggleFreeComputeError("Kaggle quota is too small for the configured minimum worker lifetime")

        acquisition_id = hashlib.sha256(
            f"{offer.provider_id}\x00{offer.domain_id}\x00{offer.offer_id}".encode("utf-8")
        ).hexdigest()
        dataset_slug = self.config.github_runner_jit_token_dataset_slug
        dataset_owned = not bool(dataset_slug)
        if dataset_owned:
            dataset_slug = f"thorio-runner-credentials-acq-{uuid.uuid4().hex[:16]}"

        worker_script = self._worker_script(
            repository_url=self.config.repository_url,
            repository_ref=self.config.repository_ref,
            acquisition_id=acquisition_id,
            domain_id=offer.domain_id,
            worker_id=offer.domain_id,
            github_runner_jit_token_dataset_slug=dataset_slug,
            github_repository=self.config.github_repository,
            github_runner_name=self.config.github_runner_name,
            github_runner_labels=self.config.github_runner_labels,
            runner_bootstrap_script=self._runner_bootstrap_script(),
        )
        metadata = {
            "id": kernel_ref,
            "title": self.config.kernel_slug,
            "code_file": "thorio_worker.py",
            "language": "python",
            "kernel_type": "script",
            "is_private": False,
            "enable_gpu": True,
            "enable_internet": True,
            "machine_shape": self.config.accelerator,
            "dataset_sources": [
                f"{self.config.username}/{dataset_slug}"
            ],
            "competition_sources": [],
            "kernel_sources": [],
            "model_sources": [],
        }
        with tempfile.TemporaryDirectory(prefix="thorio-kaggle-") as directory:
            path = Path(directory)
            (path / "kernel-metadata.json").write_text(
                json.dumps(metadata, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            (path / "thorio_worker.py").write_text(worker_script, encoding="utf-8")
            if dataset_owned:
                self._publish_private_runner_credential_dataset(dataset_slug)
            try:
                push_output = self._push_kernel_with_retry(path, timeout_seconds)
            except Exception as exc:
                cleanup_errors = []
                try:
                    self._run(["kernels", "delete", kernel_ref, "--yes"])
                except KaggleFreeComputeError as cleanup_exc:
                    if "not found" not in str(cleanup_exc).lower() and "404" not in str(cleanup_exc).lower():
                        cleanup_errors.append(f"kernel cleanup failed: {cleanup_exc}")
                if dataset_owned:
                    try:
                        self._delete_private_runner_credential_dataset(dataset_slug)
                    except Exception as cleanup_exc:
                        cleanup_errors.append(f"credential dataset cleanup failed: {cleanup_exc}")
                if cleanup_errors:
                    raise KaggleFreeComputeError(
                        f"Kaggle kernel push failed: {exc}; " + "; ".join(cleanup_errors)
                    ) from exc
                raise
            lowered_push_output = push_output.lower().strip()
            if (
                not lowered_push_output
                or "kernel push error" in lowered_push_output
                or "push error" in lowered_push_output
            ):
                cleanup_errors = []
                try:
                    self._run(["kernels", "delete", kernel_ref, "--yes"])
                except KaggleFreeComputeError as cleanup_exc:
                    if "not found" not in str(cleanup_exc).lower() and "404" not in str(cleanup_exc).lower():
                        cleanup_errors.append(f"kernel cleanup failed: {cleanup_exc}")
                if dataset_owned:
                    try:
                        self._delete_private_runner_credential_dataset(dataset_slug)
                    except Exception as cleanup_exc:
                        cleanup_errors.append(f"credential dataset cleanup failed: {cleanup_exc}")
                detail = f"Kaggle kernel push did not report an accepted submission: {push_output.strip()!r}"
                if cleanup_errors:
                    detail += "; " + "; ".join(cleanup_errors)
                raise KaggleFreeComputeError(detail)

        try:
            provider_run_status = self._wait_for_running(kernel_ref)
        except Exception as exc:
            cleanup_errors = []
            diagnostics = self._capture_kernel_failure_output(kernel_ref)
            try:
                self._run(["kernels", "delete", kernel_ref, "--yes"])
            except KaggleFreeComputeError as cleanup_exc:
                if "not found" not in str(cleanup_exc).lower() and "404" not in str(cleanup_exc).lower():
                    cleanup_errors.append(f"kernel cleanup failed: {cleanup_exc}")
            if dataset_owned:
                try:
                    self._delete_private_runner_credential_dataset(dataset_slug)
                except Exception as cleanup_exc:
                    cleanup_errors.append(f"credential dataset cleanup failed: {cleanup_exc}")
            failure_detail = (
                f"Kaggle worker did not reach running state: {type(exc).__name__}: {exc}"
            )
            if diagnostics:
                failure_detail += "\nRemote Kaggle worker diagnostics (secrets redacted):\n" + diagnostics
            if cleanup_errors:
                failure_detail += "; " + "; ".join(cleanup_errors)
            if isinstance(exc, KaggleFreeComputeError):
                raise KaggleFreeComputeError(failure_detail) from exc
            raise KaggleFreeComputeError(failure_detail) from exc

        expires_at = None
        if offer.expires_at is not None:
            expires_at = min(offer.expires_at, now + timeout_seconds)
        else:
            expires_at = now + timeout_seconds
        return AcquiredCompute(
            provider_id=self.provider_id,
            domain_id=offer.domain_id,
            offer_id=offer.offer_id,
            acquisition_id=acquisition_id,
            acquired_at=now,
            expires_at=expires_at,
            gpu_capable=True,
            enrollment={
                "provider": "Kaggle",
                "kernel_ref": kernel_ref,
                "worker_id": offer.domain_id,
                "domain_id": offer.domain_id,
                "accelerator": self.config.accelerator,
                "runtime_timeout_seconds": timeout_seconds,
                "authentication": "Run-scoped private Kaggle dataset",
                "runner_credential_dataset_slug": dataset_slug,
                "runner_credential_dataset_owned": dataset_owned,
                "physical_verification_required": True,
                "provider_submission_accepted": True,
                "provider_run_status": provider_run_status,
                "external_capacity_acquired": True,
                "free_only": True,
            },
        )

    def release_free(self, acquisition: AcquiredCompute) -> None:
        if acquisition.provider_id != self.provider_id:
            raise KaggleFreeComputeError("acquisition belongs to a different provider")
        if acquisition.domain_id != self._domain_id():
            raise KaggleFreeComputeError("acquisition domain does not match the configured Kaggle worker")
        cleanup_errors = []
        kernel_ref = str(acquisition.enrollment.get("kernel_ref") or self._kernel_ref())
        try:
            self._run(["kernels", "delete", kernel_ref, "--yes"])
        except KaggleFreeComputeError as exc:
            if "not found" not in str(exc).lower() and "404" not in str(exc).lower():
                cleanup_errors.append(f"kernel cleanup failed: {exc}")
        dataset_slug = str(acquisition.enrollment.get("runner_credential_dataset_slug") or "").strip()
        dataset_owned = acquisition.enrollment.get("runner_credential_dataset_owned") is True
        if dataset_owned and dataset_slug:
            try:
                self._delete_private_runner_credential_dataset(dataset_slug)
            except Exception as exc:
                cleanup_errors.append(f"credential dataset cleanup failed: {exc}")
        if cleanup_errors:
            raise KaggleFreeComputeError("; ".join(cleanup_errors))
