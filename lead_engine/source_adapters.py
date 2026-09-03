from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin
from urllib.request import Request
from xml.etree import ElementTree

from .http_retry import HTTPRetryError, fetch_url


@dataclass(frozen=True)
class AdapterResult:
    records: List[Dict[str, Any]]
    checkpoint: Optional[str] = None


def _text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _first_text(
    item: Dict[str, Any],
    *keys: str,
) -> str:
    for key in keys:
        value = item.get(key)

        if value is None:
            continue

        text = _text(value)

        if text:
            return text

    return ""


def _first_url(
    item: Dict[str, Any],
    *keys: str,
) -> str:
    for key in keys:
        value = item.get(key)

        if isinstance(value, dict):
            value = (
                value.get("url")
                or value.get("href")
            )

        url = _text(value)

        if url.startswith(
            ("http://", "https://")
        ):
            return url

    return ""


def _json_records(
    payload: Any,
) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [
            item
            for item in payload
            if isinstance(item, dict)
        ]

    if not isinstance(payload, dict):
        raise ValueError(
            "JSON source must return an object or list."
        )

    for key in (
        "leads",
        "jobs",
        "results",
        "items",
        "postings",
    ):
        value = payload.get(key)

        if isinstance(value, list):
            return [
                item
                for item in value
                if isinstance(item, dict)
            ]

    data = payload.get("data")

    if isinstance(data, dict):
        for key in (
            "jobs",
            "results",
            "items",
            "postings",
        ):
            value = data.get(key)

            if isinstance(value, list):
                return [
                    item
                    for item in value
                    if isinstance(item, dict)
                ]

    raise ValueError(
        "JSON source did not contain a supported record list."
    )


def normalize_job_record(
    item: Dict[str, Any],
    *,
    source: str,
    source_url: str,
) -> Optional[Dict[str, Any]]:
    title = _first_text(
        item,
        "title",
        "name",
        "job_title",
        "position",
        "role",
    )

    company = _first_text(
        item,
        "company",
        "company_name",
        "employer",
        "organization",
        "org",
    )

    url = _first_url(
        item,
        "url",
        "job_url",
        "apply_url",
        "link",
        "absolute_url",
        "jobUrl",
    )

    if not title or not company or not url:
        return None

    source_id = _first_text(
        item,
        "id",
        "job_id",
        "uuid",
        "slug",
        "requisition_id",
        "jobId",
    )

    if not source_id:
        source_id = url

    description = _first_text(
        item,
        "description",
        "content",
        "summary",
        "excerpt",
    )

    location = _first_text(
        item,
        "location",
        "locations",
        "candidate_required_location",
        "geo",
    )

    employment_type = _first_text(
        item,
        "type",
        "employment_type",
        "job_type",
    )

    signal_parts = [
        title,
        company,
    ]

    if location:
        signal_parts.append(location)

    if employment_type:
        signal_parts.append(
            employment_type
        )

    evidence_parts = [
        f"Title: {title}",
        f"Company: {company}",
    ]

    if description:
        evidence_parts.append(
            "Description: "
            f"{description[:4000]}"
        )

    if location:
        evidence_parts.append(
            f"Location: {location}"
        )

    return {
        "source": source,
        "source_id": source_id,
        "url": url,
        "company": company,
        "signal": " | ".join(
            signal_parts
        ),
        "evidence": "\n".join(
            evidence_parts
        ),
        "signal_type": "hiring",
        "source_url": source_url,
        "job_title": title,
    }


