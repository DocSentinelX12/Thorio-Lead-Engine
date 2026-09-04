from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request
from xml.etree import ElementTree

from .http_retry import HTTPRetryError, fetch_url
from .source_definition import SourceDefinition


@dataclass(frozen=True)
class AdapterResult:
    records: List[Dict[str, Any]]
    checkpoint: Optional[str] = None


def _text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _with_query_parameter(
    url: str,
    parameter: str,
    value: Any,
) -> str:
    """
    Add or replace one query parameter while preserving
    the existing URL query string and correctly encoding
    the parameter value.
    """
    parts = urlsplit(url)

    query = parse_qsl(
        parts.query,
        keep_blank_values=True,
    )

    query = [
        (key, existing_value)
        for key, existing_value in query
        if key != parameter
    ]

    query.append(
        (
            parameter,
            _text(value),
        )
    )

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def _first_text(
    item: Dict[str, Any],
    *keys: str,
) -> str:
    for key in keys:
        value = item.get(key)

        if value is None:
            continue

        if isinstance(value, (list, tuple)):
            value = ", ".join(
                _text(item)
                for item in value
                if _text(item)
            )

        if isinstance(value, dict):
            value = (
                value.get("name")
                or value.get("value")
                or value.get("text")
                or value.get("title")
            )

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


def _get_path(
    payload: Any,
    path: Optional[str],
) -> Any:
    """
    Read a dotted path from a JSON-compatible object.

    Example:
        data.jobs
        data.results
        pagination.next_cursor
    """
    if not path:
        return payload

    current = payload

    for part in path.split("."):
        part = part.strip()

        if not part:
            continue

        if isinstance(current, dict):
            current = current.get(part)
            continue

        return None

    return current


def _field_value(
    item: Dict[str, Any],
    field_name: Optional[str],
) -> Any:
    """
    Read a potentially nested field from one source record.
    """
    if not field_name:
        return None

    current: Any = item

    for part in field_name.split("."):
        part = part.strip()

        if not part:
            continue

        if isinstance(current, dict):
            current = current.get(part)
            continue

        return None

    return current


def _configured_text(
    item: Dict[str, Any],
    configured_field: Optional[str],
    *fallback_fields: str,
) -> str:
    """
    Read the configured field first, using the same structured-value
    handling as the legacy field resolver, then use legacy fallbacks.
    """
    if configured_field:
        value = _field_value(
            item,
            configured_field,
        )

        if isinstance(value, (list, tuple)):
            value = ", ".join(
                _text(entry)
                for entry in value
                if _text(entry)
            )

        if isinstance(value, dict):
            value = (
                value.get("name")
                or value.get("value")
                or value.get("text")
                or value.get("title")
            )

        text = _text(value)

        if text:
            return text

    return _first_text(
        item,
        *fallback_fields,
    )

def _configured_url(
    item: Dict[str, Any],
    configured_field: Optional[str],
    *fallback_fields: str,
) -> str:
    """
    Read the configured URL field first, then legacy fallbacks.
    """
    if configured_field:
        value = _field_value(
            item,
            configured_field,
        )

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

    return _first_url(
        item,
        *fallback_fields,
    )


def _json_records_from_definition(
    payload: Any,
    definition: SourceDefinition,
) -> List[Dict[str, Any]]:
    """
    Extract records using the source definition first.

    Legacy automatic detection remains available when no
    record_path is configured.
    """
    if definition.record_path:
        value = _get_path(
            payload,
            definition.record_path,
        )

        if isinstance(value, list):
            return [
                item
                for item in value
                if isinstance(item, dict)
            ]

        raise ValueError(
            "JSON source record_path did not "
            "resolve to a record list."
        )

    return _json_records(
        payload
    )


