from .lead_identity import canonical_opportunity_identity
from .models import Lead
from .research_package import build_canonical_research_package, build_research_intelligence
from .sales_handoff import package_digest, package_projection


def test_canonical_opportunity_identity_survives_research_and_handoff_projection():
    lead = Lead(
        source="linkedin",
        source_id="post-1",
        url="https://linkedin.example/post-1",
        company="Acme",
        person="Jane CTO",
        job_title="AI Engineer",
        signal_type="hiring",
        discovered_at="2026-09-26T00:00:00+00:00",
        signal="Hiring an AI engineer",
    )
    payload = lead.to_dict()
    identity = canonical_opportunity_identity(payload)

    company_research = {
        "company_verified": True,
        "decision_maker": "Jane CTO",
        "decision_maker_evidence": "https://acme.example/team",
        "decision_maker_verification_status": "verified",
        "public_company_facts": [{"url": "https://acme.example/about", "evidence": "Acme builds software.", "observed_at": "2026-09-26T00:30:00+00:00", "verification_status": "verified"}],
        "public_business_need_facts": [{"url": "https://acme.example/need", "evidence": "Acme needs AI engineering support.", "observed_at": "2026-09-26T01:00:00+00:00", "verification_status": "verified"}],
        "public_hiring_facts": [{"url": "https://acme.example/jobs", "evidence": "Acme is hiring AI engineers.", "observed_at": "2026-09-26T01:05:00+00:00", "verification_status": "verified"}],
        "public_product_facts": [{"url": "https://acme.example/product", "evidence": "Acme operates an AI software product.", "observed_at": "2026-09-26T01:10:00+00:00", "verification_status": "verified"}],
        "public_commercial_facts": [{"url": "https://acme.example/pricing", "evidence": "Acme sells its software commercially.", "observed_at": "2026-09-26T01:15:00+00:00", "verification_status": "verified"}],
        "public_decision_maker_facts": [{"url": "https://acme.example/team", "evidence": "Jane CTO leads technology at Acme.", "observed_at": "2026-09-26T01:20:00+00:00", "verification_status": "verified"}],
    }
    specialist_findings = {
        "recent_inquiry_discovery": {"findings": [{"url": "https://acme.example/inquiry", "evidence": "Acme is actively seeking AI engineering capacity.", "observed_at": "2026-09-26T01:25:00+00:00", "verification_status": "verified"}]},
        "engineering_demand_discovery": {"findings": [{"url": "https://acme.example/engineering", "evidence": "Acme needs AI engineering support.", "observed_at": "2026-09-26T01:30:00+00:00", "verification_status": "verified"}]},
        "social_company_context": {"findings": [{"url": "https://acme.example/commercial", "evidence": "Acme is expanding its commercial software operation.", "observed_at": "2026-09-26T01:35:00+00:00", "verification_status": "verified"}]},
    }
    package = build_canonical_research_package(payload, company_research, specialist_findings)
    enriched = {**payload, **package, "company_research": company_research, "research_status": "complete",
        "potential_routes": ["Thorio"], "eligible_routes": ["Thorio"], "preserved_routes": ["Thorio"],
        "routing_result": {"destinations": ["Thorio"], "review_required": False},
        "closer_package": {"ready": True, "verification_status": "verified", "evidence": package["business_need_research"]["evidence"]}}
    for section_name in ("business_need_research", "current_intent_research", "technical_product_hiring_research", "commercial_research", "route_research"):
        enriched[section_name]["verified"] = True
        enriched[section_name]["verification_status"] = "verified"
    enriched["research_intelligence"] = build_research_intelligence(enriched)
    projection = package_projection(enriched)

    assert enriched["opportunity_id"] == identity["opportunity_id"]
    assert enriched["fingerprint"] == identity["fingerprint"]
    assert projection["opportunity_id"] == identity["opportunity_id"]
    assert projection["fingerprint"] == identity["fingerprint"]
    assert package_digest(enriched)


def test_same_company_and_contact_can_retain_distinct_opportunity_identity():
    first = Lead(
        source="linkedin",
        source_id="post-1",
        url="https://linkedin.example/post-1",
        company="Acme",
        person="Jane CTO",
        job_title="AI Engineer",
        signal_type="hiring",
        discovered_at="2026-09-26T00:00:00+00:00",
    ).to_dict()
    second = Lead(
        source="linkedin",
        source_id="post-2",
        url="https://linkedin.example/post-2",
        company="Acme",
        person="Jane CTO",
        job_title="Data Engineer",
        signal_type="hiring",
        discovered_at="2026-09-26T00:00:00+00:00",
    ).to_dict()

    assert first["opportunity_id"] != second["opportunity_id"]


def test_durable_storage_rejects_cross_opportunity_identity(tmp_path):
    import pytest
    from .database import LeadDB

    db = LeadDB(data_dir=tmp_path)

    with pytest.raises(ValueError, match="opportunity_id.*fingerprint"):
        db.insert_if_new({
            "fingerprint": "opp-1",
            "opportunity_id": "opp-2",
            "company": "Acme",
        })
