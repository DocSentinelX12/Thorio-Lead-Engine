from __future__ import annotations

import pytest

from lead_engine.sales_intelligence import SalesIntelligenceError, build_closer_intelligence, validate_outreach_copy


def _lead(**overrides):
    lead = {
        "fingerprint": "op-1",
        "company": "Acme",
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_email": "taylor@acme.example",
            "decision_maker_evidence": "https://acme.example/team/taylor",
            "decision_maker_verification_status": "verified",
        },
        "business_need_research": {
            "verified": True,
            "verification_status": "verified",
            "summary": "Acme is expanding its engineering capacity.",
            "evidence": [{"url": "https://acme.example/jobs", "evidence": "Engineering hiring expansion"}],
        },
        "current_intent_research": {
            "verified": True,
            "verification_status": "verified",
            "current_need": "Acme is actively hiring software engineers.",
            "evidence": [{"url": "https://acme.example/careers", "evidence": "Open engineering roles"}],
        },
        "technical_product_hiring_research": {
            "verified": True,
            "verification_status": "verified",
            "summary": "Engineering hiring is active.",
            "evidence": [{"url": "https://acme.example/careers", "evidence": "Open engineering roles"}],
        },
        "commercial_research": {
            "verified": True,
            "verification_status": "verified",
            "summary": "Acme is investing in engineering growth.",
            "evidence": [{"url": "https://acme.example/about", "evidence": "Growth information"}],
        },
        "route_research": {
            "verified": True,
            "verification_status": "verified",
            "summary": "The researched need supports a technology hiring route.",
            "evidence": [{"url": "https://acme.example/careers", "evidence": "Open engineering roles"}],
        },
        "research_gaps": {"unknowns": ["budget"]},
    }
    lead.update(overrides)
    return lead


def test_closer_intelligence_is_exactly_opportunity_scoped():
    package = build_closer_intelligence(_lead())
    assert package["opportunity_fingerprint"] == "op-1"
    assert package["company"] == "Acme"
    assert package["decision_maker"]["name"] == "Taylor"
    assert all(item["evidence_refs"] for item in package["verified_facts"])
    assert package["unknowns"] == ["budget"]


def test_unverified_section_cannot_be_presented_as_verified_closer_fact():
    lead = _lead()
    lead["current_intent_research"]["verified"] = False
    lead["current_intent_research"]["verification_status"] = "observed_evidence"
    lead["business_need_research"]["verified"] = False
    lead["business_need_research"]["verification_status"] = "observed_evidence"
    with pytest.raises(SalesIntelligenceError, match="current need"):
        build_closer_intelligence(lead)


def test_verified_section_without_provenance_is_rejected():
    lead = _lead()
    lead["commercial_research"]["evidence"] = []
    with pytest.raises(SalesIntelligenceError, match="no provenance"):
        build_closer_intelligence(lead)


def test_prospect_evidence_with_another_fingerprint_is_rejected():
    lead = _lead()
    lead["business_need_research"]["evidence"][0]["fingerprint"] = "op-other"
    with pytest.raises(SalesIntelligenceError, match="different opportunity"):
        build_closer_intelligence(lead)


def test_outreach_copy_rejects_forbidden_dash_characters_and_bad_punctuation():
    ok, errors = validate_outreach_copy("Hello Taylor, I found a relevant opportunity.")
    assert ok is True
    assert errors == []

    ok, errors = validate_outreach_copy("Hello Taylor — this is relevant...")
    assert ok is False
    assert "forbidden_dash_character" in errors
    assert "repeated_periods" in errors
