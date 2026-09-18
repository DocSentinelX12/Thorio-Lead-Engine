from __future__ import annotations

import json
import os
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any, Dict, List
from urllib.parse import urljoin, urlencode
from urllib.request import Request
from xml.etree import ElementTree

from .http_retry import HTTPRetryError, fetch_url
from .source_adapters import AdapterLeadSource, AdapterResult, RssSourceAdapter, normalize_job_record


_HTML_DETAIL_SOURCES = frozenset({
    "NoDesk", "EU Remote Jobs", "AI Jobs", "Total", "FlexJobs", "US Remotely",
    "USA Remote Work", "Rocketship", "Remote Landers", "JobFill.AI", "Remote Woman", "Wellfound",
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


def _jsonld_records(raw: bytes, source: str, url: str) -> List[Dict[str, Any]]:
    text = raw.decode("utf-8", errors="replace")
    records: List[Dict[str, Any]] = []
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', text, flags=re.I | re.S):
        try:
            payload = json.loads(unescape(block))
        except Exception:
            continue
        for item in _walk(payload):
            schema_type = item.get("@type")
            if schema_type != "JobPosting" and not (isinstance(schema_type, list) and "JobPosting" in schema_type):
                continue
            employer = item.get("hiringOrganization") or {}
            company = employer.get("name") if isinstance(employer, dict) else employer
            record = normalize_job_record(
                {"title": item.get("title") or item.get("name"), "company": company,
                 "url": item.get("url") or url, "description": item.get("description"),
                 "location": item.get("jobLocation"), "id": item.get("identifier")},
                source=source, source_url=url,
            )
            if record:
                records.append(record)
    return records


def _detail_collect(source: str, listing_url: str, timeout: int) -> AdapterResult:
    raw = fetch_url(Request(listing_url, headers={"User-Agent": "Mozilla/5.0 Thorio-Lead-Engine/1.0", "Accept": "text/html,application/xhtml+xml"}), timeout=timeout)
    parser = _LinkParser(listing_url)
    parser.feed(raw.decode("utf-8", errors="replace"))
    source_hints = {
        "NoDesk": ("/remote-jobs/",), "EU Remote Jobs": ("/job/",), "AI Jobs": ("/job/",),
        "Total": ("/jobs/", "/job/"), "FlexJobs": ("/remote-jobs/",), "US Remotely": ("/job/", "/jobs/"),
        "USA Remote Work": ("/job/", "/jobs/"), "Rocketship": ("/jobs/", "/job/"),
        "Remote Landers": ("/jobs/", "/job/"), "JobFill.AI": ("/job/", "/jobs/"),
        "Remote Woman": ("/job/", "/jobs/"), "Wellfound": ("/jobs/",),
    }[source]
    candidates: List[str] = []
    for link in parser.links:
        if link in candidates:
            continue
        if any(hint in link.lower() for hint in source_hints):
            candidates.append(link)
        if len(candidates) >= (1 if os.environ.get("THORIO_SOURCE_DIAGNOSTIC") == "1" else 40):
            break
    records: Dict[str, Dict[str, Any]] = {}
    for link in candidates:
        try:
            detail = fetch_url(Request(link, headers={"User-Agent": "Mozilla/5.0 Thorio-Lead-Engine/1.0", "Accept": "text/html,application/xhtml+xml"}), timeout=timeout)
            for record in _jsonld_records(detail, source, link):
                records[record["url"]] = record
        except HTTPRetryError:
            continue
        except Exception:
            continue
    return AdapterResult(records=list(records.values()), checkpoint=None)


def _extract_algolia_credentials(raw: bytes) -> tuple[str, str]:
    text = raw.decode("utf-8", errors="replace")
    values: Dict[str, str] = {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if payload is not None:
        for item in _walk(payload):
            for key, value in item.items():
                if isinstance(value, str) and value:
                    values[str(key).lower()] = value
    else:
        assignment_pattern = re.compile(r"[\"']?([A-Za-z0-9_$.-]+)[\"']?\s*[:=]\s*[\"']([^\"']+)[\"']")
        for match in assignment_pattern.finditer(text):
            value = match.group(2).strip()
            if value:
                values[match.group(1).lower()] = value
    app_id = ""
    api_key = ""
    for key, value in values.items():
        compact = re.sub(r"[^a-z0-9]", "", key)
        if not app_id and "algolia" in compact and "app" in compact and "id" in compact:
            app_id = value
        if not api_key and "algolia" in compact and "key" in compact:
            api_key = value
    if not app_id or not api_key:
        if "algolia" in text.lower():
            for key, value in values.items():
                compact = re.sub(r"[^a-z0-9]", "", key)
                if not app_id and compact in {"applicationid", "appid"}:
                    app_id = value
                if not api_key and compact in {"apikey", "searchonlyapikey"}:
                    api_key = value
    if not app_id or not api_key:
        raise ValueError("Welcome to the Jungle public Algolia credentials were not found in /api/env")
    return app_id, api_key


class _WelcomeToTheJungleAdapter:
    name = "Welcome to the Jungle"
    source = name
    collector_type = "json"

    def __init__(self, url: str, timeout: int):
        self.url = url
        self.timeout = timeout

    def collect(self, checkpoint=None):
        env_raw = fetch_url(Request("https://www.welcometothejungle.com/api/env", headers={"User-Agent": "Mozilla/5.0 Thorio-Lead-Engine/1.0", "Accept": "application/json,application/javascript,text/javascript,*/*;q=0.1", "Referer": "https://www.welcometothejungle.com/"}), timeout=self.timeout)
        app_id, api_key = _extract_algolia_credentials(env_raw)
        endpoint = "https://%s-dsn.algolia.net/1/indexes/*/queries" % app_id
        params = urlencode({"hitsPerPage": 100, "page": 0, "query": ""})
        payload = json.dumps({"requests": [{"indexName": "wk_cms_jobs_production", "params": params}]}).encode("utf-8")
        request = Request(endpoint, data=payload, headers={"User-Agent": "Mozilla/5.0 Thorio-Lead-Engine/1.0", "Accept": "*/*", "Content-Type": "application/x-www-form-urlencoded", "Origin": "https://www.welcometothejungle.com", "Referer": "https://www.welcometothejungle.com/", "X-Algolia-Application-Id": app_id, "X-Algolia-API-Key": api_key})
        data = json.loads(fetch_url(request, timeout=self.timeout).decode("utf-8", errors="replace"))
        results = data.get("results", []) if isinstance(data, dict) else []
        first_result = results[0] if results and isinstance(results[0], dict) else {}
        hits = first_result.get("hits", []) if isinstance(first_result, dict) else []
        records = []
        for hit in hits:
            organization = hit.get("organization") or {}
            company = organization.get("name") if isinstance(organization, dict) else ""
            slug = organization.get("slug") if isinstance(organization, dict) else ""
            job_slug = hit.get("slug") or hit.get("reference") or hit.get("objectID")
            url = hit.get("url") or ("https://www.welcometothejungle.com/en/companies/%s/jobs/%s" % (slug, job_slug) if slug and job_slug else "")
            descriptions = hit.get("descriptions")
            description = descriptions.get("en", "") if isinstance(descriptions, dict) else hit.get("description")
            office = hit.get("office") or {}
            location = office.get("city", "") if isinstance(office, dict) else ""
            record = normalize_job_record({"title": hit.get("name") or hit.get("title"), "company": company, "url": url, "description": description, "id": hit.get("objectID") or hit.get("reference"), "location": location}, source=self.name, source_url=self.url)
            if record:
                records.append(record)
        return AdapterResult(records=records, checkpoint=None)


