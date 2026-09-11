from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin


_JOB_CONTAINER_WORDS = (
    "job",
    "jobs",
    "posting",
    "postings",
    "vacancy",
    "vacancies",
    "opening",
    "openings",
    "position",
    "positions",
    "listing",
    "listings",
    "career",
    "careers",
)

_COMPANY_WORDS = (
    "company",
    "employer",
    "organization",
    "organisation",
)

_TITLE_WORDS = (
    "title",
    "job-title",
    "jobtitle",
    "position",
    "role",
)

_URL_HINTS = (
    "/job/",
    "/jobs/",
    "/posting/",
    "/postings/",
    "/vacancy/",
    "/vacancies/",
    "/opening/",
    "/openings/",
    "/position/",
    "/positions/",
    "/career/",
    "/careers/",
)


class _Node:
    def __init__(self, tag: str, attrs: Dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.text_parts: List[str] = []
        self.links: List[Tuple[str, str]] = []
        self.semantic: Dict[str, str] = {}

    @property
    def text(self) -> str:
        return " ".join(
            part.strip()
            for part in self.text_parts
            if part.strip()
        ).strip()

    @property
    def classes(self) -> str:
        return " ".join(
            value
            for key, value in self.attrs.items()
            if key in {"class", "id"}
        ).lower()


class _HtmlJobParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.stack: List[_Node] = []
        self.nodes: List[_Node] = []
        self.json_payloads: List[Any] = []
        self._json_script: Optional[List[str]] = None
        self._json_script_attrs: Dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {
            str(key).lower(): str(value or "")
            for key, value in attrs
        }

        if tag.lower() == "script":
            script_type = attributes.get("type", "").lower()
            script_id = attributes.get("id", "").lower()
            if (
                script_type == "application/json"
                or script_id in {"__next_data__", "__data__", "initial-state"}
            ):
                self._json_script = []
                self._json_script_attrs = attributes

        node = _Node(tag.lower(), attributes)
        itemprop = attributes.get("itemprop", "").strip().lower()
        if itemprop:
            node.semantic["itemprop"] = itemprop

        self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._json_script is not None:
            self._json_script.append(data)

        if self.stack:
            self.stack[-1].text_parts.append(unescape(data))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag == "script" and self._json_script is not None:
            raw = "".join(self._json_script).strip()
            self._json_script = None
            self._json_script_attrs = {}
            if raw:
                try:
                    self.json_payloads.append(json.loads(unescape(raw)))
                except json.JSONDecodeError:
                    pass

        if not self.stack:
            return

        index = len(self.stack) - 1
        while index >= 0 and self.stack[index].tag != tag:
            index -= 1

        if index < 0:
            return

        node = self.stack.pop(index)
        self.nodes.append(node)

        if self.stack:
            parent = self.stack[-1]
            if node.text:
                parent.text_parts.append(node.text)
            parent.links.extend(node.links)

        if tag == "a":
            href = node.attrs.get("href", "").strip()
            if href:
                absolute = urljoin(self.base_url, href)
                node.links.append((absolute, node.text))
                if self.stack:
                    self.stack[-1].links.append((absolute, node.text))


def _has_word(value: str, words: Tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(
        re.search(rf"(?:^|[-_\s]){re.escape(word)}(?:$|[-_\s])", lowered)
        or word in lowered
        for word in words
    )


def _looks_like_job_url(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in _URL_HINTS)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _json_candidates(payloads: List[Any], base_url: str) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for payload in payloads:
        for item in _walk_json(payload):
            keys = {str(key).lower() for key in item}
            if not (
                keys.intersection({"title", "job_title", "position", "role", "name"})
                and keys.intersection({"company", "company_name", "employer", "organization", "organisation"})
            ):
                continue

            title = _clean(
                item.get("title")
                or item.get("job_title")
                or item.get("position")
                or item.get("role")
                or item.get("name")
            )
            company_value = (
                item.get("company")
                or item.get("company_name")
                or item.get("employer")
                or item.get("organization")
                or item.get("organisation")
            )
            if isinstance(company_value, dict):
                company_value = (
                    company_value.get("name")
                    or company_value.get("title")
                )
            company = _clean(company_value)
            url_value = (
                item.get("url")
                or item.get("job_url")
                or item.get("jobUrl")
                or item.get("link")
                or item.get("absolute_url")
                or item.get("hostedUrl")
                or item.get("applyUrl")
            )
            if isinstance(url_value, dict):
                url_value = url_value.get("url") or url_value.get("href")
            url = urljoin(base_url, _clean(url_value))
            if title and company and url.startswith(("http://", "https://")):
                candidates.append(
                    {
                        "title": title,
                        "company": company,
                        "url": url,
                        "description": _clean(
                            item.get("description")
                            or item.get("descriptionPlain")
                            or item.get("summary")
                            or item.get("excerpt")
                        ),
                        "location": _clean(
                            item.get("location")
                            or item.get("locations")
                            or item.get("locationName")
                        ),
                        "id": _clean(item.get("id") or item.get("job_id") or item.get("uuid")),
                    }
                )
    return candidates


def _html_candidates(parser: _HtmlJobParser, base_url: str) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen_urls = set()

    for node in parser.nodes:
        if not _has_word(node.classes, _JOB_CONTAINER_WORDS):
            continue

        links = [
            (url, _clean(text))
            for url, text in node.links
            if _looks_like_job_url(url) and _clean(text)
        ]
        if not links:
            continue

        title = ""
        company = ""
        description = ""
        location = ""

        for child in parser.nodes:
            if child is node:
                continue
            if not _has_word(child.classes, _JOB_CONTAINER_WORDS) and child.text not in node.text:
                continue
            itemprop = child.semantic.get("itemprop", "")
            if itemprop in _TITLE_WORDS and not title:
                title = child.text
            elif itemprop in _COMPANY_WORDS and not company:
                company = child.text
            elif itemprop in {"description", "summary"} and not description:
                description = child.text
            elif itemprop in {"joblocation", "location"} and not location:
                location = child.text

            marker = child.classes
            if not title and _has_word(marker, _TITLE_WORDS) and child.text:
                title = child.text
            if not company and _has_word(marker, _COMPANY_WORDS) and child.text:
                company = child.text

        if not title:
            for url, text in links:
                if text:
                    title = text
                    break

        if not company:
            match = re.search(
                r"(?:company|employer|organization|organisation)\s*[:|\-]\s*([^|\n]+)",
                node.text,
                flags=re.IGNORECASE,
            )
            if match:
                company = _clean(match.group(1))

        if not company:
            continue

        for url, _ in links:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append(
                {
                    "title": title,
                    "company": company,
                    "url": url,
                    "description": description,
                    "location": location,
                    "id": url,
                }
            )

    return candidates


def extract_html_job_records(
    raw_html: bytes,
    *,
    source: str,
    source_url: str,
) -> List[Dict[str, Any]]:
    from .source_adapters import normalize_job_record

    html = raw_html.decode("utf-8", errors="replace")
    parser = _HtmlJobParser(source_url)
    parser.feed(html)

    candidates = _json_candidates(
        parser.json_payloads,
        source_url,
    )
    candidates.extend(
        _html_candidates(parser, source_url)
    )

    records: List[Dict[str, Any]] = []
    seen = set()
    for candidate in candidates:
        record = normalize_job_record(
            candidate,
            source=source,
            source_url=source_url,
        )
        if record is None:
            continue
        key = record["url"]
        if key in seen:
            continue
        seen.add(key)
        records.append(record)

    return records


def install() -> None:
    from . import source_adapters

    original = source_adapters.HtmlSourceAdapter.collect
    if getattr(original, "_thorio_html_fallback", False):
        return

    def collect(self, checkpoint=None):
        result = original(self, checkpoint=checkpoint)
        if result.records:
            return result

        request = source_adapters.Request(
            self.url,
            headers={
                "User-Agent": "Thorio-Lead-Engine/1.0",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        try:
            raw = source_adapters.fetch_url(
                request,
                timeout=self.timeout,
            )
        except source_adapters.HTTPRetryError:
            return result

        fallback_records = extract_html_job_records(
            raw,
            source=self.source,
            source_url=self.url,
        )
        return source_adapters.AdapterResult(
            records=fallback_records,
            checkpoint=result.checkpoint,
        )

    collect._thorio_html_fallback = True
    source_adapters.HtmlSourceAdapter.collect = collect
