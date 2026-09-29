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


def test_compound_detection_preserves_repeated_hiring_as_structural_evidence():
    first = _lead("a", source="LinkedIn", matches=[])
    first.update({
        "signal_type": "hiring",
        "job_title": "Senior Software Engineer",
        "evidence": "Acme is hiring a Senior Software Engineer.",
    })
    second = _lead("b", source="Company Careers", when="2026-09-29T00:00:00+00:00", matches=["Need AI integration"])
    second.update({
        "signal_type": "hiring",
        "job_title": "AI Engineer",
        "evidence": "Acme is hiring an AI Engineer.",
    })

    result = detect_compound_opportunities([first, second])

    assert result["cluster_count"] == 1
    assert "repeated_hiring_activity" in result["clusters"][0]["commercial_triggers"]
    assert "need ai integration" in result["clusters"][0]["commercial_triggers"]


def test_repeated_hiring_alone_does_not_create_commercial_cluster():
    first = _lead("a", source="LinkedIn", matches=[])
    first.update({"signal_type": "hiring", "job_title": "Software Engineer"})
    second = _lead("b", source="Company Careers", when="2026-09-29T00:00:00+00:00", matches=[])
    second.update({"signal_type": "hiring", "job_title": "AI Engineer"})

    result = detect_compound_opportunities([first, second])

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


def test_compound_detection_uses_safe_broadened_structural_and_indirect_signals():
    first = _lead(
        "a",
        source="Product Hunt",
        matches=[],
    )
    first["company"] = "Acme"
    first["commercial_signal_broadening"] = {
        "matches": [
            {
                "phrase": "new product launch",
                "attribution": "company_named",
                "temporal_status": "current_or_unspecified",
                "certainty": "observed",
                "negated": False,
            }
        ]
    }
    second = _lead(
        "b",
        source="LinkedIn",
        when="2026-09-29T00:00:00+00:00",
        matches=[],
    )
    second["company"] = "Acme"
    second["commercial_signal_broadening"] = {
        "matches": [
            {
                "phrase": "evaluating vendors",
                "attribution": "first_person",
                "temporal_status": "current_or_unspecified",
                "certainty": "exploratory",
                "negated": False,
            }
        ]
    }

    result = detect_compound_opportunities([first, second])

    assert result["cluster_count"] == 1
    assert result["clusters"][0]["commercial_triggers"] == [
        "evaluating vendors",
        "new product launch",
    ]


def test_compound_detection_ignores_unsafe_broadened_signals():
    first = _lead("a", source="Source A")
    first["commercial_signal_broadening"] = {
        "matches": [
            {
                "phrase": "evaluating vendors",
                "attribution": "unattributed",
                "temporal_status": "current_or_unspecified",
                "certainty": "exploratory",
                "negated": False,
            }
        ]
    }
    second = _lead("b", source="Source B", when="2026-09-29T00:00:00+00:00")
    second["commercial_signal_broadening"] = {
        "matches": [
            {
                "phrase": "new product launch",
                "attribution": "company_named",
                "temporal_status": "historical",
                "certainty": "observed",
                "negated": False,
            }
        ]
    }

    result = detect_compound_opportunities([first, second])

    assert result["cluster_count"] == 0


def test_funding_followed_by_execution_is_preserved_as_ordered_cross_source_relationship():
    funding = _lead(
        "funding",
        source="Company News",
        when="2026-09-01T00:00:00+00:00",
        matches=[],
    )
    funding["commercial_signal_broadening"] = {
        "matches": [
            {
                "category": "funding_execution",
                "phrase": "raised Series A",
                "attribution": "company_named",
                "temporal_status": "current_or_unspecified",
                "certainty": "observed",
                "negated": False,
            }
        ]
    }
    execution = _lead(
        "execution",
        source="Product Hunt",
        when="2026-09-15T00:00:00+00:00",
        matches=["Need AI integration"],
    )
    execution["commercial_signal_broadening"] = {
        "matches": [
            {
                "category": "product_event",
                "phrase": "new product launch",
                "attribution": "company_named",
                "temporal_status": "current_or_unspecified",
                "certainty": "observed",
                "negated": False,
            }
        ]
    }

    result = detect_compound_opportunities([funding, execution])

    assert result["cluster_count"] == 1
    cluster = result["clusters"][0]
    assert "funding_followed_by_execution" in cluster["commercial_triggers"]
    relationship = cluster["structural_relationships"][0]
    assert relationship["relationship"] == "funding_followed_by_execution"
    assert relationship["funding"]["opportunity_id"] == "funding"
    assert relationship["execution"]["opportunity_id"] == "execution"


def test_funding_after_execution_does_not_count_as_funding_followed_by_execution():
    funding = _lead(
        "funding",
        source="Company News",
        when="2026-09-15T00:00:00+00:00",
        matches=[],
    )
    funding["commercial_signal_broadening"] = {
        "matches": [
            {
                "category": "funding_execution",
                "phrase": "new funding",
                "attribution": "company_named",
                "temporal_status": "current_or_unspecified",
                "certainty": "observed",
                "negated": False,
            }
        ]
    }
    execution = _lead(
        "execution",
        source="Product Hunt",
        when="2026-09-01T00:00:00+00:00",
        matches=[],
    )
    execution["commercial_signal_broadening"] = {
        "matches": [
            {
                "category": "product_event",
                "phrase": "product launch",
                "attribution": "company_named",
                "temporal_status": "current_or_unspecified",
                "certainty": "observed",
                "negated": False,
            }
        ]
    }

    result = detect_compound_opportunities([funding, execution])

    assert result["cluster_count"] == 0


def test_historical_funding_cannot_establish_funding_followed_by_execution():
    funding = _lead(
        "funding",
        source="Company News",
        when="2026-09-01T00:00:00+00:00",
        matches=[],
    )
    funding["commercial_signal_broadening"] = {
        "matches": [
            {
                "category": "funding_execution",
                "phrase": "new funding",
                "attribution": "company_named",
                "temporal_status": "historical",
                "certainty": "observed",
                "negated": False,
            }
        ]
    }
    execution = _lead(
        "execution",
        source="Product Hunt",
        when="2026-09-15T00:00:00+00:00",
        matches=[],
    )
    execution["commercial_signal_broadening"] = {
        "matches": [
            {
                "category": "product_event",
                "phrase": "new product launch",
                "attribution": "company_named",
                "temporal_status": "current_or_unspecified",
                "certainty": "observed",
                "negated": False,
            }
        ]
    }

    assert detect_compound_opportunities([funding, execution])["cluster_count"] == 0
