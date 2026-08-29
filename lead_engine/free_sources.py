import json
import re
from html import unescape
from typing import Any, Dict, Iterable, List, Optional
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
    "fully remote",
    "100% remote",
)

TECH_JOB_TERMS = (
    "software",
    "developer",
    "engineer",
    "engineering",
    "data",
    "data scientist",
    "data engineer",
    "machine learning",
    "artificial intelligence",
    "ai",
    "devops",
    "cloud",
    "platform",
    "backend",
    "back-end",
    "frontend",
    "front-end",
    "full stack",
    "full-stack",
    "mobile",
    "ios",
    "android",
    "cybersecurity",
    "security engineer",
    "site reliability",
    "sre",
    "qa engineer",
    "quality assurance",
    "software architect",
    "solutions architect",
    "product manager",
    "product designer",
    "ux",
    "ui",
    "technical",
    "technology",
    "tech",
)

JOB_URL_TERMS = (
    "/job/",
    "/jobs/",
    "/job-",
    "/jobs-",
    "/careers/",
    "/career/",
    "/vacancy/",
    "/vacancies/",
    "/position/",
    "/positions/",
    "/opening/",
    "/openings/",
    "/opportunity/",
    "/opportunities/",
    "/role/",
    "/roles/",
    "/apply/",
    "/listing/",
    "/listings/",
)

JOB_TEXT_TERMS = (
    "job",
    "jobs",
    "career",
    "careers",
    "vacancy",
    "vacancies",
    "position",
    "positions",
    "opening",
    "openings",
    "opportunity",
    "opportunities",
    "role",
    "roles",
    "apply",
    "application",
    "hiring",
    "we are hiring",
    "join our team",
)

MAX_RECORDS_PER_PAGE = 500
MAX_TEXT_LENGTH = 5000
MAX_TITLE_LENGTH = 300
MAX_COMPANY_LENGTH = 200


class FreeSourceError(Exception):
    """Raised when a free public source cannot be collected."""


