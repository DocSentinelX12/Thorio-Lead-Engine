from __future__ import annotations

from lead_engine.research_intelligence import build_research_intelligence


def test_route_tagged_legacy_section_evidence_is_rehomed_to_route_research():
    opportunity_id = "legacy-route-scope-1"
    route_event = {
        "opportunity_id": opportunity_id,
        "fingerprint": opportunity_id,
        "source": "linkedin",
        "url": "https://example.test/contract-team",
        "evidence": "Acme needs a contract engineering team.",
        "observed_at": "2026-11-06T12:00:00+00:00",
        "route": "Shiftr",
    }
    lead = {
        "opportunity_id": opportunity_id,
        "fingerprint": opportunity_id,
        "company": "Acme",
        "business_need_research": {
            "verified": True,
            "verification_status": "verified",
            "business_need": "Contract engineering team",
            "evidence": [route_event],
        },
        "route_research": {
            "routes": {
                "Shiftr": {
                    "verified": True,
                    "verification_status": "verified",
                    "evidence": [route_event],
                }
            }
        },
    }

    intelligence = build_research_intelligence(lead)
    nodes = intelligence["evidence_graph"]["nodes"]
    matching = [
        node for node in nodes.values()
        if node.get("url") == route_event["url"]
    ]

    assert len(matching) == 1
    assert matching[0]["research_section"] == "route_research"
    assert matching[0]["route"] == "Shiftr"
    matching_key = matching[0]["canonical_evidence_key"]
    assert not any(
        claim.get("research_section") == "business_need_research"
        and matching_key in claim.get("supporting_evidence_keys", [])
        for claim in intelligence["claims"]
    )
