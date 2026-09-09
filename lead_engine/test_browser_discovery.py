import json

import pytest

from .browser_discovery import (
    BrowserDiscoveryConfigurationError,
    BrowserDiscoveryTarget,
    _targets_from_environment,
    configured_browser_discovery_sources,
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
