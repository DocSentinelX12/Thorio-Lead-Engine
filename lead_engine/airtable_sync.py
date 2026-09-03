import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .config import LeadEngineConfig


AIRTABLE_API_URL = "https://api.airtable.com/v0"

TABLE_NAME = os.getenv(
    "AIRTABLE_LEAD_TABLE",
    "Lead Radar",
)

AIRTABLE_MAX_RETRIES = 3
AIRTABLE_INITIAL_BACKOFF = 1.0
AIRTABLE_MAX_BACKOFF = 30.0


class AirtableSyncError(Exception):
    """Raised when Airtable synchronization fails."""


def _require_config() -> None:
    missing = []

    if not os.getenv("AIRTABLE_BASE_ID"):
        missing.append("AIRTABLE_BASE_ID")

    if not os.getenv("AIRTABLE_API_KEY"):
        missing.append("AIRTABLE_API_KEY")

    if missing:
        raise AirtableSyncError(
            f"Missing Airtable configuration: {', '.join(missing)}"
        )


def _retry_delay(
    attempt: int,
    retry_after: Optional[str] = None,
) -> float:
    if retry_after:
        try:
            value = float(retry_after)

            if value >= 0:
                return min(
                    value,
                    AIRTABLE_MAX_BACKOFF,
                )

        except (TypeError, ValueError):
            pass

    delay = AIRTABLE_INITIAL_BACKOFF * (
        2 ** attempt
    )

    return min(
        delay,
        AIRTABLE_MAX_BACKOFF,
    )


