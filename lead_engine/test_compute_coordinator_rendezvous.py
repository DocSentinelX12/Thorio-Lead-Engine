from __future__ import annotations

import json
import re
import threading
import textwrap
import urllib.request
from pathlib import Path

from lead_engine.compute_coordinator import ComputeCoordinator, ComputeCoordinatorServer


def test_fabric_rendezvous_round_trip(tmp_path: Path):
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"),
        "test-token",
    )

    published = coordinator.publish_fabric_rendezvous(
        session_id="nccl-test-1",
        address="10.0.0.10",
        port=29500,
        interface_name="eth0",
    )

    assert published["ok"] is True
    assert published["address"] == "10.0.0.10"
    assert published["port"] == 29500
    assert published["interface_name"] == "eth0"

    observed = coordinator.get_fabric_rendezvous("nccl-test-1")
    assert observed["ok"] is True
    assert observed["status"] == "published"
    assert observed["address"] == "10.0.0.10"
    assert observed["port"] == 29500
    assert observed["interface_name"] == "eth0"

    assert coordinator.clear_fabric_rendezvous("nccl-test-1") is True
    assert coordinator.get_fabric_rendezvous("nccl-test-1") == {
        "ok": False,
        "session_id": "nccl-test-1",
        "status": "not_published",
    }


