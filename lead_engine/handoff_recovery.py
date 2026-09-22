from __future__ import annotations

from typing import Any, Dict, Mapping

from .agent_queue import enqueue


def _lead_fingerprint(lead: Mapping[str, Any]) -> str:
    return str(lead.get("fingerprint") or "").strip()


def _queued_or_running(db: Any, agent: str, fingerprint: str) -> bool:
    rows = db.conn.execute(
        "SELECT 1 FROM agent_queue "
        "WHERE agent=? "
        "AND json_extract(payload,'$.lead.fingerprint')=? LIMIT 1",
        (agent, fingerprint),
    ).fetchone()
    return rows is not None


def recover_processing_handoffs(db: Any, *, limit: int = 500) -> Dict[str, Any]:
    """Repair durable state -> queue gaps left by a worker/process crash.

    LeadDB is the source of truth. Queue rows are deliberately reconstructed
    from durable stage markers and use the existing dedupe keys, so repeating
    recovery cannot manufacture duplicate logical work.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit must be a positive integer")

    leads = db.all_leads()[:limit]
    recovered = []
    skipped = 0

    for lead in leads:
        fingerprint = _lead_fingerprint(lead)
        if not fingerprint:
            continue

        stage = str(lead.get("qualification_review_stage") or "").strip().lower()
        research_status = str(lead.get("research_status") or "").strip().lower()
        sales_eligibility = str(lead.get("sales_eligibility") or "").strip().lower()

        if sales_eligibility == "eligible":
            if not _queued_or_running(db, "outreach_closer", fingerprint):
                enqueue(
                    db,
                    "outreach_closer",
                    {
                        "lead": dict(lead),
                        "routing_result": dict(lead.get("routing_result") or {}),
                        "integrity_result": {
                            "sales_eligibility": "eligible",
                            "sales_eligibility_reason": lead.get("sales_eligibility_reason") or "eligible",
                        },
                    },
                    priority=10,
                    dedupe_key=f"sales:{fingerprint}",
                )
                recovered.append({"fingerprint": fingerprint, "agent": "outreach_closer"})
            continue

        if stage == "primary":
            if not _queued_or_running(db, "qualification_b", fingerprint):
                enqueue(
                    db,
                    "qualification_b",
                    {
                        "lead": dict(lead),
                        "prior_result": {
                            "agent": "qualification_a",
                            "qualified_companies": list(lead.get("potential_routes") or []),
                        },
                        "evidence_events": list(lead.get("evidence_events") or []),
                        "research_result": {
                            "status": "complete",
                            "verified_fields": list(lead.get("research_verified_fields") or []),
                        },
                    },
                    priority=9,
                    dedupe_key=f"qualification_b:{fingerprint}",
                )
                recovered.append({"fingerprint": fingerprint, "agent": "qualification_b"})
            paxus = (lead.get("qualification_results") or {}).get("Paxus", {})
            if isinstance(paxus, Mapping) and paxus.get("qualified") and not paxus.get("true_referral"):
                if not _queued_or_running(db, "paxus_research", fingerprint):
                    enqueue(
                        db,
                        "paxus_research",
                        {"lead": dict(lead), "paxus_qualification": dict(paxus)},
                        priority=10,
                        dedupe_key=f"paxus_research:{fingerprint}",
                    )
                    recovered.append({"fingerprint": fingerprint, "agent": "paxus_research"})
            continue

        if stage == "validated":
            if not _queued_or_running(db, "priority", fingerprint):
                enqueue(
                    db,
                    "priority",
                    {"lead": dict(lead), "evidence_events": list(lead.get("evidence_events") or [])},
                    priority=5,
                    dedupe_key=f"priority:{fingerprint}",
                )
                recovered.append({"fingerprint": fingerprint, "agent": "priority"})
            continue

        if (
            research_status in {"complete", "research_complete"}
            and not isinstance(lead.get("qualification_results"), Mapping)
        ):
            if not _queued_or_running(db, "qualification_a", fingerprint):
                enqueue(
                    db,
                    "qualification_a",
                    {
                        "lead": dict(lead),
                        "evidence_events": list(lead.get("evidence_events") or []),
                        "research_result": {
                            "status": research_status,
                            "verified_fields": list(lead.get("research_verified_fields") or []),
                        },
                    },
                    priority=9,
                    dedupe_key=f"qualification_a:{fingerprint}",
                )
                recovered.append({"fingerprint": fingerprint, "agent": "qualification_a"})
            continue

        skipped += 1

    return {
        "inspected_count": len(leads),
        "recovered_count": len(recovered),
        "recovered": recovered,
        "skipped_count": skipped,
    }
