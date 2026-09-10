import base64
import json

import pytest

from .account_auth import SUPPORTED_ACCOUNTS
from .browser_discovery import (
    BrowserDiscoveryConfigurationError,
    BrowserDiscoveryTarget,
    _browser_navigation_timeout,
    _targets_from_environment,
    authenticated_browser_lane_status,
    configured_browser_discovery_sources,
    validate_authenticated_browser_configuration,
)


def test_browser_targets_require_explicit_http_url(monkeypatch):
    monkeypatch.setenv(
        "THORIO_BROWSER_DISCOVERY_TARGETS",
        json.dumps([{"lane": "x_signal", "name": "X Home", "url": "not-a-url"}]),
    )
    with pytest.raises(BrowserDiscoveryConfigurationError):
        _targets_from_environment()


def test_browser_targets_load_without_credentials(monkeypatch):
    monkeypatch.setenv(
        "THORIO_BROWSER_DISCOVERY_TARGETS",
        json.dumps([
            {
                "lane": "x_signal",
                "name": "X Home",
                "url": "https://x.com/home",
                "item_selector": "article",
                "text_selector": "div[data-testid='tweetText']",
                "link_selector": "a[href*='/status/']",
                "company_selector": "a[data-company]",
            }
        ]),
    )
    targets = _targets_from_environment()
    assert targets == (
        BrowserDiscoveryTarget(
            lane="x_signal",
            name="X Home",
            url="https://x.com/home",
            company_selector="a[data-company]",
            text_selector="div[data-testid='tweetText']",
            link_selector="a[href*='/status/']",
            item_selector="article",
        ),
    )


def test_authenticated_target_requires_session_selector():
    with pytest.raises(BrowserDiscoveryConfigurationError, match="authenticated_selector"):
        BrowserDiscoveryTarget(
            lane="x_signal",
            name="X Home",
            url="https://x.com/home",
            account="x",
        )


def test_no_browser_targets_means_no_browser_sources(monkeypatch):
    monkeypatch.delenv("THORIO_BROWSER_DISCOVERY_TARGETS", raising=False)
    assert configured_browser_discovery_sources() == ()


def test_browser_target_rejects_nonpositive_limit():
    with pytest.raises(BrowserDiscoveryConfigurationError):
        BrowserDiscoveryTarget(
            lane="x_signal",
            name="X Home",
            url="https://x.com/home",
            item_selector="article",
            text_selector="div[data-testid='tweetText']",
            max_items=0,
        )


def test_browser_navigation_timeout_is_bounded_and_configurable(monkeypatch):
    monkeypatch.setenv("THORIO_BROWSER_NAVIGATION_TIMEOUT", "30")
    assert _browser_navigation_timeout() == 30_000

    monkeypatch.setenv("THORIO_BROWSER_NAVIGATION_TIMEOUT", "999")
    assert _browser_navigation_timeout() == 120_000

    monkeypatch.setenv("THORIO_BROWSER_NAVIGATION_TIMEOUT", "invalid")
    assert _browser_navigation_timeout() == 30_000


def _six_targets():
    return tuple(
        BrowserDiscoveryTarget(
            lane=f"{account}_signals",
            name=f"{account} signals",
            url="https://example.com/feed",
            item_selector="article",
            text_selector=".text",
            account=account,
            authenticated_selector="[data-authenticated='true']",
        )
        for account in SUPPORTED_ACCOUNTS
    )


def test_all_six_authenticated_account_types_are_supported():
    status = authenticated_browser_lane_status(_six_targets())
    assert status["configured_lane_count"] == 6
    assert status["authenticated_lane_count"] == 6
    assert status["all_six_account_types_supported"] is True
    assert set(status["configured_accounts"]) == set(SUPPORTED_ACCOUNTS)


def test_complete_six_lane_configuration_validates_without_secrets():
    result = validate_authenticated_browser_configuration(_six_targets())
    assert result["configured_lane_count"] == 6
    assert result["authenticated_lane_count"] == 6
    assert result["secrets_exposed"] is False


def test_complete_six_lane_configuration_rejects_missing_account():
    targets = _six_targets()[:-1]
    with pytest.raises(BrowserDiscoveryConfigurationError, match="Missing authenticated browser lanes"):
        validate_authenticated_browser_configuration(targets)


def test_complete_six_lane_configuration_can_use_storage_state_without_relogin_selectors(monkeypatch):
    state = {"cookies": [{"name": "session", "value": "opaque"}], "origins": []}
    encoded = base64.b64encode(json.dumps(state).encode()).decode()
    monkeypatch.setenv("THORIO_ACCOUNT_LINKEDIN_STORAGE_STATE_B64", encoded)
    validate_authenticated_browser_configuration(_six_targets(), require_credentials_or_storage=True)


def test_complete_six_lane_configuration_requires_runtime_auth_material_when_requested(monkeypatch):
    for account in SUPPORTED_ACCOUNTS:
        monkeypatch.delenv(f"THORIO_ACCOUNT_{account.upper()}_USERNAME", raising=False)
        monkeypatch.delenv(f"THORIO_ACCOUNT_{account.upper()}_PASSWORD", raising=False)
        monkeypatch.delenv(f"THORIO_ACCOUNT_{account.upper()}_STORAGE_STATE_B64", raising=False)
    with pytest.raises(BrowserDiscoveryConfigurationError, match="credentials or storage state"):
        validate_authenticated_browser_configuration(_six_targets(), require_credentials_or_storage=True)
