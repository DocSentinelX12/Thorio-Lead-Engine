from unittest.mock import patch

from .source_registry import (
    SUPPORTED_FREE_SOURCE_TYPES,
    _load_airtable_source_catalog,
    _load_free_source_catalog,
    available_free_sources,
    configured_sources,
)


def test_configured_sources_empty_when_unconfigured():
    with patch.dict(
        "os.environ",
        {},
        clear=True,
    ):
        sources = configured_sources()

    assert sources == []


def test_configured_sources_includes_web_source():
    with patch.dict(
        "os.environ",
        {
            "THORIO_LEAD_SOURCE_URL":
                "https://example.com/leads.json",
            "THORIO_LEAD_SOURCE_TIMEOUT":
                "20",
        },
        clear=True,
    ):
        sources = configured_sources()

    assert len(sources) == 1
    assert sources[0].name == "web"
    assert (
        sources[0].url
        == "https://example.com/leads.json"
    )


def test_free_source_catalog_has_exact_current_universe():
    catalog = _load_free_source_catalog()

    assert len(catalog) == 24
    assert len(available_free_sources()) == 24
    assert all(definition.enabled for definition in catalog)


def test_free_source_catalog_preserves_historical_public_sources():
    names = set(available_free_sources())

    historical_sources = {
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
    }

    assert historical_sources <= names
    assert {"Airbnb", "Anthropic", "Airtable", "Asana", "Brex"} <= names


def test_free_source_catalog_supports_all_public_collector_types():
    assert SUPPORTED_FREE_SOURCE_TYPES == {
        "html",
        "json",
        "rss",
        "atom",
        "xml",
    }


def test_free_source_catalog_preserves_rich_definition():
    catalog = _load_free_source_catalog()

    himalayas = next(
        definition
        for definition in catalog
        if definition.name == "Himalayas"
    )

    assert (
        himalayas.collector_type
        == "json"
    )

    assert (
        himalayas.record_path
        == "jobs"
    )

    assert (
        himalayas.pagination_type
        == "cursor"
    )

    assert (
        himalayas.cursor_parameter
        == "cursor"
    )

    assert (
        himalayas.cursor_response_field
        == "nextCursor"
    )

    assert (
        himalayas.company_field
        == "companyName"
    )


def test_free_source_catalog_preserves_company_metadata():
    catalog = _load_free_source_catalog()

    stripe = next(
        definition
        for definition in catalog
        if definition.name == "Stripe"
    )

    assert (
        stripe.provider
        == "Greenhouse"
    )

    assert (
        stripe.metadata[
            "default_company"
        ]
        == "Stripe"
    )

    assert (
        stripe.record_path
        == "jobs"
    )

    assert (
        stripe.url_field
        == "absolute_url"
    )


def test_available_free_sources_returns_catalog_names():
    names = available_free_sources()

    assert len(names) == 24
    assert "Himalayas" in names
    assert "Jobicy" in names
    assert "RemoteJobs.org" in names
    assert "Stripe" in names
    assert "GitLab" in names


def test_configured_sources_loads_all_free_sources():
    with patch.dict(
        "os.environ",
        {
            "LEAD_ENGINE_FREE_SOURCES_ENABLED":
                "true",
        },
        clear=True,
    ):
        sources = configured_sources()

    assert len(sources) == 24

    names = {
        source.name
        for source in sources
    }

    assert names == set(available_free_sources())


def test_free_source_catalog_nomado24_uses_description_field():
    catalog = _load_free_source_catalog()

    nomado24 = next(
        definition
        for definition in catalog
        if definition.name == "Nomado24"
    )

    assert (
        nomado24.description_field
        == "description"
    )


def test_active_airtable_source_without_url_fails_loudly():
    records = {
        "records": [
            {
                "id": "rec-invalid",
                "fields": {
                    "Active": True,
                    "Source / Search": "LinkedIn hiring",
                    "Source URL": "",
                    "Collector Type": "json",
                },
            }
        ]
    }
    with patch.dict(
        "os.environ",
        {
            "AIRTABLE_BASE_ID": "app-test",
            "AIRTABLE_API_KEY": "pat-test",
        },
        clear=True,
    ), patch("lead_engine.source_registry._request", return_value=records):
        try:
            _load_airtable_source_catalog()
        except RuntimeError as exc:
            assert "missing required source fields" in str(exc)
        else:
            raise AssertionError("active Airtable source without URL was silently ignored")
