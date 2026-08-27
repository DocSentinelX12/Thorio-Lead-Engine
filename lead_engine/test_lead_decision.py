from .lead_decision import (
    DECISION_APPROVE,
    DECISION_REJECT,
    DECISION_REVIEW,
    apply_lead_decision,
    decide_lead,
    is_approved_lead,
    is_rejected_lead,
    needs_lead_review,
)


def make_lead(
    *,
    route="Thorio",
    score=80,
    status="qualified",
):
    return {
        "company": "Acme",
        "route": route,
        "lead_score": score,
        "status": status,
    }


def test_qualified_high_score_is_approved():
    assert decide_lead(
        make_lead()
    ) == DECISION_APPROVE


def test_unsupported_route_needs_review():
    assert decide_lead(
        make_lead(route="Unknown")
    ) == DECISION_REVIEW


def test_zero_score_is_rejected():
    assert decide_lead(
        make_lead(score=0)
    ) == DECISION_REJECT


def test_low_score_needs_review():
    assert decide_lead(
        make_lead(score=25)
    ) == DECISION_REVIEW


def test_rejected_status_is_rejected():
    assert decide_lead(
        make_lead(status="rejected")
    ) == DECISION_REJECT


def test_delivered_lead_is_not_approved_again():
    assert decide_lead(
        make_lead(status="delivered")
    ) == DECISION_REVIEW


def test_apply_decision_preserves_lead():
    lead = make_lead()

    result = apply_lead_decision(
        lead
    )

    assert result["company"] == "Acme"
    assert result["route"] == "Thorio"
    assert result["decision"] == DECISION_APPROVE
    assert "decision" not in lead


def test_decision_helpers():
    lead = make_lead()

    assert is_approved_lead(lead)
    assert not needs_lead_review(lead)
    assert not is_rejected_lead(lead)


def test_review_helper():
    lead = make_lead(
        score=25
    )

    assert not is_approved_lead(lead)
    assert needs_lead_review(lead)
    assert not is_rejected_lead(lead)


def test_rejection_helper():
    lead = make_lead(
        score=0
    )

    assert not is_approved_lead(lead)
    assert not needs_lead_review(lead)
    assert is_rejected_lead(lead)
