from lead_engine import airtable_sync


class FakeSocket:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)


class FakeResponse:
    def __init__(self):
        self.socket = FakeSocket()
        raw = type("FakeRaw", (), {"_sock": self.socket})()
        self.fp = type("FakeFP", (), {"raw": raw})()
        self.chunks = [b'{"ok":', b'true}', b""]

    def read1(self, _size):
        return self.chunks.pop(0)


def test_response_reader_reduces_socket_timeout_to_absolute_deadline(monkeypatch):
    ticks = iter((10.0, 11.0, 12.0))
    monkeypatch.setattr(airtable_sync.time, "monotonic", lambda: next(ticks))
    response = FakeResponse()

    body = airtable_sync._read_response_with_deadline(response, 20.0)

    assert body == b'{"ok":true}'
    assert response.socket.timeouts == [10.0, 9.0, 8.0]


def test_expired_drain_deadline_fails_before_opening_an_http_connection(monkeypatch):
    import pytest
    from lead_engine.airtable_sync import AirtableTransientError, bounded_request_deadline

    monkeypatch.setenv("AIRTABLE_BASE_ID", "app-test")
    monkeypatch.setenv("AIRTABLE_API_KEY", "test-token")
    monkeypatch.setattr(airtable_sync.time, "monotonic", lambda: 50.0)
    monkeypatch.setattr(
        airtable_sync.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("expired deadline must not open a connection"),
    )

    with bounded_request_deadline(40.0), pytest.raises(
        AirtableTransientError, match="drain deadline expired"
    ):
        airtable_sync._request("GET", "https://api.airtable.com/v0/app-test/Lead%20Radar")
