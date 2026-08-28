from typing import List

from .sources import LeadSource
from .web_source_config import create_web_source_from_env


# Free/public discovery sources.
#
# These are source identities, not paid APIs.
# Individual adapters can be added behind the same LeadSource
# interface without changing the downstream pipeline.
FREE_SOURCE_NAMES = (
    "NoDesk",
    "Welcome to the Jungle",
    "EURES",
    "Remotive",
    "Working Nomads",
    "We Work Remotely",
    "Remote OK",
    "Jobspresso",
    "Landing Jobs",
    "EU Remote Jobs",
    "WorkWave",
    "AI Jobs",
    "Total",
    "FlexJobs",
    "US Remotely",
    "Rocketship",
    "JobFill.AI",
    "Remote Woman",
    "Wellfound",
)


def configured_sources() -> List[LeadSource]:
    """
    Return all currently configured lead-discovery sources.

    The existing external JSON source remains supported for
    backward compatibility.

    Free job-board adapters will be registered through this
    same source interface as they are implemented.

    Sources remain independent from the lead pipeline:
        source -> normalized records -> SourceRunner -> pipeline
    """

    sources: List[LeadSource] = []

    # Preserve the existing external JSON source when explicitly
    # configured. This is optional and is no longer the intended
    # primary discovery mechanism.
    web_source = create_web_source_from_env()

    if web_source is not None:
        sources.append(web_source)

    return sources


def available_free_sources() -> List[str]:
    """
    Return the names of the free discovery sources planned for
    the source adapter catalog.

    This does not activate a source before its adapter exists.
    """

    return list(FREE_SOURCE_NAMES)


if __name__ == "__main__":
    print(
        "Lead source registry loaded."
    )
    print(
        f"Free source catalog: "
        f"{len(FREE_SOURCE_NAMES)} sources"
    )
