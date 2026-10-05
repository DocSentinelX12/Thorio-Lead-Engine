from __future__ import annotations

from pathlib import Path

from lead_engine.compute_coordinator import coordinator_from_environment


def test_coordinator_registers_lightning_provider_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("THORIO_COMPUTE_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("THORIO_COMPUTE_DB", str(Path(tmp_path) / "coordinator.sqlite3"))
    monkeypatch.setenv("THORIO_LIGHTNING_ENABLED", "1")
    monkeypatch.setenv("THORIO_LIGHTNING_STUDIO", "thorio-test")
    monkeypatch.setenv("THORIO_LIGHTNING_MACHINE", "T4")
    monkeypatch.setenv("THORIO_LIGHTNING_FREE_GPU_HOURS_REMAINING", "1")
    monkeypatch.setenv("THORIO_LIGHTNING_OFFER_TTL_SECONDS", "1200")

    coordinator = coordinator_from_environment()

    assert coordinator.free_compute_status()["provider_ids"] == ("lightning_ai",)


def test_coordinator_does_not_register_lightning_provider_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("THORIO_COMPUTE_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("THORIO_COMPUTE_DB", str(Path(tmp_path) / "coordinator.sqlite3"))
    monkeypatch.delenv("THORIO_LIGHTNING_ENABLED", raising=False)

    coordinator = coordinator_from_environment()

    assert "lightning_ai" not in coordinator.free_compute_status()["provider_ids"]
