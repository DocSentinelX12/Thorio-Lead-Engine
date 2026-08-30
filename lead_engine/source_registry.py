import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from .free_sources import FreeJobSource
from .sources import LeadSource
from .web_source import WebLeadSource
from .web_source_config import create_web_source_from_env


DEFAULT_FREE_SOURCE_CATALOG_PATH = (
    Path(__file__).with_name("free_sources.json")
)

DEFAULT_FREE_SOURCE_TYPE = "html"

SUPPORTED_FREE_SOURCE_TYPES = {
    "html",
    "json",
}


def _free_source_catalog_path() -> Path:
    configured = os.getenv(
        "THORIO_FREE_SOURCE_CATALOG",
        "",
    ).strip()

    if configured:
        return Path(configured)

    return DEFAULT_FREE_SOURCE_CATALOG_PATH


def _validate_source_url(
    url: str,
    index: int,
) -> None:
    parsed = urlparse(url)

    if parsed.scheme.lower() not in {
        "http",
        "https",
    }:
        raise RuntimeError(
            "Free source catalog entry "
            f"{index + 1} has an invalid URL scheme: {url}"
        )

    if not parsed.netloc:
        raise RuntimeError(
            "Free source catalog entry "
            f"{index + 1} has an invalid URL: {url}"
        )


def _normalize_source_type(
    value: Any,
    index: int,
) -> str:
    if value is None:
        return DEFAULT_FREE_SOURCE_TYPE

    if not isinstance(value, str):
        raise RuntimeError(
            "Free source catalog entry "
            f"{index + 1} has invalid 'type'."
        )

    source_type = value.strip().lower()

    if not source_type:
        return DEFAULT_FREE_SOURCE_TYPE

    if source_type not in SUPPORTED_FREE_SOURCE_TYPES:
        supported = ", ".join(
            sorted(SUPPORTED_FREE_SOURCE_TYPES)
        )

        raise RuntimeError(
            "Free source catalog entry "
            f"{index + 1} has unsupported 'type': "
            f"{source_type}. Supported types: {supported}."
        )

    return source_type


def _load_free_source_catalog(
) -> Tuple[Tuple[str, str, str], ...]:
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

    catalog: List[Tuple[str, str, str]] = []
    seen_names = set()
    seen_urls = set()

    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise RuntimeError(
                "Free source catalog entry "
                f"{index + 1} must be an object."
            )

        name = entry.get(
            "name",
            "",
        )

        url = entry.get(
            "url",
            "",
        )

        enabled = entry.get(
            "enabled",
            True,
        )

        source_type = _normalize_source_type(
            entry.get("type"),
            index,
        )

        if not isinstance(name, str) or not name.strip():
            raise RuntimeError(
                "Free source catalog entry "
                f"{index + 1} is missing 'name'."
            )

        if not isinstance(url, str) or not url.strip():
            raise RuntimeError(
                "Free source catalog entry "
                f"{index + 1} is missing 'url'."
            )

        if not isinstance(enabled, bool):
            raise RuntimeError(
                "Free source catalog entry "
                f"{index + 1} has invalid 'enabled'."
            )

        name = name.strip()
        url = url.strip()

        _validate_source_url(
            url,
            index,
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
                    source_type,
                )
            )

    return tuple(catalog)


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
    source_type: str = DEFAULT_FREE_SOURCE_TYPE,
) -> LeadSource:
    timeout = _free_source_timeout()

    if source_type == "html":
        return FreeJobSource(
            name=name,
            url=url,
            timeout=timeout,
        )

    if source_type == "json":
        source = WebLeadSource(
            url=url,
            timeout=timeout,
        )

        source.name = name

        return source

    raise RuntimeError(
        f"Unsupported free source type: {source_type}"
    )


def configured_sources() -> List[LeadSource]:
    sources: List[LeadSource] = []

    web_source = create_web_source_from_env()

    if web_source is not None:
        sources.append(web_source)

    if _free_sources_enabled():
        catalog = _load_free_source_catalog()

        for name, url, source_type in catalog:
            sources.append(
                _free_source_instance(
                    name=name,
                    url=url,
                    source_type=source_type,
                )
            )

    return sources


def available_free_sources() -> List[str]:
    catalog = _load_free_source_catalog()

    return [
        name
        for name, _url, _source_type in catalog
    ]


if __name__ == "__main__":
    catalog = _load_free_source_catalog()

    print(
        "Lead source registry loaded."
    )

    print(
        f"Free source catalog: "
        f"{len(catalog)} sources"
    )

    print(
        f"Free sources enabled: "
        f"{_free_sources_enabled()}"
    )

    print(
        f"Configured source count: "
        f"{len(configured_sources())}"
)