def _configured_checkpoint(
    payload: Any,
    definition: SourceDefinition,
) -> Optional[str]:
    """
    Read the configured cursor/next-page value.

    The configured response field takes precedence over
    generic legacy detection.
    """
    if (
        definition.cursor_response_field
        and definition.pagination_type
        == "cursor"
    ):
        value = _get_path(
            payload,
            definition.cursor_response_field,
        )

        if isinstance(value, dict):
            value = (
                value.get("cursor")
                or value.get("token")
                or value.get("url")
            )

        text = _text(value)

        if text:
            return text

        return None

    if (
        definition.next_url_field
        and definition.pagination_type
        == "next_url"
    ):
        value = _get_path(
            payload,
            definition.next_url_field,
        )

        text = _text(value)

        if text:
            return text

        return None

    return _next_checkpoint(
        payload
)


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


def _next_checkpoint(
    payload: Any,
) -> Optional[str]:
    if not isinstance(payload, dict):
        return None

    for key in (
        "nextCursor",
        "next_cursor",
        "nextPage",
        "next_page",
        "next",
        "next_page_token",
        "nextPageToken",
    ):
        value = payload.get(key)

        if value is None:
            continue

        if isinstance(value, dict):
            value = (
                value.get("cursor")
                or value.get("token")
                or value.get("url")
            )

        text = _text(value)

        if text:
            return text

    return None


