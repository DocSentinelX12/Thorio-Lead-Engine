from typing import Any, Dict

from .database import LeadDB


def get_engine_status(
    db: LeadDB,
) -> Dict[str, Any]:
    """
    Return the current operational state of the lead engine.

    The local database is authoritative.
    """

    total, synced, pending = db.stats()

    return {
        "total_leads": total,
        "synced_leads": synced,
        "pending_leads": pending,
        "healthy": pending == 0,
    }


def get_sync_status(
    db: LeadDB,
) -> Dict[str, int]:
    """
    Return synchronization counts.
    """

    total, synced, pending = db.stats()

    return {
        "total": total,
        "synced": synced,
        "pending": pending,
    }


if __name__ == "__main__":
    db = LeadDB()

    print(
        get_engine_status(db)
    )
