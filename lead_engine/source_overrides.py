from __future__ import annotations

from dataclasses import replace
from typing import Callable, Tuple

from .source_definition import SourceDefinition


# Only sources proven to need a configuration correction belong here.
# Healthy sources must not be altered by this layer.
_SOURCE_OVERRIDES = {
    "The Muse": {
        "url": "https://www.themuse.com/api/public/jobs?page=1",
        "page_start": 1,
    },
}


def _apply_overrides(
    definitions: Tuple[SourceDefinition, ...],
) -> Tuple[SourceDefinition, ...]:
    updated = []

    for definition in definitions:
        override = _SOURCE_OVERRIDES.get(definition.name)
        if override is None:
            updated.append(definition)
            continue

        updated.append(
            replace(
                definition,
                **override,
            )
        )

    return tuple(updated)


def install() -> None:
    """Apply only explicit, source-specific configuration corrections."""
    from . import source_registry

    original: Callable[[], Tuple[SourceDefinition, ...]] = (
        source_registry._load_free_source_catalog
    )

    if getattr(
        original,
        "_thorio_source_overrides",
        False,
    ):
        return

    def patched() -> Tuple[SourceDefinition, ...]:
        return _apply_overrides(original())

    patched._thorio_source_overrides = True
    source_registry._load_free_source_catalog = patched
