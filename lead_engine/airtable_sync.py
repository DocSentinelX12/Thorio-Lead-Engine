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


def _normalize_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert the canonical local lead record into Airtable fields.

    The local Lead model remains the source of truth.
    Qualification remains a human decision.
    """

    fields: Dict[str, Any] = {}

    mapping = {
        "source": "Source",
        "source_id": "Source ID",
        "url": "Source URL",
        "company": "Company",
        "person": "Decision Maker",
        "signal": "Signal",
        "discovered_at": "Discovered Date",
        "route": "Recommended Partner",
        "potential_routes": "Potential Partners",
        "status": "Review Status",
        "evidence": "Evidence",
        "possible_duplicate": "Possible Duplicate",
        "fingerprint": "Duplicate Key",
    }

    for local_name, airtable_name in mapping.items():
        value = lead.get(local_name)

        if value is not None:
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)

            fields[airtable_name] = value

    return fields


def push_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Push one local lead into Airtable."""

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


def push_leads(leads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Push local leads to Airtable in batches of 10."""

    if not leads:
        return {"records": []}

    results = []

    for start in range(0, len(leads), 10):
        batch = leads[start:start + 10]

        payload = {
            "records": [
                {
                    "fields": _normalize_lead(lead)
                }
                for lead in batch
            ]
        }

        result = _request(
            "POST",
            _table_url(),
            payload,
        )

        results.extend(result.get("records", []))

    return {
        "records": results,
        "synced_count": len(results),
    }


def find_by_fingerprint(
    fingerprint: str,
) -> List[Dict[str, Any]]:
    """Find an existing Airtable lead using the canonical fingerprint."""

    if not fingerprint:
        return []

    escaped_fingerprint = fingerprint.replace('"', '\\"')

    formula = f'{{Duplicate Key}}="{escaped_fingerprint}"'

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
    """
    Create a lead only if its canonical fingerprint is not
    already present in Airtable.
    """

    fingerprint = lead.get("fingerprint")

    if fingerprint:
        existing = find_by_fingerprint(fingerprint)

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
    """Synchronize local leads without losing failed records."""

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
    print(
        "Airtable sync module loaded. "
        "Use sync_queue() or sync_lead_if_missing() from the lead engine."
    )
