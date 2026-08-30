from pathlib import Path
from typing import Any, Dict

from .database import LeadDB


def check_database(db: LeadDB) -> Dict[str, Any]:
    """Verify that the production database is accessible and usable."""

    try:
        db.pending(limit=1)

        database_path = getattr(
            db,
            "database_path",
            None,
        )

        if database_path is not None:
            path = Path(database_path)

            if not path.exists():
                return {
                    "name": "database",
                    "status": "unhealthy",
                    "ok": False,
                    "error": "database file does not exist",
                }

        return {
            "name": "database",
            "status": "healthy",
            "ok": True,
        }

    except Exception as exc:
        return {
            "name": "database",
            "status": "unhealthy",
            "ok": False,
            "error": str(exc),
        }


def check_configuration(config) -> Dict[str, Any]:
    """Verify that runtime configuration is usable."""

    errors = []

    database_dir = getattr(
        config,
        "database_dir",
        None,
    )

    if not database_dir:
        errors.append(
            "database_dir is empty"
        )

    batch_size = getattr(
        config,
        "batch_size",
        None,
    )

    if not isinstance(batch_size, int) or batch_size <= 0:
        errors.append(
            "batch_size must be greater than zero"
        )

    approval_interval = getattr(
        config,
        "approval_poll_interval_seconds",
        None,
    )

    if (
        not isinstance(approval_interval, int)
        or approval_interval < 1
    ):
        errors.append(
            "approval_poll_interval_seconds must be at least 1"
        )

    if errors:
        return {
            "name": "configuration",
            "status": "unhealthy",
            "ok": False,
            "errors": errors,
        }

    return {
        "name": "configuration",
        "status": "healthy",
        "ok": True,
    }


def health_report(
    db: LeadDB,
    config,
) -> Dict[str, Any]:
    """Return the complete production health report."""

    checks = [
        check_database(db),
        check_configuration(config),
    ]

    healthy = all(
        check["ok"]
        for check in checks
    )

    return {
        "status": (
            "healthy"
            if healthy
            else "unhealthy"
        ),
        "ok": healthy,
        "checks": checks,
    }


def check_engine(
    db: LeadDB,
) -> Dict[str, Any]:
    """
    Backward-compatible database health check.

    Existing service/application code expects the
    `healthy` field.
    """

    result = check_database(db)

    return {
        "healthy": result["ok"],
        "status": result["status"],
        "ok": result["ok"],
        "database": result,
    }
```0
