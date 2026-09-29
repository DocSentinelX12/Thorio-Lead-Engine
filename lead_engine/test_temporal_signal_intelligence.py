from datetime import datetime, timezone

from .database import LeadDB
from .temporal_signal_intelligence import analyze_temporal_signals, temporal_signal_intelligence


def _lead(fp, when, *, source="A", company="Acme", matches=None):
    return {
        "fingerprint": fp,
        "opportunity_id": fp,
        "company": company,
        "source": source,
        "discovered_at": when,
        "signal_matches": matches or [],
    }


def test_temporal_intelligence_uses_explicit_observation_times():
    result = analyze_temporal_signals([
        _lead("a", "2026-09-20T00:00:00+00:00", matches=["Need AI integration"]),
        _lead("b", "2026-09-24T00:00:00+00:00", source="B", matches=["Need MVP"]),
        _lead("c", "2026-09-27T00:00:00+00:00", source="C", matches=["Need AI integration"]),
    ], now=datetime(2026, 9, 28, tzinfo=timezone.utc))
    profile = result["profiles"][0]
    assert profile["observation_count"] == 3
    assert profile["unique_source_count"] == 3
    assert profile["unique_trigger_count"] == 2
    assert profile["recent_7d_observations"] == 2
    assert profile["observed_cadence_acceleration"] is True


def test_temporal_intelligence_does_not_treat_old_observations_as_current():
    result = analyze_temporal_signals([
        _lead("old", "2026-07-01T00:00:00+00:00"),
        _lead("recent", "2026-09-27T00:00:00+00:00"),
    ], now=datetime(2026, 9, 28, tzinfo=timezone.utc))
    assert result["profiles"][0]["observation_count"] == 1


def test_temporal_intelligence_preserves_distinct_opportunities():
    result = analyze_temporal_signals([
        _lead("a", "2026-09-25T00:00:00+00:00", source="A"),
        _lead("b", "2026-09-26T00:00:00+00:00", source="B"),
    ], now=datetime(2026, 9, 28, tzinfo=timezone.utc))
    assert result["profiles"][0]["opportunity_ids"] == ["a", "b"]


def test_temporal_intelligence_can_use_company_domain():
    first = _lead("a", "2026-09-25T00:00:00+00:00", company="Different Display")
    first["company_website"] = "https://acme.example"
    second = _lead("b", "2026-09-26T00:00:00+00:00", company="Acme")
    second["company_website"] = "acme.example"
    result = analyze_temporal_signals([first, second], now=datetime(2026, 9, 28, tzinfo=timezone.utc))
    assert result["profiles"][0]["observation_count"] == 2


def test_temporal_signal_intelligence_reads_durable_db(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    db.insert_if_new(_lead("a", "2026-09-27T00:00:00+00:00"))
    result = temporal_signal_intelligence(db, now=datetime(2026, 9, 28, tzinfo=timezone.utc))
    assert result["profiles"][0]["observation_count"] == 1
