from unittest.mock import patch

from .source_registry import _load_free_source_catalog
from .source_overrides import _SOURCE_OVERRIDES, _apply_overrides


def test_only_explicit_broken_sources_are_overridden():
    assert set(_SOURCE_OVERRIDES) == {"The Muse"}


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


def test_healthy_definition_is_unchanged():
    catalog = _load_free_source_catalog()
    healthy = next(
        definition
        for definition in catalog
        if definition.name == "Stripe"
    )
    overridden = _apply_overrides((healthy,))[0]
    assert overridden == healthy
