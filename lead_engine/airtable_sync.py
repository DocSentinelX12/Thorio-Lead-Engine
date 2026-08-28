import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


AIRTABLE_API_URL = "https://api.airtable.com/v0"

BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = os.getenv("AIRTABLE_LEAD_TABLE", "Lead Radar")
API_KEY = os.getenv("AIRTABLE_API_KEY")

AIRTABLE_MAX_RETRIES = 3
AIRTABLE_INITIAL_BACKOFF = 1.0
AIRTABLE_MAX_BACKOFF = 30.0
AIRTABLE_BATCH_SIZE = 10


class AirtableSyncError(Exception):
    """Raised when Airtable synchronization fails."""


def _require_config() -> None:
    missing = []

    if not BASE_ID:
        missing.append("AIRTABLE_BASE_ID")

    if not API_KEY:
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

    headers = {
        "Authorization": f"Bearer {API_KEY}",
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
    return (
        f"{AIRTABLE_API_URL}/"
        f"{BASE_ID}/"
        f"{urllib.parse.quote(TABLE_NAME, safe='')}"
    )


def _text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _source_platform(
    lead: Dict[str, Any],
) -> str:
    source = _text(
        lead.get("source")
    ).lower()

    if source in {"x", "twitter"}:
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
            _text(lead.get("signal")),
            _text(lead.get("evidence")),
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
    routes = lead.get("potential_routes")

    if isinstance(routes, str):
        routes = [routes]

    if not isinstance(routes, list):
        routes = []

    normalized = {
        _text(route)
        for route in routes
    }

    if {"Paxus", "Shiftr"} <= normalized:
        return "Both"

    if "Shiftr" in normalized:
        return "Shiftr"

    if "Paxus" in normalized:
        return "Paxus"

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

    score = lead.get("lead_score")

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
    qualified = lead.get("qualified")

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
        lead.get("thorio_plan_recommendation")
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

    routes = lead.get("potential_routes")

    if isinstance(routes, str):
        routes = [routes]

    if isinstance(routes, list):
        routes = {
            _text(route)
            for route in routes
        }

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

    if not isinstance(value, list):
        return []

    allowed = {
        "Paxus",
        "Shiftr",
        "Thorio",
    }

    return [
        _text(route)
        for route in value
        if _text(route) in allowed
    ]


def _normalize_lead(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
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
            lead.get("qualified", False)
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
        "Work Queue": _work_queue(
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
        fields["Discovered Date"] = discovered_at

    contact_method = _contact_method(
        lead
    )

    if contact_method:
        fields["Contact Method"] = contact_method

    thorio_fit = _thorio_fit(
        lead
    )

    if thorio_fit:
        fields["Thorio Fit"] = thorio_fit

    thorio_plan = _thorio_plan(
        lead
    )

    if thorio_plan:
        fields[
            "Thorio Plan Recommendation"
        ] = thorio_plan

    notes = _text(
        lead.get("notes")
    )

    if notes:
        fields["Notes"] = notes

    routes = _normalize_routes(
        lead.get("potential_routes")
    )

    if routes:
        fields["Applicable Routes"] = routes

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


def push_leads(
    leads: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Create multiple new Airtable records in supported batches.

    Airtable accepts up to 10 records per create request.
    This function intentionally does not perform duplicate
    checking. Duplicate checking remains the responsibility
    of sync_queue() before this function is called.
    """

    if not leads:
        return {
            "records": []
        }

    all_records = []

    for start in range(
        0,
        len(leads),
        AIRTABLE_BATCH_SIZE,
    ):
        batch = leads[
            start:start + AIRTABLE_BATCH_SIZE
        ]

        payload = {
            "records": [
                {
                    "fields": _normalize_lead(
                        lead
                    )
                }
                for lead in batch
            ]
        }

        result = _request(
            "POST",
            _table_url(),
            payload,
        )

        records = result.get(
            "records",
            [],
        )

        if isinstance(records, list):
            all_records.extend(records)

    return {
        "records": all_records
    }


def find_by_fingerprint(
    fingerprint: str,
) -> List[Dict[str, Any]]:
    if not fingerprint:
        return []

    escaped = fingerprint.replace(
        "\\",
        "\\\\",
    ).replace(
        '"',
        '\\"',
    )

    formula = (
        f'{{Duplicate Key}}="{escaped}"'
    )

    params = urllib.parse.urlencode(
        {
            "filterByFormula": formula,
            "pageSize": "10",
        }
    )

    result = _request(
        "GET",
        f"{_table_url()}?{params}",
    )

    return result.get(
        "records",
        [],
    )


def sync_lead_if_missing(
    lead: Dict[str, Any],
) -> Dict[str, Any]:
    fingerprint = _text(
        lead.get("fingerprint")
    )

    if fingerprint:
        existing = find_by_fingerprint(
            fingerprint
        )

        if existing:
            return {
                "status": "already_exists",
                "record": existing[0],
            }

    result = push_lead(
        lead
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


def _queue_key(
    lead: Dict[str, Any],
) -> str:
    """
    Return the safest local key for preventing duplicate
    work within one sync_queue() call.

    Fingerprint is preferred because it is the engine's
    canonical duplicate key. Leads without a fingerprint
    are intentionally not collapsed here.
    """

    return _text(
        lead.get("fingerprint")
    )


def sync_queue(
    leads: List[Dict[str, Any]],
) -> Dict[str, Any]:
    synced = []
    already_exists = []
    failed = []

    # Remove duplicate fingerprints from the incoming queue
    # before making any Airtable requests. Leads without a
    # fingerprint remain independent and are still processed.
    unique_leads = []
    seen_fingerprints = set()

    for lead in leads:
        fingerprint = _queue_key(
            lead
        )

        if fingerprint:
            if fingerprint in seen_fingerprints:
                already_exists.append(
                    lead
                )
                continue

            seen_fingerprints.add(
                fingerprint
            )

        unique_leads.append(
            lead
        )

    # Preserve the existing Airtable duplicate check.
    # We do this before batching creates so that batching
    # cannot bypass the existing dedupe protection.
    to_create = []

    for lead in unique_leads:
        try:
            fingerprint = _text(
                lead.get("fingerprint")
            )

            if fingerprint:
                existing = find_by_fingerprint(
                    fingerprint
                )

                if existing:
                    already_exists.append(
                        lead
        )
