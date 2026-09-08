from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from .enrichment import enrich_lead
from .qualification import evaluate_company_qualification


STATE_KEY = "paxus_research_queue"
RESEARCH_REQUIRED = "research_required"
COMPLETE = "complete"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_queue(db) -> Dict[str, Any]:
    state = db.get_state(STATE_KEY)
    if not isinstance(state, dict):
        return {}
    queue = state.get("items", {})
    return queue if isinstance(queue, dict) else {}


def _save_queue(db, queue: Dict[str, Any]) -> None:
    db.set_state(STATE_KEY, {"items": queue})


def queue_paxus_research(db, lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retain a Paxus-qualified lead for research instead of rejecting it when
    the additional referral gates are not yet verified.

    This function never manufactures a contact, communication, consent, or
    referral pass. It only records the exact missing work.
    """
    if not isinstance(lead, dict):
        raise ValueError("lead must be a dictionary")

    fingerprint = str(lead.get("fingerprint") or "").strip()
    if not fingerprint:
        raise ValueError("lead must contain a fingerprint")

    evaluation = evaluate_company_qualification(lead)
    paxus = evaluation["companies"].get("Paxus", {})
    referral = paxus.get("referral_checklist", {})

    queue = _load_queue(db)

    if not paxus.get("qualified"):
        queue.pop(fingerprint, None)
        _save_queue(db, queue)
        return {
            "status": "not_queued",
            "fingerprint": fingerprint,
            "reason": "paxus_base_qualification_not_met",
        }

    if paxus.get("true_referral"):
        queue.pop(fingerprint, None)
        _save_queue(db, queue)
        return {
            "status": COMPLETE,
            "fingerprint": fingerprint,
            "missing_items": [],
        }

    missing_items: List[str] = list(referral.get("research_required", []))
    verification_items: List[str] = list(referral.get("verification_required", []))
    queue[fingerprint] = {
        "fingerprint": fingerprint,
        "status": RESEARCH_REQUIRED,
        "missing_research": missing_items,
        "missing_verification": verification_items,
        "failures": list(referral.get("failures", [])),
        "last_attempt_at": _now(),
        "attempts": int(queue.get(fingerprint, {}).get("attempts", 0)) + 1,
    }
    _save_queue(db, queue)

    updated = db.update_payload(
        fingerprint,
        {
            "research_status": RESEARCH_REQUIRED,
            "research_queue": queue[fingerprint],
            "qualification_results": evaluation["companies"],
            "potential_routes": evaluation["qualified_companies"],
        },
    )

    return {
        "status": RESEARCH_REQUIRED,
        "fingerprint": fingerprint,
        "missing_research": missing_items,
        "missing_verification": verification_items,
        "lead": updated or lead,
    }


def process_paxus_research_queue(db, limit: int = 50) -> Dict[str, Any]:
    """
    Re-run conservative enrichment and qualification for queued Paxus leads.

    The existing enrichment layer only normalizes information already present,
    so this function does not pretend that external research occurred. It
    creates a durable retry boundary for a future research provider and
    immediately promotes a lead when all existing gates become verifiable.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit must be a positive integer")

    queue = _load_queue(db)
    processed = []
    completed = []
    still_required = []
    errors = []

    for fingerprint, item in list(queue.items())[:limit]:
        try:
            lead = db.get(fingerprint)
            if lead is None:
                queue.pop(fingerprint, None)
                continue

            enriched = enrich_lead(dict(lead))
            evaluation = evaluate_company_qualification(enriched)
            paxus = evaluation["companies"].get("Paxus", {})
            referral = paxus.get("referral_checklist", {})

            if not paxus.get("qualified"):
                queue.pop(fingerprint, None)
                db.update_payload(
                    fingerprint,
                    {
                        "enrichment_status": enriched.get("enrichment_status", "pending"),
                        "qualification_results": evaluation["companies"],
                        "potential_routes": evaluation["qualified_companies"],
                        "research_status": "complete",
                    },
                )
                processed.append(fingerprint)
                continue

            missing_research = list(referral.get("research_required", []))
            missing_verification = list(referral.get("verification_required", []))
            is_complete = bool(paxus.get("true_referral"))

            attempts = int(item.get("attempts", 0)) + 1
            updated_queue_item = {
                "fingerprint": fingerprint,
                "status": COMPLETE if is_complete else RESEARCH_REQUIRED,
                "missing_research": missing_research,
                "missing_verification": missing_verification,
                "failures": list(referral.get("failures", [])),
                "last_attempt_at": _now(),
                "attempts": attempts,
            }

            if is_complete:
                queue.pop(fingerprint, None)
                completed.append(fingerprint)
                research_status = "complete"
            else:
                queue[fingerprint] = updated_queue_item
                still_required.append(fingerprint)
                research_status = RESEARCH_REQUIRED

            db.update_payload(
                fingerprint,
                {
                    "enrichment_status": enriched.get("enrichment_status", "pending"),
                    "qualification_results": evaluation["companies"],
                    "potential_routes": evaluation["qualified_companies"],
                    "research_status": research_status,
                    "research_queue": None if is_complete else updated_queue_item,
                },
            )
            processed.append(fingerprint)
        except Exception as exc:
            errors.append({"fingerprint": fingerprint, "error": str(exc)})

    _save_queue(db, queue)

    return {
        "status": "completed" if not errors else "completed_with_errors",
        "processed": processed,
        "completed": completed,
        "still_required": still_required,
        "errors": errors,
        "queued_count": len(queue),
    }


if __name__ == "__main__":
    print("Paxus research queue loaded.")
