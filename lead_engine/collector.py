from typing import Any, Dict, Iterable, List


REQUIRED_FIELDS = {
    "source",
    "source_id",
    "url",
    "company",
    "signal",
    "evidence",
}


def validate_lead_input(lead: Dict[str, Any]) -> None:
    """
    Validate the minimum information required before a lead
    enters the processing pipeline.
    """

    missing = [
        field
        for field in REQUIRED_FIELDS
        if not lead.get(field)
    ]

    if missing:
        raise ValueError(
            "Lead is missing required fields: "
            + ", ".join(sorted(missing))
        )


def normalize_lead_input(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Normalize incoming discovery data without making
    qualification decisions.
    """

    validate_lead_input(lead)

    normalized = dict(lead)

    for field in (
        "source",
        "source_id",
        "url",
        "company",
        "signal",
        "evidence",
    ):
        value = normalized.get(field)

        if isinstance(value, str):
            normalized[field] = value.strip()

    return normalized


def collect(
    leads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Normalize a batch of discovered leads.

    Invalid leads are rejected instead of silently entering
    the processing system.
    """

    collected = []

    for lead in leads:
        collected.append(
            normalize_lead_input(lead)
        )

    return collected


if __name__ == "__main__":
    print(
        "Lead collector loaded. "
        "Use collect() to normalize discovered leads."
    )
