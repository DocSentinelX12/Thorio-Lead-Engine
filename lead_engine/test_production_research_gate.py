from __future__ import annotations

import pytest

from lead_engine.database import LeadDB
from lead_engine.production_research_gate import ProductionResearchGateError, validate_production_research_gate


def _complete_lead(fingerprint: str = "complete-1") -> dict:
    return {
        "fingerprint": fingerprint,
        "company": "Acme",
        "research_status": "complete",
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "decision_maker_verification_status": "verified",
            "decision_maker_email": "taylor@example.com",
        },
        "business_need_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/need", "evidence": "Current need"}]},
        "current_intent_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/intent", "evidence": "Current intent"}]},
        "technical_product_hiring_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/technical", "evidence": "Technical need"}]},
        "commercial_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/commercial", "evidence": "Commercial context"}]},
        "route_research": {"verified": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/route", "evidence": "Route fit"}]},
        "closer_package": {"ready": True, "verification_status": "verified", "evidence": [{"url": "https://example.com/need", "evidence": "Current need"}]},
    }


def test_production_gate_accepts_complete_synced_research(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _complete_lead()
    db.insert_if_new(lead)
    db.mark_synced(lead["fingerprint"])
    result = validate_production_research_gate(db)
    assert result["status"] == "verified"
    assert result["research_complete_checked"] == 1
    db.close()


def test_production_gate_rejects_complete_research_without_ready_closer(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _complete_lead()
    lead["closer_package"]["ready"] = False
    db.insert_if_new(lead)
    with pytest.raises(ProductionResearchGateError, match="RESEARCH/CLOSER GATE FAILURE"):
        validate_production_research_gate(db)
    db.close()


def test_production_gate_rejects_sales_eligible_without_synced_closer_handoff(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _complete_lead("sales-eligible-1")
    lead["sales_eligibility"] = "eligible"
    db.insert_if_new(lead)
    with pytest.raises(ProductionResearchGateError, match="sales_eligible_research_not_synced"):
        validate_production_research_gate(db)
    db.close()


def test_production_gate_rejects_sales_eligible_without_closer_task(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _complete_lead("sales-eligible-2")
    lead["sales_eligibility"] = "eligible"
    db.insert_if_new(lead)
    db.mark_synced(lead["fingerprint"])
    with pytest.raises(ProductionResearchGateError, match="sales_eligible_missing_closer_task"):
        validate_production_research_gate(db)
    db.close()


def test_scheduled_cli_fails_closed_when_research_gate_fails(monkeypatch):
    from lead_engine import cli

    class _Config:
        database_dir = "data"

    class _Application:
        config = _Config()
        db = object()

    monkeypatch.setattr(cli, "create_application", lambda: _Application())
    monkeypatch.setattr(cli, "_configured_runtime_sources", lambda: [])
    monkeypatch.setattr(cli, "_run_scheduled_with_lock", lambda *args, **kwargs: {"status": "completed"})
    monkeypatch.setattr(
        cli,
        "validate_production_research_gate",
        lambda db: (_ for _ in ()).throw(ProductionResearchGateError("RESEARCH/CLOSER GATE FAILURE: test")),
    )
    monkeypatch.setattr(cli, "_install_production_diagnostics", lambda: None)

    assert cli.main(["run-scheduled", "--cycles", "1"]) == 1