def _request(
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    _require_config()

    api_key = os.getenv(
        "AIRTABLE_API_KEY",
    )

    if not api_key:
        raise AirtableSyncError(
            "Missing Airtable API key."
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    last_error: Optional[AirtableSyncError] = None

    for attempt in range(
        AIRTABLE_MAX_RETRIES + 1
    ):
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=20,
            ) as response:
                body = response.read().decode(
                    "utf-8"
                )

                if not body:
                    return {}

                try:
                    result = json.loads(body)

                except json.JSONDecodeError as exc:
                    raise AirtableSyncError(
                        "Airtable returned invalid JSON."
                    ) from exc

                if not isinstance(result, dict):
                    raise AirtableSyncError(
                        "Airtable returned an invalid JSON response."
                    )

                return result

        except urllib.error.HTTPError as exc:
            retryable = (
                exc.code == 429
                or 500 <= exc.code <= 599
            )

            try:
                body = exc.read().decode(
                    "utf-8",
                    errors="replace",
                )

            except Exception:
                body = (
                    "Unable to read Airtable "
                    "error response."
                )

            error = AirtableSyncError(
                f"Airtable API error {exc.code}: {body}"
            )

            if not retryable:
                raise error from exc

            last_error = error

            if attempt >= AIRTABLE_MAX_RETRIES:
                raise error from exc

            retry_after = exc.headers.get(
                "Retry-After"
            )

            time.sleep(
                _retry_delay(
                    attempt,
                    retry_after,
                )
            )

        except (
            urllib.error.URLError,
            TimeoutError,
        ) as exc:
            if isinstance(
                exc,
                urllib.error.URLError,
            ):
                reason = exc.reason

                error = AirtableSyncError(
                    f"Airtable connection failed: {reason}"
                )

            else:
                error = AirtableSyncError(
                    "Airtable request timed out."
                )

            last_error = error

            if attempt >= AIRTABLE_MAX_RETRIES:
                raise error from exc

            time.sleep(
                _retry_delay(attempt)
            )

        except UnicodeDecodeError as exc:
            raise AirtableSyncError(
                "Airtable returned invalid UTF-8 response data."
            ) from exc

        except OSError as exc:
            error = AirtableSyncError(
                f"Airtable request failed: {exc}"
            )

            last_error = error

            if attempt >= AIRTABLE_MAX_RETRIES:
                raise error from exc

            time.sleep(
                _retry_delay(attempt)
            )

    if last_error is not None:
        raise last_error

    raise AirtableSyncError(
        "Airtable request failed unexpectedly."
    )


def _table_url() -> str:
    base_id = os.getenv(
        "AIRTABLE_BASE_ID",
        "",
    )

    table_name = os.getenv(
        "AIRTABLE_LEAD_TABLE",
        "Lead Radar",
    )

    return (
        f"{AIRTABLE_API_URL}/"
        f"{base_id}/"
        f"{urllib.parse.quote(table_name, safe='')}"
    )


def _text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


MASTER_TRACKER_TABLE_KEYS = {
    "lead_radar",
    "companies",
    "opportunities",
    "outreach",
    "referrals",
    "followups",
    "commissions",
    "lead_sources",
}


def _configured_tables() -> Dict[str, str]:
    config = LeadEngineConfig.from_environment()
    tables = config.airtable_tables

    if not MASTER_TRACKER_TABLE_KEYS.issubset(
        tables.keys()
    ):
        raise AirtableSyncError(
            "Airtable table configuration is incomplete."
        )

    return dict(tables)


def _table_name(
    table_key: str,
) -> str:
    if table_key not in MASTER_TRACKER_TABLE_KEYS:
        raise AirtableSyncError(
            f"Unknown Airtable table key: {table_key}"
        )

    table_name = _configured_tables().get(
        table_key
    )

    if not table_name:
        raise AirtableSyncError(
            f"No Airtable table configured for: {table_key}"
        )

    return table_name


def _master_table_url(
    table_key: str,
) -> str:
    table_name = _table_name(
        table_key
    )

    base_id = os.getenv(
        "AIRTABLE_BASE_ID",
        "",
    )

    return (
        f"{AIRTABLE_API_URL}/"
        f"{base_id}/"
        f"{urllib.parse.quote(table_name, safe='')}"
    )


def find_master_records(
    table_key: str,
    field_name: str,
    value: Any,
) -> List[Dict[str, Any]]:
    """
    Find Airtable records in a configured master-tracker
    table by an exact field value.

    All Airtable pagination is followed so the lookup does
    not silently stop at the first page.
    """

    if not _text(value):
        return []

    escaped = _text(value).replace(
        "\\",
        "\\\\",
    ).replace(
        '"',
        '\\"',
    )

    escaped_field = _text(field_name)

    if not escaped_field:
        raise ValueError(
            "Airtable lookup requires a field name."
        )

    formula = (
        f'{{{escaped_field}}}="{escaped}"'
    )

    records: List[Dict[str, Any]] = []
    offset: Optional[str] = None

    while True:
        params = {
            "filterByFormula": formula,
            "pageSize": "100",
        }

        if offset:
            params["offset"] = offset

        query = urllib.parse.urlencode(
            params
        )

        result = _request(
            "GET",
            f"{_master_table_url(table_key)}?{query}",
        )

        page = result.get(
            "records",
            [],
        )

        if isinstance(page, list):
            records.extend(
                record
                for record in page
                if isinstance(record, dict)
            )

        offset = result.get(
            "offset"
        )

        if not offset:
            break

    return records


def create_master_record(
    table_key: str,
    fields: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create one record in a configured master-tracker table.
    """

    if not isinstance(fields, dict):
        raise ValueError(
            "Airtable record fields must be a dictionary."
        )

    return _request(
        "POST",
        _master_table_url(table_key),
        {
            "records": [
                {
                    "fields": fields,
                }
            ]
        },
    )


def update_master_record(
    table_key: str,
    record_id: str,
    fields: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update one existing Airtable record.

    The return shape is normalized to contain a records list
    so callers can use the same result contract for create
    and update operations.
    """

    record_id = _text(record_id)

    if not record_id:
        raise ValueError(
            "Airtable update requires a record ID."
        )

    if not isinstance(fields, dict):
        raise ValueError(
            "Airtable record fields must be a dictionary."
        )

    encoded_record_id = urllib.parse.quote(
        record_id,
        safe="",
    )

    result = _request(
        "PATCH",
        (
            f"{_master_table_url(table_key)}/"
            f"{encoded_record_id}"
        ),
        {
            "fields": fields,
        },
    )

    if "records" in result:
        return result

    return {
        "records": [result],
    }


def sync_paxus_referral(
    referral: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create or update a Paxus referral in the Airtable
    Referrals table.

    This function only persists referral state.
    It does not qualify, approve, route, or submit referrals.
    """

    if not isinstance(referral, dict):
        raise ValueError(
            "Referral payload must be a dictionary."
        )

    fingerprint = _text(
        referral.get("fingerprint")
    )

    company = _text(
        referral.get("company")
    )

    if not fingerprint:
        raise ValueError(
            "Referral requires a fingerprint."
        )

    if not company:
        raise ValueError(
            "Referral requires a company."
        )

    placement_count = 0

    try:
        placement_count = int(
            referral.get(
                "placement_count",
                0,
            )
            or 0
        )

    except (TypeError, ValueError):
        placement_count = 0

    fields = {
        "Referral": fingerprint,
        "Company": company,
        "Opportunity": (
            f"{fingerprint}:Paxus"
        ),
        "Partner": "Paxus",
        "Submitted Date": (
            _text(
                referral.get(
                    "submitted_at"
                )
            )[:10]
            if referral.get(
                "referral_submitted"
            )
            else None
        ),
        "Partner Confirmed": bool(
            referral.get("paxus_accepted")
        ),
        "Partner Confirmation / ID": (
            _text(
                referral.get(
                    "referral_id"
                )
            )
            or None
        ),
        "Outcome": (
            "Won"
            if placement_count > 0
            else (
                "Accepted"
                if referral.get(
                    "paxus_accepted"
                )
                else (
                    "Submitted"
                    if referral.get(
                        "referral_submitted"
                    )
                    else "Pending"
                )
            )
        ),
        "Deal / Placement Value": referral.get(
            "placement_value"
        ),
        "Commission Rate": 0.25,
        "Expected Commission": referral.get(
            "expected_commission"
        ),
        "Payment Trigger": (
            "Client payment received"
            if referral.get(
                "client_payment_received"
            )
            else None
        ),
        "Expected Payment Date": (
            _text(
                referral.get(
                    "expected_payment_date"
                )
            )[:10]
            if referral.get(
                "expected_payment_date"
            )
            else None
        ),
        "Paid": bool(
            referral.get("paid")
        ),
        "Actual Payment": referral.get(
            "actual_payment"
        ),
        "Payment Date": (
            _text(
                referral.get(
                    "payment_date"
                )
            )[:10]
            if referral.get(
                "payment_date"
            )
            else None
        ),
        "Notes": _text(
            referral.get("notes")
        ) or None,
    }

    existing = find_master_records(
        "referrals",
        "Referral",
        fingerprint,
    )

    if existing:
        record_id = existing[0].get(
            "id"
        )

        if not record_id:
            raise AirtableSyncError(
                "Existing referral record has no Airtable record ID."
            )

        result = update_master_record(
            "referrals",
            record_id,
            {
                key: value
                for key, value in fields.items()
                if value is not None
            },
        )

        return {
            "status": "updated",
            "record": result[
                "records"
            ][0],
        }

    result = create_master_record(
        "referrals",
        {
            key: value
            for key, value in fields.items()
            if value is not None
        },
    )

    records = result.get(
        "records",
        [],
    )

    return {
        "status": "created",
        "record": (
            records[0]
            if records
            else None
        ),
    }


def sync_paxus_referral_state(
    referral: Any,
) -> Dict[str, Any]:
    if referral is None:
        raise ValueError(
            "Referral state is required."
        )

    return sync_paxus_referral(
        referral.__dict__
    )


def sync_outreach(
    outreach: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create or update a route-specific Outreach record.

    Uses Lead fingerprint + Route as the idempotency key.
    """

    if not isinstance(outreach, dict):
        raise ValueError(
            "Outreach payload must be a dictionary."
        )

    fingerprint = _text(
        outreach.get("fingerprint")
    )

    if not fingerprint:
        raise ValueError(
            "Outreach requires a fingerprint."
        )

    route = _text(
        outreach.get("route")
    )

    if not route:
        raise ValueError(
            "Outreach requires a route."
        )

    fields = {
        "Lead": fingerprint,
        "Route": route,
        "Company": _text(
            outreach.get("company")
        ),
        "Platform": _text(
            outreach.get("platform")
        ),
        "Follow-up Number": outreach.get(
            "follow_up_number",
            0,
        ),
        "Response": _text(
            outreach.get("response")
        ),
        "Outreach Status": _text(
            outreach.get(
                "outreach_status",
                "Not Contacted",
            )
        ),
        "Next Action Date": (
            _text(
                outreach.get(
                    "next_action_date"
                )
            )[:10]
            if outreach.get(
                "next_action_date"
            )
            else None
        ),
    }

    existing = find_master_records(
        "outreach",
        "Lead",
        fingerprint,
    )

    matching = [
        record
        for record in existing
        if _text(
            record.get(
                "fields",
                {},
            ).get("Route")
        ) == route
    ]

    clean_fields = {
        key: value
        for key, value in fields.items()
        if value is not None
    }

    if matching:
        record_id = matching[0].get(
            "id"
        )

        if not record_id:
            raise AirtableSyncError(
                "Existing outreach record has no Airtable ID."
            )

        result = update_master_record(
            "outreach",
            record_id,
            clean_fields,
        )

        return {
            "status": "updated",
            "record": result["records"][0],
        }

    result = create_master_record(
        "outreach",
        clean_fields,
    )

    records = result.get(
        "records",
        [],
    )

    return {
        "status": "created",
        "record": (
            records[0]
            if records
            else None
        ),
    }


def sync_followup(
    followup: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create or update a route-specific Follow-up record.

    Uses Lead fingerprint + Route + Follow-up Number as
    the idempotency key.
    """

    if not isinstance(followup, dict):
        raise ValueError(
            "Follow-up payload must be a dictionary."
        )

    fingerprint = _text(
        followup.get("fingerprint")
    )

    if not fingerprint:
        raise ValueError(
            "Follow-up requires a fingerprint."
        )

    route = _text(
        followup.get("route")
    )

    if not route:
        raise ValueError(
            "Follow-up requires a route."
        )

    follow_up_number = followup.get(
        "follow_up_number",
        0,
    )

    fields = {
        "Lead": fingerprint,
        "Route": route,
        "Company": _text(
            followup.get("company")
        ),
        "Due Date": _text(
            followup.get("due_date")
        ) or None,
        "Status": (
            _text(
                followup.get(
                    "status",
                    "Pending",
                )
            )
            or "Pending"
        ),
        "Follow-up Number": follow_up_number,
        "Notes": _text(
            followup.get("notes")
        ) or None,
    }

    existing = find_master_records(
        "followups",
        "Lead",
        fingerprint,
    )

    matching = []

    for record in existing:
        record_fields = record.get(
            "fields",
            {},
        )

        if not isinstance(
            record_fields,
            dict,
        ):
            continue

        existing_route = _text(
            record_fields.get("Route")
        )

        existing_number = record_fields.get(
            "Follow-up Number",
            0,
        )

        if (
            existing_route == route
            and str(existing_number)
            == str(follow_up_number)
        ):
            matching.append(record)

    clean_fields = {
        key: value
        for key, value in fields.items()
        if value is not None
    }

    if matching:
        record_id = matching[0].get(
            "id"
        )

        if not record_id:
            raise AirtableSyncError(
                "Existing follow-up record has no Airtable record ID."
            )

        result = update_master_record(
            "followups",
            record_id,
            clean_fields,
        )

        return {
            "status": "updated",
            "record": result[
                "records"
            ][0],
        }

    result = create_master_record(
        "followups",
        clean_fields,
    )

    records = result.get(
        "records",
        [],
    )

    return {
        "status": "created",
        "record": (
            records[0]
            if records
            else None
        ),
    }


def _source_platform(
    lead: Dict[str, Any],
) -> str:
    source = _text(
        lead.get("source")
    ).lower()

    if source in {
        "x",
        "twitter",
    }:
        return "X"

    if source == "linkedin":
        return "LinkedIn"

    if source in {
        "company",
        "company website",
        "career page",
    }:
        return "Company Website"

    if source in {
        "job board",
        "jobboard",
        "jobs",
    }:
        return "Job Board"

    if source == "news":
        return "News"

    return "Other"


def _signal_type(
    lead: Dict[str, Any],
) -> str:
    text = " ".join(
        [
            _text(
                lead.get("signal")
            ),
            _text(
                lead.get("evidence")
            ),
        ]
    ).lower()

    if any(
        phrase in text
        for phrase in (
            "ai",
            "automation",
            "machine learning",
            "ml",
        )
    ):
        return "AI / Automation Need"

    if any(
        phrase in text
        for phrase in (
            "mobile app",
            "ios",
            "android",
            "mobile developer",
        )
    ):
        return "Mobile App Need"

    if any(
        phrase in text
        for phrase in (
            "saas",
            "product build",
            "product development",
        )
    ):
        return "SaaS / Product Build"

    if any(
        phrase in text
        for phrase in (
            "staff augmentation",
            "contract developers",
            "contract engineers",
        )
    ):
        return "Staff Augmentation"

    if any(
        phrase in text
        for phrase in (
            "software",
            "developer",
            "engineer",
            "engineering",
            "tech",
            "technical",
        )
    ):
        return "Hiring Tech Talent"

    return "Other"


def _recommended_partner(
    lead: Dict[str, Any],
) -> str:
    routes = _normalize_routes(
        lead.get("potential_routes")
    )

    has_paxus = "Paxus" in routes
    has_shiftr = "Shiftr" in routes
    has_thorio = "Thorio" in routes

    if has_paxus and has_shiftr:
        return "Both"

    if has_shiftr:
        return "Shiftr"

    if has_paxus:
        return "Paxus"

    if has_thorio:
        return "Thorio"

    return "Review"


def _priority(
    lead: Dict[str, Any],
) -> str:
    value = _text(
        lead.get("priority")
    )

    if value in {
        "Hot",
        "Warm",
        "Cold",
    }:
        return value

    score = lead.get(
        "lead_score"
    )

    try:
        score = float(score)

    except (TypeError, ValueError):
        return "Cold"

    if score >= 80:
        return "Hot"

    if score >= 50:
        return "Warm"

    return "Cold"


def _review_status(
    lead: Dict[str, Any],
) -> str:
    qualified = lead.get(
        "qualified"
    )

    if qualified is True:
        return "Qualified"

    status = _text(
        lead.get("review_status")
    )

    if status in {
        "New",
        "Reviewing",
        "Qualified",
        "Rejected",
        "Added to Opportunities",
        "Contacted",
    }:
        return status

    return "Reviewing"


def _contact_method(
    lead: Dict[str, Any],
) -> Optional[str]:
    value = _text(
        lead.get("contact_method")
    )

    allowed = {
        "X",
        "Email",
        "LinkedIn",
        "Website",
        "Referral Introduction",
        "Other",
    }

    if value in allowed:
        return value

    if _text(
        lead.get("contact_email")
    ):
        return "Email"

    if _text(
        lead.get("linkedin_url")
    ):
        return "LinkedIn"

    return None


def _thorio_fit(
    lead: Dict[str, Any],
) -> Optional[str]:
    value = _text(
        lead.get("thorio_fit")
    )

    allowed = {
        "Not a Fit",
        "Single Listing - $99",
        "5-Posting Pack - $249",
        "Company Plan - $149/month",
        "Review",
    }

    if value in allowed:
        return value

    return None


def _evidence_status(
    lead: Dict[str, Any],
) -> str:
    value = _text(
        lead.get("evidence_status")
    )

    allowed = {
        "Verified",
        "Signal Only",
        "Needs Verification",
        "Disqualified",
    }

    if value in allowed:
        return value

    if lead.get("qualified") is True:
        return "Verified"

    return "Signal Only"


def _thorio_plan(
    lead: Dict[str, Any],
) -> Optional[str]:
    value = _text(
        lead.get(
            "thorio_plan_recommendation"
        )
    )

    allowed = {
        "Single Listing - $99",
        "5-Posting Pack - $249",
        "Company Plan - $149/month",
        "Review",
        "Not Applicable",
    }

    if value in allowed:
        return value

    return None


def _work_queue(
    lead: Dict[str, Any],
) -> Optional[str]:
    value = _text(
        lead.get("work_queue")
    )

    allowed = {
        "🔥 Contact Today",
        "🟣 Shiftr Verification",
        "🔵 Paxus Verification",
        "🟦 Thorio Sales",
        "📬 Follow Up",
        "🔎 Research",
        "💰 Revenue / Referral",
        "⚪ Watch",
        "🔴 Reject",
    }

    if value in allowed:
        return value

    routes = _normalize_routes(
        lead.get("potential_routes")
    )

    if "Shiftr" in routes:
        return "🟣 Shiftr Verification"

    if "Paxus" in routes:
        return "🔵 Paxus Verification"

    if "Thorio" in routes:
        return "🟦 Thorio Sales"

    return "🔎 Research"


def _outreach_status(
    lead: Dict[str, Any],
) -> str:
    value = _text(
        lead.get("outreach_status")
    )

    allowed = {
        "Not Contacted",
        "Approved to Contact",
        "Contacted",
        "Replied",
        "Interested",
        "Not Interested",
        "No Response",
        "Do Not Contact",
    }

    if value in allowed:
        return value

    return "Not Contacted"


def _normalize_routes(
    value: Any,
) -> List[str]:
    if value is None:
        return []

    if isinstance(value, str):
        value = [value]

    if not isinstance(
        value,
        (list, tuple, set),
    ):
        return []

    allowed = {
        "Paxus",
        "Shiftr",
        "Thorio",
    }

    result = []

    for route in value:
        normalized = _text(route)

        if (
            normalized in allowed
            and normalized not in result
        ):
            result.append(
                normalized
            )

    return result


def _normalize_lead(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Map local canonical lead state only to fields that
    actually exist in the inspected Lead Radar schema.

    Detailed Paxus lifecycle state remains local/canonical
    and is synchronized to the dedicated Referrals,
    Opportunities, and Commissions tables rather than
    inventing Paxus fields in Lead Radar.
    """

    company = _text(
        lead.get("company")
    )

    signal = _text(
        lead.get("signal")
    )

    lead_name = (
        company
        if company
        else _text(
            lead.get("source_id")
        )
    )

    fields: Dict[str, Any] = {
        "Lead": lead_name,
        "Company": company,
        "Signal": signal,
        "Source URL": _text(
            lead.get("url")
        ),
        "Source Platform": _source_platform(
            lead
        ),
        "Signal Type": _signal_type(
            lead
        ),
        "Recommended Partner": _recommended_partner(
            lead
        ),
        "Lead Score": lead.get(
            "lead_score",
            0,
        ),
        "Priority": _priority(
            lead
        ),
        "Decision Maker": _text(
            lead.get("person")
        ),
        "Title": _text(
            lead.get("contact_title")
        ),
        "Duplicate Key": _text(
            lead.get("fingerprint")
        ),
        "Review Status": _review_status(
            lead
        ),
        "Qualified Lead?": bool(
            lead.get(
                "qualified",
                False,
            )
        ),
        "Contact Ready": bool(
            lead.get(
                "contact_ready",
                False,
            )
        ),
        "Referral Submitted?": bool(
            lead.get(
                "referral_submitted",
                False,
            )
        ),
        "Budget Confirmed": bool(
            lead.get(
                "budget_confirmed",
                False,
            )
        ),
        "Need Confirmed": bool(
            lead.get(
                "need_confirmed",
                False,
            )
        ),
        "Decision Maker Confirmed": bool(
            lead.get(
                "decision_maker_confirmed",
                False,
            )
        ),
        "Timeline Confirmed": bool(
            lead.get(
                "timeline_confirmed",
                False,
            )
        ),
        "Qualification Score": lead.get(
            "qualification_score"
        ),
        "Reason Not Qualified": _text(
            lead.get(
                "reason_not_qualified"
            )
        ),
        "Thorio Outreach Ready": bool(
            lead.get(
                "thorio_outreach_ready",
                False,
            )
        ),
        "Remote Roles Verified": lead.get(
            "remote_roles_verified"
        ),
        "Thorio Revenue Potential": lead.get(
            "thorio_revenue_potential"
        ),
        "Why This Lead": _text(
            lead.get("evidence")
        ),
        "Evidence Status": _evidence_status(
            lead
        ),
        "Outreach Status": _outreach_status(
            lead
        ),
    }

    discovered_at = _text(
        lead.get("discovered_at")
    )

    if discovered_at:
        fields["Discovered Date"] = (
            discovered_at[:10]
        )

    contact_method = _contact_method(
        lead
    )

    if contact_method:
        fields["Contact Method"] = (
            contact_method
        )

    thorio_fit = _thorio_fit(
        lead
    )

    if thorio_fit:
        fields["Thorio Fit"] = (
            thorio_fit
        )

    thorio_plan = _thorio_plan(
        lead
    )

    if thorio_plan:
        fields[
            "Thorio Plan Recommendation"
        ] = thorio_plan

    work_queue = _work_queue(
        lead
    )

    if work_queue:
        fields["Work Queue"] = (
            work_queue
        )

    referral_id = _text(
        lead.get("referral_id")
    )

    if referral_id:
        fields[
            "Referral / Opportunity ID"
        ] = referral_id

    routes = _normalize_routes(
        lead.get("potential_routes")
    )

    if routes:
        fields["Applicable Routes"] = (
            routes
        )

    notes = _text(
        lead.get("notes")
    )

    if notes:
        fields["Notes"] = notes

    return {
        key: value
        for key, value in fields.items()
        if value is not None
    }


def push_lead(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    payload = {
        "records": [
            {
                "fields": _normalize_lead(
                    lead
                )
            }
        ]
    }

    return _request(
        "POST",
        _table_url(),
        payload,
    )


def find_by_fingerprint(
    fingerprint: str,
) -> List[Dict[str, Any]]:
    if not fingerprint:
        return []

    return find_master_records(
        "lead_radar",
        "Duplicate Key",
        fingerprint,
    )


def sync_lead_if_missing(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Upsert a canonical lead into Lead Radar.

    Existing records are updated only with machine-controlled
    discovery/evidence fields. Human-controlled lifecycle
    fields are never overwritten.

    A matching fingerprint always remains one Airtable record.
    """

    if not isinstance(lead, dict):
        raise ValueError(
            "Lead payload must be a dictionary."
        )

    fingerprint = _text(
        lead.get("fingerprint")
    )

    if fingerprint:
        existing = find_by_fingerprint(
            fingerprint
        )

        if existing:
            record_id = existing[0].get(
                "id"
            )

            if not record_id:
                raise AirtableSyncError(
                    "Existing Lead Radar record has no Airtable record ID."
                )

            normalized = _normalize_lead(
                lead
            )

            human_controlled_fields = {
                "Review Status",
                "Qualified Lead?",
                "Contact Ready",
                "Referral Submitted?",
                "Budget Confirmed",
                "Need Confirmed",
                "Decision Maker Confirmed",
                "Timeline Confirmed",
                "Qualification Score",
                "Reason Not Qualified",
                "Thorio Outreach Ready",
                "Outreach Status",
                "Contact Method",
                "Referral / Opportunity ID",
                "Work Queue",
                "Notes",
                "Thorio Fit",
                "Thorio Plan Recommendation",
            }

            machine_fields = {
                key: value
                for key, value in normalized.items()
                if key not in human_controlled_fields
            }

            result = update_master_record(
                "lead_radar",
                record_id,
                machine_fields,
            )

            records = result.get(
                "records",
                [],
            )

            return {
                "status": "updated",
                "record": (
                    records[0]
                    if records
                    else existing[0]
                ),
            }

    fields = _normalize_lead(
        lead
    )

    result = create_master_record(
        "lead_radar",
        fields,
    )

    records = result.get(
        "records",
        [],
    )

    return {
        "status": "created",
        "record": (
            records[0]
            if records
            else None
        ),
    }


def sync_queue(
    leads: List[Dict[str, Any]],
) -> Dict[str, Any]:
    synced = []
    already_exists = []
    failed = []

    for lead in leads:
        try:
            result = sync_lead_if_missing(
                lead
            )

            if result["status"] == "created":
                synced.append(lead)

            else:
                already_exists.append(
                    lead
                )

        except AirtableSyncError as exc:
            failed.append(
                {
                    "lead": lead,
                    "error": str(exc),
                }
            )

    return {
        "synced": synced,
        "already_exists": already_exists,
        "failed": failed,
        "synced_count": len(synced),
        "already_exists_count": len(already_exists),
        "failed_count": len(failed),
    }


if __name__ == "__main__":
    print(
        "Airtable sync module loaded."
    )
