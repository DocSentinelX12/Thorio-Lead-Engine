from .database import LeadDB
from .sales_handoff import package_digest, verify_airtable_handoff, verify_lead_radar_record, verify_research_record


def _ready_lead():
    return {
        "fingerprint": "handoff-test",
        "company": "Acme",
        "contact_name": "Taylor",
        "contact_email": "taylor@example.com",
        "qualified": True,
        "research_status": "complete",
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "decision_maker_verification_status": "verified",
            "decision_maker_email": "taylor@example.com",
        },
        "decision_maker_research": {"verified": True, "verification_status": "verified", "evidence": ["https://example.com/taylor"]},
        "business_need_research": {"verified": True, "verification_status": "verified", "business_need": "engineering expansion", "evidence": ["https://example.com/need"]},
        "current_intent_research": {"verified": True, "verification_status": "verified", "current_need": "engineering expansion", "evidence": ["https://example.com/intent"]},
        "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": ["https://example.com/hiring"]},
        "commercial_research": {"verified": True, "verification_status": "verified", "evidence": ["https://example.com/commercial"]},
        "route_research": {"verified": True, "verification_status": "verified", "routes": {"Thorio": {"verified": True, "verification_status": "verified", "evidence": "engineering expansion"}}},
        "closer_package": {"ready": True, "verification_status": "verified", "evidence": ["https://example.com/need"]},
        "potential_routes": ["Thorio"], "eligible_routes": ["Thorio"], "preserved_routes": ["Thorio"], "routing_result": {"destinations": ["Thorio"], "review_required": False},
    }


def _records(lead):
    digest = package_digest(lead)
    raw = dict(lead)
    raw["__thorio_package_digest"] = digest
    return (
        {"id": "recLead", "fields": {"Duplicate Key": lead["fingerprint"], "Company": lead["company"]}},
        {"id": "recResearch", "fields": {"Research Key": lead["fingerprint"], "Lead Fingerprint": lead["fingerprint"], "Raw Research Package": __import__("json").dumps(raw, sort_keys=True)}},
        {"status": "synced", "company": {"status": "created", "record": {"id": "recCompany", "fields": {"Company": lead["company"]}}}, "opportunities": []},
    )


def test_exact_handoff_verification_accepts_matching_records():
    lead = _ready_lead()
    lead_record, research_record, master_tracker = _records(lead)
    confirmed, value = verify_airtable_handoff({"airtable_record": lead_record, "research_record": research_record, "master_tracker": master_tracker}, lead)
    assert confirmed is True
    assert value == package_digest(lead)


def test_exact_handoff_verification_rejects_stale_research_package():
    lead = _ready_lead()
    lead_record, research_record, master_tracker = _records(lead)
    changed = dict(lead)
    changed["business_need"] = "different current need"
    confirmed, reason = verify_airtable_handoff({"airtable_record": lead_record, "research_record": research_record, "master_tracker": master_tracker}, changed)
    assert confirmed is False
    assert reason == "research_record_package_mismatch"


def test_handoff_confirmation_is_durable_and_digest_bound(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _ready_lead()
    digest = package_digest(lead)
    db.record_airtable_handoff(lead["fingerprint"], digest, "recLead", "recResearch", ["recCompany"], "2026-09-18T00:00:00+00:00")
    stored = db.get_airtable_handoff(lead["fingerprint"])
    assert stored["package_digest"] == digest
    assert stored["lead_radar_record_id"] == "recLead"
    assert stored["research_record_id"] == "recResearch"


def _multi_route_master_tracker(lead):
    return {
        "status": "synced",
        "company": {"status": "created", "record": {"id": "recCompany", "fields": {"Company": lead["company"]}}},
        "opportunities": [
            {"status": "created", "record": {"id": "recPaxus", "fields": {"Opportunity": f'{lead["fingerprint"]}:Paxus', "Company": lead["company"], "Partner": "Paxus", "Notes": f'Lead fingerprint: {lead["fingerprint"]}'}}},
            {"status": "created", "record": {"id": "recShiftr", "fields": {"Opportunity": f'{lead["fingerprint"]}:Shiftr', "Company": lead["company"], "Partner": "Shiftr", "Notes": f'Lead fingerprint: {lead["fingerprint"]}'}}},
        ],
    }


def test_master_tracker_verification_requires_exact_route_bound_opportunities():
    lead = _ready_lead()
    lead["potential_routes"] = ["Paxus", "Shiftr", "Thorio"]
    result = _multi_route_master_tracker(lead)
    assert verify_airtable_handoff(
        {"airtable_record": _records(lead)[0], "research_record": _records(lead)[1], "master_tracker": result},
        lead,
    )[0] is True


def test_master_tracker_verification_rejects_wrong_route_opportunity():
    lead = _ready_lead()
    lead["potential_routes"] = ["Paxus", "Shiftr"]
    result = _multi_route_master_tracker(lead)
    result["opportunities"][1]["record"]["fields"]["Opportunity"] = f'{lead["fingerprint"]}:Thorio'
    result["opportunities"][1]["record"]["fields"]["Partner"] = "Thorio"
    assert verify_airtable_handoff(
        {"airtable_record": _records(lead)[0], "research_record": _records(lead)[1], "master_tracker": result},
        lead,
    )[0] is False


def test_master_tracker_verification_rejects_missing_route_opportunity():
    lead = _ready_lead()
    lead["potential_routes"] = ["Paxus", "Shiftr"]
    result = _multi_route_master_tracker(lead)
    result["opportunities"] = result["opportunities"][:1]
    assert verify_airtable_handoff(
        {"airtable_record": _records(lead)[0], "research_record": _records(lead)[1], "master_tracker": result},
        lead,
    )[0] is False


def test_package_projection_contains_canonical_identity():
    from .sales_handoff import package_projection

    lead = _ready_lead()
    lead.update({
        "source": "linkedin",
        "source_id": "post-1",
        "url": "https://linkedin.example/post-1",
        "person": "Taylor",
        "job_title": "CTO",
        "signal_type": "hiring",
        "discovered_at": "2026-09-26T00:00:00+00:00",
    })
    from .lead_identity import canonical_opportunity_identity
    lead.update(canonical_opportunity_identity(lead))

    projection = package_projection(lead)

    assert projection["opportunity_id"] == lead["fingerprint"]
    assert projection["identity_version"] == "1"
    assert projection["identity_derivation"]["source_id"] == "post-1"


def test_package_projection_rejects_mismatched_canonical_identity():
    import pytest
    from .sales_handoff import package_projection

    lead = _ready_lead()
    lead["opportunity_id"] = "different-opportunity"

    with pytest.raises(ValueError, match="opportunity_id.*fingerprint"):
        package_projection(lead)
