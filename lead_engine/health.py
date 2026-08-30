from typing import Any, Dict, Iterable

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
        or isinstance(batch_size, bool)
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
        or isinstance(approval_interval, bool)
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


def check_source(
    source,
) -> Dict[str, Any]:
    """
    Validate one configured lead source without performing collection.

    This is intentionally a configuration/interface health check.
    Network collection belongs to the source execution path and must
    not be performed as part of a general health check.
    """

    errors = []

    if source is None:
        return {
            "name": "source",
            "status": "unhealthy",
            "ok": False,
            "source": None,
            "errors": [
                "source is None"
            ],
        }

    source_name = getattr(
        source,
        "name",
        None,
    )

    if not isinstance(source_name, str) or not source_name.strip():
        errors.append(
            "source name is empty"
        )
    else:
        source_name = source_name.strip()

    collect = getattr(
        source,
        "collect",
        None,
    )

    if not callable(collect):
        errors.append(
            "source collect method is not callable"
        )

    url = getattr(
        source,
        "url",
        None,
    )

    if url is not None:
        if (
            not isinstance(url, str)
            or not url.strip()
        ):
            errors.append(
                "source URL is empty"
            )

    timeout = getattr(
        source,
        "timeout",
        None,
    )

    if timeout is not None:
        if (
            not isinstance(timeout, int)
            or isinstance(timeout, bool)
            or timeout <= 0
        ):
            errors.append(
                "source timeout must be a positive integer"
            )

    if errors:
        return {
            "name": "source",
            "status": "unhealthy",
            "ok": False,
            "source": source_name,
            "errors": errors,
        }

    return {
        "name": "source",
        "status": "healthy",
        "ok": True,
        "source": source_name,
    }


def check_sources(
    sources: Iterable[Any],
) -> Dict[str, Any]:
    """
    Validate every configured source independently.

    One invalid source must not prevent the remaining sources from
    being validated.
    """

    results = []
    sources = list(sources)

    for source in sources:
        try:
            result = check_source(source)
        except Exception as exc:
            result = {
                "name": "source",
                "status": "unhealthy",
                "ok": False,
                "source": getattr(
                    source,
                    "name",
                    None,
                ),
                "errors": [
                    str(exc)
                ],
            }

        results.append(result)

    healthy = all(
        result["ok"]
        for result in results
    )

    return {
        "name": "sources",
        "status": (
            "healthy"
            if healthy
            else "unhealthy"
        ),
        "ok": healthy,
        "source_count": len(results),
        "healthy_count": sum(
            1
            for result in results
            if result["ok"]
        ),
        "unhealthy_count": sum(
            1
            for result in results
            if not result["ok"]
        ),
        "sources": results,
    }


def health_report(
    db: LeadDB,
    config,
    sources: Iterable[Any] | None = None,
) -> Dict[str, Any]:
    """Return the complete engine health report."""

    checks = [
        check_database(db),
        check_configuration(config),
    ]

    if sources is not None:
        checks.append(
            check_sources(sources)
        )

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


if __name__ == "__main__":
    db = LeadDB()

    print(
        check_engine(db)
    )