def normalize_job_record(
    item: Dict[str, Any],
    *,
    source: str,
    source_url: str,
    definition: Optional[SourceDefinition] = None,
) -> Optional[Dict[str, Any]]:
    if definition is None:
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

        source_id = _first_text(
            item,
            "id",
            "job_id",
            "uuid",
            "slug",
            "requisition_id",
            "jobId",
        )

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

    else:
        title = _configured_text(
            item,
            definition.title_field,
            "title",
            "name",
            "job_title",
            "position",
            "role",
        )

        company = _configured_text(
            item,
            definition.company_field,
            "company",
            "company_name",
            "employer",
            "organization",
            "org",
        )

        url = _configured_url(
            item,
            definition.url_field,
            "url",
            "job_url",
            "apply_url",
            "link",
            "absolute_url",
            "jobUrl",
        )

        source_id = _configured_text(
            item,
            definition.source_id_field,
            "id",
            "job_id",
            "uuid",
            "slug",
            "requisition_id",
            "jobId",
        )

        description = _configured_text(
            item,
            definition.description_field,
            "description",
            "content",
            "summary",
            "excerpt",
        )

        location = _configured_text(
            item,
            definition.location_field,
            "location",
            "locations",
            "candidate_required_location",
            "geo",
        )

    if not title or not company or not url:
        return None

    if not source_id:
        source_id = url

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
        signal_parts.append(
            location
        )

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
        definition: Optional[SourceDefinition] = None,
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
        self.definition = definition

    def _request_url(
        self,
        checkpoint: Optional[str],
    ) -> str:
        if not checkpoint:
            return self.url

        # Preserve the original adapter behavior for legacy callers
        # that construct JsonSourceAdapter directly without a
        # SourceDefinition.
        if self.definition is None:
            return _with_query_parameter(
              self.url,
              "cursor",
              checkpoint,
            )

        # Definition-driven collection only sends a checkpoint when
        # the source explicitly declares cursor pagination.
        if (
            self.definition.pagination_type
            != "cursor"
        ):
            return self.url

        parameter = (
            self.definition.cursor_parameter
        )

        if not parameter:
            return self.url

        return _with_query_parameter(
          self.url,
          parameter,
          checkpoint,
        )

    def collect(
        self,
        checkpoint: Optional[str] = None,
    ) -> AdapterResult:
        # Preserve the original one-request behavior for legacy
        # JsonSourceAdapter callers that do not provide a definition.
        if self.definition is None:
            request_url = self._request_url(
                checkpoint
            )

            request = Request(
                request_url,
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
                    "JSON source returned invalid "
                    "UTF-8 JSON."
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

            return AdapterResult(
                records=normalized,
                checkpoint=_next_checkpoint(
                    payload
                ),
            )

        definition = self.definition

        max_pages = definition.max_pages
        max_requests = definition.max_requests
        max_records = definition.max_records

        pagination_type = (
            definition.pagination_type
        )

        # Pagination "none" remains exactly one request.
        if pagination_type == "none":
            request_url = self.url

            request = Request(
                request_url,
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
                    "JSON source returned invalid "
                    "UTF-8 JSON."
                ) from exc

            records = _json_records_from_definition(
                payload,
                definition,
            )

            normalized = []

            for item in records:
                record = normalize_job_record(
                    item,
                    source=self.source,
                    source_url=self.url,
                    definition=definition,
                )

                if record is not None:
                    normalized.append(record)

                if len(normalized) >= max_records:
                    break

            return AdapterResult(
                records=normalized,
                checkpoint=None,
            )

        collected = []

        requests_made = 0
        pages_seen = 0

        current_checkpoint = checkpoint

        if pagination_type == "page":
            if current_checkpoint is None:
                current_page = (
                    definition.page_start
                )
            else:
                try:
                    current_page = int(
                        current_checkpoint
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    current_page = (
                        definition.page_start
                    )

            request_url = self.url

            parameter = (
                definition.page_parameter
            )

            request_url = _with_query_parameter(
              request_url,
              parameter,
              current_page,
            )

        elif pagination_type == "offset":
            if current_checkpoint is None:
                current_offset = (
                    definition.offset_start
                )
            else:
                try:
                    current_offset = int(
                        current_checkpoint
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    current_offset = (
                        definition.offset_start
                    )

            request_url = self.url

            parameter = (
                definition.offset_parameter
            )

            request_url = _with_query_parameter(
              self.url,
              parameter,
              current_offset,
            )

        elif pagination_type == "next_url":
            request_url = (
                checkpoint
                or self.url
            )

        elif pagination_type == "cursor":
            request_url = self._request_url(
                checkpoint
            )

        else:
            request_url = self.url

        visited_urls = set()
        final_checkpoint = checkpoint

        while request_url:
            if pages_seen >= max_pages:
                break

            if requests_made >= max_requests:
                break

            if request_url in visited_urls:
                raise ValueError(
                    "JSON source pagination "
                    "returned a previously "
                    "visited URL."
                )

            visited_urls.add(
                request_url
            )

            request = Request(
                request_url,
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

            requests_made += 1
            pages_seen += 1

            try:
                payload = json.loads(
                    raw.decode("utf-8")
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
            ) as exc:
                raise ValueError(
                    "JSON source returned invalid "
                    "UTF-8 JSON."
                ) from exc

            records = _json_records_from_definition(
                payload,
                definition,
            )

            for item in records:
                record = normalize_job_record(
                    item,
                    source=self.source,
                    source_url=self.url,
                    definition=definition,
                )

                if record is not None:
                    collected.append(record)

                if len(collected) >= max_records:
                    collected = collected[
                        :max_records
                    ]
                    return AdapterResult(
                        records=collected,
                        checkpoint=final_checkpoint,
                    )

            if pagination_type == "cursor":
                next_checkpoint = (
                    _configured_checkpoint(
                        payload,
                        definition,
                    )
                )

                if not next_checkpoint:
                    final_checkpoint = None
                    break

                if (
                    next_checkpoint
                    == current_checkpoint
                ):
                    raise ValueError(
                        "JSON source cursor "
                        "did not advance."
                    )

                final_checkpoint = (
                    next_checkpoint
                )

                if checkpoint is not None:
                    break

                current_checkpoint = (
                    next_checkpoint
                )

                request_url = (
                    self._request_url(
                        next_checkpoint
                    )
                )

                continue

            if pagination_type == "page":
                current_page += 1

                final_checkpoint = str(
                    current_page
                )

                parameter = (
                    definition.page_parameter
                )

                request_url = _with_query_parameter(
                  self.url,
                  parameter,
                  current_page,
                )

                continue

            if pagination_type == "offset":
                step = (
                    definition.offset_step
                    or definition.page_limit
                )

                if not step:
                    step = len(records)

                if not step:
                    step = 1

                current_offset += step

                final_checkpoint = str(
                    current_offset
                )

                parameter = (
                    definition.offset_parameter
                )

                request_url = _with_query_parameter(
                  request_url,
                  parameter,
                  current_offset,
                )

                continue

            if pagination_type == "next_url":
                next_url = (
                    _configured_checkpoint(
                        payload,
                        definition,
                    )
                )

                if not next_url:
                    final_checkpoint = None
                    break

                if (
                    next_url
                    == request_url
                ):
                    raise ValueError(
                        "JSON source pagination "
                        "returned the current URL."
                    )

                final_checkpoint = (
                    next_url
                )

                current_checkpoint = (
                    next_url
                )

                request_url = next_url

                continue

            break

        return AdapterResult(
            records=collected,
            checkpoint=final_checkpoint,
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

    def collect(
        self,
        checkpoint: Optional[str] = None,
    ) -> AdapterResult:
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

            company = (
                values.get("company")
                or values.get("employer")
                or ""
            )

            if not company:
                continue

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
                    "company": company,
                    "signal": title,
                    "evidence": (
                        f"Title: {title}\n"
                        f"Company: {company}\n"
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
            checkpoint=None,
        )


class _JobPostingParser(HTMLParser):
    """
    Extract JSON-LD JobPosting objects from HTML.

    We intentionally do not manufacture a company name from
    the source website. A job must contain structured employer
    information to enter the normalized lead pipeline.
    """

    def __init__(self):
        super().__init__()

        self._script_depth = 0
        self._script_parts: List[str] = []
        self.job_postings: List[Dict[str, Any]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs,
    ) -> None:
        if tag.lower() != "script":
            return

        attributes = dict(attrs)

        if (
            attributes.get("type", "")
            .lower()
            == "application/ld+json"
        ):
            self._script_depth += 1
            self._script_parts = []

    def handle_data(
        self,
        data: str,
    ) -> None:
        if self._script_depth:
            self._script_parts.append(
                data
            )

    def handle_endtag(
        self,
        tag: str,
    ) -> None:
        if (
            tag.lower() != "script"
            or not self._script_depth
        ):
            return

        self._script_depth -= 1

        if self._script_depth:
            return

        raw = "".join(
            self._script_parts
        ).strip()

        self._script_parts = []

        if not raw:
            return

        try:
            payload = json.loads(
                unescape(raw)
            )
        except json.JSONDecodeError:
            return

        self._extract(
            payload
        )

    def _extract(
        self,
        payload: Any,
    ) -> None:
        if isinstance(payload, list):
            for item in payload:
                self._extract(item)

            return

        if not isinstance(payload, dict):
            return

        graph = payload.get("@graph")

        if isinstance(graph, list):
            for item in graph:
                self._extract(item)

        schema_type = payload.get(
            "@type"
        )

        if isinstance(schema_type, list):
            is_job = (
                "JobPosting"
                in schema_type
            )
        else:
            is_job = (
                schema_type
                == "JobPosting"
            )

        if is_job:
            self.job_postings.append(
                payload
            )


class HtmlSourceAdapter:
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

    def collect(
        self,
        checkpoint: Optional[str] = None,
    ) -> AdapterResult:
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

        parser = _JobPostingParser()

        parser.feed(html)

        records = []

        for item in parser.job_postings:
            employer = item.get(
                "hiringOrganization"
            )

            if isinstance(
                employer,
                dict,
            ):
                company = _text(
                    employer.get("name")
                )
            else:
                company = _text(
                    employer
                )

            title = _text(
                item.get("title")
            )

            job_url = _first_url(
                item,
                "url",
            )

            if not job_url:
                job_url = self.url

            if not title or not company:
                continue

            source_id = (
                _text(
                    item.get("identifier")
                )
                or job_url
            )

            if isinstance(
                item.get("identifier"),
                dict,
            ):
                source_id = (
                    _text(
                        item["identifier"].get(
                            "value"
                        )
                    )
                    or job_url
                )

            description = _text(
                item.get("description")
            )

            location = item.get(
                "jobLocation"
            )

            location_text = ""

            if isinstance(
                location,
                list,
            ):
                locations = []

                for entry in location:
                    if not isinstance(
                        entry,
                        dict,
                    ):
                        continue

                    address = entry.get(
                        "address"
                    )

                    if isinstance(
                        address,
                        dict,
                    ):
                        address_text = ", ".join(
                            _text(
                                address.get(key)
                            )
                            for key in (
                                "addressLocality",
                                "addressRegion",
                                "addressCountry",
                            )
                            if _text(
                                address.get(key)
                            )
                        )

                        if address_text:
                            locations.append(
                                address_text
                            )

                location_text = "; ".join(
                    locations
                )

            elif isinstance(
                location,
                dict,
            ):
                address = location.get(
                    "address"
                )

                if isinstance(
                    address,
                    dict,
                ):
                    location_text = ", ".join(
                        _text(
                            address.get(key)
                        )
                        for key in (
                            "addressLocality",
                            "addressRegion",
                            "addressCountry",
                        )
                        if _text(
                            address.get(key)
                        )
                    )

            records.append(
                {
                    "source": self.source,
                    "source_id": source_id,
                    "url": job_url,
                    "company": company,
                    "signal": (
                        f"{title} | "
                        f"{company}"
                    ),
                    "evidence": (
                        f"Title: {title}\n"
                        f"Company: {company}\n"
                        f"Source: {self.url}\n"
                        f"Location: {location_text}\n"
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
            checkpoint=None,
        )


class AdapterLeadSource:
    """
    Compatibility wrapper implementing the source interface
    expected by the existing scheduler.

    The wrapper now carries the complete SourceDefinition so
    collection configuration remains available to the adapter
    layer without changing the existing LeadSource boundary.
    """

    def __init__(
        self,
        adapter: Any,
        definition: SourceDefinition,
    ):
        if adapter is None:
            raise ValueError(
                "Adapter is required."
            )

        if not isinstance(
            definition,
            SourceDefinition,
        ):
            raise ValueError(
                "Source definition is required."
            )

        self.adapter = adapter
        self.definition = definition
        self.name = definition.name
        self.url = definition.url
        self.last_checkpoint = None

    def collect(
        self,
        checkpoint: Optional[str] = None,
    ) -> Iterable[Dict[str, Any]]:
        result = self.adapter.collect(
            checkpoint=checkpoint
        )

        if not isinstance(
            result,
            AdapterResult,
        ):
            raise ValueError(
                "Source adapter returned an invalid result."
            )

        self.last_checkpoint = (
            result.checkpoint
        )

        return result.records


def create_adapter(
    *,
    collector_type: Optional[str] = None,
    url: Optional[str] = None,
    source: Optional[str] = None,
    timeout: int = 20,
    definition: Optional[SourceDefinition] = None,
) -> AdapterLeadSource:
    """
    Create a source adapter from a SourceDefinition.

    The legacy collector_type/url/source arguments remain supported
    so existing callers and tests continue to work.

    New production code should provide a SourceDefinition.
    """

    if definition is None:
        if (
            collector_type is None
            or url is None
            or source is None
        ):
            raise ValueError(
                "SourceDefinition or "
                "collector_type, url, and source "
                "are required."
            )

        definition = SourceDefinition(
            name=source,
            provider=source,
            collector_type=collector_type,
            url=url,
        )

    if not isinstance(
        definition,
        SourceDefinition,
    ):
        raise ValueError(
            "definition must be a SourceDefinition."
        )

    collector = (
        definition.collector_type
        .strip()
        .lower()
    )

    if collector == "json":
        adapter = JsonSourceAdapter(
            url=definition.url,
            source=definition.name,
            timeout=timeout,
            definition=definition,
        )

    elif collector in {
        "rss",
        "atom",
        "xml",
    }:
        adapter = RssSourceAdapter(
            url=definition.url,
            source=definition.name,
            timeout=timeout,
        )

    elif collector == "html":
        adapter = HtmlSourceAdapter(
            url=definition.url,
            source=definition.name,
            timeout=timeout,
        )

    else:
        raise ValueError(
            "Unsupported collector type: "
            f"{definition.collector_type}"
        )

    return AdapterLeadSource(
        adapter=adapter,
        definition=definition,
        )
