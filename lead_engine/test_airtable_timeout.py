from unittest.mock import patch

from lead_engine.airtable_sync import (
    AIRTABLE_REQUEST_TIMEOUT,
    _request,
)


class Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return b'{"records": []}'


def test_airtable_request_timeout_is_not_overly_strict():
    assert AIRTABLE_REQUEST_TIMEOUT == 60.0


def test_airtable_request_uses_configured_timeout(monkeypatch):
    monkeypatch.setenv("AIRTABLE_BASE_ID", "app_test")
    monkeypatch.setenv("AIRTABLE_API_KEY", "pat_test")

    with patch(
        "lead_engine.airtable_sync.urllib.request.urlopen",
        return_value=Response(),
    ) as mocked:
        result = _request(
            "GET",
            "https://example.com",
        )

    assert result == {"records": []}
    assert mocked.call_args.kwargs["timeout"] == 60.0
