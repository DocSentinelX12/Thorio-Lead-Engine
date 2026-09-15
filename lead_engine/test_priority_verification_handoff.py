from datetime import datetime, timezone

from .agent_orchestrator import AgentOrchestrator
from .agent_queue import pending
from .database import LeadDB


def test_priority_result_cannot_strand_verified_opportunity(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    lead = {
        "fingerprint": "priority-verification-handoff",
        "company": "Acme",
        "signal": "Acme is hiring a remote software engineer",
        "business_need": "remote software engineer hiring",
        "qualified": True,
        "potential_routes": ["Thorio"],
        "research_status": "complete",
        "research_verified_fields": ["current_intent_research", "route_research"],
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "decision_maker_email": "taylor@example.com",
            "decision_maker_verification_status": "verified",
        },
        "current_intent_research": {
            "verified": True,
            "verification_status": "verified",
            "current_need": "remote software engineer hiring",
            "observed_at": now,
            "evidence_url": "https://example.com/need",
        },
        "route_research": {
            "verified": True,
            "verification_status": "verified",
            "routes": {
                "Thorio": {
                    "verified": True,
                    "verification_status": "verified",
                    "evidence": "Current remote software engineering hiring need.",
                }
            },
        },
        "qualification_results": {
            "Thorio": {
                "qualified": True,
                "route_research": {
                    "verified": True,
                    "verification_status": "verified",
                    "evidence": "Current remote software engineering hiring need.",
                },
            }
        },
    }
    db = LeadDB(data_dir=tmp_path)
    try:
        db.insert_if_new(lead)
        orchestrator = AgentOrchestrator(db, worker_prefix="priority-handoff-test")
        orchestrator.dispatch_processing("priority", {"lead": lead})
        result = orchestrator.run_all_once(limit_per_agent=1, max_rounds=1)
        assert result["failed_count"] == 0, result
        queued = [task for task in pending(db) if task.get("agent") == "verification" and task.get("status") == "queued"]
        assert len(queued) == 1
        assert queued[0]["payload"]["lead"]["fingerprint"] == lead["fingerprint"]
    finally:
        db.close()
