from typing import Any, Dict, List

from .airtable_sync import sync_lead_if_missing
from .database import LeadDB


def sync_pending(
    db: LeadDB,
    limit: int = 50,
) -> Dict[str, Any]:
    rows = db.pending(limit=limit)

    synced: List[Dict[str, Any]] = []
    already_exists: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for fingerprint, payload, attempts in rows:
        if isinstance(payload, dict):
            lead = dict(payload)
        else:
            failed.append(
                {
                    "fingerprint": fingerprint,
                    "attempts": attempts,
                    "error": "Invalid pending lead payload",
                }
            )
            continue

        try:
            result = sync_lead_if_missing(lead)

            status = result.get("status")

            if status == "created":
                db.mark_synced(
                    fingerprint,
                    result.get("record"),
                )

                synced.append(
                    {
                        "fingerprint": fingerprint,
                        "record": result.get("record"),
                        "attempts": attempts,
                    }
                )

            elif status == "exists":
                db.mark_synced(
                    fingerprint,
                    result.get("record"),
                )

                already_exists.append(
                    {
                        "fingerprint": fingerprint,
                        "record": result.get("record"),
                        "attempts": attempts,
                    }
                )

            else:
                db.mark_sync_failed(
                    fingerprint,
                    result.get(
                        "error",
                        "Airtable sync failed",
                    ),
                )

                failed.append(
                    {
                        "fingerprint": fingerprint,
                        "attempts": attempts,
                        "error": result.get(
                            "error",
                            "Airtable sync failed",
                        ),
                    }
                )

        except Exception as exc:
            db.mark_sync_failed(
                fingerprint,
                str(exc),
            )

            failed.append(
                {
                    "fingerprint": fingerprint,
                    "attempts": attempts,
                    "error": str(exc),
                }
            )

    return {
        "processed": len(rows),
        "synced": synced,
        "already_exists": already_exists,
        "failed": failed,
        "synced_count": len(synced),
        "already_exists_count": len(already_exists),
        "failed_count": len(failed),
    }