def test_fabric_rendezvous_http_publish_and_read(tmp_path: Path):
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"), "test-token"
    )
    server = ComputeCoordinatorServer(coordinator, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        publish_request = urllib.request.Request(
            base + "/fabric/acquisition/rendezvous",
            data=json.dumps(
                {
                    "action": "publish",
                    "session_id": "nccl-http-test",
                    "address": "10.0.0.20",
                    "port": 29501,
                    "interface_name": "eth1",
                    "ttl_seconds": 60,
                }
            ).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(publish_request, timeout=5) as response:
            published = json.loads(response.read().decode("utf-8"))

        assert published["ok"] is True
        assert published["session_id"] == "nccl-http-test"

        read_request = urllib.request.Request(
            base + "/fabric/acquisition/rendezvous?session_id=nccl-http-test",
            headers={"Authorization": "Bearer test-token"},
        )
        with urllib.request.urlopen(read_request, timeout=5) as response:
            observed = json.loads(response.read().decode("utf-8"))

        assert observed["ok"] is True
        assert observed["address"] == "10.0.0.20"
        assert observed["port"] == 29501
        assert observed["interface_name"] == "eth1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_fabric_rendezvous_via_existing_handoff_route(tmp_path: Path):
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"), "test-token"
    )
    server = ComputeCoordinatorServer(coordinator, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def post(payload):
            request = urllib.request.Request(
                base + "/fabric/acquisition/handoff",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": "Bearer test-token",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))

        published = post(
            {
                "action": "rendezvous_publish",
                "session_id": "nccl-handoff-route-test",
                "address": "10.0.0.30",
                "port": 29502,
                "interface_name": "eth2",
                "ttl_seconds": 60,
            }
        )
        assert published["ok"] is True
        assert published["address"] == "10.0.0.30"
        assert published["port"] == 29502
        assert published["interface_name"] == "eth2"

        observed = post(
            {
                "action": "rendezvous_get",
                "session_id": "nccl-handoff-route-test",
            }
        )
        assert observed["ok"] is True
        assert observed["status"] == "published"
        assert observed["address"] == "10.0.0.30"
        assert observed["port"] == 29502
        assert observed["interface_name"] == "eth2"

        cleared = post(
            {
                "action": "rendezvous_clear",
                "session_id": "nccl-handoff-route-test",
            }
        )
        assert cleared["ok"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_fabric_rendezvous_rejects_invalid_endpoint(tmp_path: Path):
    coordinator = ComputeCoordinator(
        str(tmp_path / "coordinator.sqlite3"), "test-token"
    )

    try:
        coordinator.publish_fabric_rendezvous(
            session_id="nccl-test-2",
            address="",
            port=29500,
            interface_name="eth0",
        )
    except ValueError as exc:
        assert "address" in str(exc)
    else:
        raise AssertionError("empty rendezvous address must be rejected")

    try:
        coordinator.publish_fabric_rendezvous(
            session_id="nccl-test-3",
            address="10.0.0.10",
            port=70000,
            interface_name="eth0",
        )
    except ValueError as exc:
        assert "port" in str(exc)
    else:
        raise AssertionError("invalid rendezvous port must be rejected")


def test_physical_nccl_workflow_uses_dedicated_rendezvous_route():
    workflow = Path(__file__).parents[1] / ".github" / "workflows" / "physical-multi-node-nccl-proof.yml"
    text = workflow.read_text(encoding="utf-8")

    assert 'base + "/fabric/acquisition/handoff"' in text
    assert text.count("/fabric/acquisition/handoff") >= 4
    assert 'base + "/fabric/rendezvous"' not in text
    action_pattern = r'\\?"action\\?"\s*:\s*\\?"{action}\\?"'
    assert re.search(action_pattern.format(action="rendezvous_publish"), text)
    assert re.search(action_pattern.format(action="rendezvous_get"), text)
    assert re.search(action_pattern.format(action="rendezvous_clear"), text)
    assert '"User-Agent": "Mozilla/5.0' in text
    assert '"User-Agent: Mozilla/5.0' in text
    assert "for attempt in range(1, 4):" in text
    assert "if exc.code not in {502, 503, 504} or attempt == 3:" in text
    assert "thorio-nccl-rank-" in text
    assert '"runner_label": f"thorio-nccl-rank-{rank}"' in text
    assert "thorio-nccl-rank-${{ matrix.rank }}" in text
    assert "Release Kaggle GPU workers and JIT runner registrations" in text
    assert "NCCL_GPU_AND_RUNNER_CLEANUP_VERIFIED" in text
    assert "THORIO_KAGGLE_GITHUB_RUNNER_NAME" in text
    assert "runner_names.update(" in text
    assert "hmac.new(key, message, hashlib.sha256).hexdigest()[:32]" in text
    assert "thorio-nccl-relay:{run_id}:{proof_sha}:{rank}" in text
    assert "sha256sum | cut -c1-32" not in text
    assert "Clear stale NCCL JIT runner registrations" in text
    assert "kaggle_jit_secret_configured:" in text
    assert "Require Kaggle JIT secret confirmation before GPU acquisition" in text
    assert '"--search", "thorio-"' in text


def test_physical_external_gpu_proof_has_canonical_dispatch_and_matching_kaggle_slug():
    root = Path(__file__).parents[1]
    workflow_path = root / ".github" / "workflows" / "physical-external-gpu-proof.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    controller = (root / ".github" / "workflows" / "workflow-dispatch-controller.yml").read_text(encoding="utf-8")

    assert "name: Physical External GPU Proof" in workflow
    assert "workflow_dispatch:" in workflow
    assert '"id": "${KAGGLE_USERNAME}/${THORIO_KAGGLE_KERNEL_SLUG}"' in workflow
    assert '"title": "${THORIO_KAGGLE_KERNEL_SLUG}"' in workflow
    assert '"is_private": false' in workflow
    assert "printf '%s\\\\n'" not in workflow
    assert "printf '%s\\n'" in workflow
    assert "failing fast rather than consuming the full proof timeout" in workflow
    assert "physical-external-gpu-proof.yml" in controller
    assert "physical-external-gpu-proof-run.yml" not in controller
    assert "autonomous-gpu-capacity-broker.yml" in controller
    assert "kaggle_jit_secret_configured" in controller
    assert "free-external-gpu-runner.yml|autonomous-gpu-capacity-broker.yml|physical-external-gpu-proof.yml|physical-multi-node-nccl-proof.yml" in controller
    assert '-f proof_ref="$TARGET_REF"' in controller
    assert '-f cleanup_only="$CLEANUP_ONLY"' in controller
    assert not (root / ".github" / "workflows" / "physical-external-gpu-proof-manual.yml").exists()

def test_free_external_gpu_runner_uses_run_scoped_runner_identity_and_cleanup():
    root = Path(__file__).parents[1]
    workflow = (root / ".github" / "workflows" / "free-external-gpu-runner.yml").read_text(encoding="utf-8")

    assert "THORIO_KAGGLE_GITHUB_RUNNER_NAME: thorio-free-gpu-worker-${{ github.run_id }}" in workflow
    assert "cleanup_only:" in workflow
    assert "kaggle_jit_secret_configured:" in workflow
    assert "Require Kaggle JIT secret confirmation before GPU acquisition" in workflow
    assert "Remove stale Thorio Kaggle kernels and JIT runner registrations only" in workflow
    assert "No GPU has been acquired." in workflow
    assert 'if: ${{ !inputs.cleanup_only && inputs.kaggle_jit_secret_configured }}' in workflow
    assert 'expected_name="thorio-free-gpu-worker-${GITHUB_RUN_ID}"' in workflow
    assert "Remove any remaining JIT runner registration" in workflow
    assert "EXTERNAL_GPU_JIT_RUNNER_REMOVED" in workflow
    assert "Clear stale Thorio free GPU JIT runner registrations" in workflow
    assert '"--search", "thorio-free-gpu-worker-"' in workflow
    assert '"--page", str(page)' in workflow
    assert "No structured Kaggle kernel list was returned; continuing." not in workflow

def test_capacity_broker_delegates_to_the_authoritative_gpu_lifecycle():
    root = Path(__file__).parents[1]
    broker = (root / ".github" / "workflows" / "autonomous-gpu-capacity-broker.yml").read_text(encoding="utf-8")
    worker = (root / ".github" / "workflows" / "free-external-gpu-runner.yml").read_text(encoding="utf-8")

    assert "workflow_call:" in worker
    assert "workflow_dispatch:" in broker
    assert "push:" not in broker
    assert "uses: ./.github/workflows/free-external-gpu-runner.yml" in broker
    assert "with:" in broker
    assert "kaggle_jit_secret_configured: ${{ inputs.kaggle_jit_secret_configured }}" in broker
    assert "Acquire, enroll, physically verify, and release a real free GPU" in broker
    assert "python -m lead_engine.gpu_capacity_broker | tee" not in broker

def test_gpu_workflow_embedded_python_blocks_compile():
    root = Path(__file__).parents[1]
    workflow_paths = (
        root / ".github" / "workflows" / "free-external-gpu-runner.yml",
        root / ".github" / "workflows" / "physical-multi-node-nccl-proof.yml",
        root / ".github" / "workflows" / "physical-external-gpu-proof.yml",
    )
    pattern = re.compile(r"(?m)^[ \t]*python - <<'PY'[ \t]*\n(.*?)^[ \t]*PY[ \t]*$", re.DOTALL | re.MULTILINE)
    compiled = 0
    for workflow_path in workflow_paths:
        workflow = workflow_path.read_text(encoding="utf-8")
        for index, match in enumerate(pattern.finditer(workflow), start=1):
            source = textwrap.dedent(match.group(1))
            compile(source, f"{workflow_path.name}:python-heredoc-{index}", "exec")
            compiled += 1
    assert compiled >= 5

def test_external_gpu_workflows_share_non_cancelling_concurrency_group():
    root = Path(__file__).parents[1]
    workflow_paths = (
        root / ".github" / "workflows" / "free-external-gpu-runner.yml",
        root / ".github" / "workflows" / "physical-multi-node-nccl-proof.yml",
        root / ".github" / "workflows" / "physical-external-gpu-proof.yml",
    )
    for workflow_path in workflow_paths:
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "group: thorio-external-gpu-fabric" in workflow
        assert "cancel-in-progress: false" in workflow
