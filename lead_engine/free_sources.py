import re
from typing import Any, Dict, Iterable, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USER_AGENT = "Thorio-Lead-Engine/1.0"

REMOTE_JOB_TERMS = (
    "remote",
    "work from home",
    "distributed",
)

TECH_JOB_TERMS = (
    "software",
    "developer",
    "engineer",
    "engineering",
    "data",
    "machine learning",
    "artificial intelligence",
    "ai",
    "devops",
    "cloud",
    "platform",
    "product manager",
    "product designer",
    "ux",
    "ui",
)


class FreeSourceError(Exception):
    """Raised when a free public source cannot be collected."""


class FreeJobSource:
    """
    Lightweight collector for a public job-board page.

    This adapter intentionally uses only standard-library HTTP
    functionality. It does not require a paid API, scraping service,
    proxy, database, or third-party package.

    The adapter extracts obvious job-like links and converts them
    into the normalized source-record format expected downstream.
    """

    def __init__(
        self,
        name: str,
        url: str,
        timeout: int = 20,
    ):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Source name is required.")

        if not isinstance(url, str) or not url.strip():
            raise ValueError("Source URL is required.")

        if not isinstance(timeout, int) or isinstance(timeout, bool):
            raise ValueError(
                "Source timeout must be an integer."
            )

        if timeout <= 0:
            raise ValueError(
                "Source timeout must be positive."
            )

        self.name = name.strip()
        self.url = url.strip()
        self.timeout = timeout

    def _fetch(self) -> str:
        request = Request(
            self.url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/json"
                ),
            },
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout,
            ) as response:
                raw = response.read()

        except HTTPError as exc:
            raise FreeSourceError(
                f"{self.name} returned HTTP {exc.code}."
            ) from exc

        except URLError as exc:
            raise FreeSourceError(
                f"{self.name} connection failed: {exc.reason}"
            ) from exc

        except TimeoutError as exc:
            raise FreeSourceError(
                f"{self.name} request timed out."
            ) from exc

        except OSError as exc:
            raise FreeSourceError(
                f"{self.name} request failed: {exc}"
            ) from exc

        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FreeSourceError(
                f"{self.name} returned invalid UTF-8."
            ) from exc

    @staticmethod
    def _strip_html(value: str) -> str:
        value = re.sub(
            r"<script\b[^>]*>.*?</script>",
            " ",
            value,
            flags=re.IGNORECASE | re.DOTALL,
        )

        value = re.sub(
            r"<style\b[^>]*>.*?</style>",
            " ",
            value,
            flags=re.IGNORECASE | re.DOTALL,
        )

        value = re.sub(
            r"<[^>]+>",
            " ",
            value,
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value.strip()

    @staticmethod
    def _is_technology_job(text: str) -> bool:
        lowered = text.lower()

        has_remote = any(
            term in lowered
            for term in REMOTE_JOB_TERMS
        )

        has_technology = any(
            term in lowered
            for term in TECH_JOB_TERMS
        )

        return has_remote and has_technology

    def _extract_links(
        self,
        html: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        pattern = re.compile(
            r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>'
            r"(.*?)"
            r"</a>",
            flags=re.IGNORECASE | re.DOTALL,
        )

        for href, anchor in pattern.findall(html):
            title = self._strip_html(anchor)

            if not title:
                continue

            if not self._is_technology_job(title):
                continue

            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                base = self.url.rstrip("/")
                href = base + href
            elif not href.startswith(
                ("http://", "https://")
            ):
                continue

            records.append(
                {
                    "source": self.name,
                    "source_id": href,
                    "company": "",
                    "signal": title,
                    "evidence": (
                        f"Public listing discovered from "
                        f"{self.name}."
                    ),
                    "url": href,
                }
            )

        return records

    def collect(self) -> Iterable[Dict[str, Any]]:
        html = self._fetch()

        records = self._extract_links(html)

        # Never make an empty source failure.
        # A source can legitimately have no matching listings.
        return records


def collect_free_source(
    name: str,
    url: str,
    timeout: int = 20,
) -> List[Dict[str, Any]]:
    """
    Collect normalized records from one free public source.
    """

    return list(
        FreeJobSource(
            name=name,
            url=url,
            timeout=timeout,
        ).collect()
    )


if __name__ == "__main__":
    print(
        "Free public source adapter loaded."
    )
