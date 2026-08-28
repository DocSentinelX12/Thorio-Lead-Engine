from typing import Any, Dict, Iterable, List


def run_source(source: Any) -> Dict[str, Any]:
    """
    Run one lead source without allowing a source failure
    to crash the entire engine.
    """
    name = getattr(source, "name", source.__class__.__name__)

    try:
        leads = list(source.collect())

        return {
            "source": name,
            "status": "success",
            "count": len(leads),
            "leads": leads,
            "error": None,
        }

    except Exception as exc:
        return {
            "source": name,
            "status": "failed",
            "count": 0,
            "leads": [],
            "error": str(exc),
        }


def run_sources(
    sources: Iterable[Any],
) -> List[Dict[str, Any]]:
    """
    Run all configured sources independently.

    A failure in one source must not prevent other sources
    from running.
    """
    results: List[Dict[str, Any]] = []

    for source in sources:
        results.append(run_source(source))

    return results
