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

    result = create_delivery_record(
        lead
    )

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

    result = create_delivery_record(
        lead
    )

    assert result["delivery_status"] == "review"
    assert (
        result["delivery_reason"]
        == "route_evidence_mismatch"
    )
    assert result["delivery_route"] == "Review"


def test_unknown_route_defaults_to_review():
    lead = {
        "company": "Acme",
        "route": "Unknown",
    }

    result = create_delivery_record(
        lead
    )

    assert result["delivery_status"] == "review"
    assert result["delivery_route"] == "Unknown"


def test_apply_delivery_record_does_not_mutate_original():
    lead = {
        "company": "Acme",
        "route": "Thorio",
        "delivery_status": "approved",
        "delivery_reason": "",
    }

    result = apply_delivery_record(
        lead
    )

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

    result = create_delivery_record(
        lead
    )

    assert result["delivery_status"] == "rejected"
    assert (
        result["delivery_reason"]
        == "missing_evidence"
    )
    assert result["delivery_route"] == "Paxus"
