from typing import Any, Dict, List

from .airtable_sync import AirtableSyncError, sync_lead_if_missing


SYNC_PENDING = "pending"
SYNC_SYNCED = "synced"
SYNC_FAILED = "failed"


def sync_one(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Attempt to synchronize one local lead with Airtable.

    The local lead remains the source of truth.
    A failed Airtable request never deletes the local lead.
    """

    try:
        result = sync_lead_if_missing(lead)

        if result["status"] == "already_exists":
            return {
                "status": SYNC_SYNCED,
                "lead": lead,
                "airtable_record": result.get("record"),
                "error": None,
            }

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
    leads: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Synchronize all pending local leads.

    Failed leads are returned so the caller can keep them in the
    local queue and retry them later.
    """

    synced = []
    failed = []

    for lead in leads:
        result = sync_one(lead)

        if result["status"] == SYNC_SYNCED:
            synced.append(result)
        else:
            failed.append(result)

    return {
        "synced": synced,
        "failed": failed,
        "synced_count": len(synced),
        "failed_count": len(failed),
    }


def should_retry(status: str) -> bool:
    """
    Determine whether a local queue item should be retried.
    """

    return status in {
        SYNC_PENDING,
        SYNC_FAILED,
    }


def prepare_retry_queue(
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Return only leads that need another synchronization attempt.

    This does not delete or modify the original local records.
    """

    return [
        result["lead"]
        for result in results
        if result["status"] == SYNC_FAILED
    ]


if __name__ == "__main__":
    print(
        "Lead sync worker loaded. "
        "Pending local leads can now be synchronized safely."
  )
