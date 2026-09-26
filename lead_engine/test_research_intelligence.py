from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from lead_engine import research_package
from lead_engine.sales_handoff import package_digest, package_projection


def _lead() -> dict:
    return {
        "opportunity_id": "opp-intel-1",
        "fingerprint": "opp-intel-1",
        "identity_version": "1",
        "identity_derivation": {},
        "company": "Acme",
        "company_website": "https://acme.example",
        "source": "LinkedIn",
        "source_id": "source-1",
        "url": "https://linkedin.example/opportunity",
        "person": "Jane Doe",
        "contact_name": "Jane Doe",
        "contact_title": "CTO",
        "contact_email": "jane@acme.example",
        "linkedin_url": "https://linkedin.example/in/janedoe",
        "business_need": "Acme needs an engineering team for its new product.",
        "current_need": "Acme is actively hiring backend engineers.",
        "signal": "Acme is hiring backend engineers.",
        "evidence": "Acme careers page lists backend engineering roles.",
        "potential_routes": ["Shiftr", "Thorio"],
        "company_research": {
            "company_verified": True,
            "company_description": "Acme builds workflow software.",
            "industry": "B2B software",
            "company_size": "51-200",
            "decision_maker": "Jane Doe",
            "decision_maker_title": "CTO",
            "decision_maker_email": "jane@acme.example",
            "decision_maker_verification_status": "verified",
            "decision_maker_evidence": "Jane Doe is CTO at Acme.",
            "public_company_facts": [
                {"url": "https://acme.example/about", "evidence": "Acme builds workflow software.", "observed_at": "2026-09-26T00:00:00+00:00"}
            ],
        },
        "decision_maker_research": {
            "role": "CTO",
            "responsibilities": ["engineering", "technology"],
            "evidence": [
                {"url": "https://acme.example/team", "evidence": "Jane Doe is CTO at Acme.", "observed_at": "2026-09-26T00:00:00+00:00"}
            ],
        },
        "business_need_research": {
            "verified": True,
            "verification_status": "verified",
            "evidence": [
                {
                    "opportunity_id": "opp-intel-1",
                    "fingerprint": "opp-intel-1",
                    "url": "https://acme.example/need",
                    "evidence": "Acme needs an engineering team for its new product.",
                    "observed_at": "2026-09-26T00:00:00+00:00",
                    "verification_status": "verified",
                }
            ],
        },
        "current_intent_research": {
            "verified": True,
            "verification_status": "verified",
            "evidence": [
                {
                    "opportunity_id": "opp-intel-1",
                    "fingerprint": "opp-intel-1",
                    "url": "https://acme.example/careers",
                    "evidence": "Acme is actively hiring backend engineers.",
                    "observed_at": "2026-09-26T00:00:00+00:00",
                    "verification_status": "verified",
                }
            ],
        },
        "technical_product_hiring_research": {
            "verified": True,
            "verification_status": "verified",
            "evidence": [
                {
                    "opportunity_id": "opp-intel-1",
                    "fingerprint": "opp-intel-1",
                    "url": "https://acme.example/jobs",
                    "evidence": "Backend engineering roles are open.",
                    "observed_at": "2026-09-26T00:00:00+00:00",
                    "verification_status": "verified",
                }
            ],
        },
        "commercial_research": {
            "verified": True,
            "verification_status": "verified",
            "evidence": [
                {
                    "opportunity_id": "opp-intel-1",
                    "fingerprint": "opp-intel-1",
                    "url": "https://acme.example/pricing",
                    "evidence": "Acme sells enterprise workflow software.",
                    "observed_at": "2026-09-26T00:00:00+00:00",
                    "verification_status": "verified",
                }
            ],
        },
        "route_research": {
            "routes": {
                "Shiftr": {
                    "verified": True,
                    "verification_status": "verified",
                    "evidence": [
                        {
                            "opportunity_id": "opp-intel-1",
                            "fingerprint": "opp-intel-1",
                            "url": "https://acme.example/careers",
                            "evidence": "Acme needs software engineering support.",
                            "observed_at": "2026-09-26T00:00:00+00:00",
                            "verification_status": "verified",
                        }
                    ],
                },
                "Thorio": {
                    "verified": True,
                    "verification_status": "verified",
                    "evidence": [
                        {
                            "opportunity_id": "opp-intel-1",
                            "fingerprint": "opp-intel-1",
                            "url": "https://acme.example/careers",
                            "evidence": "Acme is hiring backend engineers.",
                            "observed_at": "2026-09-26T00:00:00+00:00",
                            "verification_status": "verified",
                        }
                    ],
                },
            }
        },
        "research_gaps": {"unknowns": ["budget"]},
        "evidence_events": [],
    }


def test_research_intelligence_public_seam_exists():
    assert callable(getattr(research_package, "build_research_intelligence", None))


