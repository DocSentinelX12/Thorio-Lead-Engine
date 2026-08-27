import json
from pathlib import Path
from typing import Any, Dict, Iterable

from .sources import LeadSource


class JsonLeadSource(LeadSource):
    """
    Lead source backed by a local JSON file.

    The file must contain either:
    - a JSON array of lead objects, or
    - an object containing a "leads" array.

    No network access is performed.
    """

    name = "json"

    def __init__(self, path: str):
        self.path = Path(path)

    def collect(self) -> Iterable[Dict[str, Any]]:
        if not self.path.exists():
            raise FileNotFoundError(
                f"Lead source file not found: {self.path}"
            )

        with self.path.open(
            "r",
            encoding="utf-8",
        ) as handle:
            payload = json.load(handle)

        if isinstance(payload, list):
            leads = payload

        elif isinstance(payload, dict):
            leads = payload.get("leads")

        else:
            raise ValueError(
                "JSON lead source must contain a list of leads."
            )

        if not isinstance(leads, list):
            raise ValueError(
                "JSON lead source must contain a 'leads' list."
            )

        for lead in leads:
            if not isinstance(lead, dict):
                raise ValueError(
                    "Every JSON lead must be an object."
                )

        return leads


if __name__ == "__main__":
    print(
        "JSON lead source loaded."
    )
