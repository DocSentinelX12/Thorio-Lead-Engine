from __future__ import annotations

from lead_engine.agent_queue import enqueue
from lead_engine.agent_workers import run_worker_once
from lead_engine.database import LeadDB


def test_company_research_worker_persists_canonical_sections_from_specialist_findings(tmp_path):
    db = LeadDB(str(tmp_path))
    fingerprint = "worker-canonical-1"
    lead = {
        "fingerprint": fingerprint,
        "company": "Acme",
        "person": "Jane Doe",
        "signal": "Acme is hiring engineers now.",
        "specialist_findings": {
            "recent_inquiry_discovery": {
                "findings": [{
                    "url": "https://example.com/inquiry",
                    "evidence": "Acme is looking for an engineering team now.",
                    "observed_at": "2026-09-16T00:00:00+00:00",
                }]
            },
            "engineering_demand_discovery": {
                "findings": [{
                    "url": "https://example.com/engineering",
                    "evidence": "Acme needs backend engineering support.",
                    "observed_at": "2026-09-16T00:00:00+00:00",
                }]
            },
        },
    }
    assert db.insert_if_new(lead) is True
    enqueue(db, "company_research", {"lead": lead}, dedupe_key=f"company_research:{fingerprint}")

    result = run_worker_once(db, "company_research", worker_id="test-company-research")
    stored = db.get(fingerprint)

    assert result["completed_count"] == 1
    assert stored is not None
    for section_name in (
        "business_need_research",
        "current_intent_research",
        "technical_product_hiring_research",
        "commercial_research",
        "route_research",
        "closer_package",
    ):
        assert section_name in stored
    assert stored["current_intent_research"]["evidence"]
    assert stored["business_need_research"]["evidence"]
    assert stored["technical_product_hiring_research"]["evidence"]
    assert stored["closer_package"]["ready"] is False
    assert stored["closer_package"]["verification_status"] == "research_required"
    assert stored["current_intent_research"]["verified"] is False
    assert stored["current_intent_research"]["verification_status"] == "observed_evidence"
    assert stored["research_status"] == "research_required"
    db.close()


def test_company_research_worker_refreshes_stale_queue_payload_before_handoff(tmp_path):
    db = LeadDB(str(tmp_path))
    fingerprint = "worker-canonical-refresh"
    original = {"fingerprint": fingerprint, "company": "Acme", "signal": "Observed signal."}
    assert db.insert_if_new(original) is True
    enqueue(db, "company_research", {"lead": original}, dedupe_key=f"company_research:{fingerprint}")
    db.update_payload(fingerprint, {
        "specialist_findings": {
            "social_hiring_research": {
                "findings": [{
                    "url": "https://example.com/hiring",
                    "evidence": "Acme is actively hiring backend engineers.",
                    "observed_at": "2026-09-16T00:00:00+00:00",
                }]
            }
        }
    })

    result = run_worker_once(db, "company_research", worker_id="test-company-research-refresh")
    stored = db.get(fingerprint)

    assert result["completed_count"] == 1
    assert stored["current_intent_research"]["evidence"]
    assert any("actively hiring backend engineers" in item["evidence"] for item in stored["current_intent_research"]["evidence"])
    db.close()
