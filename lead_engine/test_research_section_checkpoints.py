from __future__ import annotations

from typing import Any

from .agent_queue import enqueue
from .agent_workers import run_worker_once
from .database import LeadDB


def _db(tmp_path) -> LeadDB:
    return LeadDB(data_dir=tmp_path)


def test_company_research_sections_survive_worker_failure_mid_research(tmp_path):
    db = _db(tmp_path)
    lead = {
        "fingerprint": "section-checkpoint-1",
        "company": "Acme",
        "signal": "Acme is hiring engineers",
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "decision_maker_verification_status": "verified",
            "public_business_need_facts": [{"url": "https://example.com/need", "evidence": "Engineering team hiring"}],
            "public_hiring_facts": [{"url": "https://example.com/jobs", "evidence": "Open engineering roles"}],
            "public_product_facts": [{"url": "https://example.com/product", "evidence": "Acme product"}],
            "public_commercial_facts": [{"url": "https://example.com/about", "evidence": "Commercial context"}],
        },
    }
    assert db.insert_if_new(lead)
    enqueue(db, "company_research", {"lead": lead, "evidence_events": []})

    original = db.update_payload
    calls = {"count": 0}

    def fail_after_two(fingerprint: str, payload: dict[str, Any]):
        calls["count"] += 1
        if calls["count"] == 3:
            raise RuntimeError("worker lost after two research checkpoints")
        return original(fingerprint, payload)

    db.update_payload = fail_after_two
    try:
        failed = run_worker_once(db, "company_research", worker_id="research-worker")
    finally:
        db.update_payload = original

    assert failed["failed_count"] == 1
    stored = db.get("section-checkpoint-1")
    assert stored["business_need_research"]["evidence"]
    assert stored["current_intent_research"]["evidence"]

    enqueue(db, "company_research", {"lead": stored}, dedupe_key="company_research:section-checkpoint-1")
    recovered = run_worker_once(db, "company_research", worker_id="research-worker-2")
    assert recovered["completed_count"] == 1
    recovered_lead = db.get("section-checkpoint-1")
    assert recovered_lead["business_need_research"]["evidence"]
    assert recovered_lead["current_intent_research"]["evidence"]
    assert recovered_lead["technical_product_hiring_research"]["evidence"]