def test_research_intelligence_preserves_company_need_decision_maker_and_commercial_context():
    intelligence = research_package.build_research_intelligence(_lead())

    assert intelligence["opportunity_id"] == "opp-intel-1"
    assert intelligence["company"]["name"] == "Acme"
    assert intelligence["company"]["known"]["industry"] == "B2B software"
    assert intelligence["need"]["known"]["business_need"] == "Acme needs an engineering team for its new product."
    assert intelligence["need"]["known"]["current_need"] == "Acme is actively hiring backend engineers."
    assert intelligence["decision_maker"]["name"] == "Jane Doe"
    assert intelligence["decision_maker"]["title"] == "CTO"
    assert intelligence["decision_maker"]["verification_status"] == "verified"
    assert intelligence["commercial"]["routes"] == ["Shiftr", "Thorio"]


def test_research_intelligence_claims_are_traceable_and_do_not_promote_observation():
    lead = _lead()
    lead["current_intent_research"]["evidence"][0]["verification_status"] = "observed_evidence"
    lead["current_intent_research"]["verified"] = False

    intelligence = research_package.build_research_intelligence(lead)

    claims = {claim["claim_type"]: claim for claim in intelligence["claims"]}
    assert claims["current_intent"]["status"] == "observed"
    assert claims["current_intent"]["supporting_evidence_keys"]
    assert all(key in intelligence["evidence_graph"]["nodes"] for key in claims["current_intent"]["supporting_evidence_keys"])
    assert claims["current_intent"]["status"] != "verified"


def test_research_intelligence_preserves_conflicting_claims_without_collapsing_them():
    lead = _lead()
    lead["business_need_research"]["evidence"].append(
        {
            "opportunity_id": "opp-intel-1",
            "fingerprint": "opp-intel-1",
            "url": "https://acme.example/status",
            "evidence": "Acme says the engineering project is paused.",
            "observed_at": "2026-09-26T00:30:00+00:00",
            "verification_status": "verified",
            "claim_type": "current_need",
            "claim_value": "paused",
        }
    )

    intelligence = research_package.build_research_intelligence(lead)

    conflicts = intelligence["conflicts"]
    assert conflicts
    assert any(item["claim_type"] == "current_need" for item in conflicts)
    assert len([claim for claim in intelligence["claims"] if claim["claim_type"] == "current_need"]) >= 2


def test_research_intelligence_marks_stale_evidence_without_deleting_it():
    lead = _lead()
    stale_at = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    lead["current_intent_research"]["evidence"][0]["observed_at"] = stale_at

    intelligence = research_package.build_research_intelligence(lead)

    assert intelligence["evidence_graph"]["nodes"]
    node = next(iter(intelligence["evidence_graph"]["nodes"].values()))
    assert node["freshness_status"] == "stale"
    assert intelligence["stale_evidence"]


def test_research_intelligence_rejects_cross_opportunity_evidence():
    lead = _lead()
    lead["business_need_research"]["evidence"].append(
        {
            "opportunity_id": "different-opportunity",
            "fingerprint": "different-opportunity",
            "url": "https://other.example/need",
            "evidence": "Foreign opportunity evidence.",
            "observed_at": "2026-09-26T00:00:00+00:00",
        }
    )

    with pytest.raises(ValueError, match="opportunity"):
        research_package.build_research_intelligence(lead)


def test_research_intelligence_survives_complete_handoff_projection_and_changes_digest():
    lead = _lead()
    intelligence = research_package.build_research_intelligence(lead)
    enriched = {**lead, "research_intelligence": intelligence}

    projection = package_projection(enriched)
    assert projection["research_intelligence"] == intelligence

    digest_before = package_digest(lead)
    digest_after = package_digest(enriched)
    assert digest_before != digest_after


def test_research_intelligence_validates_its_canonical_identity():
    intelligence = research_package.build_research_intelligence(_lead())
    intelligence["opportunity_id"] = "wrong"

    with pytest.raises(ValueError, match="opportunity"):
        research_package.validate_research_intelligence(intelligence, opportunity_id="opp-intel-1")


def test_research_intelligence_merge_preserves_richer_profiles_and_evidence():
    first = research_package.build_research_intelligence(_lead())
    second_lead = _lead()
    second_lead["company_research"]["company_size"] = "201-500"
    second_lead["decision_maker_research"]["responsibilities"] = ["engineering", "security"]
    second_lead["business_need_research"]["evidence"].append({
        "opportunity_id": "opp-intel-1",
        "fingerprint": "opp-intel-1",
        "url": "https://acme.example/need-2",
        "evidence": "The new product requires backend capacity.",
        "observed_at": "2026-09-26T01:00:00+00:00",
        "verification_status": "observed_evidence",
    })
    second = research_package.build_research_intelligence(second_lead)

    merged = research_package.merge_research_intelligence(first, second, opportunity_id="opp-intel-1")

    assert merged["company"]["known"]["company_size"] == "201-500"
    assert merged["decision_maker"]["known"]["responsibilities"] == ["engineering", "security"]
    assert merged["evidence_graph"]["node_count"] >= first["evidence_graph"]["node_count"]
    assert merged["evidence_graph"]["edge_count"] >= first["evidence_graph"]["edge_count"]
