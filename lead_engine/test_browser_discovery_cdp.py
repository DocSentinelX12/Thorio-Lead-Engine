import os

from lead_engine import browser_discovery


def test_browser_cdp_endpoint_is_optional(monkeypatch):
    monkeypatch.delenv("THORIO_BROWSER_CDP_URL", raising=False)
    assert browser_discovery._browser_endpoint() == ""


def test_browser_cdp_endpoint_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("THORIO_BROWSER_CDP_URL", "http://127.0.0.1:9222")
    assert browser_discovery._browser_endpoint() == "http://127.0.0.1:9222"
