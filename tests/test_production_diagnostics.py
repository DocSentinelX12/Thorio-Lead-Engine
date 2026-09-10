import os

from lead_engine.cli import DEFAULT_PRODUCTION_MAX_SECONDS, _install_production_diagnostics


def test_production_diagnostics_has_bounded_default():
    assert DEFAULT_PRODUCTION_MAX_SECONDS == 840.0


def test_production_diagnostics_can_be_disabled(monkeypatch):
    monkeypatch.setenv("THORIO_PRODUCTION_DIAGNOSTICS", "0")
    assert _install_production_diagnostics() is None


def test_production_diagnostics_accepts_short_test_budget(monkeypatch):
    monkeypatch.setenv("THORIO_PRODUCTION_DIAGNOSTICS", "1")
    monkeypatch.setenv("THORIO_PRODUCTION_MAX_SECONDS", "1")
    cleanup = _install_production_diagnostics()
    try:
        assert callable(cleanup)
        assert os.environ["THORIO_PRODUCTION_MAX_SECONDS"] == "1"
    finally:
        cleanup()
