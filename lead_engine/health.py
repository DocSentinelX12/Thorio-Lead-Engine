from typing import Any, Dict

from .database import LeadDB


def check_database(db: LeadDB) -> Dict[str, Any]:
    """
    Verify that the local database is accessible.
    """

    try:
        db.pending(limit=1)

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
    """
    Verify that runtime configuration is usable.
    """

    errors = []

    if not config.database_dir:
        errors.append(
            "database_dir is empty"
        )

    if config.batch_size <= 0:
        errors.append(
            "batch_size must be greater than zero"
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
    """
    Return the complete local health report.
    """

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
