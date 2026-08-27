import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


AIRTABLE_API_URL = "https://api.airtable.com/v0"

BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TABLE_NAME = os.getenv("AIRTABLE_LEAD_TABLE", "Lead Radar")
API_KEY = os.getenv("AIRTABLE_API_KEY")


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

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}

    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise AirtableSyncError(
            f"Airtable API error {exc.code}: {body}"
        ) from exc

    except urllib.error.URLError as exc:
        raise AirtableSyncError(
            f"Airtable connection failed: {exc.reason}"
        ) from exc


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


def _source_platform(lead: Dict[str, Any]) -> str:
    source = _text(lead.get("source")).lower()

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


def _signal_type(lead: Dict[str, Any]) -> str:
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


def _priority(lead: Dict[str, Any]) -> str:
    value = _text(lead.get("priority"))

    if value in {"Hot", "Warm", "Cold"}:
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


def _review_status(lead: Dict[str, Any]) -> str:
    qualified = lead.get("qualified")

    if qualified is True:
        return "Qualified"

    status = _text(lead.get("review_status"))

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


def _contact_method(lead: Dict[str, Any]) -> Optional[str]:
    value = _text(lead.get("contact_method"))

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

    if _text(lead.get("contact_email")):
        return "Email"

    if _text(lead.get("linkedin_url")):
        return "LinkedIn"

    return None


def _thorio_fit(lead: Dict[str, Any]) -> Optional[str]:
    value = _text(lead.get("thorio_fit"))

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
    value = _text(lead.get("evidence_status"))

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
    value = _text(lead.get("work_queue"))

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
    value = _text(lead.get("outreach_status"))

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
    company = _text(lead.get("company"))
    signal = _text(lead.get("signal"))

    lead_name = (
        company
        if company
        else _text(lead.get("source_id"))
    )

    fields: Dict[str, Any] = {
        "Lead": lead_name,
        "Company": company,
        "Signal": signal,
        "Source URL": _text(lead.get("url")),
        "Source Platform": _source_platform(lead),
        "Signal Type": _signal_type(lead),
        "Recommended Partner": _recommended_partner(lead),
        "Lead Score": lead.get("lead_score", 0),
        "Priority": _priority(lead),
        "Decision Maker": _text(lead.get("person")),
        "Title": _text(lead.get("contact_title")),
        "Duplicate Key": _text(lead.get("fingerprint")),
        "Review Status": _review_status(lead),
        "Qualified Lead?": bool(
            lead.get("qualified", False)
        ),
        "Budget Confirmed": bool(
            lead.get("budget_confirmed", False)
        ),
        "Need Confirmed": bool(
            lead.get("need_confirmed", False)
        ),
        "Decision Maker Confirmed": bool(
            lead.get("decision_maker_confirmed", False)
        ),
        "Timeline Confirmed": bool(
            lead.get("timeline_confirmed", False)
        ),
        "Qualification Score": lead.get(
            "qualification_score"
        ),
        "Reason Not Qualified": _text(
            lead.get("reason_not_qualified")
        ),
        "Contact Ready": bool(
            lead.get("contact_ready", False)
        ),
        "Referral Submitted?": bool(
            lead.get("referral_submitted", False)
        ),
        "Thorio Outreach Ready": bool(
            lead.get("thorio_outreach_ready", False)
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
        "Evidence Status": _evidence_status(lead),
        "Work Queue": _work_queue(lead),
        "Outreach Status": _outreach_status(lead),
    }

    discovered_at = _text(
        lead.get("discovered_at")
    )

    if discovered_at:
        fields["Discovered Date"] = discovered_at

    contact_method = _contact_method(lead)

    if contact_method:
        fields["Contact Method"] = contact_method

    thorio_fit = _thorio_fit(lead)

    if thorio_fit:
        fields["Thorio Fit"] = thorio_fit

    thorio_plan = _thorio_plan(lead)

    if thorio_plan:
        fields["Thorio Plan Recommendation"] = (
            thorio_plan
        )

    notes = _text(lead.get("notes"))

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
                "fields": _normalize_lead(lead)
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

    return result.get("records", [])


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

    result = push_lead(lead)

    records = result.get("records", [])

    return {
        "status": "created",
        "record": records[0] if records else None,
    }


def sync_queue(
    leads: List[Dict[str, Any]],
) -> Dict[str, Any]:
    synced = []
    already_exists = []
    failed = []

    for lead in leads:
        try:
            result = sync_lead_if_missing(lead)

            if result["status"] == "created":
                synced.append(lead)
            else:
                already_exists.append(lead)

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
    print("Airtable sync module loaded.")
