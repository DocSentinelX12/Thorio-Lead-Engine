from __future__ import annotations

from dataclasses import replace
from typing import Callable, Tuple

from .source_definition import SourceDefinition


# Only sources proven to need a configuration correction belong here.
# Healthy sources must not be altered by this layer.
_SOURCE_OVERRIDES = {
    "The Muse": {"url": "https://www.themuse.com/api/public/jobs?page=1", "page_start": 1},
    "EURES": {"enabled": False, "allowed_for_thorio": False},
    "Jobicy": {"collector_type": "rss", "url": "https://jobicy.com/jobs/feed", "pagination_type": "none", "max_pages": 1, "max_requests": 1, "max_records": 200},
    "RemoteJobs.org": {"collector_type": "json", "url": "https://remotejobs.org/api/v1/jobs?limit=50", "record_path": "data", "title_field": "title", "company_field": "company.name", "description_field": "description", "url_field": "url", "source_id_field": "id", "location_field": "location", "pagination_type": "offset", "offset_parameter": "offset", "offset_start": 0, "offset_step": 50, "page_limit": 50, "max_pages": 10, "max_requests": 10, "max_records": 500},
    "Remote First Jobs": {"collector_type": "json", "url": "https://remotefirstjobs.com/api/search-jobs", "record_path": "jobs", "title_field": "title", "company_field": "company_name", "description_field": "description", "url_field": "url", "source_id_field": "id", "location_field": "locations", "pagination_type": "page", "page_parameter": "page", "page_start": 0, "page_limit": 100, "max_pages": 5, "max_requests": 5, "max_records": 500},
    "Arbeitnow": {"collector_type": "json", "url": "https://www.arbeitnow.com/api/job-board-api", "record_path": "data", "title_field": "title", "company_field": "company_name", "description_field": "description", "url_field": "url", "source_id_field": "slug", "location_field": "location", "pagination_type": "page", "page_parameter": "page", "page_start": 1, "max_pages": 10, "max_requests": 10, "max_records": 500},
    "Nomado24": {"collector_type": "json", "url": "https://api.nomado24.de/api/public/v1/jobs?per_page=100&language=en", "record_path": "data", "title_field": "title", "company_field": "companyName", "description_field": "description", "url_field": "url", "source_id_field": "slug", "location_field": "location", "pagination_type": "page", "page_parameter": "page", "page_start": 1, "page_limit": 100, "max_pages": 10, "max_requests": 10, "max_records": 1000},
    "Remotive": {"collector_type": "json", "url": "https://remotive.com/api/remote-jobs", "record_path": "jobs", "title_field": "title", "company_field": "company_name", "description_field": "description", "url_field": "url", "source_id_field": "id", "location_field": "candidate_required_location", "pagination_type": "none", "max_pages": 1, "max_requests": 1, "max_records": 500},
    "Working Nomads": {"collector_type": "json", "url": "https://www.workingnomads.com/api/exposed_jobs/", "pagination_type": "none", "max_pages": 1, "max_requests": 1, "max_records": 500},
    # Landing Jobs is preserved as a historical source identity. Its public Atom feed currently returns HTTP 403 from CI, so it is not allowed for Thorio until a live endpoint is verified.
    "Landing Jobs": {"collector_type": "atom", "url": "https://landing.jobs/feed?remote=true", "pagination_type": "none", "max_pages": 1, "max_requests": 1, "max_records": 55, "allowed_for_thorio": False},
    "WorkWave": {"collector_type": "json", "url": "https://api.lever.co/v0/postings/workwave?mode=json", "record_path": "", "title_field": "text", "company_field": "company", "description_field": "descriptionPlain", "url_field": "hostedUrl", "source_id_field": "id", "location_field": "categories.location", "pagination_type": "none", "max_pages": 1, "max_requests": 1, "max_records": 500, "metadata": {"default_company": "WorkWave"}},
    "NoDesk": {"collector_type": "html", "url": "https://nodesk.co/remote-jobs/", "pagination_type": "none", "max_pages": 1, "max_requests": 1, "max_records": 500},
    "We Work Remotely": {"collector_type": "rss", "url": "https://weworkremotely.com/remote-jobs.rss", "pagination_type": "none", "max_pages": 1, "max_requests": 1, "max_records": 500},
    "Jobspresso": {"collector_type": "rss", "url": "https://jobspresso.co/?feed=job_feed", "pagination_type": "none", "max_pages": 1, "max_requests": 1, "max_records": 500},
    "US Remotely": {"provider": "USA Remote Work", "collector_type": "html", "url": "https://www.usaremotework.com/jobs", "pagination_type": "none", "max_pages": 1, "max_requests": 1, "max_records": 500, "attribution_required": False, "attribution_url": "https://www.usaremotework.com/", "allowed_for_thorio": True},
    "Rocketship": {"provider": "Remote Landers", "collector_type": "json", "url": "https://remotelanders.com/api/jobs?limit=100&page=1", "record_path": "jobs", "title_field": "title", "company_field": "company", "description_field": None, "url_field": "applyUrl", "source_id_field": "slug", "location_field": "location", "pagination_type": "page", "page_parameter": "page", "page_start": 1, "page_limit": 100, "max_pages": 5, "max_requests": 5, "max_records": 500, "attribution_required": True, "attribution_url": "https://remotelanders.com/", "allowed_for_thorio": True},
}


def _apply_overrides(definitions: Tuple[SourceDefinition, ...]) -> Tuple[SourceDefinition, ...]:
    updated = []
    for definition in definitions:
        override = _SOURCE_OVERRIDES.get(definition.name)
        if override is None:
            updated.append(definition)
            continue
        values = dict(override)
        if "metadata" in values:
            values["metadata"] = {**definition.metadata, **values["metadata"]}
        updated.append(replace(definition, **values))
    return tuple(updated)


def apply_source_overrides(definitions: Tuple[SourceDefinition, ...]) -> Tuple[SourceDefinition, ...]:
    return _apply_overrides(definitions)


def install() -> None:
    """Apply only explicit, source-specific configuration corrections."""
    from . import source_registry

    original: Callable[[], Tuple[SourceDefinition, ...]] = source_registry._load_free_source_catalog
    if getattr(original, "_thorio_source_overrides", False):
        return

    def patched() -> Tuple[SourceDefinition, ...]:
        return tuple(
            definition
            for definition in _apply_overrides(original())
            if definition.enabled and definition.allowed_for_thorio
        )

    patched._thorio_source_overrides = True
    source_registry._load_free_source_catalog = patched
