from . import gmail_imap_inbound as inbound


def test_message_id_normalization():
    assert inbound._normalize_message_id('<abc123@thorio.co>') == 'abc123@thorio.co'


def test_message_id_extraction():
    assert inbound._message_ids('refs <abc123@thorio.co> <reply@example.com>') == {'abc123@thorio.co', 'reply@example.com'}


def test_outbound_index_only_contains_accepted_gmail_messages():
    class DB:
        def all_leads(self):
            return [{
                "fingerprint": "lead-1",
                "conversation_id": "conversation-1",
                "outreach_history": [{
                    "provider_result": {
                        "provider": "gmail_smtp",
                        "accepted": True,
                        "message_id": "<abc123@thorio.co>",
                        "recipient": "buyer@example.com",
                    }
                }],
            }]

    result = inbound._outbound_message_index(DB(), limit=10)
    assert result == {
        "abc123@thorio.co": {
            "opportunity_id": "lead-1",
            "conversation_id": "conversation-1",
            "recipient": "buyer@example.com",
        }
    }


def test_unconfigured_gmail_observer_is_disabled(monkeypatch):
    monkeypatch.delenv("THORIO_ACCOUNT_GMAIL_USERNAME", raising=False)
    monkeypatch.delenv("THORIO_ACCOUNT_GMAIL_PASSWORD", raising=False)

    class DB:
        def all_leads(self):
            return []

    result = inbound.poll_gmail_revenue_inbound(DB())
    assert result["status"] == "disabled"
    assert result["observer"] == "gmail_imap"
