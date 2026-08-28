from typing import Any, Dict, Iterable, List
from urllib.request import Request, urlopen


class WebLeadSource:
    """
    Simple HTTP source adapter.

    Fetches a JSON endpoint containing a list of standardized
    lead records. Discovery remains separate from qualification.
    """

    name = "web"

    def __init__(
        self,
        url: str,
        timeout: int = 20,
    ):
        self.url = url
        self.timeout = timeout

    def collect(self) -> Iterable[Dict[str, Any]]:
        request = Request(
            self.url,
            headers={
                "User-Agent": "Thorio-Lead-Engine/1.0",
                "Accept": "application/json",
            },
        )

        with urlopen(
            request,
            timeout=self.timeout,
        ) as response:
            import json

            payload = json.loads(
                response.read().decode("utf-8")
            )

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

        return leads


def collect_from_url(
    url: str,
    timeout: int = 20,
) -> List[Dict[str, Any]]:
    """
    Convenience function for fetching leads from a JSON URL.
    """

    return list(
        WebLeadSource(
            url=url,
            timeout=timeout,
        ).collect()
    )
