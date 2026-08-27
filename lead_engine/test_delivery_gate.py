from lead_engine.delivery_gate import (
    evaluate_delivery_gate,
    prepare_for_delivery,
)
from lead_engine.delivery_policy import MIN_DELIVERY_SCORE


def valid_lead(route="Shiftr"):
    return {
        "company": "Acme",
        "route": route,
        "lead_score": MIN_DELIVERY_SCORE,
        "signal": "remote software engineer",
        "evidence": "Acme is hiring a remote software engineer.",
        "url": "https://example.com/jobs/123",
    }


def test_valid_shiftr_lead_passes_gate():
    result = evaluate_delivery_gate(valid_lead("Shiftr"))

    assert result["approved"] is True
    assert result["route"] == "Shiftr"
    assert result["reason"] == ""


def test_valid_thorio_lead_passes_gate():
    result = evaluate_delivery_gate(valid_lead("Thorio"))

    assert result["approved"] is True
    assert result["route"] == "Thorio"


def test_valid_paxus_lead_requires_paxus_evidence():
    lead = valid_lead("Paxus")
    lead["signal"] = "contract staffing need"
    lead["evidence"] = "Acme needs contractors for a technology project."

    result = evaluate_delivery_gate(lead)

    assert result["approved"] is True
    assert result["route"] == "Paxus"


def test_low_score_is_blocked():
    lead = valid_lead()
    lead["lead_score"] = MIN_DELIVERY_SCORE - 1

    result = evaluate_delivery_gate(lead)

    assert result["approved"] is False
    assert result["reason"] == "delivery_policy_rejected"


def test_review_route_is_blocked():
    lead = valid_lead("Review")

    result = evaluate_delivery_gate(lead)

    assert result["approved"] is False
    assert result["route"] == "Review"


def test_route_evidence_mismatch_is_blocked():
    lead = valid_lead("Shiftr")
    lead["signal"] = "office manager"
    lead["evidence"] = "Acme is hiring an office manager."

    result = evaluate_delivery_gate(lead)

    assert result["approved"] is False
    assert result["reason"] == "route_evidence_mismatch"


def test_generic_hiring_is_blocked():
    lead = valid_lead("Shiftr")
    lead["signal"] = "hiring"
    lead["evidence"] = "Acme is hiring."

    result = evaluate_delivery_gate(lead)

    assert result["approved"] is False


def test_prepare_for_delivery_returns_lead_when_approved():
    lead = valid_lead()

    result = prepare_for_delivery(lead)

    assert result["approved"] is True
    assert result["lead"] == lead


def test_prepare_for_delivery_does_not_return_rejected_lead():
    lead = valid_lead()
    lead["signal"] = "office manager"
    lead["evidence"] = "Acme is hiring an office manager."

    result = prepare_for_delivery(lead)

    assert result["approved"] is False
    assert result["lead"] is None
