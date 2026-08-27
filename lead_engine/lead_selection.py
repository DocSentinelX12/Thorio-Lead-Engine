from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .lead_ranking import rank_leads


def select_leads(
    leads: Iterable[Dict[str, Any]],
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Select the best leads for the next processing stage.

    Leads are ranked before the optional limit is applied.
    """

    ranked = rank_leads(leads)

    if limit is None:
        return ranked

    if limit < 0:
        raise ValueError("limit must be non-negative")

    return ranked[:limit]


def select_top_lead(
    leads: Iterable[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return the highest-ranked lead, or None when empty."""

    selected = select_leads(leads, limit=1)

    return selected[0] if selected else None
