from typing import Any, Dict, List

from .airtable_sync import (
    AirtableSyncError,
    sync_lead_if_missing,
)
from .database import LeadDB


def sync_one(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        result = sync_lead_if_missing(lead)

        return {
            "status": (
                "synced"
                if result["status"] == "created"
                else "already_exists"
            ),
            "lead": lead,
            "airtable_record": result.get("record"),
            "error": None,
        }

    except Exception as exc:
        return {
            "status": "failed",
            "lead": lead,
            "airtable_record": None,
            "error": str(exc),
        }


def sync_pending(
    db: LeadDB,
) -> Dict[str, Any]:
    pending = db.list_unsynced()

    synced: List[Dict[str, Any]] = []
    already_exists: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for lead in pending:
        result = sync_one(lead)

        if result["status"] == "synced":
            synced.append(result)
            db.mark_synced(lead)

        elif result["status"] == "already_exists":
            already_exists.append(result)
            db.mark_synced(lead)

        else:
            failed.append(result)

    return {
        "synced": synced,
        "already_exists": already_exists,
        "failed": failed,
        "synced_count": len(synced),
        "already_exists_count": len(already_exists),
        "failed_count": len(failed),
    }
