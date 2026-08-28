import html
import re
from typing import Any, Dict, Iterable, List
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


USER_AGENT = "Thorio-Lead-Engine/1.0"

REMOTE_JOB_TERMS = (
    "remote",
    "work from home",
    "work-from-home",
    "distributed",
    "anywhere",
    "remote-first",
    "remote first",
)

TECH_JOB_TERMS = (
    "software",
    "developer",
    "engineer",
    "engineering",
    "data",
    "machine learning",
    "machine-learning",
    "artificial intelligence",
    "artificial-intelligence",
    "ai",
    "devops",
    "cloud",
    "platform",
    "product manager",
    "product designer",
    "ux",
    "ui",
    "technical",
    "technology",
)

JOB_TITLE_TERMS = (
    "engineer",
    "developer",
    "software",
    "data scientist",
    "data analyst",
    "data engineer",
    "machine learning",
    "artificial intelligence",
    "ai engineer",
    "devops",
    "cloud engineer",
    "platform engineer",
    "product manager",
    "product designer",
    "ux designer",
    "ui designer",
    "technical",
)

JOB_URL_TERMS = (
    "/job",
    "/jobs",
    "/career",
    "/careers",
    "/position",
    "/positions",
    "/opening",
    "/openings",
    "/vacancy",
    "/vacancies",
    "/apply",
)


class FreeSourceError(Exception):
    """Raised when a free public source cannot be collected."""


class FreeJobSource:
    """
    Lightweight collector for public job-board pages.

    Uses only Python standard-library functionality.

    The collector is intentionally conservative about what it sends
    downstream. It discovers likely remote technology job listings,
    preserves the original listing URL, and leaves qualification,
    routing, scoring, deduplication, and outreach decisions to later
    stages of the pipeline.
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

        except UnicodeDecodeError:
            try:
                return raw.decode("latin-1")

            except UnicodeDecodeError as exc:
                raise FreeSourceError(
                    f"{self.name} returned unreadable text."
                ) from exc

    @staticmethod
    def _strip_html(value: str) -> str:
        value = html.unescape(value)

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
            r"<noscript\b[^>]*>.*?</noscript>",
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
    def _page_text(html_content: str) -> str:
        return FreeJobSource._strip_html(
            html_content
        ).lower()

    @staticmethod
    def _contains_remote(text: str) -> bool:
        lowered = text.lower()

        return any(
            term in lowered
            for term in REMOTE_JOB_TERMS
        )

    @staticmethod
    def _contains_technology(text: str) -> bool:
        lowered = text.lower()

        return any(
            term in lowered
            for term in TECH_JOB_TERMS
        )

    @staticmethod
    def _contains_job_title(text: str) -> bool:
        lowered = text.lower()

        return any(
            term in lowered
            for term in JOB_TITLE_TERMS
        )

    @staticmethod
    def _looks_like_job_url(url: str) -> bool:
        lowered = url.lower()

        return any(
            term in lowered
            for term in JOB_URL_TERMS
        )

    @staticmethod
    def _is_http_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
        except ValueError:
            return False

        return parsed.scheme in {
            "http",
            "https",
        } and bool(parsed.netloc)

    def _absolute_url(self, href: str) -> str:
        href = html.unescape(
            href.strip()
        )

        if not href:
            return ""

        absolute = urljoin(
            self.url,
            href,
        )

        if not self._is_http_url(absolute):
            return ""

        return absolute

    @staticmethod
    def _clean_title(title: str) -> str:
        title = FreeJobSource._strip_html(title)

        title = re.sub(
            r"\s+",
            " ",
            title,
        )

        return title.strip()

    @staticmethod
    def _extract_company(
        title: str,
        context: str,
    ) -> str:
        """
        Extract an obvious company name when a source places it
        directly in the listing text.

        This intentionally returns an empty value when the company
        cannot be identified safely. Downstream enrichment can handle
        the missing company instead of inventing one.
        """

        patterns = (
            r"\bat\s+([A-Z][A-Za-z0-9&.,' -]{1,80})",
            r"\b@\s*([A-Z][A-Za-z0-9&.,' -]{1,80})",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                title,
            )

            if match:
                company = match.group(1).strip(
                    " .,-"
                )

                if company:
                    return company

        for pattern in patterns:
            match = re.search(
                pattern,
                context,
            )

            if match:
                company = match.group(1).strip(
                    " .,-"
                )

                if company:
                    return company

        return ""

    @staticmethod
    def _candidate_score(
        title: str,
        context: str,
        href: str,
    ) -> int:
        text = " ".join(
            [
                title,
                context,
                href,
            ]
        ).lower()

        score = 0

        if FreeJobSource._contains_remote(text):
            score += 2

        if FreeJobSource._contains_technology(text):
            score += 2

        if FreeJobSource._contains_job_title(title):
            score += 3

        if FreeJobSource._looks_like_job_url(href):
            score += 1

        return score

    def _extract_links(
        self,
        html_content: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        seen_urls = set()

        pattern = re.compile(
            r"<a\b"
            r"[^>]*?"
            r"href\s*=\s*"
            r"[\"']"
            r"([^\"']+)"
            r"[\"']"
            r"[^>]*>"
            r"(.*?)"
            r"</a>",
            flags=re.IGNORECASE | re.DOTALL,
        )

        matches = pattern.findall(
            html_content
        )

        for href, anchor in matches:
            title = self._clean_title(
                anchor
            )

            absolute_url = self._absolute_url(
                href
            )

            if not title or not absolute_url:
                continue

            if absolute_url in seen_urls:
                continue

            context = self._clean_title(
                html_content[
                    max(
                        0,
                        html_content.find(anchor) - 500,
                    ):
                    html_content.find(anchor)
                    + len(anchor)
                    + 500
                ]
            )

            score = self._candidate_score(
                title,
                context,
                absolute_url,
            )

            if score < 4:
                continue

            combined = " ".join(
                [
                    title,
                    context,
                    absolute_url,
                ]
            )

            if not self._contains_remote(
                combined
            ):
                continue

            if not self._contains_technology(
                combined
            ):
                continue

            company = self._extract_company(
                title,
                context,
            )

            seen_urls.add(
                absolute_url
            )

            records.append(
                {
                    "source": self.name,
                    "source_id": absolute_url,
                    "company": company,
                    "signal": title,
                    "evidence": (
                        f"Remote technology job listing "
                        f"discovered from {self.name}."
                    ),
                    "url": absolute_url,
                }
            )

        return records

    def _extract_json_ld_jobs(
        self,
        html_content: str,
    ) -> List[Dict[str, Any]]:
        """
        Discover JobPosting structured-data records when a site
        exposes them.

        Invalid or unrelated JSON-LD is ignored safely.
        """

        records: List[Dict[str, Any]] = []

        pattern = re.compile(
            r"<script\b[^>]*"
            r"type\s*=\s*[\"']application/ld\+json[
