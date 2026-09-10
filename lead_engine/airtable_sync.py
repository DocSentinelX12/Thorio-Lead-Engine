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
AIRTABLE_REQUEST_TIMEOUT = 60.0


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
                timeout=AIRTABLE_REQUEST_TIMEOUT,
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
    "followups",
    "paxus_referrals",
    "commissions",
}
