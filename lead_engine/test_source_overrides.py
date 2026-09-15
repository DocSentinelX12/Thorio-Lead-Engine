from .source_registry import _load_free_source_catalog
from .source_overrides import _SOURCE_OVERRIDES, _apply_overrides


_ACTIVE_SOURCES = {
    "Himalayas",
    "Remote OK",
    "Airbnb",
    "Anthropic",
    "Airtable",
    "Asana",
    "Brex",
    "Cloudflare",
    "Coinbase",
    "Datadog",
    "Discord",
    "Dropbox",
    "Figma",
    "GitLab",
    "Instacart",
    "Lyft",
    "Netlify",
    "Stripe",
}

_EXPECTED_BROKEN_SOURCE_OVERRIDES = {
    "The Muse",
    "Remotive",
    "Jobicy",
    "RemoteJobs.org",
    "Remote First Jobs",
    "Arbeitnow",
    "Nomado24",
    "Working Nomads",
    "Landing Jobs",
    "WorkWave",
    "NoDesk",
    "We Work Remotely",
    "Jobspresso",
    "US Remotely",
    "Rocketship",
    "EURES",
}


def test_only_explicit_broken_sources_are_overridden():
    assert set(_SOURCE_OVERRIDES) == _EXPECTED_BROKEN_SOURCE_OVERRIDES
    assert not (set(_SOURCE_OVERRIDES) & _ACTIVE_SOURCES)


def test_the_muse_uses_current_api_page_one():
    catalog = _load_free_source_catalog()
    muse = next(
        definition
        for definition in catalog
        if definition.name == "The Muse"
    )

    assert muse.url == "https://www.themuse.com/api/public/jobs?page=1"
    assert muse.page_start == 1
    assert muse.pagination_type == "page"
    assert muse.page_parameter == "page"
    assert muse.record_path == "results"
    assert muse.title_field == "name"
    assert muse.company_field == "company.name"
    assert muse.url_field == "refs.landing_page"


def test_historical_source_identities_use_verified_live_replacements():
    catalog = _load_free_source_catalog()
    definitions = {definition.name: definition for definition in catalog}
    overridden = {definition.name: definition for definition in _apply_overrides(tuple(catalog))}

    us_remotely = overridden["US Remotely"]
    assert us_remotely.name == "US Remotely"
    assert us_remotely.provider == "USA Remote Work"
    assert us_remotely.url == "https://www.usaremotework.com/jobs"
    assert us_remotely.collector_type == "html"

    rocketship = overridden["Rocketship"]
    assert rocketship.name == "Rocketship"
    assert rocketship.provider == "Remote Landers"
    assert rocketship.url == "https://remotelanders.com/api/jobs?limit=100&page=1"
    assert rocketship.collector_type == "json"
    assert rocketship.record_path == "jobs"
    assert rocketship.url_field == "applyUrl"

    assert definitions["US Remotely"].url == "https://www.usaremotework.com/jobs"
    assert definitions["Rocketship"].url == "https://remotelanders.com/api/jobs?limit=100&page=1"
    assert "Remote Landers" not in definitions
    assert "USA Remote Work" not in definitions


def test_jobicy_uses_public_rss_fallback():
    catalog = _load_free_source_catalog()
    jobicy = next(
        definition
        for definition in _apply_overrides(tuple(catalog))
        if definition.name == "Jobicy"
    )

    assert jobicy.collector_type == "rss"
    assert jobicy.url == "https://jobicy.com/jobs/feed"
    assert jobicy.pagination_type == "none"
    assert jobicy.max_pages == 1
    assert jobicy.max_requests == 1


def test_landing_jobs_uses_public_rss_feed():
    catalog = _load_free_source_catalog()
    landing_jobs = next(
        definition
        for definition in _apply_overrides(tuple(catalog))
        if definition.name == "Landing Jobs"
    )

    assert landing_jobs.collector_type == "rss"
    assert landing_jobs.url == "https://landing.jobs/feed"
    assert landing_jobs.pagination_type == "none"
    assert landing_jobs.max_pages == 1
    assert landing_jobs.max_requests == 1
    assert landing_jobs.max_records == 55


def test_current_api_corrections_remove_stale_explicit_page_parameters():
    catalog = _load_free_source_catalog()
    definitions = {definition.name: definition for definition in catalog}

    remote_jobs = definitions["RemoteJobs.org"]
    assert remote_jobs.url == "https://remotejobs.org/api/v1/jobs?limit=50"
    assert remote_jobs.offset_start == 0
    assert remote_jobs.offset_parameter == "offset"

    remote_first = definitions["Remote First Jobs"]
    assert remote_first.url == "https://remotefirstjobs.com/api/search-jobs"
    assert remote_first.page_start == 0

    arbeitnow = definitions["Arbeitnow"]
    assert arbeitnow.url == "https://www.arbeitnow.com/api/job-board-api"
    assert arbeitnow.page_start == 1

    nomado24 = definitions["Nomado24"]
    assert nomado24.url == "https://api.nomado24.de/api/public/v1/jobs?per_page=100&language=en"

    landing_jobs = definitions["Landing Jobs"]
    assert landing_jobs.url == "https://landing.jobs/feed"
    assert landing_jobs.collector_type == "rss"
    assert landing_jobs.pagination_type == "none"


def test_remotive_uses_current_jobs_api():
    catalog = _load_free_source_catalog()
    remotive = next(
        definition
        for definition in catalog
        if definition.name == "Remotive"
    )

    assert remotive.url == "https://remotive.com/api/remote-jobs"
    assert remotive.collector_type == "json"
    assert remotive.record_path == "jobs"
    assert remotive.company_field == "company_name"
    assert remotive.url_field == "url"


def test_nodesk_uses_live_html_listing_instead_of_broken_rss():
    catalog = _load_free_source_catalog()
    nodesk = next(
        definition
        for definition in catalog
        if definition.name == "NoDesk"
    )

    assert nodesk.collector_type == "html"
    assert nodesk.url == "https://nodesk.co/remote-jobs/"


def test_every_active_source_definition_is_unchanged():
    catalog = _load_free_source_catalog()
    definitions = {
        definition.name: definition
        for definition in catalog
    }

    active_definitions = tuple(
        definitions[name]
        for name in sorted(_ACTIVE_SOURCES)
    )

    assert _apply_overrides(active_definitions) == active_definitions
