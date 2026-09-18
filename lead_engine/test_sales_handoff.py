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
        "potential_routes": ["Thorio"],
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
