from .lead_identity import (
    add_lead_identity,
    lead_identity,
    normalize_identity_value,
)


def test_normalize_identity_value():
    assert normalize_identity_value("  Acme   Company  ") == "acme company"


def test_identity_includes_observation_context():
    first = {"source": "linkedin", "source_id": "ABC-123", "company": "Acme", "discovered_at": "2026-01-01T00:00:00+00:00"}
    second = {"source": "linkedin", "source_id": "ABC-123", "company": "Acme", "discovered_at": "2026-01-01T00:00:01+00:00"}
    assert lead_identity(first) != lead_identity(second)


def test_identity_falls_back_without_source_id():
    first = {"company": "Acme", "url": "https://example.com/job/123", "signal": "Remote software engineer"}
    second = {"company": "  ACME ", "url": " https://example.com/job/123 ", "signal": "Remote   software engineer"}
    assert lead_identity(first) == lead_identity(second)


def test_add_lead_identity_preserves_original_fields():
    lead = {"company": "Acme", "route": "Thorio"}
    result = add_lead_identity(lead)
    assert result["company"] == "Acme"
    assert result["route"] == "Thorio"
    assert result["lead_identity"]
    assert lead == {"company": "Acme", "route": "Thorio"}


def test_identity_ignores_non_identity_fields():
    first = {"source": "linkedin", "source_id": "ABC-123", "company": "Acme", "route": "Thorio", "lead_score": 50}
    second = {"source": "linkedin", "source_id": "ABC-123", "company": "Acme", "route": "Paxus", "lead_score": 100}
    assert lead_identity(first) == lead_identity(second)
