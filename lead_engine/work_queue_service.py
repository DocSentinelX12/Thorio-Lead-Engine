import json
from typing import Any, Dict, List

from .database import LeadDB
from .work_queue import build_work_queue


def get_work_queue(
    db: LeadDB,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Return the highest-priority local leads requiring human work.

    The local database remains authoritative.
    """

    rows = db.pending(limit=limit)

    leads = []

    for fingerprint, payload, attempts in rows:
        lead = json.loads(payload)

        lead["_fingerprint"] = fingerprint
        lead["_sync_attempts"] = attempts

        leads.append(lead)

    return build_work_queue(leads)


def get_next_work_item(
    db: LeadDB,
) -> Dict[str, Any] | None:
    """
    Return the next highest-priority lead requiring human work.
    """

    queue = get_work_queue(db)

    return queue[0] if queue else None


if __name__ == "__main__":
    database = LeadDB()
    queue = get_work_queue(database)

    print(
        f"Work queue loaded. "
        f"{len(queue)} local leads require attention."
    )
