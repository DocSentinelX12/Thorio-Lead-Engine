from .database import LeadDB
from .opportunity_signal_intelligence import detect_compound_opportunities, detect_compound_opportunities_from_db


def _lead(fp, *, source, company="Acme", when="2026-09-28T00:00:00+00:00", matches=None):
    return {
        "fingerprint": fp,
        "opportunity_id": fp,
        "source": source,
        "company": company,
        "discovered_at": when,
        "signal_matches": matches or [],
    }


def test_compound_detection_requires_distinct_sources_and_exact_triggers():
    result = detect_compound_opportunities([
        _lead("a", source="Source A", matches=["Need AI integration"]),
        _lead("b", source="Source B", when="2026-09-29T00:00:00+00:00", matches=["Looking for a development partner"]),
    ])

    assert result["cluster_count"] == 1
    cluster = result["clusters"][0]
    assert cluster["opportunity_ids"] == ["a", "b"]
    assert cluster["sources"] == ["Source A", "Source B"]
    assert cluster["commercial_triggers"] == ["looking for a development partner", "need ai integration"]


def test_compound_detection_does_not_merge_opportunity_identity():
    result = detect_compound_opportunities([
        _lead("a", source="Source A", matches=["Need AI integration"]),
        _lead("b", source="Source B", when="2026-09-29T00:00:00+00:00", matches=["Need MVP"]),
    ])
    assert result["clusters"][0]["opportunity_ids"] == ["a", "b"]
    assert result["clusters"][0]["opportunity_count"] == 2


def test_compound_detection_rejects_single_source_or_single_trigger():
    result = detect_compound_opportunities([
        _lead("a", source="Source A", matches=["Need AI integration"]),
        _lead("b", source="Source A", when="2026-09-29T00:00:00+00:00", matches=["Need MVP"]),
        _lead("c", source="Source B", when="2026-11-01T00:00:00+00:00", matches=["Need AI integration"]),
    ])
    assert result["cluster_count"] == 0


def test_compound_detection_respects_time_window():
    result = detect_compound_opportunities([
        _lead("a", source="Source A", when="2026-01-01T00:00:00+00:00", matches=["Need AI integration"]),
        _lead("b", source="Source B", when="2026-03-15T00:00:00+00:00", matches=["Need MVP"]),
    ], window_seconds=30 * 24 * 60 * 60)
    assert result["cluster_count"] == 0


def test_compound_detection_uses_company_domain_when_available():
    first = _lead("a", source="Source A", company="Acme One", matches=["Need AI integration"])
    first["company_website"] = "https://acme.example"
    second = _lead("b", source="Source B", company="Different Display Name", when="2026-09-29T00:00:00+00:00", matches=["Need MVP"])
    second["company_website"] = "acme.example"
    result = detect_compound_opportunities([first, second])
    assert result["cluster_count"] == 1


def test_compound_detection_db_reader_is_durable(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    db.insert_if_new(_lead("a", source="Source A", matches=["Need AI integration"]))
    db.insert_if_new(_lead("b", source="Source B", when="2026-09-29T00:00:00+00:00", matches=["Need MVP"]))
    assert detect_compound_opportunities_from_db(db)["cluster_count"] == 1
