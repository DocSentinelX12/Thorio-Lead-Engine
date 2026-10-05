from __future__ import annotations

from lead_engine.compute_worker import ComputeWorkerClient


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b'{"ok": true}'


def test_coordinator_request_uses_proxy_compatible_headers(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = ComputeWorkerClient(
        "https://coordinator.example",
        "secret",
        "worker-1",
    )

    assert client.request("/workers/heartbeat", {"worker_id": "worker-1"}) == {"ok": True}
    request = captured["request"]
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("User-agent").startswith("Mozilla/5.0")
    assert request.get_header("Authorization") == "Bearer secret"
    assert captured["timeout"] == 20
