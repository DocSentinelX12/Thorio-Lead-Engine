import os
from typing import Optional

from .web_source import WebLeadSource


def create_web_source_from_env() -> Optional[WebLeadSource]:
    """
    Create the web lead source when THORIO_LEAD_SOURCE_URL
    is configured.

    Returns None when no source URL is configured.
    """

    url = os.getenv("THORIO_LEAD_SOURCE_URL", "").strip()

    if not url:
        return None

    timeout_raw = os.getenv(
        "THORIO_LEAD_SOURCE_TIMEOUT",
        "20",
    ).strip()

    try:
        timeout = int(timeout_raw)
    except ValueError:
        raise ValueError(
            "THORIO_LEAD_SOURCE_TIMEOUT must be an integer."
        )

    if timeout < 1:
        raise ValueError(
            "THORIO_LEAD_SOURCE_TIMEOUT must be greater than 0."
        )

    return WebLeadSource(
        url=url,
        timeout=timeout,
    )
