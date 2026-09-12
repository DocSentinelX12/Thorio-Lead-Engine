import json

import pytest

from .browser_revenue_transport import (
    BrowserRevenueConfigurationError,
    BrowserRevenueTarget,
    configured_browser_revenue_targets,
)


def test_browser_revenue_target_requires_explicit_runtime_controls():
    with pytest.raises(BrowserRevenueConfigurationError):
        BrowserRevenueTarget(
            channel="linkedin",
            account="linkedin",
            recipient_url_template="https://example.invalid/{recipient}",
            composer_selector="",
            body_selector="textarea",
            send_selector="button[type=submit]",
            sent_selector=".sent",
        )


def test_browser_revenue_targets_are_loaded_without_platform_defaults(monkeypatch):
    payload = [{
        "channel": "linkedin",
        "account": "linkedin",
        "recipient_url_template": "https://example.invalid/{recipient}",
        "composer_selector": "[data-test=composer]",
        "body_selector": "textarea",
        "send_selector": "button[type=submit]",
        "sent_selector": "[data-test=sent]",
    }]
    monkeypatch.setenv("THORIO_REVENUE_BROWSER_TARGETS", json.dumps(payload))
    targets = configured_browser_revenue_targets()
    assert set(targets) == {"linkedin"}
    assert targets["linkedin"].recipient_url_template == "https://example.invalid/{recipient}"


def test_browser_revenue_targets_reject_duplicate_channels(monkeypatch):
    target = {
        "channel": "linkedin",
        "account": "linkedin",
        "recipient_url_template": "https://example.invalid/{recipient}",
        "composer_selector": "[data-test=composer]",
        "body_selector": "textarea",
        "send_selector": "button[type=submit]",
        "sent_selector": "[data-test=sent]",
    }
    monkeypatch.setenv("THORIO_REVENUE_BROWSER_TARGETS", json.dumps([target, target]))
    with pytest.raises(BrowserRevenueConfigurationError, match="duplicate"):
        configured_browser_revenue_targets()
