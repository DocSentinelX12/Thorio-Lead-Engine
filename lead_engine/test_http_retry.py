from unittest.mock import patch

import pytest

from .http_retry import (
    HTTPRetryError,
    fetch_url,
)


class Response:
    def __init__(self, body=b"ok"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        return False

    def read(self):
        return self.body


def test_fetch_url_succeeds_without_retry():
    request = object()

    with patch(
        "lead_engine.http_retry.urlopen",
        return_value=Response(
            b"success"
        ),
    ) as mocked:
        result = fetch_url(
            request,
            timeout=20,
        )

    assert result == b"success"
    assert mocked.call_count == 1


def test_fetch_url_retries_timeout_then_succeeds():
    request = object()

    with patch(
        "lead_engine.http_retry.urlopen",
        side_effect=[
            TimeoutError(),
            TimeoutError(),
            Response(b"success"),
        ],
    ) as mocked, patch(
        "lead_engine.http_retry.time.sleep"
    ) as sleep:
        result = fetch_url(
            request,
            timeout=20,
        )

    assert result == b"success"
    assert mocked.call_count == 3

    assert [
        call.args[0]
        for call in sleep.call_args_list
    ] == [
        1.0,
        2.0,
    ]


def test_fetch_url_retries_http_500():
    from urllib.error import HTTPError

    request = object()

    error = HTTPError(
        "https://example.com",
        500,
        "server error",
        {},
        None,
    )

    with patch(
        "lead_engine.http_retry.urlopen",
        side_effect=[
            error,
            Response(b"success"),
        ],
    ) as mocked, patch(
        "lead_engine.http_retry.time.sleep"
    ):
        result = fetch_url(
            request,
            timeout=20,
        )

    assert result == b"success"
    assert mocked.call_count == 2


def test_fetch_url_retries_rate_limit():
    from urllib.error import HTTPError

    request = object()

    error = HTTPError(
        "https://example.com",
        429,
        "rate limited",
        {
            "Retry-After": "7",
        },
        None,
    )

    with patch(
        "lead_engine.http_retry.urlopen",
        side_effect=[
            error,
            Response(b"success"),
        ],
    ), patch(
        "lead_engine.http_retry.time.sleep"
    ) as sleep:
        result = fetch_url(
            request,
            timeout=20,
        )

    assert result == b"success"

    sleep.assert_called_once_with(7.0)


def test_fetch_url_does_not_retry_http_404():
    from urllib.error import HTTPError

    request = object()

    error = HTTPError(
        "https://example.com",
        404,
        "not found",
        {},
        None,
    )

    with patch(
        "lead_engine.http_retry.urlopen",
        side_effect=error,
    ) as mocked, patch(
        "lead_engine.http_retry.time.sleep"
    ) as sleep:
        with pytest.raises(
            HTTPRetryError,
            match="status 404",
        ):
            fetch_url(
                request,
                timeout=20,
            )

    assert mocked.call_count == 1
    sleep.assert_not_called()


def test_fetch_url_fails_after_retry_limit():
    request = object()

    with patch(
        "lead_engine.http_retry.urlopen",
        side_effect=TimeoutError(),
    ) as mocked, patch(
        "lead_engine.http_retry.time.sleep"
    ) as sleep:
        with pytest.raises(
            HTTPRetryError,
            match="timed out",
        ):
            fetch_url(
                request,
                timeout=20,
                max_retries=3,
            )

    assert mocked.call_count == 4
    assert sleep.call_count == 3


@pytest.mark.parametrize(
    "timeout",
    [
        0,
        -1,
    ],
)
def test_fetch_url_requires_positive_timeout(
    timeout,
):
    with pytest.raises(
        ValueError,
        match="timeout must be positive",
    ):
        fetch_url(
            object(),
            timeout=timeout,
        )


def test_fetch_url_allows_zero_retries():
    request = object()

    with patch(
        "lead_engine.http_retry.urlopen",
        side_effect=TimeoutError(),
    ) as mocked:
        with pytest.raises(
            HTTPRetryError,
        ):
            fetch_url(
                request,
                timeout=20,
                max_retries=0,
            )

    assert mocked.call_count == 1
