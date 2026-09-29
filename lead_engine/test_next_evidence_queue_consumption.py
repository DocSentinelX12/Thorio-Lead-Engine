from __future__ import annotations

from lead_engine.agent_queue import enqueue, pending
from lead_engine.agent_workers import run_worker_once
from lead_engine.database import LeadDB
from lead_engine import public_research


def _lead(fingerprint: str) -> dict:
    return {
        "fingerprint": fingerprint,
        "opportunity_id": fingerprint,
        "company": "Acme",
        "website": "https://acme.example/",
        "signal": "Acme is hiring engineers.",
        "research_gaps": {
            "missing_sections": [
                "current_intent_research",
                "commercial_research",
            ]
        },
        "potential_routes": ["Thorio"],
    }


def test_company_research_queue_materializes_current_next_evidence_plan(tmp_path):
    db = LeadDB(str(tmp_path))
    lead = _lead("next-evidence-queue-1")
    assert db.insert_if_new(lead) is True

    task = enqueue(db, "company_research", {"lead": lead}, dedupe_key="company_research:next-evidence-queue-1")
    plan = task["payload"]["next_evidence_to_find"]

    assert plan["missing_sections"] == ["current_intent_research", "commercial_research"]
    assert plan["target_count"] == 2
    assert all(item["research_section"] in plan["missing_sections"] for item in plan["targets"])
    assert "evidence" not in plan

    queued = pending(db, "company_research")
    assert queued[0]["payload"]["next_evidence_to_find"] == plan
    db.close()


def test_company_research_refreshes_targets_from_authoritative_persisted_lead(tmp_path, monkeypatch):
    db = LeadDB(str(tmp_path))
    lead = _lead("next-evidence-queue-refresh")
    assert db.insert_if_new(lead) is True
    enqueue(db, "company_research", {"lead": lead}, dedupe_key="company_research:next-evidence-queue-refresh")

    db.update_payload(
        lead["fingerprint"],
        {"research_gaps": {"missing_sections": ["technical_product_hiring_research"]}},
    )

    class Response:
        status_code = 200
        encoding = "utf-8"
        headers = {"content-type": "text/html"}
        text = ""
        is_redirect = False
        is_permanent_redirect = False

        def iter_content(self, chunk_size=16384):
            yield b"<html><head><title>Acme Product</title></head><body>Acme product platform.</body></html>"

    monkeypatch.setattr(public_research, "_public_host", lambda url: (True, "public_address"))
    monkeypatch.setattr(public_research.requests, "get", lambda *args, **kwargs: Response())
    public_research._ROBOTS_CACHE.clear()
    public_research._PAGE_CACHE.clear()

    result = run_worker_once(db, "company_research", worker_id="next-evidence-worker")
    stored = db.get(lead["fingerprint"])

    assert result["completed_count"] == 1
    assert stored["company_research"]["research_focus"]["missing_sections"] == ["technical_product_hiring_research"]
    assert stored["research_status"] == "research_required"
    db.close()


def test_public_research_focus_prioritizes_requested_paths_without_treating_targets_as_evidence():
    lead = {
        "company": "Acme",
        "website": "https://acme.example/",
        "research_focus": {
            "targets": [
                {"research_section": "commercial_research", "evidence_to_find": ["funding"]},
                {"research_section": "current_intent_research", "evidence_to_find": ["hiring"]},
            ]
        },
    }
    urls = public_research._candidate_urls(lead)
    assert urls[0] == "https://acme.example/"
    assert urls[1].endswith("/pricing")
    assert urls[2].endswith("/enterprise")
    assert urls[3].endswith("/contact")
    assert all("funding" not in str(item) for item in urls)
