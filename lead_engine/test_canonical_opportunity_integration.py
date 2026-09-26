from .lead_identity import canonical_opportunity_identity
from .models import Lead
from .research_package import build_canonical_research_package
from .sales_handoff import package_digest, package_projection


def test_canonical_opportunity_identity_survives_research_and_handoff_projection():
    lead = Lead(
        source="linkedin",
        source_id="post-1",
        url="https://linkedin.example/post-1",
        company="Acme",
        person="Jane CTO",
        job_title="AI Engineer",
        signal_type="hiring",
        discovered_at="2026-09-26T00:00:00+00:00",
        signal="Hiring an AI engineer",
    )
    payload = lead.to_dict()
    identity = canonical_opportunity_identity(payload)

    package = build_canonical_research_package(
        payload,
        {"public_business_need_facts": [{"url": "https://acme.example/need", "evidence": "Needs AI engineering", "observed_at": "2026-09-26T01:00:00+00:00"}]},
        {},
    )
    enriched = {**payload, **package}
    projection = package_projection(enriched)

    assert enriched["opportunity_id"] == identity["opportunity_id"]
    assert enriched["fingerprint"] == identity["fingerprint"]
    assert projection["opportunity_id"] == identity["opportunity_id"]
    assert projection["fingerprint"] == identity["fingerprint"]
    assert package_digest(enriched)


def test_same_company_and_contact_can_retain_distinct_opportunity_identity():
    first = Lead(
        source="linkedin",
        source_id="post-1",
        url="https://linkedin.example/post-1",
        company="Acme",
        person="Jane CTO",
        job_title="AI Engineer",
        signal_type="hiring",
        discovered_at="2026-09-26T00:00:00+00:00",
    ).to_dict()
    second = Lead(
        source="linkedin",
        source_id="post-2",
        url="https://linkedin.example/post-2",
        company="Acme",
        person="Jane CTO",
        job_title="Data Engineer",
        signal_type="hiring",
        discovered_at="2026-09-26T00:00:00+00:00",
    ).to_dict()

    assert first["opportunity_id"] != second["opportunity_id"]


def test_durable_storage_rejects_cross_opportunity_identity(tmp_path):
    import pytest
    from .database import LeadDB

    db = LeadDB(data_dir=tmp_path)

    with pytest.raises(ValueError, match="opportunity_id.*fingerprint"):
        db.insert_if_new({
            "fingerprint": "opp-1",
            "opportunity_id": "opp-2",
            "company": "Acme",
        })
