from typing import Any, Dict, List

from .airtable_client import list_records


APPROVAL_STATUSES = {
    "Qualified",
    "Approved",
    "Pending Review",
}


def fetch_pending_approvals(
    *,
    table: str = "Lead Radar",
    max_records: int = 100,
) -> List[Dict[str, Any]]:
    records = list_records(
        table=table,
        max_records=max_records,
    )

    pending: List[Dict[str, Any]] = []

    for record in records:
        fields = record.get("fields", {})

        review_status = fields.get(
            "Review Status"
        )

        if review_status not in APPROVAL_STATUSES:
            continue

        if not fields.get(
            "Applicable Routes"
        ):
            continue

        pending.append(
            {
                "record_id": record["id"],
                "lead": {
                    "company": fields.get(
                        "Company",
                        "",
                    ),
                    "fingerprint": fields.get(
                        "Fingerprint",
                        "",
                    ),
                    "potential_routes": fields.get(
                        "Potential Routes",
                        [],
                    ),
                },
            }
        )

    return pending
