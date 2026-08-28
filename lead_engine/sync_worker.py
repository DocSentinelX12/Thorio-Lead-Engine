import json
from typing import Any, Dict, List

from .airtable_sync import sync_lead_if_missing
from .database import LeadDB


def sync_one(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Synchronize one lead to Airtable.

    Airtable failures are contained and returned as a failed
    result so the local database remains the source of truth.
    """

    if not isinstance(lead, dict):
        return {
            "status": "failed",
            "lead": {},
            "airtable_record": None,
            "error": "Lead payload must be an object.",
        }

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
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Retry locally stored leads that have not successfully
    synchronized.

    Invalid stored payloads are marked as errors without
    stopping the remaining retry work.
    """

    rows = db.pending(limit=limit)

    synced: List[Dict[str, Any]] = []
    already_exists: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for fingerprint, payload_json, attempts in rows:
        try:
            lead = json.loads(payload_json)

        except (TypeError, ValueError) as exc:
            result = {
                "status": "failed",
                "lead": {},
                "airtable_record": None,
                "error": f"Invalid stored lead payload: {exc}",
            }

            failed.append(result)

            db.mark_error(
                fingerprint,
                result["error"],
            )

            continue

        if not isinstance(lead, dict):
            result = {
                "status": "failed",
                "lead": {},
                "airtable_record": None,
                "error": "Invalid stored lead payload: expected an object.",
            }

            failed.append(result)

            db.mark_error(
                fingerprint,
                result["error"],
            )

            continue

        result = sync_one(lead)

        if result["status"] == "synced":
            synced.append(result)
            db.mark_synced(fingerprint)

        elif result["status"] == "already_exists":
            already_exists.append(result)
            db.mark_synced(fingerprint)

        else:
            failed.append(result)

            db.mark_error(
                fingerprint,
                result["error"],
            )

    return {
        "synced": synced,
        "already_exists": already_exists,
        "failed": failed,
        "synced_count": len(synced),
        "already_exists_count": len(already_exists),
        "failed_count": len(failed),
    }
