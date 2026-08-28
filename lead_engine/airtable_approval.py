from typing import Any, Dict, List, Optional

from .airtable_sync import (
    _request,
    _table_url,
)
from .delivery_approval import (
    approve_lead,
    reject_lead,
)


APPROVAL_FIELD = "Review Status"
ROUTES_FIELD = "Applicable Routes"
REJECTION_REASON_FIELD = "Reason Not Qualified"


def _extract_routes(
    fields: Dict[str, Any],
) -> List[str]:
    routes = fields.get(ROUTES_FIELD, [])

    if isinstance(routes, str):
        routes = [routes]

    if not isinstance(routes, list):
        return []

    allowed = {
        "Paxus",
        "Shiftr",
        "Thorio",
    }

    return [
        str(route).strip()
        for route in routes
        if str(route).strip() in allowed
    ]


def _approval_state(
    fields: Dict[str, Any],
) -> str:
    value = str(
        fields.get(APPROVAL_FIELD, "")
        or ""
    ).strip().lower()

    if value in {
        "qualified",
        "approved",
        "approved to contact",
    }:
        return "approved"

    if value in {
        "rejected",
        "do not contact",
    }:
        return "rejected"

    return "pending"


def build_approved_lead(
    lead: Dict[str, Any],
    fields: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    state = _approval_state(fields)

    if state != "approved":
        return None

    routes = _extract_routes(fields)

    if not routes:
        return None

    result = approve_lead(
        lead,
        approved_routes=routes,
    )

    result["airtable_approval_state"] = "approved"

    return result


def build_rejected_lead(
    lead: Dict[str, Any],
    fields: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    state = _approval_state(fields)

    if state != "rejected":
        return None

    reason = str(
        fields.get(REJECTION_REASON_FIELD, "")
        or ""
    ).strip()

    result = reject_lead(
        lead,
        reason=reason,
    )

    result["airtable_approval_state"] = "rejected"

    return result


def fetch_record(
    record_id: str,
) -> Dict[str, Any]:
    return _request(
        "GET",
        f"{_table_url()}/{record_id}",
    )


def read_approval(
    lead: Dict[str, Any],
    record_id: str,
) -> Dict[str, Any]:
    record = fetch_record(record_id)

    fields = record.get("fields", {})

    state = _approval_state(fields)

    if state == "approved":
        result = build_approved_lead(
            lead,
            fields,
        )

        return {
            "status": "approved",
            "record": record,
            "lead": result,
        }

    if state == "rejected":
        result = build_rejected_lead(
            lead,
            fields,
        )

        return {
            "status": "rejected",
            "record": record,
            "lead": result,
        }

    return {
        "status": "pending",
        "record": record,
        "lead": lead,
  }
