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
    assert targets["linkedin"].recipient_selector == ""
    assert targets["linkedin"].open_composer is False


def test_gmail_revenue_target_can_require_real_recipient_entry_and_confirmation_text(monkeypatch):
    payload = [{
        "channel": "gmail",
        "account": "gmail",
        "recipient_url_template": "https://mail.google.com/mail/u/0/#inbox",
        "composer_selector": "[data-test=operator-verified-compose]",
        "recipient_selector": "[data-test=operator-verified-to]",
        "subject_selector": "[data-test=operator-verified-subject]",
        "body_selector": "[data-test=operator-verified-body]",
        "send_selector": "[data-test=operator-verified-send]",
        "sent_selector": "[data-test=operator-verified-sent]",
        "sent_text": "Message sent",
        "open_composer": True,
        "recipient_commit_key": "Enter",
    }]
    monkeypatch.setenv("THORIO_REVENUE_BROWSER_TARGETS", json.dumps(payload))
    targets = configured_browser_revenue_targets()
    target = targets["gmail"]
    assert target.recipient_selector == "[data-test=operator-verified-to]"
    assert target.subject_selector == "[data-test=operator-verified-subject]"
    assert target.open_composer is True
    assert target.recipient_commit_key == "Enter"
    assert target.sent_text == "Message sent"


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


def test_recipient_commit_key_accepts_playwright_named_keys():
    target = BrowserRevenueTarget(
        channel="gmail",
        account="gmail",
        recipient_url_template="https://mail.google.com/mail/u/0/#inbox",
        composer_selector="[data-test=compose]",
        body_selector="[data-test=body]",
        send_selector="[data-test=send]",
        sent_selector="[data-test=sent]",
        recipient_commit_key="Enter",
    )
    assert target.recipient_commit_key == "Enter"
