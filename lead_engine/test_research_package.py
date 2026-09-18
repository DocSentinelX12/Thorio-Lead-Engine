from __future__ import annotations

from lead_engine.research_package import RESEARCH_SECTIONS, build_canonical_research_package, merge_canonical_section


def test_build_canonical_research_package_materializes_all_sections_without_verifying_observed_evidence():
    lead = {"fingerprint": "canonical-1", "company": "Acme", "person": "Jane Doe"}
    company_research = {
        "public_company_facts": [{"url": "https://acme.example/", "evidence": "Acme company facts", "observed_at": "2026-09-17T00:00:00+00:00"}],
        "public_product_facts": [{"url": "https://acme.example/product", "evidence": "Acme product facts", "observed_at": "2026-09-17T00:00:00+00:00"}],
        "public_hiring_facts": [{"url": "https://acme.example/careers", "evidence": "Acme is hiring software engineers", "observed_at": "2026-09-17T00:00:00+00:00"}],
        "public_business_need_facts": [{"url": "https://acme.example/about", "evidence": "Acme needs to scale engineering", "observed_at": "2026-09-17T00:00:00+00:00"}],
        "public_commercial_facts": [{"url": "https://acme.example/pricing", "evidence": "Acme has an enterprise plan", "observed_at": "2026-09-17T00:00:00+00:00"}],
        "social_findings": [{"url": "https://social.example/post", "evidence": "Jane posted that Acme is hiring now", "observed_at": "2026-09-16T00:00:00+00:00", "source": "LinkedIn"}],
        "fabricated_fields": [],
    }
    findings = {
        "business_need": [{"url": "https://social.example/need", "evidence": "Acme needs a development team", "observed_at": "2026-09-16T00:00:00+00:00"}],
        "current_intent": [{"url": "https://social.example/intent", "evidence": "Acme is actively looking for engineers", "observed_at": "2026-09-16T00:00:00+00:00"}],
        "recent_inquiry": [{"url": "https://social.example/inquiry", "evidence": "Acme asked for recommendations", "observed_at": "2026-09-15T00:00:00+00:00"}],
        "technical_product_hiring": [{"url": "https://acme.example/jobs", "evidence": "Acme needs backend engineering", "observed_at": "2026-09-16T00:00:00+00:00"}],
        "commercial": [{"url": "https://acme.example/enterprise", "evidence": "Acme offers enterprise services", "observed_at": "2026-09-16T00:00:00+00:00"}],
        "route": [{"url": "https://social.example/route", "evidence": "Acme is seeking an engineering team", "observed_at": "2026-09-16T00:00:00+00:00"}],
    }

    package = build_canonical_research_package(lead, company_research, findings)

    assert tuple(package) == RESEARCH_SECTIONS
    for section_name in ("business_need_research", "current_intent_research", "technical_product_hiring_research", "commercial_research"):
        section = package[section_name]
        assert section["verification_status"] == "observed_evidence"
        assert section["verified"] is False
        assert section["evidence"]
        assert section["provenance"]["evidence_count"] == len(section["evidence"])

    route = package["route_research"]
    assert route["verification_status"] == "observed_evidence"
    assert route["verified"] is False
    assert set(route["routes"]) == {"Shiftr", "Paxus", "Thorio"}
    assert all(item["verified"] is False for item in route["routes"].values())

    gaps = package["research_gaps"]
    assert gaps["verification_status"] == "observed_evidence"
    assert gaps["missing_sections"] == []
    assert "company_verification" in gaps["unknowns"]

    closer = package["closer_package"]
    assert closer["ready"] is False
    assert closer["verification_status"] == "research_required"
    assert closer["evidence"]
    assert closer["provenance"]["source"] == "canonical_research_sections"
    assert "company_verification" in closer["unknowns"]


def test_build_canonical_research_package_never_creates_evidence_from_missing_sections():
    package = build_canonical_research_package(
        {"fingerprint": "canonical-empty", "company": "Acme"},
        {"fabricated_fields": []},
        {},
    )

    for section_name in ("business_need_research", "current_intent_research", "technical_product_hiring_research", "commercial_research"):
        section = package[section_name]
        assert section["verified"] is False
        assert section["verification_status"] == "observed_evidence"
        assert section["evidence"] == []
        assert section["provenance"]["evidence_count"] == 0
    route = package["route_research"]
    assert route["routes"]["Shiftr"]["evidence"] == []
    assert package["research_gaps"]["missing_sections"] == [
        "business_need_research",
        "current_intent_research",
        "technical_product_hiring_research",
        "commercial_research",
        "route_research",
    ]
    assert package["closer_package"]["evidence"] == []


def test_merge_canonical_section_preserves_verified_existing_section():
    generated = {"verified": False, "verification_status": "observed_evidence", "evidence": [{"url": "https://new.example", "evidence": "new"}]}
    existing = {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://verified.example", "evidence": "verified"}], "custom": "preserve"}

    merged = merge_canonical_section(generated, existing)

    assert merged == existing


def test_merge_canonical_section_keeps_existing_and_new_observed_evidence():
    generated = {"verified": False, "verification_status": "observed_evidence", "evidence": [{"url": "https://new.example", "evidence": "new", "observed_at": "2026-09-17T00:00:00+00:00"}], "provenance": {"source_sections": ["new"]}}
    existing = {"verified": False, "verification_status": "observed_evidence", "evidence": [{"url": "https://old.example", "evidence": "old", "observed_at": "2026-09-16T00:00:00+00:00"}], "provenance": {"source_sections": ["old"]}}

    merged = merge_canonical_section(generated, existing)

    assert {item["evidence"] for item in merged["evidence"]} == {"new", "old"}
    assert set(merged["provenance"]["source_sections"]) == {"new", "old"}
    assert merged["provenance"]["evidence_count"] == 2


def test_route_research_keeps_evidence_scoped_to_supported_routes():
    lead = {"fingerprint": "route-scope", "company": "Acme"}
    company_research = {
        "public_hiring_facts": [
            {
                "url": "https://acme.example/careers",
                "evidence": "Acme is hiring a remote software engineer.",
                "observed_at": "2026-09-17T00:00:00+00:00",
            }
        ],
        "public_product_facts": [],
        "public_business_need_facts": [],
        "public_commercial_facts": [],
        "social_findings": [],
    }
    package = build_canonical_research_package(lead, company_research, {})
    routes = package["route_research"]["routes"]
    assert routes["Thorio"]["evidence"]
    assert routes["Shiftr"]["evidence"]
    assert routes["Paxus"]["evidence"] == []
