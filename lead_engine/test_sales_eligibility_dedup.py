from datetime import datetime, timezone

from .active_processing import _sales_eligibility
from .database import LeadDB


def _lead(fingerprint, business_need="remote software engineer hiring"):
    return {
        "fingerprint": fingerprint,
        "company": "Acme",
        "person": "Taylor",
        "business_need": business_need,
        "contact_email": "taylor@example.com",
        "qualified": True,
        "potential_routes": ["Thorio"],
        "need_at": datetime.now(timezone.utc).isoformat(),
        "company_research": {
            "decision_maker": "Taylor",
            "decision_maker_evidence": "verified company evidence",
            "decision_maker_email": "taylor@example.com",
        },
    }


def _routing():
    return {"destinations": ["Thorio"], "review_required": False}


def test_missing_exact_opportunity_is_blocked(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _lead("missing-opportunity", business_need="")
    db.insert_if_new(lead)
    eligible, reason = _sales_eligibility(lead, _routing(), {}, db)
    assert eligible is False
    assert reason == "missing_exact_opportunity"


def test_exact_same_company_person_and_need_is_blocked_as_duplicate(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    existing = _lead("existing-opportunity")
    current = _lead("current-opportunity")
    db.insert_if_new(existing)
    db.insert_if_new(current)

    eligible, reason = _sales_eligibility(current, _routing(), {}, db)
    assert eligible is False
    assert reason == "exact_duplicate"


def test_different_business_need_remains_eligible(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    existing = _lead("existing-opportunity")
    current = _lead("current-opportunity", business_need="AI agent development")
    db.insert_if_new(existing)
    db.insert_if_new(current)

    eligible, reason = _sales_eligibility(current, _routing(), {}, db)
    assert eligible is True
    assert reason == "eligible"
