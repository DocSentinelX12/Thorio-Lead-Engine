import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .free_sources import FreeJobSource
from .sources import LeadSource
from .web_source_config import create_web_source_from_env


DEFAULT_FREE_SOURCE_CATALOG_PATH = (
    Path(__file__).with_name("free_sources.json")
)


def _free_source_catalog_path() -> Path:
    configured = os.getenv(
        "THORIO_FREE_SOURCE_CATALOG",
        "",
    ).strip()

    if configured:
        return Path(configured)

    return DEFAULT_FREE_SOURCE_CATALOG_PATH


def _load_free_source_catalog() -> Tuple[Tuple[str, str], ...]:
    path = _free_source_catalog_path()

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as handle:
            data = json.load(handle)

    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Free source catalog not found: {path}"
        ) from exc

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Free source catalog contains invalid JSON: {path}"
        ) from exc

    if not isinstance(data, list):
        raise RuntimeError(
            "Free source catalog must contain a JSON array."
        )

    catalog: List[Tuple[str, str]] = []
    seen_names = set()
    seen_urls = set()

    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise RuntimeError(
                "Free source catalog entry "
                f"{index + 1} must be an object."
            )

        name = str(
            entry.get("name", "")
        ).strip()

        url = str(
            entry.get("url", "")
        ).strip()

        enabled = entry.get(
            "enabled",
            True,
        )

        if not name:
            raise RuntimeError(
                "Free source catalog entry "
                f"{index + 1} is missing 'name'."
            )

        if not url:
            raise RuntimeError(
                "Free source catalog entry "
                f"{index + 1} is missing 'url'."
            )

        if not isinstance(enabled, bool):
            raise RuntimeError(
                "Free source catalog entry "
                f"{index + 1} has invalid 'enabled'."
            )

        normalized_name = name.casefold()
        normalized_url = url.casefold()

        if normalized_name in seen_names:
            raise RuntimeError(
                f"Duplicate free source name: {name}"
            )

        if normalized_url in seen_urls:
            raise RuntimeError(
                f"Duplicate free source URL: {url}"
            )

        seen_names.add(normalized_name)
        seen_urls.add(normalized_url)

        if enabled:
            catalog.append(
                (
                    name,
                    url,
                )
            )

    return tuple(catalog)


FREE_SOURCE_CATALOG = _load_free_source_catalog()


FREE_SOURCE_NAMES = tuple(
    name
    for name, _url in FREE_SOURCE_CATALOG
)


def _free_sources_enabled() -> bool:
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
    return FreeJobSource(
        name=name,
        url=url,
        timeout=_free_source_timeout(),
    )


def configured_sources() -> List[LeadSource]:
    sources: List[LeadSource] = []

    web_source = create_web_source_from_env()

    if web_source is not None:
        sources.append(web_source)

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
