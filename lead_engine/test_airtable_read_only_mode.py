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
