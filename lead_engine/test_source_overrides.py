from .source_registry import _load_free_source_catalog
from .source_overrides import _SOURCE_OVERRIDES, _apply_overrides


_ACTIVE_SOURCES = {
    "Himalayas",
    "Jobicy",
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


def test_only_explicit_broken_sources_are_overridden():
    assert set(_SOURCE_OVERRIDES) == {"The Muse"}
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
