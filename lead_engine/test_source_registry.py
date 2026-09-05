from unittest.mock import patch

from .source_registry import (
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


def test_free_source_catalog_contains_at_least_20_sources():
    catalog = _load_free_source_catalog()

    assert len(catalog) >= 20


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

    assert len(names) >= 20
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

    assert len(sources) >= 20

    names = {
        source.name
        for source in sources
    }

    assert "Himalayas" in names
    assert "Jobicy" in names
    assert "RemoteJobs.org" in names
    assert "Stripe" in names
    assert "GitLab" in names


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
