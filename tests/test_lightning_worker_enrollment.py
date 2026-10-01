from __future__ import annotations

import json

import pytest

from lead_engine.lightning_worker_bootstrap import _enroll_with_coordinator


def test_lightning_worker_enrollment_requires_url_and_token_together(monkeypatch):
    monkeypatch.setenv("THORIO_COMPUTE_COORDINATOR_URL", "https://coordinator.example")
    monkeypatch.delenv("THORIO_COMPUTE_AUTH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="must be provided together"):
        _enroll_with_coordinator({"worker_id": "node-1"})


def test_lightning_worker_enrollment_can_be_disabled_without_faking_registration(monkeypatch):
    monkeypatch.delenv("THORIO_COMPUTE_COORDINATOR_URL", raising=False)
    monkeypatch.delenv("THORIO_COMPUTE_AUTH_TOKEN", raising=False)

    assert _enroll_with_coordinator({"worker_id": "node-1"}) == {
        "attempted": False,
        "status": "not_configured",
    }


def test_lightning_worker_enrollment_posts_authenticated_evidence(monkeypatch):
    class Response:
        status = 200

        def read(self):
            return json.dumps({"ok": True, "worker_id": "node-1"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["content_type"] = request.get_header("Content-type")
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setenv("THORIO_COMPUTE_COORDINATOR_URL", "https://coordinator.example/")
    monkeypatch.setenv("THORIO_COMPUTE_AUTH_TOKEN", "secret")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = _enroll_with_coordinator({"worker_id": "node-1", "gpu_resources": [{"gpu_uuid": "GPU-1"}]})

    assert result["attempted"] is True
    assert result["status"] == "registered"
    assert captured == {
        "url": "https://coordinator.example/workers/register",
        "authorization": "Bearer secret",
        "content_type": "application/json",
        "body": {"worker_id": "node-1", "gpu_resources": [{"gpu_uuid": "GPU-1"}]},
        "timeout": 30,
    }
