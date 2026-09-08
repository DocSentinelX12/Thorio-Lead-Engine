from datetime import datetime, timezone

from .database import LeadDB
from .research_queue import process_paxus_research_queue, queue_paxus_research


NOW = datetime.now(timezone.utc).isoformat()


def _lead(fingerprint="paxus-1", **extra):
    lead = {
        "fingerprint": fingerprint,
        "company": "ExampleCo",
        "signal": "technology recruitment support",
        "evidence": "The company is seeking technology recruitment support.",
        "need_at": NOW,
        "discovered_at": NOW,
    }
    lead.update(extra)
    return lead


def test_queue_retains_paxus_qualified_lead_for_missing_research(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    try:
        lead = _lead()
        db.insert_if_new(lead)

        result = queue_paxus_research(db, lead)

        assert result["status"] == "research_required"
        assert "named_hiring_contact" in result["missing_research"]
        assert db.pending_research(10)[0]["fingerprint"] == "paxus-1"
        stored = db.get("paxus-1")
        assert stored["research_status"] == "research_required"
        assert stored["research_queue"]["status"] == "research_required"
    finally:
        db.close()


def test_queue_does_not_treat_missing_communication_or_consent_as_research_pass(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    try:
        lead = _lead(contact_name="Jane Doe")
        db.insert_if_new(lead)

        result = queue_paxus_research(db, lead)

        assert result["status"] == "research_required"
        assert result["missing_research"] == []
        assert "contact_communication" in result["missing_verification"]
        assert "contact_consent" in result["missing_verification"]
        assert db.pending_research(10)
    finally:
        db.close()


def test_research_queue_promotes_when_all_existing_gates_become_present(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    try:
        lead = _lead(fingerprint="paxus-2")
        db.insert_if_new(lead)
        queue_paxus_research(db, lead)

        db.update_payload(
            "paxus-2",
            {
                "contact_name": "Jane Doe",
                "contact_communicated": True,
                "contact_consent": True,
            },
        )

        result = process_paxus_research_queue(db, 10)

        assert "paxus-2" in result["completed"]
        assert db.pending_research(10) == []
        stored = db.get("paxus-2")
        assert stored["research_status"] == "complete"
        assert stored["qualification_results"]["Paxus"]["true_referral"] is True
    finally:
        db.close()


def test_research_retry_preserves_missing_items_and_never_fakes_consent(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    try:
        lead = _lead(
            fingerprint="paxus-3",
            contact_name="Jane Doe",
        )
        db.insert_if_new(lead)
        queue_paxus_research(db, lead)

        result = process_paxus_research_queue(db, 10)

        assert "paxus-3" in result["still_required"]
        queued = db.pending_research(10)[0]
        assert "contact_communication" in queued["missing_items"]
        assert "contact_consent" in queued["missing_items"]
        stored = db.get("paxus-3")
        assert stored["qualification_results"]["Paxus"]["true_referral"] is False
    finally:
        db.close()
