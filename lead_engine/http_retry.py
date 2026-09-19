import time
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_BACKOFF = 1.0
DEFAULT_MAX_BACKOFF = 30.0


class HTTPRetryError(Exception):
    """Raised when a retried HTTP request ultimately fails."""

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        url: Optional[str] = None,
        reason: Optional[str] = None,
        response_body: Optional[str] = None,
        response_headers: Optional[dict[str, str]] = None,
        attempts: Optional[int] = None,
    ):
        super().__init__(message)
        self.status = status
        self.url = url
        self.reason = reason
        self.response_body = response_body
        self.response_headers = response_headers or {}
        self.attempts = attempts


def _retry_delay(
    attempt: int,
    retry_after: Optional[str] = None,
    initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    remaining: Optional[float] = None,
) -> float:
    if retry_after:
        try:
            value = float(retry_after)
            if value >= 0:
                delay = min(value, max_backoff)
                return min(delay, remaining) if remaining is not None else delay
        except (TypeError, ValueError):
            pass

    delay = min(initial_backoff * (2 ** attempt), max_backoff)
    return min(delay, remaining) if remaining is not None else delay


def fetch_url(
    request: Request,
    *,
    timeout: int,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    deadline: Optional[float] = None,
) -> bytes:
    """
    Fetch a URL with bounded retry, exponential backoff, and optional absolute deadline.

    ``timeout`` bounds an individual network operation. ``deadline`` bounds the
    complete retry operation using ``time.monotonic()``. When the deadline is
    reached, no additional attempt or backoff is started.
    """
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("timeout must be positive")

    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
        raise ValueError("HTTP max_retries must be a non-negative integer.")

    if not isinstance(initial_backoff, (int, float)) or isinstance(initial_backoff, bool) or initial_backoff < 0:
        raise ValueError("HTTP initial_backoff must be non-negative.")

    if not isinstance(max_backoff, (int, float)) or isinstance(max_backoff, bool) or max_backoff < 0:
        raise ValueError("HTTP max_backoff must be non-negative.")

    if deadline is not None:
        if not isinstance(deadline, (int, float)) or isinstance(deadline, bool):
            raise ValueError("HTTP deadline must be a monotonic timestamp.")
        if deadline <= time.monotonic():
            raise HTTPRetryError("HTTP request deadline exceeded before request started.", url=request.full_url, attempts=0)

    last_error: Optional[HTTPRetryError] = None

    for attempt in range(max_retries + 1):
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HTTPRetryError(
                    "HTTP request deadline exceeded.",
                    url=request.full_url,
                    attempts=attempt,
                ) from last_error
            request_timeout = min(timeout, max(0.001, remaining))
        else:
            remaining = None
            request_timeout = timeout

        try:
            with urlopen(request, timeout=request_timeout) as response:
                return response.read()

        except HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            try:
                response_bytes = exc.read()
                if not response_bytes and getattr(exc, "fp", None) is not None:
                    response_bytes = exc.fp.read()
                response_body = response_bytes.decode("utf-8", errors="replace")
            except Exception:
                response_body = "<unable to read HTTP error response body>"

            response_headers = {}
            try:
                for header_name in ("Content-Type", "Retry-After", "Server", "Date"):
                    header_value = exc.headers.get(header_name)
                    if header_value:
                        response_headers[header_name] = header_value
            except Exception:
                response_headers = {}

            error = HTTPRetryError(
                f"HTTP request failed with status {exc.code}. "
                f"reason={exc.reason!s}. url={exc.geturl()!s}. "
                f"response_body={response_body!r}",
                status=exc.code,
                url=exc.geturl(),
                reason=str(exc.reason),
                response_body=response_body,
                response_headers=response_headers,
                attempts=attempt + 1,
            )

            if not retryable or attempt >= max_retries:
                raise error from exc

            last_error = error
            retry_after = None
            try:
                retry_after = exc.headers.get("Retry-After")
            except Exception:
                pass

            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            delay = _retry_delay(attempt, retry_after, initial_backoff, max_backoff, remaining)
            if delay <= 0:
                raise HTTPRetryError(
                    "HTTP request deadline exceeded before retry.",
                    status=exc.code,
                    url=exc.geturl(),
                    reason=str(exc.reason),
                    response_body=response_body,
                    response_headers=response_headers,
                    attempts=attempt + 1,
                ) from exc
            time.sleep(delay)

        except (URLError, TimeoutError) as exc:
            if isinstance(exc, URLError):
                error = HTTPRetryError(f"HTTP connection failed: {exc.reason}")
            else:
                error = HTTPRetryError("HTTP request timed out.")
            last_error = error

            if attempt >= max_retries:
                raise error from exc

            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            delay = _retry_delay(attempt, None, initial_backoff, max_backoff, remaining)
            if delay <= 0:
                raise HTTPRetryError(
                    "HTTP request deadline exceeded before retry.",
                    url=request.full_url,
                    attempts=attempt + 1,
                ) from exc
            time.sleep(delay)

        except OSError as exc:
            error = HTTPRetryError(f"HTTP request failed: {exc}")
            last_error = error

            if attempt >= max_retries:
                raise error from exc

            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            delay = _retry_delay(attempt, None, initial_backoff, max_backoff, remaining)
            if delay <= 0:
                raise HTTPRetryError(
                    "HTTP request deadline exceeded before retry.",
                    url=request.full_url,
                    attempts=attempt + 1,
                ) from exc
            time.sleep(delay)

    if last_error is not None:
        raise last_error
    raise HTTPRetryError("HTTP request failed unexpectedly.")
