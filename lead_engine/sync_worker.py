from typing import Any, Dict, List

from .airtable_sync import AirtableSyncError, sync_lead_if_missing
from .database import LeadDB


SYNC_PENDING = "pending"
SYNC_SYNCED = "synced"
SYNC_FAILED = "failed"


def sync_one(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Attempt to synchronize one canonical local lead with Airtable.

    The local database remains the source of truth.
    """

    try:
        result = sync_lead_if_missing(lead)

        return {
            "status": SYNC_SYNCED,
            "lead": lead,
            "airtable_record": result.get("record"),
            "error": None,
        }

    except AirtableSyncError as exc:
        return {
            "status": SYNC_FAILED,
            "lead": lead,
            "airtable_record": None,
            "error": str(exc),
        }


def sync_pending(
    db: LeadDB,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Synchronize pending leads from the permanent local database.

    Successful records are marked synced.
    Failed records remain pending/failed for retry.
    """

    synced = []
    failed = []

    for fingerprint, payload_json, attempts in db.pending(limit):
        try:
            import json

            lead = json.loads(payload_json)

            result = sync_one(lead)

            if result["status"] == SYNC_SYNCED:
                db.mark_synced(fingerprint)
                synced.append(result)
            else:
                db.mark_error(
                    fingerprint,
                    result["error"] or "Unknown sync error",
                )
                failed.append(result)

        except Exception as exc:
            db.mark_error(fingerprint, str(exc))

            failed.append(
                {
                    "status": SYNC_FAILED,
                    "lead": None,
                    "airtable_record": None,
                    "error": str(exc),
                }
            )

    return {
        "synced": synced,
        "failed": failed,
        "synced_count": len(synced),
        "failed_count": len(failed),
    }


def should_retry(status: str) -> bool:
    """
    Determine whether a synchronization item should be retried.
    """

    return status in {
        SYNC_PENDING,
        SYNC_FAILED,
    }


if __name__ == "__main__":
    print(
        "Lead sync worker loaded. "
        "Use sync_pending(db) to synchronize local leads safely."
    )
