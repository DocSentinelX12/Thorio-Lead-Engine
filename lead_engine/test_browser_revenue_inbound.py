import json

import pytest

from .browser_revenue_inbound import (
    BrowserRevenueInboundConfigurationError,
    BrowserRevenueInboundTarget,
    configured_browser_revenue_inbound_targets,
    poll_browser_revenue_inbound,
)


def test_inbound_target_requires_explicit_runtime_controls():
    with pytest.raises(BrowserRevenueInboundConfigurationError):
        BrowserRevenueInboundTarget(
            channel="linkedin",
            account="linkedin",
            inbox_url="https://example.invalid/inbox",
            thread_url_template="https://example.invalid/thread?url={thread_url}",
            message_selector="",
            message_author_selector=".author",
            message_id_selector=".id",
            timestamp_selector=".time",
            body_selector=".body",
            self_marker="Thorio",
        )


def test_inbound_targets_are_loaded_without_platform_defaults(monkeypatch):
    payload = [{
        "channel": "linkedin",
        "account": "linkedin",
        "inbox_url": "https://example.invalid/inbox",
        "thread_url_template": "{thread_url}",
        "message_selector": ".message",
        "message_author_selector": ".author",
        "message_id_selector": ".id",
        "timestamp_selector": ".time",
        "body_selector": ".body",
        "self_marker": "Thorio",
    }]
    monkeypatch.setenv("THORIO_REVENUE_BROWSER_INBOUND_TARGETS", json.dumps(payload))
    targets = configured_browser_revenue_inbound_targets()
    assert set(targets) == {"linkedin"}
    assert targets["linkedin"].self_marker == "Thorio"


def test_inbound_targets_reject_duplicate_channels(monkeypatch):
    target = {
        "channel": "linkedin",
        "account": "linkedin",
        "inbox_url": "https://example.invalid/inbox",
        "thread_url_template": "{thread_url}",
        "message_selector": ".message",
        "message_author_selector": ".author",
        "message_id_selector": ".id",
        "timestamp_selector": ".time",
        "body_selector": ".body",
        "self_marker": "Thorio",
    }
    monkeypatch.setenv("THORIO_REVENUE_BROWSER_INBOUND_TARGETS", json.dumps([target, target]))
    with pytest.raises(BrowserRevenueInboundConfigurationError, match="duplicate"):
        configured_browser_revenue_inbound_targets()


class _DB:
    def all_leads(self):
        return [{
            "fingerprint": "lead-1",
            "conversation_id": "conversation-1",
            "outreach_channel": "linkedin",
            "revenue_lifecycle_state": "conversation_active",
            "outreach_history": [{
                "provider_result": {"thread_url": "https://example.invalid/thread/1"},
            }],
        }]


def test_poll_records_real_observer_events_before_followup_logic(monkeypatch):
    target = {
        "channel": "linkedin",
        "account": "linkedin",
        "inbox_url": "https://example.invalid/inbox",
        "thread_url_template": "{thread_url}",
        "message_selector": ".message",
        "message_author_selector": ".author",
        "message_id_selector": ".id",
        "timestamp_selector": ".time",
        "body_selector": ".body",
        "self_marker": "Thorio",
    }
    monkeypatch.setenv("THORIO_REVENUE_BROWSER_INBOUND_TARGETS", json.dumps([target]))

    class Observer:
        def observe(self, *, channel, thread_url):
            assert channel == "linkedin"
            assert thread_url == "https://example.invalid/thread/1"
            return [{"event_id": "linkedin:message-1", "body": "Yes, tell me more."}]

    recorded = []
    monkeypatch.setattr(
        "lead_engine.browser_revenue_inbound.record_inbound_event",
        lambda db, **kwargs: recorded.append(kwargs) or {"conversation_id": kwargs["conversation_id"]},
    )
    result = poll_browser_revenue_inbound(_DB(), observer=Observer())
    assert result["observed_count"] == 1
    assert result["recorded_count"] == 1
    assert result["failed_count"] == 0
    assert recorded[0]["opportunity_id"] == "lead-1"
    assert recorded[0]["conversation_id"] == "conversation-1"
    assert recorded[0]["event_id"] == "linkedin:message-1"
    assert recorded[0]["text"] == "Yes, tell me more."
