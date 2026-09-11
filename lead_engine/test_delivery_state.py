from lead_engine.delivery_state import (
    is_delivery_complete,
    is_ready_for_delivery,
    normalize_delivery_state,
    set_delivery_state,
)


def qualified_lead():
    return {
        "company": "Acme",
        "person": "Jane Doe",
        "route": "Shiftr",
        "lead_score": 80,
        "qualified": True,
        "qualification_status": "qualified",
        "business_need": "Build a remote AI engineering team",
        "signal": "remote software engineer",
        "evidence": "Acme is hiring a remote software engineer.",
        "url": "https://example.com/jobs/123",
    }


def test_normalize_delivery_state_accepts_supported_state():
    assert normalize_delivery_state("approved") == "approved"


def test_normalize_delivery_state_is_case_insensitive():
    assert normalize_delivery_state(" APPROVED ") == "approved"


def test_normalize_delivery_state_unknown_fails_closed_to_review():
    assert normalize_delivery_state("something_else") == "review"


def test_set_delivery_state_returns_copy():
    lead = {"company": "Acme", "route": "Shiftr"}

    result = set_delivery_state(lead, "approved")

    assert result is not lead
    assert result["delivery_status"] == "approved"
    assert result["delivery_reason"] == ""
    assert result["route"] == "Shiftr"


def test_set_delivery_state_stores_reason():
    lead = {"company": "Acme", "route": "Paxus"}

    result = set_delivery_state(lead, "review", "needs_manual_review")

    assert result["delivery_status"] == "review"
    assert result["delivery_reason"] == "needs_manual_review"


def test_delivery_complete_for_delivered():
    assert is_delivery_complete({"delivery_status": "delivered"}) is True


def test_delivery_complete_for_permanently_failed():
    assert is_delivery_complete({"delivery_status": "permanently_failed"}) is True


def test_retryable_delivery_is_not_complete():
    assert is_delivery_complete({"delivery_status": "retryable"}) is False


def test_delivery_not_complete_for_approved():
    assert is_delivery_complete({"delivery_status": "approved"}) is False


def test_ready_for_delivery_requires_approval_and_qualification():
    lead = qualified_lead()
    lead["delivery_status"] = "approved"

    assert is_ready_for_delivery(lead) is True


def test_ready_for_delivery_rejects_approved_but_unqualified_lead():
    lead = qualified_lead()
    lead["delivery_status"] = "approved"
    lead["qualified"] = False

    assert is_ready_for_delivery(lead) is False


def test_ready_for_delivery_rejects_missing_route():
    lead = qualified_lead()
    lead["delivery_status"] = "approved"
    lead["route"] = ""

    assert is_ready_for_delivery(lead) is False


def test_ready_for_delivery_rejects_review_state():
    lead = qualified_lead()
    lead["delivery_status"] = "review"

    assert is_ready_for_delivery(lead) is False