class JsonSourceAdapter:
    def __init__(
        self,
        url: str,
        source: str,
        timeout: int = 20,
    ):
        if not url.strip():
            raise ValueError(
                "JSON source URL is required."
            )

        if not source.strip():
            raise ValueError(
                "JSON source name is required."
            )

        if timeout <= 0:
            raise ValueError(
                "JSON source timeout must be positive."
            )

        self.url = url.strip()
        self.name = source.strip()
        self.source = self.name
        self.timeout = timeout

    def collect(self) -> AdapterResult:
        request = Request(
            self.url,
            headers={
                "User-Agent":
                    "Thorio-Lead-Engine/1.0",
                "Accept":
                    "application/json",
            },
        )

        try:
            raw = fetch_url(
                request,
                timeout=self.timeout,
            )
        except HTTPRetryError as exc:
            raise ValueError(
                f"JSON source request failed: {exc}"
            ) from exc

        try:
            payload = json.loads(
                raw.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                "JSON source returned invalid UTF-8 JSON."
            ) from exc

        records = _json_records(
            payload
        )

        normalized = []

        for item in records:
            record = normalize_job_record(
                item,
                source=self.source,
                source_url=self.url,
            )

            if record is not None:
                normalized.append(record)

        checkpoint = None

        if isinstance(payload, dict):
            checkpoint = _first_text(
                payload,
                "nextCursor",
                "next_cursor",
                "nextPage",
                "next_page",
                "cursor",
            )

        return AdapterResult(
            records=normalized,
            checkpoint=checkpoint or None,
        )


class RssSourceAdapter:
    def __init__(
        self,
        url: str,
        source: str,
        timeout: int = 20,
    ):
        if not url.strip():
            raise ValueError(
                "RSS source URL is required."
            )

        if not source.strip():
            raise ValueError(
                "RSS source name is required."
            )

        if timeout <= 0:
            raise ValueError(
                "RSS source timeout must be positive."
            )

        self.url = url.strip()
        self.name = source.strip()
        self.source = self.name
        self.timeout = timeout

    def collect(self) -> AdapterResult:
        request = Request(
            self.url,
            headers={
                "User-Agent":
                    "Thorio-Lead-Engine/1.0",
                "Accept": (
                    "application/rss+xml, "
                    "application/atom+xml, "
                    "application/xml, "
                    "text/xml"
                ),
            },
        )

        try:
            raw = fetch_url(
                request,
                timeout=self.timeout,
            )
        except HTTPRetryError as exc:
            raise ValueError(
                f"RSS source request failed: {exc}"
            ) from exc

        try:
            root = ElementTree.fromstring(
                raw
            )
        except ElementTree.ParseError as exc:
            raise ValueError(
                "RSS source returned invalid XML."
            ) from exc

        records = []

        for item in root.iter():
            tag = (
                item.tag
                .split("}")[-1]
                .lower()
            )

            if tag not in {
                "item",
                "entry",
            }:
                continue

            values: Dict[str, str] = {}

            for child in item:
                child_tag = (
                    child.tag
                    .split("}")[-1]
                    .lower()
                )

                if child_tag == "link":
                    href = child.attrib.get(
                        "href"
                    )

                    if href:
                        values["link"] = urljoin(
                            self.url,
                            href,
                        )
                    elif child.text:
                        values["link"] = urljoin(
                            self.url,
                            child.text.strip(),
                        )

                    continue

                if child.text:
                    values[child_tag] = (
                        child.text.strip()
                    )

            title = values.get(
                "title",
                "",
            )

            link = values.get(
                "link",
                "",
            )

            if not title or not link:
                continue

            description = (
                values.get("description")
                or values.get("summary")
                or values.get("content")
                or ""
            )

            source_id = (
                values.get("guid")
                or values.get("id")
                or link
            )

            records.append(
                {
                    "source": self.source,
                    "source_id": source_id,
                    "url": link,
                    "company": (
                        values.get("company")
                        or values.get("author")
                        or self.source
                    ),
                    "signal": title,
                    "evidence": (
                        f"Title: {title}\n"
                        "Description: "
                        f"{description[:4000]}"
                    ),
                    "signal_type": "hiring",
                    "source_url": self.url,
                    "job_title": title,
                }
            )

        return AdapterResult(
            records=records,
        )


