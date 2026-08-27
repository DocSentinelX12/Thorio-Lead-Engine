from lead_engine.delivery_policy import (
    MIN_DELIVERY_SCORE,
    delivery_rejection_reason,
    is_delivery_ready,
)


def valid_lead():
    return {
        "company": "Acme",
        "route": "Shiftr",
        "lead_score": MIN_DELIVERY_SCORE,
        "signal": "remote software engineer",
        "evidence": "Acme is hiring a remote software engineer.",
        "url": "https://example.com/jobs/123",
    }


def test_valid_lead_is_delivery_ready():
    assert is_delivery_ready(valid_lead()) is True
    assert delivery_rejection_reason(valid_lead()) == ""


def test_review_route_is_not_delivery_ready():
    lead = valid_lead()
    lead["route"] = "Review"

    assert is_delivery_ready(lead) is False
    assert delivery_rejection_reason(lead) == "unsupported_route"


def test_low_score_is_not_delivery_ready():
    lead = valid_lead()
    lead["lead_score"] = MIN_DELIVERY_SCORE - 1

    assert is_delivery_ready(lead) is False
    assert delivery_rejection_reason(lead) == "score_below_threshold"


def test_missing_company_is_rejected():
    lead = valid_lead()
    lead["company"] = ""

    assert is_delivery_ready(lead) is False
    assert delivery_rejection_reason(lead) == "missing_company"


def test_missing_signal_is_rejected():
    lead = valid_lead()
    lead["signal"] = ""

    assert is_delivery_ready(lead) is False
    assert delivery_rejection_reason(lead) == "missing_signal"


def test_missing_evidence_is_rejected():
    lead = valid_lead()
    lead["evidence"] = ""

    assert is_delivery_ready(lead) is False
    assert delivery_rejection_reason(lead) == "missing_evidence"


def test_missing_url_is_rejected():
    lead = valid_lead()
    lead["url"] = ""

    assert is_delivery_ready(lead) is False
    assert delivery_rejection_reason(lead) == "missing_url"


def test_all_three_partner_routes_are_supported():
    for route in ("Shiftr", "Paxus", "Thorio"):
        lead = valid_lead()
        lead["route"] = route

        assert is_delivery_ready(lead) is True
