from .advanced_agent_logic import company_research
from .database import LeadDB


class Context:
    def __init__(self, db):
        self.db = db


def test_company_research_persists_observed_person_and_handoff(tmp_path):
    db = LeadDB(str(tmp_path))
    fingerprint = "research-test"
    lead = {
        "fingerprint": fingerprint,
        "company": "ExampleCo",
        "person": "Jane Doe",
        "signal": "We are hiring a software engineer now.",
        "evidence": "Jane Doe posted that ExampleCo is hiring a software engineer now.",
        "url": "https://example.com/post",
        "source_url": "https://example.com/post",
    }
    assert db.insert_if_new(lead) is True

    result = company_research({"lead": lead, "evidence_events": [lead]}, Context(db))
    stored = db.get(fingerprint)

    # A named person observed in collector evidence is not automatically a
    # verified decision-maker. Role verification must come from separate
    # evidence before research can be marked complete.
    assert result["research_status"] == "research_required"
    assert result["decision_maker_verified"] is False
    assert stored["company_research"]["company_verified"] is True
    assert stored["company_research"]["decision_maker"] == "Jane Doe"
    assert stored["company_research"]["decision_maker_evidence"]
    assert stored["company_research"]["decision_maker_verification_status"] == "observed_needs_role_verification"
    assert stored["research_status"] == "research_required"
    db.close()


def test_company_research_does_not_invent_missing_person(tmp_path):
    db = LeadDB(str(tmp_path))
    fingerprint = "research-test-no-person"
    lead = {
        "fingerprint": fingerprint,
        "company": "ExampleCo",
        "signal": "We are hiring a software engineer now.",
        "evidence": "Current hiring evidence.",
        "url": "https://example.com/job",
    }
    assert db.insert_if_new(lead) is True

    result = company_research({"lead": lead}, Context(db))
    stored = db.get(fingerprint)

    assert result["research_status"] == "research_required"
    assert result["decision_maker_verified"] is False
    assert "decision_maker" not in stored["company_research"]
    assert stored["company_research"]["fabricated_fields"] == []
    db.close()
