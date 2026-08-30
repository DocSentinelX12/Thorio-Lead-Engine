import pytest

from .source_pagination import (
    PaginationError,
    build_page_url,
    collect_paginated,
)


def test_collect_paginated_collects_multiple_pages():
    pages = {
        "https://example.com/jobs": [
            {
                "source_id": "001",
            },
        ],
        "https://example.com/jobs?page=2": [
            {
                "source_id": "002",
            },
        ],
        "https://example.com/jobs?page=3": [
            {
                "source_id": "003",
            },
        ],
    }

    calls = []

    def fetch_page(url):
        calls.append(url)
        return pages[url]

    def next_url(url, records):
        if url.endswith("jobs"):
            return "https://example.com/jobs?page=2"

        if url.endswith("page=2"):
            return "https://example.com/jobs?page=3"

        return None

    result = collect_paginated(
        fetch_page,
        "https://example.com/jobs",
        next_url=next_url,
    )

    assert result == [
        {"source_id": "001"},
        {"source_id": "002"},
        {"source_id": "003"},
    ]

    assert calls == [
        "https://example.com/jobs",
        "https://example.com/jobs?page=2",
        "https://example.com/jobs?page=3",
    ]


def test_collect_paginated_stops_at_max_pages():
    calls = []

    def fetch_page(url):
        calls.append(url)
        return [
            {
                "source_id": str(
                    len(calls)
                ),
            }
        ]

    def next_url(url, records):
        page = len(calls) + 1
        return (
            f"https://example.com/jobs?page={page}"
        )

    result = collect_paginated(
        fetch_page,
        "https://example.com/jobs",
        max_pages=2,
        next_url=next_url,
    )

    assert len(result) == 2
    assert len(calls) == 2


def test_collect_paginated_stops_at_max_requests():
    calls = []

    def fetch_page(url):
        calls.append(url)
        return [
            {
                "source_id": str(
                    len(calls)
                ),
            }
        ]

    def next_url(url, records):
        return (
            "https://example.com/jobs"
            f"?page={len(calls) + 1}"
        )

    result = collect_paginated(
        fetch_page,
        "https://example.com/jobs",
        max_pages=10,
        max_requests=3,
        next_url=next_url,
    )

    assert len(result) == 3
    assert len(calls) == 3


def test_collect_paginated_stops_at_max_records():
    calls = []

    def fetch_page(url):
        calls.append(url)

        return [
            {
                "source_id": "001",
            },
            {
                "source_id": "002",
            },
            {
                "source_id": "003",
            },
        ]

    def next_url(url, records):
        return (
            "https://example.com/jobs?page=2"
        )

    result = collect_paginated(
        fetch_page,
        "https://example.com/jobs",
        max_pages=10,
        max_records=2,
        next_url=next_url,
    )

    assert result == [
        {"source_id": "001"},
        {"source_id": "002"},
    ]

    assert len(calls) == 1


def test_collect_paginated_rejects_repeated_url():
    def fetch_page(url):
        return [
            {
                "source_id": "001",
            }
        ]

    def next_url(url, records):
        return url

    with pytest.raises(
        PaginationError,
        match="previously visited URL",
    ):
        collect_paginated(
            fetch_page,
            "https://example.com/jobs",
            next_url=next_url,
        )


def test_collect_paginated_rejects_non_object_record():
    def fetch_page(url):
        return [
            {
                "source_id": "001",
            },
            "bad-record",
        ]

    with pytest.raises(
        PaginationError,
        match="non-object record",
    ):
        collect_paginated(
            fetch_page,
            "https://example.com/jobs",
        )


def test_collect_paginated_rejects_none_page():
    def fetch_page(url):
        return None

    with pytest.raises(
        PaginationError,
        match="returned None",
    ):
        collect_paginated(
            fetch_page,
            "https://example.com/jobs",
        )


def test_build_page_url_preserves_existing_query():
    result = build_page_url(
        "https://example.com/jobs?category=tech",
        parameter="page",
        value=2,
    )

    assert result == (
        "https://example.com/jobs"
        "?category=tech&page=2"
    )


def test_build_page_url_replaces_existing_parameter():
    result = build_page_url(
        "https://example.com/jobs?page=1&limit=50",
        parameter="page",
        value=2,
    )

    assert result == (
        "https://example.com/jobs"
        "?page=2&limit=50"
    )


@pytest.mark.parametrize(
    "max_pages,max_records,max_requests",
    [
        (0, 10, 10),
        (10, 0, 10),
        (10, 10, 0),
        (-1, 10, 10),
    ],
)
def test_collect_paginated_requires_positive_limits(
    max_pages,
    max_records,
    max_requests,
):
    with pytest.raises(
        ValueError
    ):
        collect_paginated(
            lambda url: [],
            "https://example.com/jobs",
            max_pages=max_pages,
            max_records=max_records,
            max_requests=max_requests,
              )
