import json
import os
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from .airtable_sync import (
    AirtableSyncError,
    _master_table_url,
    _request,
)
from .free_sources import FreeJobSource
from .sources import LeadSource
from .source_adapters import create_adapter
from .source_definition import SourceDefinition
from .web_source_config import create_web_source_from_env


DEFAULT_FREE_SOURCE_CATALOG_PATH = (
    Path(__file__).with_name("free_sources.json")
)

DEFAULT_FREE_SOURCE_TYPE = "html"

SUPPORTED_FREE_SOURCE_TYPES = {
    "html",
    "json",
    "rss",
    "atom",
    "xml",
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
) -> Tuple[SourceDefinition, ...]:
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

    catalog: List[SourceDefinition] = []
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

        if not isinstance(
            name,
            str,
        ) or not name.strip():
            raise RuntimeError(
                "Free source catalog entry "
                f"{index + 1} is missing 'name'."
            )

        if not isinstance(
            url,
            str,
        ) or not url.strip():
            raise RuntimeError(
                "Free source catalog entry "
                f"{index + 1} is missing 'url'."
            )

        if not isinstance(
            enabled,
            bool,
        ):
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

        seen_names.add(
            normalized_name
        )

        seen_urls.add(
            normalized_url
        )

        if not enabled:
            continue

        provider = entry.get(
            "provider",
            name,
        )

        if not isinstance(
            provider,
            str,
        ) or not provider.strip():
            provider = name

        restrictions = entry.get(
            "restrictions",
            (),
        )

        if isinstance(
            restrictions,
            list,
        ):
            restrictions = tuple(
                str(value).strip()
                for value in restrictions
                if str(value).strip()
            )

        elif isinstance(
            restrictions,
            tuple,
        ):
            restrictions = tuple(
                str(value).strip()
                for value in restrictions
                if str(value).strip()
            )

        else:
            raise RuntimeError(
                "Free source catalog entry "
                f"{index + 1} has invalid 'restrictions'."
            )

        metadata = entry.get(
            "metadata",
            {},
        )

        if not isinstance(
            metadata,
            dict,
        ):
            raise RuntimeError(
                "Free source catalog entry "
                f"{index + 1} has invalid 'metadata'."
            )

        try:
            definition = SourceDefinition(
                name=name,
                provider=provider.strip(),
                collector_type=source_type,
                url=url,
                enabled=True,
                record_path=entry.get(
                    "record_path"
                ),
                title_field=entry.get(
                    "title_field",
                    "title",
                ),
                company_field=entry.get(
                    "company_field",
                    "company",
                ),
                description_field=entry.get(
                    "description_field",
                    "description",
                ),
                url_field=entry.get(
                    "url_field",
                    "url",
                ),
                source_id_field=entry.get(
                    "source_id_field"
                ),
                location_field=entry.get(
                    "location_field"
                ),
                pagination_type=entry.get(
                    "pagination_type",
                    "none",
                ),
                cursor_parameter=entry.get(
                    "cursor_parameter"
                ),
                cursor_response_field=entry.get(
                    "cursor_response_field"
                ),
                page_parameter=entry.get(
                    "page_parameter"
                ),
                page_start=entry.get(
                    "page_start",
                    1,
                ),
                page_limit=entry.get(
                    "page_limit"
                ),
                offset_parameter=entry.get(
                    "offset_parameter"
                ),
                offset_start=entry.get(
                    "offset_start",
                    0,
                ),
                offset_step=entry.get(
                    "offset_step"
                ),
                next_url_field=entry.get(
                    "next_url_field"
                ),
                max_pages=entry.get(
                    "max_pages",
                    10,
                ),
                max_requests=entry.get(
                    "max_requests",
                    10,
                ),
                max_records=entry.get(
                    "max_records",
                    5000,
                ),
                poll_interval_seconds=entry.get(
                    "poll_interval_seconds",
                    3600,
                ),
                attribution_required=entry.get(
                    "attribution_required",
                    False,
                ),
                attribution_url=entry.get(
                    "attribution_url"
                ),
                allowed_for_thorio=entry.get(
                    "allowed_for_thorio",
                    True,
                ),
                restrictions=restrictions,
                metadata=metadata,
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise RuntimeError(
                "Invalid free source catalog entry "
                f"{index + 1} ({name}): {exc}"
            ) from exc

        catalog.append(
            definition
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
    definition: SourceDefinition,
) -> LeadSource:
    timeout = _free_source_timeout()

    return create_adapter(
        definition=definition,
        timeout=timeout,
    )


def _load_airtable_source_catalog() -> Tuple[
    Tuple[str, str, str, Tuple[str, ...]],
    ...,
]:
    """
    Load active collector configurations from Airtable.

    Only active records with a source URL and supported
    collector type are returned.
    """

    base_id = os.getenv(
        "AIRTABLE_BASE_ID",
        "",
    ).strip()

    api_key = os.getenv(
        "AIRTABLE_API_KEY",
        "",
    ).strip()

    if not base_id or not api_key:
        return tuple()

    try:
        records: List[Dict[str, Any]] = []
        offset = None

        while True:
            params = {
                "pageSize": "100",
            }

            if offset:
                params["offset"] = offset

            query = urllib.parse.urlencode(
                params
            )

            result = _request(
                "GET",
                f"{_master_table_url('lead_sources')}?{query}",
            )

            page = result.get(
                "records",
                [],
            )

            if isinstance(page, list):
                records.extend(
                    record
                    for record in page
                    if isinstance(record, dict)
                )

            offset = result.get(
                "offset"
            )

            if not offset:
                break

    except AirtableSyncError as exc:
        raise RuntimeError(
            f"Unable to load Airtable Lead Sources: {exc}"
        ) from exc

    catalog = []
    seen_names = set()
    seen_urls = set()

    for index, record in enumerate(records):
        fields = record.get(
            "fields",
            {},
        )

        if not isinstance(fields, dict):
            continue

        if fields.get(
            "Active",
            False,
        ) is not True:
            continue

        name = fields.get(
            "Source / Search",
            "",
        )

        url = fields.get(
            "Source URL",
            "",
        )

        source_type = fields.get(
            "Collector Type",
            "",
        )

        signal_keywords = fields.get(
            "Signal Keywords",
            "",
        )

        if not isinstance(name, str):
            name = ""

        if not isinstance(url, str):
            url = ""

        if not isinstance(source_type, str):
            source_type = ""

        if not isinstance(signal_keywords, str):
            signal_keywords = ""

        name = name.strip()
        url = url.strip()
        source_type = source_type.strip().lower()

        signal_keywords = tuple(
            keyword.strip()
            for keyword in signal_keywords.split(";")
            if keyword.strip()
        )

        if not name:
            raise RuntimeError(
                "Airtable Lead Sources record "
                f"{index + 1} is missing 'Source / Search'."
            )

        if not url:
            continue

        _validate_source_url(
            url,
            index,
        )

        if source_type not in SUPPORTED_FREE_SOURCE_TYPES:
            raise RuntimeError(
                "Airtable Lead Sources record "
                f"{index + 1} has unsupported Collector Type: "
                f"{source_type or '<empty>'}. "
                "Supported types: "
                f"{', '.join(sorted(SUPPORTED_FREE_SOURCE_TYPES))}."
            )

        normalized_name = name.casefold()
        normalized_url = url.casefold()

        if normalized_name in seen_names:
            raise RuntimeError(
                "Duplicate Airtable Lead Source name: "
                f"{name}"
            )

        if normalized_url in seen_urls:
            raise RuntimeError(
                "Duplicate Airtable Lead Source URL: "
                f"{url}"
            )

        seen_names.add(
            normalized_name
        )
        seen_urls.add(
            normalized_url
        )

        catalog.append(
            (
                name,
                url,
                source_type,
                signal_keywords,
            )
        )

    return tuple(catalog)


def configured_sources() -> List[LeadSource]:
    sources: List[LeadSource] = []

    web_source = create_web_source_from_env()

    if web_source is not None:
        sources.append(
            web_source
        )

    for (
        name,
        url,
        source_type,
        signal_keywords,
    ) in _load_airtable_source_catalog():

        definition = SourceDefinition(
            name=name,
            provider="Airtable",
            collector_type=source_type,
            url=url,
            enabled=True,
            pagination_type="none",
            metadata={
                "signal_keywords": ";".join(
                    signal_keywords
                ),
            },
        )

        sources.append(
            _free_source_instance(
                definition=definition,
            )
        )

    if _free_sources_enabled():
        for definition in _load_free_source_catalog():
            sources.append(
                _free_source_instance(
                    definition=definition,
                )
            )

    return sources


def available_free_sources() -> List[str]:
    return [
        definition.name
        for definition
        in _load_free_source_catalog()
    ]


if __name__ == "__main__":
    catalog = _load_free_source_catalog()

    print(
        "Lead source registry loaded."
    )

    print(
        f"Free source catalog: {len(catalog)} sources"
    )

    print(
        f"Free sources enabled: {_free_sources_enabled()}"
    )

    print(
        f"Configured source count: {len(configured_sources())}"
            )
