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


def test_canonical_opportunity_identity_exposes_version_and_derivation():
    from .lead_identity import canonical_opportunity_identity

    lead = {
        "source": "linkedin",
        "source_id": "post-1",
        "url": "https://linkedin.example/post-1",
        "company": "Acme",
        "person": "Jane CTO",
        "job_title": "AI Engineer",
        "signal_type": "hiring",
        "discovered_at": "2026-09-26T00:00:00+00:00",
        "signal": "first observation",
    }

    identity = canonical_opportunity_identity(lead)

    assert identity["opportunity_id"] == identity["fingerprint"]
    assert identity["identity_version"]
    assert identity["derivation"]["source"] == "linkedin"
    assert identity["derivation"]["source_id"] == "post-1"


def test_canonical_identity_derivation_retains_available_company_and_contact_context():
    from .lead_identity import canonical_opportunity_identity

    identity = canonical_opportunity_identity({
        "source": "linkedin",
        "source_id": "post-1",
        "url": "https://linkedin.example/post-1",
        "company": "Acme",
        "company_website": "https://acme.example",
        "person": "Jane CTO",
        "contact_name": "Jane CTO",
        "contact_title": "Chief Technology Officer",
        "contact_email": "jane@example.com",
        "linkedin_url": "https://linkedin.example/in/jane",
        "job_title": "AI Engineer",
        "signal_type": "hiring",
        "discovered_at": "2026-09-26T00:00:00+00:00",
    })

    derivation = identity["derivation"]

    assert derivation["company"] == "acme"
    assert derivation["company_website"] == "https://acme.example"
    assert derivation["contact_name"] == "jane cto"
    assert derivation["contact_title"] == "chief technology officer"
    assert derivation["contact_email"] == "jane@example.com"
    assert derivation["linkedin_url"] == "https://linkedin.example/in/jane"


def test_canonical_opportunity_identity_ignores_research_mutation():
    from .lead_identity import canonical_opportunity_identity

    base = {
        "source": "linkedin",
        "source_id": "post-1",
        "url": "https://linkedin.example/post-1",
        "company": "Acme",
        "person": "Jane CTO",
        "job_title": "AI Engineer",
        "signal_type": "hiring",
        "discovered_at": "2026-09-26T00:00:00+00:00",
    }
    enriched = {
        **base,
        "business_need_research": {"summary": "new evidence"},
        "evidence_events": [{"evidence": "new evidence"}],
        "route": "Paxus",
        "research_status": "complete",
    }

    assert canonical_opportunity_identity(base)["opportunity_id"] == canonical_opportunity_identity(enriched)["opportunity_id"]


def test_validate_opportunity_identity_rejects_mismatched_ids():
    import pytest
    from .lead_identity import validate_opportunity_identity

    payload = {
        "fingerprint": "fingerprint-a",
        "opportunity_id": "fingerprint-b",
        "company": "Acme",
    }

    with pytest.raises(ValueError, match="opportunity_id.*fingerprint"):
        validate_opportunity_identity(payload)


def test_validate_opportunity_identity_rejects_identity_drift():
    import pytest
    from .lead_identity import canonical_opportunity_identity, validate_opportunity_identity

    original = {
        "source": "linkedin",
        "source_id": "post-1",
        "url": "https://linkedin.example/post-1",
        "company": "Acme",
        "person": "Jane CTO",
        "job_title": "AI Engineer",
        "signal_type": "hiring",
        "discovered_at": "2026-09-26T00:00:00+00:00",
    }
    identity = canonical_opportunity_identity(original)
    payload = {
        **original,
        "fingerprint": identity["fingerprint"],
        "opportunity_id": identity["opportunity_id"],
        "identity_version": identity["identity_version"],
        "identity_derivation": identity["derivation"],
        "company": "Other Company",
    }

    with pytest.raises(ValueError, match="canonical opportunity identity"):
        validate_opportunity_identity(payload)


def test_validate_opportunity_identity_accepts_matching_ids():
    from .lead_identity import validate_opportunity_identity

    payload = {"fingerprint": "abc123", "opportunity_id": "abc123"}

    assert validate_opportunity_identity(payload) == "abc123"
