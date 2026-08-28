import os
from typing import List, Tuple

from .free_sources import FreeJobSource
from .sources import LeadSource
from .web_source_config import create_web_source_from_env


# Free/public discovery catalog.
#
# These are public web pages, not paid APIs.
# Each source is independent. A failure in one source is handled
# by the existing service boundary without stopping other sources.
FREE_SOURCE_CATALOG: Tuple[Tuple[str, str], ...] = (
    (
        "NoDesk",
        "https://nodesk.co/remote-jobs/",
    ),
    (
        "Welcome to the Jungle",
        "https://www.welcometothejungle.com/en/pages/jobs",
    ),
    (
        "EURES",
        "https://europa.eu/eures/portal/jv-se/home?lang=en&pageCode=find_a_job",
    ),
    (
        "Remotive",
        "https://remotive.com/",
    ),
    (
        "Working Nomads",
        "https://www.workingnomads.com/jobs",
    ),
    (
        "We Work Remotely",
        "https://weworkremotely.com/remote-jobs/all-jobs",
    ),
    (
        "Remote OK",
        "https://remoteok.com/",
    ),
    (
        "Jobspresso",
        "https://jobspresso.co/jobs/",
    ),
    (
        "Landing Jobs",
        "https://landing.jobs/",
    ),
    (
        "EU Remote Jobs",
        "https://euremotejobs.com/",
    ),
    (
        "WorkWave",
        "https://jobs.lever.co/workwave/?workplaceType=remote",
    ),
    (
        "AI Jobs",
        "https://ai-jobs.net/",
    ),
    (
        "Total",
        "https://www.totaljobs.com/",
    ),
    (
        "FlexJobs",
        "https://www.flexjobs.com/",
    ),
    (
        "US Remotely",
        "https://usremotely.com/",
    ),
    (
        "Rocketship",
        "https://rocketship.fm/jobs",
    ),
    (
        "JobFill.AI",
        "https://jobfill.ai/",
    ),
    (
        "Remote Woman",
        "https://remotewoman.com/",
    ),
    (
        "Wellfound",
        "https://wellfound.com/remote",
    ),
)


# Preserve the existing public name catalog contract.
FREE_SOURCE_NAMES = tuple(
    name
    for name, _url in FREE_SOURCE_CATALOG
)


def _free_sources_enabled() -> bool:
    """
    Determine whether the free public source catalog is active.

    Default is disabled so existing installations and tests that
    intentionally run without configured sources remain unchanged.

    The production workflow can enable this with:

        LEAD_ENGINE_FREE_SOURCES_ENABLED=true
    """

    value = os.getenv(
        "LEAD_ENGINE_FREE_SOURCES_ENABLED",
        "",
    ).strip().lower()

    return value in {
        "1",
        "true",
        "yes",
        "on",
    }


def _free_source_timeout() -> int:
    """
    Return the timeout used by free public source adapters.
    """

    raw = os.getenv(
        "LEAD_ENGINE_FREE_SOURCE_TIMEOUT",
        "20",
    ).strip()

    try:
        timeout = int(raw)
    except ValueError:
        return 20

    if timeout <= 0:
        return 20

    return timeout


def _free_source_instance(
    name: str,
    url: str,
) -> LeadSource:
    """
    Build one independent free source adapter.

    FreeJobSource exposes the same collect() contract used by
    SourceRunner, while keeping each source's identity and URL
    separate.
    """

    return FreeJobSource(
        name=name,
        url=url,
        timeout=_free_source_timeout(),
    )


def configured_sources() -> List[LeadSource]:
    """
    Return all currently active lead-discovery sources.

    Sources are deliberately independent:

        free source -> normalized records -> SourceRunner -> pipeline

    The existing optional JSON source remains supported for
    backward compatibility.

    Free public sources are activated only when explicitly enabled.
    """

    sources: List[LeadSource] = []

    # Preserve the existing external JSON source when explicitly
    # configured.
    web_source = create_web_source_from_env()

    if web_source is not None:
        sources.append(web_source)

    # Activate the free public catalog independently.
    if _free_sources_enabled():
        for name, url in FREE_SOURCE_CATALOG:
            sources.append(
                _free_source_instance(
                    name=name,
                    url=url,
                )
            )

    return sources


def available_free_sources() -> List[str]:
    """
    Return every source currently represented in the free catalog.

    This is metadata only. Activation is controlled separately by
    LEAD_ENGINE_FREE_SOURCES_ENABLED.
    """

    return list(FREE_SOURCE_NAMES)


if __name__ == "__main__":
    print(
        "Lead source registry loaded."
    )

    print(
        f"Free source catalog: "
        f"{len(FREE_SOURCE_CATALOG)} sources"
    )

    print(
        f"Free sources enabled: "
        f"{_free_sources_enabled()}"
    )

    print(
        f"Configured source count: "
        f"{len(configured_sources())}"
    )
