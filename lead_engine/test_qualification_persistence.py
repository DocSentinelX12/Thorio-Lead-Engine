from .database import LeadDB
from .qualification import qualify_lead


def test_qualification_decision_persists_locally(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    lead = {
        "fingerprint": "qualification-test-001",
        "company": "Acme",
        "qualified": False,
        "status": "Unverified",
        "review_status": "Review",
    }

    inserted = db.insert_if_new(lead)

    assert inserted is True

    qualified = qualify_lead(
        lead,
        qualified=True,
    )

    stored = db.update_payload(
        lead["fingerprint"],
        qualified,
    )

    assert stored is not None
    assert stored["qualified"] is True
    assert stored["status"] == "Qualified"
    assert stored["review_status"] == "Qualified"


def test_not_qualified_decision_persists_locally(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    lead = {
        "fingerprint": "qualification-test-002",
        "company": "Example Corp",
        "qualified": False,
        "status": "In Review",
        "review_status": "Review",
    }

    db.insert_if_new(lead)

    rejected = qualify_lead(
        lead,
        qualified=False,
        reason="No confirmed technology need.",
    )

    stored = db.update_payload(
        lead["fingerprint"],
        rejected,
    )

    assert stored is not None
    assert stored["qualified"] is False
    assert stored["status"] == "Not Qualified"
    assert stored["review_status"] == "Not Qualified"
    assert stored["reason_not_qualified"] == (
        "No confirmed technology need."
    )
