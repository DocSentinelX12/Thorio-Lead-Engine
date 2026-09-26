from __future__ import annotations

from datetime import datetime, timezone

import pytest

from lead_engine.qualification import _route_research
from lead_engine.research_package import _explicitly_verified, _section_has_evidence, finalize_research_readiness, research_readiness
from lead_engine.research_intelligence import build_research_intelligence, validate_research_intelligence


def _route_section(*, evidence: bool = True, verified: bool = True) -> dict:
    return {
        "verified": False,
        "verification_status": "observed_evidence",
        "evidence": [{"url": "https://example.test/route", "evidence": "Current engineering hiring need.", "observed_at": datetime.now(timezone.utc).isoformat()}] if evidence else [],
        "routes": {
            "Thorio": {
                "verified": verified,
                "verification_status": "verified" if verified else "observed_evidence",
                "evidence": [{"url": "https://example.test/route", "evidence": "Current engineering hiring need.", "observed_at": datetime.now(timezone.utc).isoformat()}] if evidence else [],
            }
        },
    }


def test_nested_verified_route_is_a_real_verified_route_section():
    section = _route_section()

    assert _section_has_evidence(section) is True
    assert _explicitly_verified(section) is True
    assert _route_research({"route_research": section}, "Thorio") == {
        "verified": True,
        "evidence": "Current engineering hiring need.",
        "reason": "Thorio route research verified.",
    }


def test_nested_route_without_evidence_cannot_become_verified():
    section = _route_section(evidence=False, verified=True)

    assert _section_has_evidence(section) is False
    assert _explicitly_verified(section) is False
    result = _route_research({"route_research": section}, "Thorio")
    assert result["verified"] is False
    assert result["evidence"] == ""


def test_observed_route_parent_cannot_promote_unverified_nested_route():
    section = _route_section(evidence=True, verified=False)

    assert _explicitly_verified(section) is False
    result = _route_research({"route_research": section}, "Thorio")
    assert result["verified"] is False


def test_research_gaps_report_actual_empty_sections_not_verified_state():
    lead = {
        "business_need_research": {"verified": True, "verification_status": "verified", "evidence": [{"evidence": "Need", "url": "https://example.test/need"}]},
        "current_intent_research": {"verified": True, "verification_status": "verified", "evidence": [{"evidence": "Hiring", "url": "https://example.test/hiring"}]},
        "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": [{"evidence": "Engineering", "url": "https://example.test/engineering"}]},
        "commercial_research": {"verified": True, "verification_status": "verified", "evidence": []},
        "route_research": _route_section(),
        "research_gaps": {},
    }

    updated, readiness = finalize_research_readiness(lead)

    assert readiness["ready"] is False
    assert readiness["missing_sections"] == ["commercial_research"]
    assert updated["research_gaps"]["missing_sections"] == ["commercial_research"]
    assert "research_intelligence" in readiness["blockers"]


def test_empty_research_intelligence_can_never_make_handoff_ready():
    lead = {
        "opportunity_id": "opp-regression-1",
        "fingerprint": "opp-regression-1",
        "business_need_research": {"verified": True, "verification_status": "verified", "evidence": [{"evidence": "Need", "url": "https://example.test/need"}]},
        "current_intent_research": {"verified": True, "verification_status": "verified", "evidence": [{"evidence": "Hiring", "url": "https://example.test/hiring"}]},
        "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": [{"evidence": "Engineering", "url": "https://example.test/engineering"}]},
        "commercial_research": {"verified": True, "verification_status": "verified", "evidence": [{"evidence": "Commercial context", "url": "https://example.test/commercial"}]},
        "route_research": _route_section(),
        "company_research": {"company_verified": True, "decision_maker": "Jane Doe", "decision_maker_evidence": "https://example.test/team", "decision_maker_verification_status": "verified"},
        "closer_package": {"ready": True, "evidence": [{"evidence": "Need", "url": "https://example.test/need"}]},
        "research_intelligence": {},
    }

    readiness = research_readiness(lead)

    assert readiness["ready"] is False
    assert "research_intelligence" in readiness["blockers"]


def test_research_intelligence_identity_is_checked_at_validation_boundary():
    lead = {
        "opportunity_id": "opp-regression-2",
        "fingerprint": "opp-regression-2",
        "company": "Acme",
        "company_research": {"company_verified": True, "decision_maker": "Jane Doe", "decision_maker_verification_status": "verified", "decision_maker_evidence": "https://example.test/team"},
        "business_need_research": {"verified": True, "verification_status": "verified", "evidence": [{"opportunity_id": "opp-regression-2", "fingerprint": "opp-regression-2", "url": "https://example.test/need", "evidence": "Acme needs engineers.", "observed_at": datetime.now(timezone.utc).isoformat(), "verification_status": "verified"}]},
    }
    intelligence = build_research_intelligence(lead)
    intelligence["opportunity_id"] = "wrong-opportunity"

    with pytest.raises(ValueError, match="opportunity"):
        validate_research_intelligence(intelligence, opportunity_id="opp-regression-2")
