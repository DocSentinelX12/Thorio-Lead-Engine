from typing import Dict, Any


EMPTY = ""


def normalize_contact(value: Any) -> str:
    """
    Normalize a contact value without inventing information.

    Missing or non-string values become an empty string.
    """
    if value is None:
        return EMPTY

    if not isinstance(value, str):
        return EMPTY

    return value.strip()


def enrich_lead(lead: Dict[str, object]) -> Dict[str, object]:
    """
    Prepare a lead for downstream routing and outreach.

    Enrichment is deliberately conservative:
    - existing information is preserved
    - missing information is left empty
    - no contact details are invented
    - enrichment never changes route or qualification
    """

    updated = dict(lead)

    updated["contact_name"] = normalize_contact(
        updated.get("contact_name")
    )

    updated["contact_title"] = normalize_contact(
        updated.get("contact_title")
    )

    updated["contact_email"] = normalize_contact(
        updated.get("contact_email")
    )

    updated["contact_phone"] = normalize_contact(
        updated.get("contact_phone")
    )

    updated["linkedin_url"] = normalize_contact(
        updated.get("linkedin_url")
    )

    updated["company_website"] = normalize_contact(
        updated.get("company_website")
    )

    updated["enrichment_status"] = (
        "enriched"
        if any(
            [
                updated["contact_name"],
                updated["contact_title"],
                updated["contact_email"],
                updated["contact_phone"],
                updated["linkedin_url"],
                updated["company_website"],
            ]
        )
        else "pending"
    )

    return updated


def has_contact_information(lead: Dict[str, object]) -> bool:
    """
    Return True when at least one usable contact field exists.
    """

    fields = (
        "contact_name",
        "contact_title",
        "contact_email",
        "contact_phone",
        "linkedin_url",
    )

    return any(
        normalize_contact(lead.get(field))
        for field in fields
    )


if __name__ == "__main__":
    print(
        enrich_lead(
            {
                "company": "ExampleCo",
                "signal": "remote software engineer",
            }
        )
    )