class HtmlSourceAdapter:
    JOB_HINTS = (
        "software",
        "engineer",
        "developer",
        "engineering",
        "data",
        "machine learning",
        "artificial intelligence",
        "cybersecurity",
        "devops",
        "cloud",
        "product manager",
        "technical",
        "technology",
        "mobile",
        "frontend",
        "backend",
        "full stack",
    )

    def __init__(
        self,
        url: str,
        source: str,
        timeout: int = 20,
    ):
        if not url.strip():
            raise ValueError(
                "HTML source URL is required."
            )

        if not source.strip():
            raise ValueError(
                "HTML source name is required."
            )

        if timeout <= 0:
            raise ValueError(
                "HTML source timeout must be positive."
            )

        self.url = url.strip()
        self.name = source.strip()
        self.source = self.name
        self.timeout = timeout

    def collect(self) -> AdapterResult:
        request = Request(
            self.url,
            headers={
                "User-Agent":
                    "Thorio-Lead-Engine/1.0",
                "Accept": "text/html",
            },
        )

        try:
            raw = fetch_url(
                request,
                timeout=self.timeout,
            )
        except HTTPRetryError as exc:
            raise ValueError(
                f"HTML source request failed: {exc}"
            ) from exc

        html = raw.decode(
            "utf-8",
            errors="replace",
        )

        links = re.findall(
            r'href=["\']([^"\']+)["\']',
            html,
            flags=re.IGNORECASE,
        )

        records = []

        for link in links:
            absolute_url = urljoin(
                self.url,
                link,
            )

            lowered = (
                absolute_url.lower()
            )

            if not any(
                hint in lowered
                for hint in (
                    "/job",
                    "/jobs/",
                    "/position",
                    "/career",
                    "/careers",
                    "/opening",
                    "/vacanc",
                )
            ):
                continue

            title = (
                link
                .rsplit("/", 1)[-1]
                .replace("-", " ")
                .replace("_", " ")
                .strip()
            )

            if not title:
                continue

            if not any(
                hint in title.lower()
                for hint in self.JOB_HINTS
            ):
                continue

            records.append(
                {
                    "source": self.source,
                    "source_id": absolute_url,
                    "url": absolute_url,
                    "company": self.source,
                    "signal": title,
                    "evidence": (
                        "Public job URL discovered "
                        f"from {self.url}: "
                        f"{absolute_url}"
                    ),
                    "signal_type": "hiring",
                    "source_url": self.url,
                    "job_title": title,
                }
            )

        return AdapterResult(
            records=records,
        )


class AdapterLeadSource:
    """
    Compatibility wrapper implementing the source
    interface expected by the existing scheduler.
    """

    def __init__(
        self,
        adapter: Any,
        name: str,
    ):
        if adapter is None:
            raise ValueError(
                "Adapter is required."
            )

        if not isinstance(
            name,
            str,
        ) or not name.strip():
            raise ValueError(
                "Source name is required."
            )

        self.adapter = adapter
        self.name = name.strip()

        if hasattr(
            adapter,
            "url",
        ):
            self.url = adapter.url

    def collect(
        self,
    ) -> Iterable[Dict[str, Any]]:
        result = self.adapter.collect()

        if not isinstance(
            result,
            AdapterResult,
        ):
            raise ValueError(
                "Source adapter returned an invalid result."
            )

        return result.records


def create_adapter(
    *,
    collector_type: str,
    url: str,
    source: str,
    timeout: int = 20,
) -> AdapterLeadSource:
    collector = (
        collector_type
        .strip()
        .lower()
    )

    if collector == "json":
        adapter = JsonSourceAdapter(
            url=url,
            source=source,
            timeout=timeout,
        )

    elif collector in {
        "rss",
        "atom",
        "xml",
    }:
        adapter = RssSourceAdapter(
            url=url,
            source=source,
            timeout=timeout,
        )

    elif collector == "html":
        adapter = HtmlSourceAdapter(
            url=url,
            source=source,
            timeout=timeout,
        )

    else:
        raise ValueError(
            "Unsupported collector type: "
            f"{collector_type}"
        )

    return AdapterLeadSource(
        adapter=adapter,
        name=source,
    )
