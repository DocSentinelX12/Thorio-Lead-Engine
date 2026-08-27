from lead_engine.delivery_state import (
    is_delivery_complete,
    is_ready_for_delivery,
    normalize_delivery_state,
    set_delivery_state,
)


def test_normalize_delivery_state_accepts_supported_state():
    assert normalize_delivery_state(
        "approved"
    ) == "approved"


def test_normalize_delivery_state_is_case_insensitive():
    assert normalize_delivery_state(
        " APPROVED "
    ) == "approved"


def test_normalize_delivery_state_unknown_becomes_pending():
    assert normalize_delivery_state(
        "something_else"
    ) == "pending"


def test_set_delivery_state_returns_copy():
    lead = {
        "company": "Acme",
        "route": "Shiftr",
    }

    result = set_delivery_state(
        lead,
        "approved",
    )

    assert result is not lead
    assert result["delivery_status"] == "approved"
    assert result["delivery_reason"] == ""
    assert result["route"] == "Shiftr"


def test_set_delivery_state_stores_reason():
    lead = {
        "company": "Acme",
        "route": "Paxus",
    }

    result = set_delivery_state(
        lead,
        "review",
        "needs_manual_review",
    )

    assert result["delivery_status"] == "review"
    assert (
        result["delivery_reason"]
        == "needs_manual_review"
    )


def test_delivery_complete_for_delivered():
    lead = {
        "delivery_status": "delivered",
    }

    assert is_delivery_complete(lead) is True


def test_delivery_complete_for_failed():
    lead = {
        "delivery_status": "failed",
    }

    assert is_delivery_complete(lead) is True


def test_delivery_not_complete_for_approved():
    lead = {
        "delivery_status": "approved",
    }

    assert is_delivery_complete(lead) is False


def test_ready_for_delivery_requires_approval_and_route():
    lead = {
        "delivery_status": "approved",
        "route": "Shiftr",
    }

    assert is_ready_for_delivery(lead) is True


def test_ready_for_delivery_rejects_missing_route():
    lead = {
        "delivery_status": "approved",
        "route": "",
    }

    assert is_ready_for_delivery(lead) is False


def test_ready_for_delivery_rejects_review_state():
    lead = {
        "delivery_status": "review",
        "route": "Thorio",
    }

    assert is_ready_for_delivery(lead) is False
