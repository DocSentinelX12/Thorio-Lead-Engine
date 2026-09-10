import pytest

from .browser_discovery import (
    BrowserDiscoveryConfigurationError,
    BrowserDiscoveryTarget,
    _browser_navigation_timeout,
    authenticated_browser_lane_status,
)
from .account_auth import SUPPORTED_ACCOUNTS


def _target(account):
    return BrowserDiscoveryTarget(
        lane=f"{account}_signals",
        name=f"{account} signals",
        url="https://example.com/feed",
        item_selector="article",
        text_selector=".text",
        account=account,
        authenticated_selector="[data-authenticated='true']",
    )


def test_all_six_authenticated_account_types_are_supported():
    targets = tuple(_target(account) for account in SUPPORTED_ACCOUNTS)
    status = authenticated_browser_lane_status(targets)
    assert status["configured_lane_count"] == 6
    assert status["authenticated_lane_count"] == 6
    assert status["all_six_account_types_supported"] is True
    assert set(status["configured_accounts"]) == set(SUPPORTED_ACCOUNTS)


def test_authenticated_target_rejects_unknown_account():
    with pytest.raises(BrowserDiscoveryConfigurationError):
        _target("unknown_platform")


def test_browser_navigation_timeout_has_safe_default_and_upper_bound(monkeypatch):
    monkeypatch.delenv("THORIO_BROWSER_NAVIGATION_TIMEOUT", raising=False)
    assert _browser_navigation_timeout() == 30_000

    monkeypatch.setenv("THORIO_BROWSER_NAVIGATION_TIMEOUT", "999")
    assert _browser_navigation_timeout() == 120_000

    monkeypatch.setenv("THORIO_BROWSER_NAVIGATION_TIMEOUT", "1")
    assert _browser_navigation_timeout() == 5_000
