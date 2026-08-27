from __future__ import annotations

from typing import Any, Dict, Iterable


def health_summary(
    leads: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return basic health information for a lead collection."""

    records = list(leads)

    total = len(records)

    if total == 0:
        return {
            "total": 0,
            "scored": 0,
            "unscored": 0,
            "with_contact": 0,
            "without_contact": 0,
            "score_coverage": 0.0,
            "contact_coverage": 0.0,
        }

    scored = 0
    with_contact = 0

    for lead in records:
        score = lead.get("lead_score")

        if score is not None and score != "":
            try:
                float(score)
                scored += 1
            except (TypeError, ValueError):
                pass

        email = str(
            lead.get("contact_email", "") or ""
        ).strip()

        if email:
            with_contact += 1

    return {
        "total": total,
        "scored": scored,
        "unscored": total - scored,
        "with_contact": with_contact,
        "without_contact": total - with_contact,
        "score_coverage": scored / total,
        "contact_coverage": with_contact / total,
    }