class FreeJobSource:
    """
    Free public job-board collector.

    The collector is intentionally discovery-oriented. It does not
    qualify, score, route, deduplicate against the database, or sync
    to Airtable. Those responsibilities remain downstream.

    The collector uses only Python's standard library and public
    pages. It supports several common job-board structures instead
    of requiring the anchor text itself to contain every signal.
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

    def collect(self) -> List[Dict[str, Any]]:
        html = self._fetch()

        records = []

        records.extend(
            self._extract_json_ld(html)
        )

        records.extend(
            self._extract_links(
                html,
                self.url,
                self.name,
            )
        )

        seen = set()
        collected = []

        for record in records:
            if not isinstance(record, dict):
                continue

            record["source"] = self.name

            key = self._record_key(record)

            if not key or key in seen:
                continue

            seen.add(key)
            collected.append(record)

            if len(collected) >= MAX_RECORDS_PER_PAGE:
                break

        return collected
        
    def _fetch(self) -> str:
        request = Request(
            self.url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/json"
                ),
                "Accept-Language": "en-US,en;q=0.8",
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
            return raw.decode("utf-8", errors="replace")
        except Exception as exc:
            raise FreeSourceError(
                f"{self.name} response could not be decoded."
            ) from exc

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""

        text = unescape(str(value))

        text = re.sub(
            r"<script\b[^>]*>.*?</script>",
            " ",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        text = re.sub(
            r"<style\b[^>]*>.*?</style>",
            " ",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        text = re.sub(
            r"<noscript\b[^>]*>.*?</noscript>",
            " ",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        text = re.sub(
            r"<[^>]+>",
            " ",
            text,
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        return text.strip()

    @staticmethod
    def _strip_html(value: str) -> str:
        return FreeJobSource._clean_text(value)

    @staticmethod
    def _normalize_url(
        href: str,
        base_url: str,
    ) -> str:
        href = unescape(str(href)).strip()

        if not href:
            return ""

        if href.startswith("#"):
            return ""

        if href.startswith(
            (
                "javascript:",
                "mailto:",
                "tel:",
                "data:",
            )
        ):
            return ""

        return urljoin(
            base_url,
            href,
        )

    @staticmethod
    def _url_is_http(url: str) -> bool:
        try:
            return urlparse(url).scheme.lower() in (
                "http",
                "https",
            )
        except Exception:
            return False

    @staticmethod
    def _contains_any(
        text: str,
        terms: Iterable[str],
    ) -> bool:
        lowered = text.lower()

        return any(
            term in lowered
            for term in terms
        )

    @classmethod
    def _has_remote_signal(
        cls,
        text: str,
    ) -> bool:
        return cls._contains_any(
            text,
            REMOTE_JOB_TERMS,
        )

    @classmethod
    def _has_technology_signal(
        cls,
        text: str,
    ) -> bool:
        return cls._contains_any(
            text,
            TECH_JOB_TERMS,
        )

    @classmethod
    def _looks_like_job_url(
        cls,
        url: str,
    ) -> bool:
        lowered = url.lower()

        return any(
            term in lowered
            for term in JOB_URL_TERMS
        )

    @classmethod
    def _looks_like_job_text(
        cls,
        text: str,
    ) -> bool:
        return cls._contains_any(
            text,
            JOB_TEXT_TERMS,
        )

    @classmethod
    def _is_technology_job(
        cls,
        text: str,
    ) -> bool:
        """
        Preserve the original public behavior for callers that use
        this helper directly.

        A text-only candidate is considered a technology job only
        when both remote and technology signals are present.
        Broader discovery is handled by _extract_links and
        _extract_json_ld.
        """

        return (
            cls._has_remote_signal(text)
            and cls._has_technology_signal(text)
        )

    @staticmethod
    def _first_nonempty(
        *values: Any,
    ) -> str:
        for value in values:
            cleaned = FreeJobSource._clean_text(
                value
            )

            if cleaned:
                return cleaned

        return ""

    @staticmethod
    def _truncate(
        value: str,
        maximum: int,
    ) -> str:
        value = value.strip()

        if len(value) <= maximum:
            return value

        return value[: maximum - 1].rstrip() + "…"

    @classmethod
    def _extract_company(
        cls,
        attrs: str,
        body: str,
    ) -> str:
        patterns = (
            r'data-company=["\']([^"\']+)["\']',
            r'data-employer=["\']([^"\']+)["\']',
            r'data-company-name=["\']([^"\']+)["\']',
            r'company-name[^>]*>\s*([^<]+)',
            r'employer-name[^>]*>\s*([^<]+)',
            r'company[^>]*>\s*([^<]+)',
            r'employer[^>]*>\s*([^<]+)',
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                attrs + " " + body,
                flags=re.IGNORECASE,
            )

            if match:
                company = cls._clean_text(
                    match.group(1)
                )

                if company:
                    return cls._truncate(
                        company,
                        MAX_COMPANY_LENGTH,
                    )

        return ""

    @classmethod
    def _extract_title_from_context(
        cls,
        anchor_text: str,
        surrounding: str,
        url: str,
    ) -> str:
        title = cls._clean_text(
            anchor_text
        )

        if title and not cls._looks_like_job_text(title):
            return cls._truncate(
                title,
                MAX_TITLE_LENGTH,
            )

        heading_patterns = (
            r"<h1\b[^>]*>(.*?)</h1>",
            r"<h2\b[^>]*>(.*?)</h2>",
            r"<h3\b[^>]*>(.*?)</h3>",
            r"<h4\b[^>]*>(.*?)</h4>",
        )

        for pattern in heading_patterns:
            match = re.search(
                pattern,
                surrounding,
                flags=re.IGNORECASE | re.DOTALL,
            )

            if match:
                heading = cls._clean_text(
                    match.group(1)
                )

                if heading:
                    return cls._truncate(
                        heading,
                        MAX_TITLE_LENGTH,
                    )

        path = urlparse(url).path

        segments = [
            segment
            for segment in path.split("/")
            if segment
        ]

        if segments:
            candidate = segments[-1]

            candidate = re.sub(
                r"\.(html?|php|aspx?)$",
                "",
                candidate,
                flags=re.IGNORECASE,
            )

            candidate = re.sub(
                r"[-_]+",
                " ",
                candidate,
            )

            candidate = cls._clean_text(
                candidate
            )

            if candidate:
                return cls._truncate(
                    candidate,
                    MAX_TITLE_LENGTH,
                )

        return ""

    @classmethod
    def _candidate_is_useful(
        cls,
        title: str,
        context: str,
        url: str,
    ) -> bool:
        combined = " ".join(
            value
            for value in (
                title,
                context,
                url,
            )
            if value
        )

        if not cls._has_technology_signal(
            combined
        ):
            return False

        if (
            cls._has_remote_signal(combined)
            or cls._looks_like_job_url(url)
            or cls._looks_like_job_text(title)
        ):
            return True

        return False

    @staticmethod
    def _record_key(
        record: Dict[str, Any],
    ) -> str:
        url = str(
            record.get("url") or ""
        ).strip().lower()

        if url:
            return url

        return (
            str(
                record.get("source_id")
                or ""
            )
            .strip()
            .lower()
        )

    @classmethod
    def _make_record(
        cls,
        *,
        url: str,
        title: str,
        company: str,
        evidence: str,
    ) -> Optional[Dict[str, Any]]:
        if not url:
            return None

        if not cls._url_is_http(url):
            return None

        title = cls._truncate(
            cls._clean_text(title),
            MAX_TITLE_LENGTH,
        )

        company = cls._truncate(
            cls._clean_text(company),
            MAX_COMPANY_LENGTH,
        )

        evidence = cls._truncate(
            cls._clean_text(evidence),
            MAX_TEXT_LENGTH,
        )

        if not title:
            title = "Remote technology job listing"

        return {
            "source": "",
            "source_id": url,
            "company": company,
            "signal": title,
            "evidence": evidence,
            "url": url,
        }

    @classmethod
    def _extract_json_ld(
        cls,
        html: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        pattern = re.compile(
            r'<script\b[^>]*type\s*=\s*'
            r'["\']application/ld\+json["\']'
            r'[^>]*>(.*?)</script>',
            flags=re.IGNORECASE | re.DOTALL,
        )

        for raw_json in pattern.findall(html):
            raw_json = raw_json.strip()

            if not raw_json:
                continue

            try:
                data = json.loads(
                    unescape(raw_json)
                )
            except (
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ):
                continue

            objects: List[Any] = []

            if isinstance(data, list):
                objects.extend(data)

            elif isinstance(data, dict):
                objects.append(data)

                graph = data.get("@graph")

                if isinstance(graph, list):
                    objects.extend(graph)

            for item in objects:
                if not isinstance(item, dict):
                    continue

                item_type = item.get("@type")

                if isinstance(item_type, list):
                    is_job = any(
                        str(value).lower()
                        == "jobposting"
                        for value in item_type
                    )
                else:
                    is_job = (
                        str(item_type).lower()
                        == "jobposting"
                    )

                if not is_job:
                    continue

                title = cls._first_nonempty(
                    item.get("title"),
                    item.get("name"),
                )

                description = cls._clean_text(
                    item.get("description")
                )

                url = cls._first_nonempty(
                    item.get("url"),
                    item.get("sameAs"),
                )

                if not url:
                    url = self_url = ""

                if not cls._url_is_http(url):
                    continue

                company = ""

                hiring = item.get(
                    "hiringOrganization"
                )

                if isinstance(
                    hiring,
                    dict,
                ):
                    company = cls._first_nonempty(
                        hiring.get("name"),
                    )

                elif isinstance(hiring, str):
                    company = cls._clean_text(
                        hiring
                    )

                location_text = ""

                job_location = item.get(
                    "jobLocation"
                )

                if isinstance(
                    job_location,
                    dict,
                ):
                    address = job_location.get(
                        "address"
                    )

                    if isinstance(
                        address,
                        dict,
                    ):
                        location_text = (
                            cls._first_nonempty(
                                address.get(
                                    "addressLocality"
                                ),
                                address.get(
                                    "addressRegion"
                                ),
                                address.get(
                                    "addressCountry"
                                ),
                            )
                        )

                    else:
                        location_text = (
                            cls._clean_text(
                                address
                            )
                        )

                elif isinstance(
                    job_location,
                    list,
                ):
                    location_text = cls._clean_text(
                        " ".join(
                            cls._clean_text(
                                location
                            )
                            if not isinstance(
                                location,
                                dict,
                            )
                            else cls._clean_text(
                                location.get(
                                    "address"
                                )
                            )
                            for location in job_location
                        )
                    )

                remote_value = (
                    item.get("jobLocationType")
                    or item.get(
                        "workplaceType"
                    )
                    or ""
                )

                context = " ".join(
                    value
                    for value in (
                        title,
                        description,
                        location_text,
                        cls._clean_text(
                            remote_value
                        ),
                    )
                    if value
                )

                if not cls._has_technology_signal(
                    context
                ):
                    continue

                if not (
                    cls._has_remote_signal(
                        context
                    )
                    or "remote" in context.lower()
                    or "anywhere" in context.lower()
                ):
                    continue

                record = cls._make_record(
                    url=url,
                    title=title,
                    company=company,
                    evidence=(
                        f"JobPosting structured data "
                        f"discovered from {self.name}."
                    ),
                )

                if record:
                    records.append(record)

                if len(records) >= MAX_RECORDS_PER_PAGE:
                    break

            if len(records) >= MAX_RECORDS_PER_PAGE:
                break

        return records

    @classmethod
    def _extract_links(
        cls,
        html: str,
        base_url: str,
        source_name: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        pattern = re.compile(
            r'<a\b([^>]*?)href\s*=\s*'
            r'(["\'])(.*?)\2([^>]*)>'
            r'(.*?)</a>',
            flags=re.IGNORECASE | re.DOTALL,
        )

        for (
            before,
            _quote,
            href,
            after,
            anchor,
        ) in pattern.findall(html):
            url = cls._normalize_url(
                href,
                base_url,
            )

            if not cls._url_is_http(url):
                continue

        
