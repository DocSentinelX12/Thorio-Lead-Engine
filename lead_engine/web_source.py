import json
from typing import Any, Dict, Iterable, List
from urllib.request import Request

from .http_retry import HTTPRetryError, fetch_url


class WebLeadSource:
    """HTTP source adapter for a JSON lead feed."""

    name = "web"

    def __init__(
        self,
        url: str,
        timeout: int = 20,
    ):
        if not isinstance(url, str) or not url.strip():
            raise ValueError("Web source URL is required.")

        if not isinstance(timeout, int) or isinstance(timeout, bool):
            raise ValueError(
                "Web source timeout must be an integer."
            )

        if timeout <= 0:
            raise ValueError(
                "Web source timeout must be positive."
            )

        self.url = url.strip()
        self.timeout = timeout

    def collect(self) -> Iterable[Dict[str, Any]]:
        request = Request(
            self.url,
            headers={
                "User-Agent": "Thorio-Lead-Engine/1.0",
                "Accept": "application/json",
            },
        )

        try:
            raw = fetch_url(
                request,
                timeout=self.timeout,
            )

        except HTTPRetryError as exc:
            raise ValueError(
                f"Web source request failed: {exc}"
            ) from exc

        try:
            payload = json.loads(
                raw.decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "Web source must return valid UTF-8 JSON."
            ) from exc

        if isinstance(payload, dict):
            leads = payload.get("leads", [])
        elif isinstance(payload, list):
            leads = payload
        else:
            raise ValueError(
                "Web source must return a JSON list "
                "or an object containing 'leads'."
            )

        if not isinstance(leads, list):
            raise ValueError(
                "Web source 'leads' value must be a list."
            )

        for index, lead in enumerate(leads):
            if not isinstance(lead, dict):
                raise ValueError(
                    f"Web source lead at index {index} "
                    "must be an object."
                )

        return leads


def collect_from_url(
    url: str,
    timeout: int = 20,
) -> List[Dict[str, Any]]:
    """Fetch and validate leads from a JSON URL."""

    return list(
        WebLeadSource(
            url=url,
            timeout=timeout,
        ).collect()
    )
