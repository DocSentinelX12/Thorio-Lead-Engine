import pytest

from . import airtable_sync


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("AIRTABLE_READ_ONLY_MODE", "true"),
        ("AIRTABLE_SYNC_BLOCK_REASON", "record_capacity"),
    ],
)
def test_airtable_read_only_mode_blocks_mutations_before_network(monkeypatch, variable, value):
    monkeypatch.setenv("AIRTABLE_BASE_ID", "appxz89RYpxIOpdMD")
    monkeypatch.setenv("AIRTABLE_API_KEY", "not-a-real-token")
    monkeypatch.setenv(variable, value)

    def unexpected_network_call(*args, **kwargs):
        pytest.fail("Airtable mutation reached the network while read-only mode was active")

    monkeypatch.setattr(airtable_sync.urllib.request, "urlopen", unexpected_network_call)
    with pytest.raises(airtable_sync.AirtableSyncError, match="mutation blocked"):
        airtable_sync._request(
            "POST",
            "https://api.airtable.com/v0/appxz89RYpxIOpdMD/Lead%20Radar",
            {"records": []},
        )

class FakeResponse:
    def __init__(self, body):
        self.body = body
        self.read = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read1(self, size=-1):
        if self.read:
            return b""
        self.read = True
        return self.body


def test_record_capacity_allows_patch_to_known_existing_record(monkeypatch):
    monkeypatch.setenv("AIRTABLE_BASE_ID", "appxz89RYpxIOpdMD")
    monkeypatch.setenv("AIRTABLE_API_KEY", "not-a-real-token")
    monkeypatch.setenv("AIRTABLE_READ_ONLY_MODE", "false")
    monkeypatch.setenv("AIRTABLE_SYNC_BLOCK_REASON", "record_capacity")
    calls = []

    def fake_network_call(request, timeout):
        calls.append((request.get_method(), request.full_url))
        return FakeResponse(b'{"id":"recExisting123","fields":{"Notes":"updated"}}')

    monkeypatch.setattr(airtable_sync.urllib.request, "urlopen", fake_network_call)
    result = airtable_sync._request(
        "PATCH",
        "https://api.airtable.com/v0/appxz89RYpxIOpdMD/Lead%20Radar/recExisting123",
        {"fields": {"Notes": "updated"}},
    )

    assert result["id"] == "recExisting123"
    assert calls == [
        ("PATCH", "https://api.airtable.com/v0/appxz89RYpxIOpdMD/Lead%20Radar/recExisting123")
    ]


def test_record_capacity_still_blocks_table_level_upsert(monkeypatch):
    monkeypatch.setenv("AIRTABLE_BASE_ID", "appxz89RYpxIOpdMD")
    monkeypatch.setenv("AIRTABLE_API_KEY", "not-a-real-token")
    monkeypatch.setenv("AIRTABLE_READ_ONLY_MODE", "false")
    monkeypatch.setenv("AIRTABLE_SYNC_BLOCK_REASON", "record_capacity")

    def unexpected_network_call(*args, **kwargs):
        pytest.fail("Airtable upsert reached the network while record capacity was exhausted")

    monkeypatch.setattr(airtable_sync.urllib.request, "urlopen", unexpected_network_call)
    with pytest.raises(airtable_sync.AirtableSyncError, match="new records"):
        airtable_sync._request(
            "PATCH",
            "https://api.airtable.com/v0/appxz89RYpxIOpdMD/Lead%20Radar",
            {"performUpsert": {"fieldsToMergeOn": ["Duplicate Key"]}, "records": []},
        )
