from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any, Dict, List
from urllib.parse import urljoin, urlencode
from urllib.request import Request

from .http_retry import HTTPRetryError, fetch_url
from .source_adapters import AdapterResult, normalize_job_record


_HTML_DETAIL_SOURCES = frozenset({
    "NoDesk",
    "EU Remote Jobs",
    "AI Jobs",
    "Total",
    "FlexJobs",
    "US Remotely",
    "Rocketship",
    "JobFill.AI",
    "Remote Woman",
    "Wellfound",
})


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(urljoin(self.base_url, href))


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _jsonld_records(raw: bytes, source: str, url: str) -> List[Dict[str, Any]]:
    text = raw.decode("utf-8", errors="replace")
    records: List[Dict[str, Any]] = []
    for block in re.findall(
        r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
        text,
        flags=re.I | re.S,
    ):
        try:
            payload = json.loads(unescape(block))
        except Exception:
            continue
        for item in _walk(payload):
            schema_type = item.get("@type")
            if schema_type != "JobPosting" and not (
                isinstance(schema_type, list) and "JobPosting" in schema_type
            ):
                continue
            employer = item.get("hiringOrganization") or {}
            company = employer.get("name") if isinstance(employer, dict) else employer
            job_url = item.get("url") or url
            record = normalize_job_record(
                {
                    "title": item.get("title") or item.get("name"),
                    "company": company,
                    "url": job_url,
                    "description": item.get("description"),
                    "location": item.get("jobLocation"),
                    "id": item.get("identifier"),
                },
                source=source,
                source_url=url,
            )
            if record:
                records.append(record)
    return records


def _detail_collect(source: str, listing_url: str, timeout: int) -> AdapterResult:
    request = Request(
        listing_url,
        headers={
            "User-Agent": "Mozilla/5.0 Thorio-Lead-Engine/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    raw = fetch_url(request, timeout=timeout)
    parser = _LinkParser(listing_url)
    parser.feed(raw.decode("utf-8", errors="replace"))

    candidates: List[str] = []
    source_hints = {
        "NoDesk": ("/remote-jobs/",),
        "EU Remote Jobs": ("/job/",),
        "AI Jobs": ("/job/",),
        "Total": ("/jobs/", "/job/"),
        "FlexJobs": ("/remote-jobs/",),
        "US Remotely": ("/job/", "/jobs/"),
        "Rocketship": ("/jobs/", "/job/"),
        "JobFill.AI": ("/job/", "/jobs/"),
        "Remote Woman": ("/job/", "/jobs/"),
        "Wellfound": ("/jobs/",),
    }[source]

    for link in parser.links:
        if link in candidates:
            continue
        if any(hint in link.lower() for hint in source_hints):
            candidates.append(link)
        if len(candidates) >= 40:
            break

    records: Dict[str, Dict[str, Any]] = {}
    for link in candidates:
        try:
            detail = fetch_url(
                Request(
                    link,
                    headers={
                        "User-Agent": "Mozilla/5.0 Thorio-Lead-Engine/1.0",
                        "Accept": "text/html,application/xhtml+xml",
                    },
                ),
                timeout=timeout,
            )
            for record in _jsonld_records(detail, source, link):
                records[record["url"]] = record
        except HTTPRetryError:
            continue
        except Exception:
            continue

    return AdapterResult(records=list(records.values()), checkpoint=None)


class _WelcomeToTheJungleAdapter:
    name = "Welcome to the Jungle"
    source = name
    collector_type = "json"

    def __init__(self, url: str, timeout: int):
        self.url = url
        self.timeout = timeout

    def collect(self, checkpoint=None):
        env_request = Request(
            "https://www.welcometothejungle.com/api/env",
            headers={
                "User-Agent": "Mozilla/5.0 Thorio-Lead-Engine/1.0",
                "Accept": "application/json",
                "Referer": "https://www.welcometothejungle.com/",
            },
        )
        env_raw = fetch_url(env_request, timeout=self.timeout)
        env = json.loads(env_raw.decode("utf-8", errors="replace"))
        values = {}
        for item in _walk(env):
            for key, value in item.items():
                if isinstance(value, str) and value:
                    values[str(key).lower()] = value
        app_id = next((v for k, v in values.items() if "algolia" in k and "app" in k and "id" in k), "")
        api_key = next((v for k, v in values.items() if "algolia" in k and "key" in k), "")
        if not app_id or not api_key:
            raise ValueError("Welcome to the Jungle public Algolia credentials were not found")

        endpoint = "https://%s-dsn.algolia.net/1/indexes/wk_cms_jobs_production/query" % app_id
        params = urlencode({"hitsPerPage": 100, "page": 0, "query": ""})
        payload = json.dumps({"query": "", "hitsPerPage": 100, "page": 0}).encode()
        request = Request(
            endpoint,
            data=payload,
            headers={
                "User-Agent": "Mozilla/5.0 Thorio-Lead-Engine/1.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Algolia-Application-Id": app_id,
                "X-Algolia-API-Key": api_key,
                "Referer": "https://www.welcometothejungle.com/",
            },
        )
        raw = fetch_url(request, timeout=self.timeout)
        data = json.loads(raw.decode("utf-8", errors="replace"))
        hits = data.get("hits", []) if isinstance(data, dict) else []
        records = []
        for hit in hits:
            organization = hit.get("organization") or {}
            company = organization.get("name") if isinstance(organization, dict) else ""
            slug = organization.get("slug") if isinstance(organization, dict) else ""
            job_slug = hit.get("slug") or hit.get("reference") or hit.get("objectID")
            url = hit.get("url") or (
                "https://www.welcometothejungle.com/en/companies/%s/jobs/%s" % (slug, job_slug)
                if slug and job_slug else ""
            )
            record = normalize_job_record(
                {
                    "title": hit.get("name") or hit.get("title"),
                    "company": company,
                    "url": url,
                    "description": (hit.get("descriptions") or {}).get("en", "") if isinstance(hit.get("descriptions"), dict) else hit.get("description"),
                    "id": hit.get("objectID") or hit.get("reference"),
                    "location": (hit.get("office") or {}).get("city", "") if isinstance(hit.get("office"), dict) else "",
                },
                source=self.name,
                source_url=self.url,
            )
            if record:
                records.append(record)
        return AdapterResult(records=records, checkpoint=None)


def install() -> None:
    from . import source_adapters
    original = source_adapters.create_adapter
    if getattr(original, "_thorio_source_specific", False):
        return

    def patched(*, collector_type=None, url=None, source=None, timeout=20, definition=None):
        name = getattr(definition, "name", None) or source or ""
        if name == "Welcome to the Jungle":
            return _WelcomeToTheJungleAdapter(url or "", timeout)
        if name in _HTML_DETAIL_SOURCES:
            return _DetailAdapter(name, url or "", timeout)
        return original(
            collector_type=collector_type,
            url=url,
            source=source,
            timeout=timeout,
            definition=definition,
        )

    class _DetailAdapter:
        def __init__(self, name: str, url: str, timeout: int):
            self.name = name
            self.source = name
            self.url = url
            self.collector_type = "html"
            self.timeout = timeout

        def collect(self, checkpoint=None):
            return _detail_collect(self.name, self.url, self.timeout)

    patched._thorio_source_specific = True
    source_adapters.create_adapter = patched
