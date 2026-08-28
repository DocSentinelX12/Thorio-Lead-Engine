from typing import Any, Dict

from .database import LeadDB


def _safe_state(
    db: LeadDB,
    key: str,
) -> Dict[str, Any]:
    try:
        value = db.get_state(key)
    except Exception:
        return {}

    if isinstance(value, dict):
        return value

    return {}


def _pending_details(
    db: LeadDB,
) -> Dict[str, Any]:
    try:
        rows = db.conn.execute(
            """
            SELECT
                COUNT(*) AS pending_count,
                COALESCE(SUM(attempts), 0) AS total_attempts,
                COALESCE(MAX(attempts), 0) AS max_attempts,
                MIN(created_at) AS oldest_created_at,
                MIN(updated_at) AS oldest_updated_at
            FROM leads
            WHERE synced = 0
            """
        ).fetchone()
    except Exception:
        return {
            "pending_count": 0,
            "total_attempts": 0,
            "max_attempts": 0,
            "oldest_pending_created_at": None,
            "oldest_pending_updated_at": None,
        }

    return {
        "pending_count": int(rows[0] or 0),
        "total_attempts": int(rows[1] or 0),
        "max_attempts": int(rows[2] or 0),
        "oldest_pending_created_at": rows[3],
        "oldest_pending_updated_at": rows[4],
    }


def _failed_sync_details(
    db: LeadDB,
) -> Dict[str, Any]:
    try:
        row = db.conn.execute(
            """
            SELECT
                COUNT(*) AS failed_leads,
                COALESCE(SUM(attempts), 0) AS failed_attempts,
                MAX(updated_at) AS last_failure_at
            FROM leads
            WHERE synced = 0
              AND attempts > 0
            """
        ).fetchone()
    except Exception:
        return {
            "failed_sync_leads": 0,
            "failed_sync_attempts": 0,
            "last_sync_failure": None,
        }

    return {
        "failed_sync_leads": int(row[0] or 0),
        "failed_sync_attempts": int(row[1] or 0),
        "last_sync_failure": row[2],
    }


def _source_observability(
    db: LeadDB,
) -> Dict[str, Any]:
    state = _safe_state(
        db,
        "source_observability",
    )

    return {
        "sources_started": int(
            state.get("sources_started", 0) or 0
        ),
        "sources_completed": int(
            state.get("sources_completed", 0) or 0
        ),
        "sources_failed": int(
            state.get("sources_failed", 0) or 0
        ),
        "last_source": state.get(
            "last_source"
        ),
        "last_source_started_at": state.get(
            "last_source_started_at"
        ),
        "last_source_completed_at": state.get(
            "last_source_completed_at"
        ),
        "last_source_failure_at": state.get(
            "last_source_failure_at"
        ),
        "last_source_error": state.get(
            "last_source_error"
        ),
        "last_source_record_count": int(
            state.get(
                "last_source_record_count",
                0,
            )
            or 0
        ),
    }


def _sync_observability(
    db: LeadDB,
) -> Dict[str, Any]:
    state = _safe_state(
        db,
        "sync_observability",
    )

    return {
        "sync_runs": int(
            state.get("sync_runs", 0) or 0
        ),
        "successful_sync_runs": int(
            state.get(
                "successful_sync_runs",
                0,
            )
            or 0
        ),
        "failed_sync_runs": int(
            state.get(
                "failed_sync_runs",
                0,
            )
            or 0
        ),
        "last_sync_started_at": state.get(
            "last_sync_started_at"
        ),
        "last_sync_completed_at": state.get(
            "last_sync_completed_at"
        ),
        "last_successful_sync": state.get(
            "last_successful_sync"
        ),
        "last_sync_failure": state.get(
            "last_sync_failure"
        ),
        "last_sync_error": state.get(
            "last_sync_error"
        ),
        "last_sync_processed_count": int(
            state.get(
                "last_sync_processed_count",
                0,
            )
            or 0
        ),
        "last_sync_success_count": int(
            state.get(
                "last_sync_success_count",
                0,
            )
            or 0
        ),
        "last_sync_failure_count": int(
            state.get(
                "last_sync_failure_count",
                0,
            )
            or 0
        ),
    }


def get_engine_status(
    db: LeadDB,
) -> Dict[str, Any]:
    """
    Return the current operational state of the lead engine.

    The local database remains authoritative.

    Existing status fields are preserved for compatibility while
    additional operational information is exposed for monitoring.
    """

    total, synced, pending = db.stats()

    pending_details = _pending_details(db)
    failed_details = _failed_sync_details(db)
    source_details = _source_observability(db)
    sync_details = _sync_observability(db)

    has_sync_failures = (
        failed_details["failed_sync_leads"] > 0
        or sync_details["failed_sync_runs"] > 0
    )

    healthy = not has_sync_failures

    return {
        # Existing public status contract.
        "total_leads": total,
        "synced_leads": synced,
        "pending_leads": pending,
        "healthy": healthy,

        # Pending queue observability.
        "pending_count": pending_details[
            "pending_count"
        ],
        "pending_attempts": pending_details[
            "total_attempts"
        ],
        "max_pending_attempts": pending_details[
            "max_attempts"
        ],
        "oldest_pending_created_at": (
            pending_details[
                "oldest_pending_created_at"
            ]
        ),
        "oldest_pending_updated_at": (
            pending_details[
                "oldest_pending_updated_at"
            ]
        ),

        # Airtable synchronization failures.
        "failed_sync_leads": failed_details[
            "failed_sync_leads"
        ],
        "failed_sync_attempts": failed_details[
            "failed_sync_attempts"
        ],
        "last_sync_failure": (
            sync_details["last_sync_failure"]
            or failed_details["last_sync_failure"]
        ),

        # Source observability.
        **source_details,

        # Sync observability.
        **sync_details,
    }


def get_sync_status(
    db: LeadDB,
) -> Dict[str, Any]:
    """
    Return synchronization counts and operational state.
    """

    total, synced, pending = db.stats()

    pending_details = _pending_details(db)
    failed_details = _failed_sync_details(db)
    sync_details = _sync_observability(db)

    return {
        # Existing contract.
        "total": total,
        "synced": synced,
        "pending": pending,

        # Operational information.
        "failed_leads": failed_details[
            "failed_sync_leads"
        ],
        "failed_attempts": failed_details[
            "failed_sync_attempts"
        ],
        "oldest_pending_created_at": (
            pending_details[
                "oldest_pending_created_at"
            ]
        ),
        "oldest_pending_updated_at": (
            pending_details[
                "oldest_pending_updated_at"
            ]
        ),
        "last_successful_sync": (
            sync_details[
                "last_successful_sync"
            ]
        ),
        "last_sync_failure": (
            sync_details[
                "last_sync_failure"
            ]
            or failed_details[
                "last_sync_failure"
            ]
        ),
        "last_sync_error": sync_details[
            "last_sync_error"
        ],
        "sync_runs": sync_details[
            "sync_runs"
        ],
        "successful_sync_runs": sync_details[
            "successful_sync_runs"
        ],
        "failed_sync_runs": sync_details[
            "failed_sync_runs"
        ],
    }


if __name__ == "__main__":
    db = LeadDB()

    print(
        get_engine_status(db)
)
