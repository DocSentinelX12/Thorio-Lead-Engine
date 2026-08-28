from typing import List

from .sources import LeadSource
from .web_source_config import create_web_source_from_env


def configured_sources() -> List[LeadSource]:
    """
    Return all enabled lead-discovery sources.

    Sources are opt-in. An unconfigured source is not added.
    """

    sources: List[LeadSource] = []

    web_source = create_web_source_from_env()

    if web_source is not None:
        sources.append(web_source)

    return sources
