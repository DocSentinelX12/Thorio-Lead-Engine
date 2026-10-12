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
    monkeypatch.delenv("THORIO_GMAIL_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("THORIO_GMAIL_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("THORIO_GMAIL_OAUTH_REFRESH_TOKEN", raising=False)

    class DB:
        def all_leads(self):
            return []

    result = inbound.poll_gmail_revenue_inbound(DB())
    assert result["status"] == "disabled"
    assert result["observer"] == "gmail_imap"


def test_imap_observer_correlates_real_reply_headers_without_sending(monkeypatch):
    raw = (
        b"From: buyer@example.com\r\n"
        b"Message-ID: <reply-1@example.com>\r\n"
        b"In-Reply-To: <abc123@thorio.co>\r\n"
        b"Subject: Re: Hiring\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Yes, let's discuss.\r\n\r\n> original message\r\n"
    )

    class FakeIMAP:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, username, password):
            assert username == "thorio.partners@gmail.com"
            assert password == "app-password"
            return "OK", []

        def select(self, mailbox, readonly=False):
            assert mailbox == "INBOX" and readonly is True
            return "OK", [b"1"]

        def search(self, charset, *criteria):
            assert "In-Reply-To" in criteria
            return "OK", [b"1"]

        def fetch(self, sequence_id, query):
            return "OK", [(b"1 (RFC822)", raw), b")"]

        def logout(self):
            return "BYE", []

    monkeypatch.setattr(inbound.imaplib, "IMAP4_SSL", FakeIMAP)
    observer = inbound.GmailIMAPObserver(
        username="thorio.partners@gmail.com",
        password="app-password",
    )
    replies = observer.observe_replies({
        "abc123@thorio.co": {
            "opportunity_id": "lead-1",
            "conversation_id": "conversation-1",
            "recipient": "buyer@example.com",
        }
    })
    assert len(replies) == 1
    assert replies[0]["event_id"] == "gmail:reply-1@example.com"
    assert replies[0]["in_reply_to"] == "abc123@thorio.co"
    assert replies[0]["body"] == "Yes, let's discuss."


def test_gmail_poll_reports_exact_outbound_message_ids_checked(monkeypatch):
    class DB:
        def all_leads(self):
            return [{
                "fingerprint": "lead-1",
                "conversation_id": "conversation-1",
                "revenue_lifecycle_state": "conversation_active",
                "outreach_history": [{
                    "provider_result": {
                        "provider": "gmail_smtp", "accepted": True,
                        "message_id": "<abc123@thorio.co>",
                        "recipient": "buyer@example.com",
                    }
                }],
            }]

    class Observer:
        def observe_replies(self, outbound):
            assert set(outbound) == {"abc123@thorio.co"}
            return []

    result = inbound.poll_gmail_revenue_inbound(DB(), observer=Observer())
    assert result["status"] == "completed"
    assert result["observed_message_ids"] == ["abc123@thorio.co"]


def test_gmail_imap_password_normalizes_grouped_app_password(monkeypatch):
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_USERNAME", "thorio.partners@gmail.com")
    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_PASSWORD", "abcd efgh\nijkl mnop")
    assert inbound.gmail_imap_configured() is True
    observer = inbound.GmailIMAPObserver()
    assert observer.password == "abcdefghijklmnop"

def test_imap_observer_uses_oauth_xoauth2_when_configured(monkeypatch):
    raw = (
        b"From: buyer@example.com\\r\\n"
        b"Message-ID: <reply-oauth@example.com>\\r\\n"
        b"In-Reply-To: <abc123@thorio.co>\\r\\n"
        b"Subject: Re: Hiring\\r\\n"
        b"Content-Type: text/plain; charset=utf-8\\r\\n\\r\\n"
        b"Yes, let's discuss.\\r\\n"
    )

    class FakeIMAP:
        def __init__(self, *args, **kwargs):
            self.authenticated = None

        def authenticate(self, mechanism, authobject):
            self.authenticated = (mechanism, authobject(None))
            assert self.authenticated == (
                "XOAUTH2",
                b"user=thorio.partners@gmail.com\x01auth=Bearer access-token\x01\x01",
            )
            return "OK", [b"authenticated"]

        def select(self, mailbox, readonly=False):
            return "OK", [b"1"]

        def search(self, charset, *criteria):
            return "OK", [b"1"]

        def fetch(self, sequence_id, query):
            return "OK", [(b"1 (RFC822)", raw), b")"]

        def logout(self):
            return "BYE", []

    monkeypatch.setenv("THORIO_ACCOUNT_GMAIL_USERNAME", "thorio.partners@gmail.com")
    monkeypatch.delenv("THORIO_ACCOUNT_GMAIL_PASSWORD", raising=False)
    monkeypatch.setenv("THORIO_GMAIL_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("THORIO_GMAIL_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("THORIO_GMAIL_OAUTH_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setattr(inbound, "refresh_gmail_access_token", lambda **kwargs: "access-token")
    monkeypatch.setattr(inbound.imaplib, "IMAP4_SSL", FakeIMAP)

    observer = inbound.GmailIMAPObserver()
    replies = observer.observe_replies({
        "abc123@thorio.co": {
            "opportunity_id": "lead-1",
            "conversation_id": "conversation-1",
            "recipient": "buyer@example.com",
        }
    })
    assert replies[0]["event_id"] == "gmail:reply-oauth@example.com"
    assert replies[0]["body"] == "Yes, let's discuss."
