from typing import Any, Dict, Optional

from .database import LeadDB


def approval_key(record_id: str) -> str:
    return f"airtable_approval:{record_id}"


def get_approval_state(
    db: LeadDB,
    record_id: str,
) -> Optional[Dict[str, Any]]:
    key = approval_key(record_id)

    if hasattr(db, "get_state"):
        return db.get_state(key)

    return None


def mark_approval_processed(
    db: LeadDB,
    record_id: str,
    status: str,
    approved_routes: Optional[list] = None,
) -> None:
    value = {
        "record_id": record_id,
        "status": status,
        "approved_routes": approved_routes or [],
    }

    if hasattr(db, "set_state"):
        db.set_state(
            approval_key(record_id),
            value,
        )


def should_process_approval(
    db: LeadDB,
    record_id: str,
    status: str,
    approved_routes: Optional[list] = None,
) -> bool:
    previous = get_approval_state(
        db,
        record_id,
    )

    if previous is None:
        return True

    previous_routes = previous.get(
        "approved_routes",
        [],
    )

    current_routes = approved_routes or []

    return (
        previous.get("status") != status
        or previous_routes != current_routes
    )
