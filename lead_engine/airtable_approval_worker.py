from typing import Any, Dict, List

from .airtable_approval import read_approval
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

    if status == "rejected":
        return {
            "status": "rejected",
            "delivered": False,
            "record_id": record_id,
            "lead": result["lead"],
        }

    approved_lead = result["lead"]

    return {
        "status": "approved",
        "delivered": False,
        "record_id": record_id,
        "lead": approved_lead,
        "approved_routes": approved_lead.get(
            "approved_routes",
            [],
        ),
    }


def process_approval_batch(
    db: LeadDB,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    approved = []
    pending = []
    rejected = []

    for item in items:
        result = process_airtable_approval(
            db=db,
            lead=item["lead"],
            record_id=item["record_id"],
        )

        if result["status"] == "approved":
            approved.append(result)
        elif result["status"] == "rejected":
            rejected.append(result)
        else:
            pending.append(result)

    return {
        "approved": approved,
        "pending": pending,
        "rejected": rejected,
        "approved_count": len(approved),
        "pending_count": len(pending),
        "rejected_count": len(rejected),
    }
