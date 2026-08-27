from lead_engine.lead_status import (
    VALID_STATUSES,
    is_valid_status,
    normalize_status,
    status_metadata,
)


def test_valid_statuses_are_supported():
    assert "new" in VALID_STATUSES
    assert "qualified" in VALID_STATUSES
    assert "contacted" in VALID_STATUSES
    assert "replied" in VALID_STATUSES
    assert "interested" in VALID_STATUSES
    assert "referred" in VALID_STATUSES
    assert "converted" in VALID_STATUSES
    assert "rejected" in VALID_STATUSES


def test_normalize_status_trims_and_lowercases():
    assert normalize_status("  QUALIFIED  ") == "qualified"


def test_empty_status_defaults_to_new():
    assert normalize_status("") == "new"
    assert normalize_status(None) == "new"


def test_unknown_status_defaults_to_new():
    assert normalize_status("something_invalid") == "new"


def test_status_aliases_are_normalized():
    assert normalize_status("pending") == "new"
    assert normalize_status("responded") == "replied"
    assert normalize_status("discarded") == "rejected"
    assert normalize_status("qualified_lead") == "qualified"


def test_is_valid_status():
    assert is_valid_status("new") is True
    assert is_valid_status("qualified") is True
    assert is_valid_status("not-a-status") is False
    assert is_valid_status(None) is False


def test_terminal_statuses_are_marked_terminal():
    converted = status_metadata("converted")
    rejected = status_metadata("rejected")

    assert converted["status"] == "converted"
    assert converted["terminal"] is True
    assert converted["active"] is False

    assert rejected["status"] == "rejected"
    assert rejected["terminal"] is True
    assert rejected["active"] is False


def test_active_statuses_are_not_terminal():
    result = status_metadata("qualified")

    assert result["status"] == "qualified"
    assert result["terminal"] is False
    assert result["active"] is True
