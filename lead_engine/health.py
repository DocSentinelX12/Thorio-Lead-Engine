from typing import Any, Dict

from .database import LeadDB


def check_database(db: LeadDB) -> Dict[str, Any]:
    """Verify that the local database is accessible and usable."""

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
    """Verify that required runtime configuration is valid."""

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

    if (
        not isinstance(batch_size, int)
        or batch_size <= 0
    ):
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


def check_airtable_configuration(
    config,
) -> Dict[str, Any]:
    """Verify required Airtable production configuration."""

    base_id = getattr(
        config,
        "airtable_base_id",
        "",
    )

    table = getattr(
        config,
        "airtable_table",
        "",
    )

    if not base_id:
        return {
            "name": "airtable_configuration",
            "status": "unhealthy",
            "ok": False,
            "error": "AIRTABLE_BASE_ID is not configured",
        }

    if not table:
        return {
            "name": "airtable_configuration",
            "status": "unhealthy",
            "ok": False,
            "error": "Airtable table is not configured",
        }

    return {
        "name": "airtable_configuration",
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
        check_airtable_configuration(config),
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
    """

    result = check_database(db)

    return {
        "healthy": result["ok"],
        "status": result["status"],
        "ok": result["ok"],
        "database": result,
                       }
