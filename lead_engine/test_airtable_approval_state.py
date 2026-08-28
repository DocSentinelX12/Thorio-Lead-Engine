from unittest.mock import MagicMock

from lead_engine.airtable_approval_state import (
    approval_key,
    get_approval_state,
    mark_approval_processed,
    should_process_approval,
)


def test_approval_key_is_deterministic():
    assert approval_key(
        "rec_123"
    ) == "airtable_approval:rec_123"


def test_unknown_approval_should_be_processed():
    db = MagicMock()
    db.get_state.return_value = None

    assert should_process_approval(
        db,
        "rec_new",
        "approved",
        ["Shiftr"],
    ) is True


def test_same_approval_does_not_need_reprocessing():
    db = MagicMock()

    db.get_state.return_value = {
        "record_id": "rec_existing",
        "status": "approved",
        "approved_routes": [
            "Shiftr",
        ],
    }

    assert should_process_approval(
        db,
        "rec_existing",
        "approved",
        ["Shiftr"],
    ) is False


def test_changed_routes_require_reprocessing():
    db = MagicMock()

    db.get_state.return_value = {
        "record_id": "rec_existing",
        "status": "approved",
        "approved_routes": [
            "Shiftr",
        ],
    }

    assert should_process_approval(
        db,
        "rec_existing",
        "approved",
        [
            "Shiftr",
            "Thorio",
        ],
    ) is True


def test_changed_status_requires_reprocessing():
    db = MagicMock()

    db.get_state.return_value = {
        "record_id": "rec_existing",
        "status": "pending",
        "approved_routes": [],
    }

    assert should_process_approval(
        db,
        "rec_existing",
        "approved",
        ["Paxus"],
    ) is True
