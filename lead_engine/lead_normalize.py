from typing import Any, Dict


NORMALIZED_TEXT_FIELDS = {
    "source",
    "source_id",
    "url",
    "company",
    "signal",
    "evidence",
    "person",
    "contact_name",
    "contact_title",
    "contact_phone",
    "linkedin_url",
    "company_website",
    "enrichment_status",
    "reason_not_qualified",
}


def normalize_lead(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Canonical production normalization for lead records.

    Normalization is intentionally limited to data representation.
    It does not qualify, score, route, deduplicate, persist, or
    otherwise remove leads.

    The original input is never mutated.

    None values remain None. Unknown fields are preserved.
    """

    if not isinstance(lead, dict):
        raise ValueError(
            "Lead input must be an object."
        )

    normalized = dict(lead)

    for field in NORMALIZED_TEXT_FIELDS:
        value = normalized.get(field)

        if isinstance(value, str):
            normalized[field] = value.strip()

    contact_email = normalized.get("contact_email")

    if isinstance(contact_email, str):
        normalized["contact_email"] = contact_email.strip().lower()

    return normalized
