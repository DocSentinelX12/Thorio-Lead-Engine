from typing import Any, Dict, List

from .airtable_approval import read_approval
from .airtable_approval_state import (
    mark_approval_processed,
    should_process_approval,
)
from .database import LeadDB


def process_airtable_approval(
    db: LeadDB,
    lead: Dict[str, Any],
    record_id: str,
) -> Dict[str, Any]:
    result = read_approval(
        lead,
        record_id,
    )

    status = result["status"]

    if status == "pending":
        return {
            "status": "pending",
            "delivered": False,
            "record_id": record_id,
        }

    approved_routes = result["lead"].get(
        "approved_routes",
        [],
    ) if result.get("lead") else []

    if not should_process_approval(
        db,
        record_id,
        status,
        approved_routes,
    ):
        previous = result.get("lead", lead)

        return {
            "status": status,
            "delivered": False,
            "record_id": record_id,
            "lead": previous,
            "approved_routes": approved_routes,
            "already_processed": True,
        }

    if status == "rejected":
        mark_approval_processed(
            db,
            record_id,
            status,
            [],
        )

        return {
            "status": "rejected",
            "delivered": False,
            "record_id": record_id,
            "lead": result["lead"],
            "approved_routes": [],
            "already_processed": False,
        }

    approved_lead = result["lead"]

    mark_approval_processed(
        db,
        record_id,
        status,
        approved_routes,
    )

    return {
        "status": "approved",
        "delivered": False,
        "record_id": record_id,
        "lead": approved_lead,
        "approved_routes": approved_routes,
        "already_processed": False,
    }


def process_approval_batch(
    db: LeadDB,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    approved = []
    pending = []
    rejected = []
    already_processed = []

    for item in items:
        result = process_airtable_approval(
            db=db,
            lead=item["lead"],
            record_id=item["record_id"],
        )

        if result.get("already_processed"):
            already_processed.append(result)
        elif result["status"] == "approved":
            approved.append(result)
        elif result["status"] == "rejected":
            rejected.append(result)
        else:
            pending.append(result)

    return {
        "approved": approved,
        "pending": pending,
        "rejected": rejected,
        "already_processed": already_processed,
        "approved_count": len(approved),
        "pending_count": len(pending),
        "rejected_count": len(rejected),
        "already_processed_count": len(already_processed),
    }
