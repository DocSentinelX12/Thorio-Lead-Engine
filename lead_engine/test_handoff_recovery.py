from datetime import datetime, timezone

from .database import LeadDB
from .scheduler import LeadScheduler


class _Pipeline:
    def __init__(self, db):
        self.db = db
        self.sync_enabled = False


class _Runner:
    def __init__(self, db):
        self.pipeline = _Pipeline(db)


def _research_complete_lead(fingerprint="handoff-recovery-qualification"):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "fingerprint": fingerprint,
        "company": "Acme",
        "business_need": "remote software engineering hiring",
        "signal": "Acme is hiring a remote software engineer",
        "research_status": "complete",
        "qualification_review_stage": "primary",
        "qualified": True,
        "potential_routes": ["Thorio"],
        "qualification_results": {
            "Thorio": {
                "qualified": True,
                "route_research": {"verified": True, "evidence": "Current engineering hiring need."},
            }
        },
        "company_research": {
            "company_verified": True,
            "decision_maker": "Taylor",
            "decision_maker_evidence": "https://example.com/taylor",
            "decision_maker_verification_status": "verified",
            "decision_maker_email": "taylor@example.com",
        },
        "current_intent_research": {
            "verified": True,
            "verification_status": "verified",
            "current_need": "remote software engineering hiring",
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
                    "evidence": "Current engineering hiring need.",
                }
            },
        },
    }


def _sales_eligible_lead(fingerprint="handoff-recovery-sales"):
    lead = _research_complete_lead(fingerprint)
    lead.update(
        {
            "qualification_review_stage": "validated",
            "sales_eligibility": "eligible",
            "sales_eligibility_reason": "eligible",
            "eligible_routes": ["Thorio"],
            "preserved_routes": ["Thorio"],
            "revenue_lifecycle_state": "sales_eligible",
            "contact_email": "taylor@example.com",
        }
    )
    return lead


def _queue_rows(db, agent, fingerprint):
    return db.conn.execute(
        "SELECT task_id,status,dedupe_key FROM agent_queue "
        "WHERE agent=? AND json_extract(payload,'$.lead.fingerprint')=? "
        "ORDER BY created_at",
        (agent, fingerprint),
    ).fetchall()


def test_scheduler_recovers_missing_qualification_handoff_after_durable_persistence(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _research_complete_lead()
    db.insert_if_new(lead)

    result = LeadScheduler(_Runner(db)).run([], agent_max_rounds=1)

    rows = _queue_rows(db, "qualification_b", lead["fingerprint"])
    assert rows, result
    assert len(rows) == 1
    assert rows[0][2] == f"qualification_b:{lead['fingerprint']}"


def test_scheduler_recovers_sales_eligibility_to_outreach_and_is_idempotent(tmp_path):
    db = LeadDB(data_dir=tmp_path)
    lead = _sales_eligible_lead()
    db.insert_if_new(lead)

    first = LeadScheduler(_Runner(db)).run([], agent_max_rounds=1)
    second = LeadScheduler(_Runner(db)).run([], agent_max_rounds=1)

    rows = _queue_rows(db, "outreach_closer", lead["fingerprint"])
    assert rows, {"first": first, "second": second}
    assert len(rows) == 1
    assert rows[0][2] == f"sales:{lead['fingerprint']}"
