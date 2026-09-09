import json

import pytest

from .discovery_collectors import (
    DISCOVERY_LANES,
    AuthorizedDiscoveryLeadSource,
    AuthorizedJsonDiscoveryCollector,
    DiscoveryConfigurationError,
    DiscoverySourceConfig,
    _record_to_lead,
    load_authorized_discovery_configs,
)


def test_all_ten_discovery_lanes_have_explicit_contracts():
    assert len(DISCOVERY_LANES) == 10
    assert len(set(DISCOVERY_LANES)) == 10
    for lane in DISCOVERY_LANES:
        config = DiscoverySourceConfig(
            lane=lane,
            source=lane,
            endpoint="https://collector.example.test/data",
        )
        assert config.lane == lane


def test_missing_required_lane_configuration_is_reported(monkeypatch):
    for lane in DISCOVERY_LANES:
        monkeypatch.delenv(f"THORIO_DISCOVERY_{lane.upper()}_URL", raising=False)
        monkeypatch.delenv(f"THORIO_DISCOVERY_{lane.upper()}_ENABLED", raising=False)
    with pytest.raises(DiscoveryConfigurationError) as exc:
        load_authorized_discovery_configs(required=True)
    message = str(exc.value)
    assert "x_signal" in message
    assert "web_job_signal" in message


def test_enabled_lane_without_endpoint_cannot_silently_disable_it(monkeypatch):
    for lane in DISCOVERY_LANES:
        monkeypatch.delenv(f"THORIO_DISCOVERY_{lane.upper()}_URL", raising=False)
        monkeypatch.delenv(f"THORIO_DISCOVERY_{lane.upper()}_ENABLED", raising=False)
    monkeypatch.setenv("THORIO_DISCOVERY_X_SIGNAL_ENABLED", "true")
    with pytest.raises(DiscoveryConfigurationError, match="x_signal"):
        load_authorized_discovery_configs(required=False)


def test_collector_normalizes_only_records_with_observed_company_and_url():
    config = DiscoverySourceConfig(
        lane="x_signal",
        source="X",
        endpoint="https://collector.example.test/data",
    )
    valid = _record_to_lead(
        {"id": "p1", "url": "https://x.example/p1", "text": "Need an AI engineering team", "company": "Acme"},
        config,
    )
    incomplete = _record_to_lead(
        {"id": "p2", "url": "https://x.example/p2", "text": "Need an AI engineering team"},
        config,
    )
    assert valid["company"] == "Acme"
    assert valid["discovery_agent"] == "x_signal"
    assert incomplete is None


def test_authorized_collector_uses_token_and_checkpoint(monkeypatch):
    captured = {}

    class Raw:
        def decode(self, encoding):
            assert encoding == "utf-8"
            return json.dumps({
                "data": [{
                    "id": "p1",
                    "url": "https://x.example/p1",
                    "text": "Need developers",
                    "company": "Acme",
                }],
                "next_cursor": "next-2",
            })

    def fake_fetch(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers.get("Authorization")
        captured["timeout"] = timeout
        return Raw()

    monkeypatch.setattr("lead_engine.discovery_collectors.fetch_url", fake_fetch)
    config = DiscoverySourceConfig(
        lane="x_signal",
        source="X",
        endpoint="https://collector.example.test/data?query=ai",
        token="secret-token",
    )
    result = AuthorizedJsonDiscoveryCollector(config).collect("cursor-1")
    assert "cursor=cursor-1" in captured["url"]
    assert captured["authorization"] == "Bearer secret-token"
    assert captured["timeout"] == 20
    assert result.checkpoint == "next-2"
    assert len(result.records) == 1
    assert result.records[0]["source_id"] == "p1"


def test_lead_source_wrapper_preserves_checkpoint_for_scheduler():
    config = DiscoverySourceConfig(
        lane="reddit_signal",
        source="Reddit",
        endpoint="https://collector.example.test/reddit",
    )
    source = AuthorizedDiscoveryLeadSource(config)
    assert source.name == "Reddit"
    assert source.definition.lane == "reddit_signal"
    assert source.last_checkpoint is None
