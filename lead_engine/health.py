from typing import Any, Dict

from .database import LeadDB


def check_database(
    db: LeadDB,
) -> Dict[str, Any]:
    """
    Verify that the local database is accessible.
    """

    try:
        total, synced, pending = db.stats()

        return {
            "name": "database",
            "healthy": True,
            "total_leads": total,
            "synced_leads": synced,
            "pending_leads": pending,
            "error": None,
        }

    except Exception as exc:
        return {
            "name": "database",
            "healthy": False,
            "total_leads": 0,
            "synced_leads": 0,
            "pending_leads": 0,
            "error": str(exc),
        }


def check_engine(
    db: LeadDB,
) -> Dict[str, Any]:
    """
    Return the overall health of the local lead engine.
    """

    database = check_database(db)

    return {
        "healthy": database["healthy"],
        "checks": [
            database,
        ],
    }


if __name__ == "__main__":
    db = LeadDB()

    print(
        check_engine(db)
    )
