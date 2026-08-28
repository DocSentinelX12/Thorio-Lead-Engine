import json
from unittest.mock import patch

import pytest

from .web_source import WebLeadSource, collect_from_url


def mock_response(payload):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    return Response()


def test_web_source_accepts_list():
    payload = [
        {
            "company": "Example Corp",
            "source_id": "example-001",
        }
    ]

    with patch(
        "lead_engine.web_source.urlopen",
        return_value=mock_response(payload),
    ):
        result = collect_from_url("https://example.com/leads")

    assert result == payload


def test_web_source_accepts_leads_object():
    payload = {
        "leads": [
            {
                "company": "Example Corp",
                "source_id": "example-002",
            }
        ]
    }

    with patch(
        "lead_engine.web_source.urlopen",
        return_value=mock_response(payload),
    ):
        result = collect_from_url("https://example.com/leads")

    assert result == payload["leads"]


def test_web_source_rejects_non_object_lead():
    payload = {
        "leads": [
            "not-a-lead"
        ]
    }

    with patch(
        "lead_engine.web_source.urlopen",
        return_value=mock_response(payload),
    ):
        with pytest.raises(
            ValueError,
            match="lead at index 0 must be an object",
        ):
            collect_from_url("https://example.com/leads")


def test_web_source_rejects_invalid_payload():
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return b"not valid json"

    with patch(
        "lead_engine.web_source.urlopen",
        return_value=Response(),
    ):
        with pytest.raises(
            ValueError,
            match="valid UTF-8 JSON",
        ):
            collect_from_url("https://example.com/leads")


def test_web_source_requires_url():
    with pytest.raises(
        ValueError,
        match="URL is required",
    ):
        WebLeadSource("")


def test_web_source_requires_positive_timeout():
    with pytest.raises(
        ValueError,
        match="timeout must be positive",
    ):
        WebLeadSource(
            "https://example.com/leads",
            timeout=0,
        )
