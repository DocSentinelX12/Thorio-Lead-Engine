from typing import Any, Dict, Iterable, List


REQUIRED_FIELDS = {
    "source",
    "source_id",
    "url",
    "company",
    "signal",
    "evidence",
}


def validate_lead_input(
    lead: Dict[str, Any],
) -> None:
    """
    Validate the required discovery fields at the production
    input boundary.

    Invalid records raise ValueError so SourceRunner can isolate
    the bad record without stopping the source or remaining leads.
    """

    if not isinstance(lead, dict):
        raise ValueError(
            "Lead input must be an object."
        )

    required_fields = (
        "source",
        "source_id",
        "url",
        "company",
        "signal",
        "evidence",
    )

    for field in required_fields:
        value = lead.get(field)

        if not isinstance(value, str):
            raise ValueError(
                f"Lead field '{field}' must be a string."
            )

        if not value.strip():
            raise ValueError(
                f"Lead field '{field}' cannot be empty."
            )

    url = lead["url"].strip()

    if not (
        url.startswith("https://")
        or url.startswith("http://")
    ):
        raise ValueError(
            "Lead field 'url' must be an HTTP or HTTPS URL."
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
