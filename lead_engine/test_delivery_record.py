from lead_engine.delivery_record import (
    apply_delivery_record,
    create_delivery_record,
)


def test_create_delivery_record_preserves_approved_route():
    lead = {
        "company": "Acme",
        "route": "Shiftr",
        "delivery_status": "approved",
        "delivery_reason": "",
    }

    result = create_delivery_record(lead)

    assert result == {
        "delivery_status": "approved",
        "delivery_reason": "",
        "delivery_route": "Shiftr",
    }


def test_create_delivery_record_preserves_rejection_reason():
    lead = {
        "company": "Acme",
        "route": "Review",
        "delivery_status": "review",
        "delivery_reason": "route_evidence_mismatch",
    }

    result = create_delivery_record(lead)

    assert result["delivery_status"] == "review"
    assert result["delivery_reason"] == "route_evidence_mismatch"
    assert result["delivery_route"] == "Review"


def test_missing_delivery_status_fails_closed_to_review():
    result = create_delivery_record({"company": "Acme", "route": "Shiftr"})

    assert result["delivery_status"] == "review"
    assert result["delivery_reason"] == "delivery_status_missing_or_unrecognized"
    assert result["delivery_route"] == "Shiftr"


def test_route_alone_never_implies_approval():
    result = create_delivery_record({"company": "Acme", "route": "Paxus"})

    assert result["delivery_status"] != "approved"


def test_existing_delivery_state_is_preserved():
    for state in ("queued", "attempting", "delivered", "failed", "retryable", "permanently_failed"):
        result = create_delivery_record(
            {"route": "Thorio", "delivery_status": state}
        )
        assert result["delivery_status"] == state


def test_unknown_route_defaults_to_review():
    lead = {
        "company": "Acme",
        "route": "Unknown",
    }

    result = create_delivery_record(lead)

    assert result["delivery_status"] == "review"
    assert result["delivery_route"] == "Unknown"


def test_apply_delivery_record_does_not_mutate_original():
    lead = {
        "company": "Acme",
        "route": "Thorio",
        "delivery_status": "approved",
        "delivery_reason": "",
    }

    result = apply_delivery_record(lead)

    assert result is not lead
    assert lead == {
        "company": "Acme",
        "route": "Thorio",
        "delivery_status": "approved",
        "delivery_reason": "",
    }

    assert result["delivery_route"] == "Thorio"


def test_existing_delivery_status_is_preserved():
    lead = {
        "route": "Paxus",
        "delivery_status": "rejected",
        "delivery_reason": "missing_evidence",
    }

    result = create_delivery_record(lead)

    assert result["delivery_status"] == "rejected"
    assert result["delivery_reason"] == "missing_evidence"
    assert result["delivery_route"] == "Paxus"
