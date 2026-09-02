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

ALLOWED_ROUTES = {
    "Paxus",
    "Shiftr",
    "Thorio",
}


def _extract_routes(
    fields: Dict[str, Any],
) -> List[str]:
    routes = fields.get(
        ROUTES_FIELD,
        [],
    )

    if isinstance(routes, str):
        routes = [routes]

    if not isinstance(routes, list):
        return []

    return [
        str(route).strip()
        for route in routes
        if str(route).strip() in ALLOWED_ROUTES
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


def _field(
    fields: Dict[str, Any],
    name: str,
) -> Any:
    return fields.get(name)


def _text_field(
    fields: Dict[str, Any],
    name: str,
) -> str:
    value = _field(
        fields,
        name,
    )

    if value is None:
        return ""

    return str(value).strip()


def airtable_record_to_lead(
    record: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Reconstruct the canonical lead representation from
    an Airtable Lead Radar record.

    The Airtable record ID is retained separately by the
    polling layer and is also included as airtable_record_id
    for traceability.
    """

    if not isinstance(record, dict):
        raise ValueError(
            "Airtable record must be an object."
        )

    record_id = _text_field(
        record,
        "id",
    )

    fields = record.get(
        "fields",
        {},
    )

    if not isinstance(fields, dict):
        raise ValueError(
            "Airtable record fields must be an object."
        )

    routes = _extract_routes(
        fields
    )

    qualified_value = _field(
        fields,
        "Qualified Lead?",
    )

    lead_score = _field(
        fields,
        "Lead Score",
    )

    qualification_score = _field(
        fields,
        "Qualification Score",
    )

    lead = {
        "airtable_record_id": record_id,
        "company": _text_field(
            fields,
            "Company",
        ),
        "signal": _text_field(
            fields,
            "Signal",
        ),
        "url": _text_field(
            fields,
            "Source URL",
        ),
        "source": _text_field(
            fields,
            "Source Platform",
        ),
        "person": _text_field(
            fields,
            "Decision Maker",
        ),
        "contact_name": _text_field(
            fields,
            "Decision Maker",
        ),
        "contact_title": _text_field(
            fields,
            "Title",
        ),
        "fingerprint": _text_field(
            fields,
            "Duplicate Key",
        ),
        "lead_score": lead_score,
        "qualification_score": qualification_score,
        "qualified": (
            bool(qualified_value)
            if qualified_value is not None
            else False
        ),
        "evidence": _text_field(
            fields,
            "Why This Lead",
        ),
        "evidence_status": _text_field(
            fields,
            "Evidence Status",
        ),
        "potential_routes": routes,
        "review_status": _text_field(
            fields,
            "Review Status",
        ),
        "budget_confirmed": bool(
            _field(
                fields,
                "Budget Confirmed",
            )
        ),
        "need_confirmed": bool(
            _field(
                fields,
                "Need Confirmed",
            )
        ),
        "decision_maker_confirmed": bool(
            _field(
                fields,
                "Decision Maker Confirmed",
            )
        ),
        "timeline_confirmed": bool(
            _field(
                fields,
                "Timeline Confirmed",
            )
        ),
        "reason_not_qualified": _text_field(
            fields,
            "Reason Not Qualified",
        ),
        "contact_ready": bool(
            _field(
                fields,
                "Contact Ready",
            )
        ),
        "referral_submitted": bool(
            _field(
                fields,
                "Referral Submitted?",
            )
        ),
        "thorio_outreach_ready": bool(
            _field(
                fields,
                "Thorio Outreach Ready",
            )
        ),
        "remote_roles_verified": _field(
            fields,
            "Remote Roles Verified",
        ),
        "thorio_revenue_potential": _field(
            fields,
            "Thorio Revenue Potential",
        ),
        "contact_method": _text_field(
            fields,
            "Contact Method",
        ),
        "thorio_fit": _text_field(
            fields,
            "Thorio Fit",
        ),
        "thorio_plan_recommendation": _text_field(
            fields,
            "Thorio Plan Recommendation",
        ),
        "work_queue": _text_field(
            fields,
            "Work Queue",
        ),
        "outreach_status": _text_field(
            fields,
            "Outreach Status",
        ),
        "notes": _text_field(
            fields,
            "Notes",
        ),
        "discovered_at": _text_field(
            fields,
            "Discovered Date",
        ),
    }

    return {
        key: value
        for key, value in lead.items()
        if value is not None
    }


def list_records(
    page_size: int = 100,
) -> List[Dict[str, Any]]:
    """
    Retrieve all Lead Radar records using Airtable pagination.
    """

    if page_size < 1 or page_size > 100:
        raise ValueError(
            "page_size must be between 1 and 100."
        )

    records: List[Dict[str, Any]] = []
    offset: Optional[str] = None

    while True:
        params = {
            "pageSize": str(page_size),
        }

        if offset:
            params["offset"] = offset

        import urllib.parse

        query = urllib.parse.urlencode(
            params
        )

        result = _request(
            "GET",
            f"{_table_url()}?{query}",
        )

        page = result.get(
            "records",
            [],
        )

        if not isinstance(page, list):
            raise ValueError(
                "Airtable records response is invalid."
            )

        records.extend(page)

        offset = result.get(
            "offset"
        )

        if not offset:
            break

    return records


def fetch_approval_candidates(
    page_size: int = 100,
) -> List[Dict[str, Any]]:
    """
    Retrieve Airtable records that can participate in the
    approval state machine.

    We intentionally do not filter only on 'Reviewing'.
    Previously approved/rejected records must remain visible
    so route or status changes can be detected by the
    persistent approval state layer.
    """

    records = list_records(
        page_size=page_size
    )

    candidates = []

    for record in records:
        if not isinstance(record, dict):
            continue

        record_id = str(
            record.get("id", "")
            or ""
        ).strip()

        if not record_id:
            continue

        fields = record.get(
            "fields",
            {},
        )

        if not isinstance(fields, dict):
            continue

        lead = airtable_record_to_lead(
            record
        )

        candidates.append(
            {
                "record_id": record_id,
                "lead": lead,
            }
        )

    return candidates


def build_approved_lead(
    lead: Dict[str, Any],
    fields: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    state = _approval_state(
        fields
    )

    if state != "approved":
        return None

    routes = _extract_routes(
        fields
    )

    if not routes:
        return None

    result_lead = dict(
        lead
    )

    result_lead["routes"] = routes

    result = approve_lead(
        result_lead,
        approved_routes=routes,
    )

    result["routes"] = routes
    result["approved_routes"] = routes

    return result


def build_rejected_lead(
    lead: Dict[str, Any],
    fields: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    state = _approval_state(
        fields
    )

    if state != "rejected":
        return None

    reason = str(
        fields.get(
            REJECTION_REASON_FIELD,
            "",
        )
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
    if not str(record_id).strip():
        raise ValueError(
            "record_id is required."
        )

    return _request(
        "GET",
        f"{_table_url()}/{record_id}",
    )


def read_approval(
    lead: Dict[str, Any],
    record_id: str,
) -> Dict[str, Any]:
    record = fetch_record(
        record_id
    )

    fields = record.get(
        "fields",
        {},
    )

    state = _approval_state(
        fields
    )

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
