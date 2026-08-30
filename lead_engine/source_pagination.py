from typing import Any, Callable, Dict, Iterable, List, Optional, Set
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


DEFAULT_MAX_PAGES = 10
DEFAULT_MAX_RECORDS = 5000
DEFAULT_MAX_REQUESTS = 10


class PaginationError(Exception):
    """Raised when bounded source pagination cannot continue safely."""


def _validate_positive_limit(
    value: int,
    name: str,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise ValueError(
            f"{name} must be a positive integer."
        )

    return value


def _normalize_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise PaginationError(
            "Pagination URL must be a non-empty string."
        )

    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in {
        "http",
        "https",
    }:
        raise PaginationError(
            "Pagination URL must use HTTP or HTTPS."
        )

    if not parsed.netloc:
        raise PaginationError(
            "Pagination URL must contain a host."
        )

    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def build_page_url(
    url: str,
    *,
    parameter: str,
    value: int,
) -> str:
    """
    Return a URL with one pagination parameter replaced.

    Existing query parameters are preserved.
    """
    if not isinstance(parameter, str) or not parameter.strip():
        raise ValueError(
            "Pagination parameter is required."
        )

    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise ValueError(
            "Pagination value must be a positive integer."
        )

    normalized = _normalize_url(url)

    parsed = urlparse(normalized)

    query = dict(
        parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )
    )

    query[parameter.strip()] = str(value)

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query),
            parsed.fragment,
        )
    )


def collect_paginated(
    fetch_page: Callable[
        [str],
        Iterable[Dict[str, Any]],
    ],
    start_url: str,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_requests: int = DEFAULT_MAX_REQUESTS,
    next_url: Optional[
        Callable[
            [str, List[Dict[str, Any]]],
            Optional[str],
        ]
    ] = None,
) -> List[Dict[str, Any]]:
    """
    Collect records through a bounded pagination contract.

    The fetch_page callback performs exactly one source request.

    Pagination stops when:
      * there is no next URL,
      * max_pages is reached,
      * max_requests is reached,
      * max_records is reached.

    Repeated URLs are rejected to prevent infinite loops.
    """
    max_pages = _validate_positive_limit(
        max_pages,
        "max_pages",
    )

    max_records = _validate_positive_limit(
        max_records,
        "max_records",
    )

    max_requests = _validate_positive_limit(
        max_requests,
        "max_requests",
    )

    if not callable(fetch_page):
        raise ValueError(
            "fetch_page must be callable."
        )

    current_url = _normalize_url(
        start_url
    )

    collected: List[Dict[str, Any]] = []
    visited_urls: Set[str] = set()

    pages = 0
    requests = 0

    while current_url:
        if pages >= max_pages:
            break

        if requests >= max_requests:
            break

        normalized_url = _normalize_url(
            current_url
        )

        if normalized_url in visited_urls:
            raise PaginationError(
                "Pagination returned a previously visited URL."
            )

        visited_urls.add(
            normalized_url
        )

        requests += 1
        pages += 1

        page_records = fetch_page(
            normalized_url
        )

        if page_records is None:
            raise PaginationError(
                "Pagination page returned None."
            )

        page_records = list(
            page_records
        )

        for record in page_records:
            if not isinstance(record, dict):
                raise PaginationError(
                    "Pagination page contained "
                    "a non-object record."
                )

            collected.append(record)

            if len(collected) >= max_records:
                return collected[
                    :max_records
                ]

        if next_url is None:
            break

        candidate = next_url(
            normalized_url,
            page_records,
        )

        if candidate is None:
            break

        if not isinstance(candidate, str):
            raise PaginationError(
                "Pagination next URL must be "
                "a string or None."
            )

        candidate = candidate.strip()

        if not candidate:
            break

        current_url = candidate

    return collected
