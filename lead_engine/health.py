from __future__ import annotations

from typing import Any, Dict


def health_status(
    *,
    database: Any = None,
    scheduler: Any = None,
    worker: Any = None,
) -> Dict[str, Any]:
    """
    Return a safe, dependency-light health snapshot.

    Health checks are intentionally defensive so the monitoring layer
    never takes down the lead engine while checking another component.
    """

    checks: Dict[str, Any] = {}

    if database is None:
        checks["database"] = {"status": "unknown"}
    else:
        try:
            if hasattr(database, "health"):
                result = database.health()
            elif hasattr(database, "check_health"):
                result = database.check_health()
            else:
                result = {"status": "available"}

            checks["database"] = (
                result if isinstance(result, dict) else {"status": str(result)}
            )
        except Exception as exc:
            checks["database"] = {
                "status": "unhealthy",
                "error": str(exc),
            }

    if scheduler is None:
        checks["scheduler"] = {"status": "unknown"}
    else:
        try:
            if hasattr(scheduler, "health"):
                result = scheduler.health()
            elif hasattr(scheduler, "status"):
                result = scheduler.status()
            else:
                result = {"status": "available"}

            checks["scheduler"] = (
                result if isinstance(result, dict) else {"status": str(result)}
            )
        except Exception as exc:
            checks["scheduler"] = {
                "status": "unhealthy",
                "error": str(exc),
            }

    if worker is None:
        checks["worker"] = {"status": "unknown"}
    else:
        try:
            if hasattr(worker, "health"):
                result = worker.health()
            elif hasattr(worker, "status"):
                result = worker.status()
            else:
                result = {"status": "available"}

            checks["worker"] = (
                result if isinstance(result, dict) else {"status": str(result)}
            )
        except Exception as exc:
            checks["worker"] = {
                "status": "unhealthy",
                "error": str(exc),
            }

    statuses = [
        value.get("status")
        for value in checks.values()
        if isinstance(value, dict)
    ]

    if any(status == "unhealthy" for status in statuses):
        overall = "unhealthy"
    elif any(status == "unknown" for status in statuses):
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "checks": checks,
    }


def health(
    *,
    database: Any = None,
    scheduler: Any = None,
    worker: Any = None,
) -> Dict[str, Any]:
    """Compatibility alias for health_status."""
    return health_status(
        database=database,
        scheduler=scheduler,
        worker=worker,
    )
