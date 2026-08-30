from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse


REQUIRED_FIELDS = {
    "source",
    "source_id",
    "url",
    "company",
    "signal",
    "evidence",
}

OPTIONAL_TEXT_FIELDS = {
    "person",
    "contact_name",
    "contact_title",
    "contact_phone",
    "enrichment_status",
    "reason_not_qualified",
}

OPTIONAL_URL_FIELDS = {
    "linkedin_url",
    "company_website",
}

OPTIONAL_EMAIL_FIELDS = {
    "contact_email",
}


def _validate_text_field(
    field: str,
    value: Any,
) -> None:
    if not isinstance(value, str):
        raise ValueError(
            f"Lead field '{field}' must be a string."
        )

    if not value.strip():
        raise ValueError(
            f"Lead field '{field}' cannot be empty."
        )

    if any(
        ord(character) < 32
        and character not in ("\t", "\n", "\r")
        for character in value
    ):
        raise ValueError(
            f"Lead field '{field}' contains invalid control characters."
        )


def _validate_url_field(
    field: str,
    value: Any,
) -> None:
    _validate_text_field(
        field,
        value,
    )

    url = value.strip()
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"Lead field '{field}' must be an HTTP or HTTPS URL."
        )

    if not parsed.netloc:
        raise ValueError(
            f"Lead field '{field}' must contain a valid host."
        )


def _validate_email_field(
    field: str,
    value: Any,
) -> None:
    _validate_text_field(
        field,
        value,
    )

    email = value.strip()

    if email.count("@") != 1:
        raise ValueError(
            f"Lead field '{field}' must contain a valid email address."
        )

    local_part, domain = email.split("@")

    if not local_part or not domain:
        raise ValueError(
            f"Lead field '{field}' must contain a valid email address."
        )

    if any(
        character.isspace()
        for character in email
    ):
        raise ValueError(
            f"Lead field '{field}' must contain a valid email address."
        )

    if "." not in domain:
        raise ValueError(
            f"Lead field '{field}' must contain a valid email address."
        )


def validate_lead_input(
    lead: Dict[str, Any],
) -> None:
    """
    Validate discovered lead data at the production input boundary.

    Discovery validation intentionally does not require contact,
    qualification, referral, consent, or routing fields. Those
    belong to later lifecycle boundaries.

    Invalid records raise ValueError so SourceRunner can isolate
    the bad record without stopping the source or remaining leads.
    """

    if not isinstance(lead, dict):
        raise ValueError(
            "Lead input must be an object."
        )

    for field in REQUIRED_FIELDS:
        if field not in lead:
            raise ValueError(
                f"Lead field '{field}' is required."
            )

        _validate_text_field(
            field,
            lead[field],
        )

    _validate_url_field(
        "url",
        lead["url"],
    )

    for field in OPTIONAL_TEXT_FIELDS:
        if field in lead and lead[field] is not None:
            _validate_text_field(
                field,
                lead[field],
            )

    for field in OPTIONAL_URL_FIELDS:
        if field in lead and lead[field] is not None:
            _validate_url_field(
                field,
                lead[field],
            )

    for field in OPTIONAL_EMAIL_FIELDS:
        if field in lead and lead[field] is not None:
            _validate_email_field(
                field,
                lead[field],
            )


def normalize_lead_input(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Normalize incoming discovery data without making
    qualification, routing, or deduplication decisions.
    """

    validate_lead_input(lead)

    normalized = dict(lead)

    for field in REQUIRED_FIELDS:
        value = normalized.get(field)

        if isinstance(value, str):
            normalized[field] = value.strip()

    for field in OPTIONAL_TEXT_FIELDS:
        value = normalized.get(field)

        if isinstance(value, str):
            normalized[field] = value.strip()

    for field in OPTIONAL_URL_FIELDS:
        value = normalized.get(field)

        if isinstance(value, str):
            normalized[field] = value.strip()

    for field in OPTIONAL_EMAIL_FIELDS:
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
    the processing system. SourceRunner is responsible for
    isolating rejected records from the remaining source data.
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
