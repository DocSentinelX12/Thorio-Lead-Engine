from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urljoin
from urllib.request import Request

from .collector import normalize_lead_input
from .http_retry import HTTPRetryError, fetch_url


DISCOVERY_LANES = (
    "x_signal",
    "threads_signal",
    "reddit_signal",
    "linkedin_signal",
    "facebook_signal",
    "instagram_signal",
    "hacker_news_signal",
    "indie_hackers_signal",
    "product_hunt_signal",
    "web_job_signal",
)


class DiscoveryConfigurationError(RuntimeError):
    """Raised when a discovery lane is enabled without a real source contract."""


class DiscoveryCollectionError(RuntimeError):
    """Raised when an enabled discovery source cannot be collected safely."""


@dataclass(frozen=True)
class DiscoverySourceConfig:
    lane: str
    source: str
    endpoint: str
    token: Optional[str] = None
    token_header: str = "Authorization"
    token_prefix: str = "Bearer "
    records_path: Optional[str] = None
    id_field: str = "id"
    url_field: str = "url"
    text_fields: tuple[str, ...] = ("text", "content", "body", "title")
    company_fields: tuple[str, ...] = ("company", "company_name", "organization")
    person_fields: tuple[str, ...] = ("author", "author_name", "person", "user", "username")
    signal_type: str = "business_intent"
    timeout_seconds: int = 20

    def __post_init__(self) -> None:
        if self.lane not in DISCOVERY_LANES:
            raise DiscoveryConfigurationError(f"Unsupported discovery lane: {self.lane}")
        if not self.source.strip():
            raise DiscoveryConfigurationError("Discovery source name is required")
        if not self.endpoint.startswith(("http://", "https://")):
            raise DiscoveryConfigurationError(f"Discovery endpoint must be HTTP(S): {self.endpoint!r}")
        if self.timeout_seconds <= 0:
            raise DiscoveryConfigurationError("Discovery timeout must be positive")
        if self.token_header.strip() == "":
            raise DiscoveryConfigurationError("Token header cannot be empty")


@dataclass(frozen=True)
class DiscoveryCollectionResult:
    lane: str
    source: str
    records: List[Dict[str, Any]]
    checkpoint: Optional[str]
    collected_at: str


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _path(value: Any, path: Optional[str]) -> Any:
    if not path:
        return value
    current = value
    for part in path.split("."):
        if not part:
            continue
        if isinstance(current, Mapping):
            current = current.get(part)
        else:
            return None
    return current


def _first_value(record: Mapping[str, Any], fields: Iterable[str]) -> str:
    for field in fields:
        value = _path(record, field)
        if isinstance(value, Mapping):
            value = value.get("name") or value.get("text") or value.get("username") or value.get("url")
        if isinstance(value, (list, tuple)):
            value = " ".join(str(item).strip() for item in value if str(item).strip())
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _records(payload: Any, path: Optional[str]) -> List[Dict[str, Any]]:
    value = _path(payload, path)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if path:
        raise DiscoveryCollectionError(f"Configured records_path did not resolve to a list: {path}")
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("data", "items", "results", "posts", "comments", "messages", "jobs"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, Mapping)]
        raise DiscoveryCollectionError("Discovery response contains no supported record list")
    raise DiscoveryCollectionError("Discovery response must be JSON object or array")


def _checkpoint(payload: Any) -> Optional[str]:
    if not isinstance(payload, Mapping):
        return None
    for key in ("next_cursor", "nextCursor", "cursor", "next_page_token", "nextPageToken", "next"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            value = value.get("cursor") or value.get("token") or value.get("url")
        text = str(value or "").strip()
        if text:
            return text
    return None


def _record_to_lead(item: Mapping[str, Any], config: DiscoverySourceConfig) -> Optional[Dict[str, Any]]:
    url = _first_value(item, (config.url_field, "permalink", "link", "html_url", "web_url"))
    text = _first_value(item, config.text_fields)
    company = _first_value(item, config.company_fields)
    person = _first_value(item, config.person_fields)
    source_id = _first_value(item, (config.id_field, "uuid", "slug")) or url

    if not url or not text or not source_id:
        return None

    if not company:
        company = "Unknown company"

    signal = text if not person else f"{person}: {text}"
    evidence = f"Source: {config.source}\nURL: {url}\nSignal: {signal}"
    lead = {
        "source": config.source,
        "source_id": source_id,
        "url": url,
        "company": company,
        "signal": signal,
        "evidence": evidence,
        "signal_type": config.signal_type,
        "source_url": url,
        "discovery_agent": config.lane,
        "discovery_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if person:
        lead["person"] = person
    return normalize_lead_input(lead)


class AuthorizedJsonDiscoveryCollector:
    """Collect evidence from an explicitly authorized JSON endpoint.

    Credentials are read only from the process environment. Nothing is stored
    in source code, logs, Airtable records, or Git history.
    """

    def __init__(self, config: DiscoverySourceConfig):
        self.config = config

    def collect(self, checkpoint: Optional[str] = None) -> DiscoveryCollectionResult:
        endpoint = self.config.endpoint
        if checkpoint and "?" in endpoint:
            endpoint = f"{endpoint}&cursor={checkpoint}"
        elif checkpoint:
            endpoint = f"{endpoint}?cursor={checkpoint}"

        headers = {
            "User-Agent": "Thorio-Lead-Engine/1.0",
            "Accept": "application/json",
        }
        if self.config.token:
            headers[self.config.token_header] = f"{self.config.token_prefix}{self.config.token}" if self.config.token_prefix else self.config.token

        request = Request(endpoint, headers=headers, method="GET")
        try:
            raw = fetch_url(request, timeout=self.config.timeout_seconds)
        except HTTPRetryError as exc:
            raise DiscoveryCollectionError(f"{self.config.source} request failed: {exc}") from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DiscoveryCollectionError(f"{self.config.source} returned invalid JSON") from exc

        normalized: List[Dict[str, Any]] = []
        for item in _records(payload, self.config.records_path):
            lead = _record_to_lead(item, self.config)
            if lead is not None:
                normalized.append(lead)

        return DiscoveryCollectionResult(
            lane=self.config.lane,
            source=self.config.source,
            records=normalized,
            checkpoint=_checkpoint(payload),
            collected_at=datetime.now(timezone.utc).isoformat(),
        )


def load_authorized_discovery_configs(*, required: bool = False) -> tuple[DiscoverySourceConfig, ...]:
    """Load configured discovery lanes from environment without inventing endpoints.

    Each active lane uses THORIO_DISCOVERY_<LANE>_URL. A token may be supplied
    directly through THORIO_DISCOVERY_<LANE>_TOKEN or indirectly through
    THORIO_DISCOVERY_<LANE>_TOKEN_ENV. Missing configuration is reported rather
    than silently skipped when required=True.
    """
    configs: List[DiscoverySourceConfig] = []
    missing: List[str] = []
    for lane in DISCOVERY_LANES:
        prefix = f"THORIO_DISCOVERY_{lane.upper()}"
        endpoint = _env(f"{prefix}_URL")
        enabled = _env(f"{prefix}_ENABLED").lower() in {"1", "true", "yes", "on"}
        if not endpoint:
            if enabled or required:
                missing.append(f"{lane}: {prefix}_URL")
            continue

        token = _env(f"{prefix}_TOKEN")
        token_env = _env(f"{prefix}_TOKEN_ENV")
        if not token and token_env:
            token = _env(token_env)

        records_path = _env(f"{prefix}_RECORDS_PATH") or None
        url_field = _env(f"{prefix}_URL_FIELD") or "url"
        id_field = _env(f"{prefix}_ID_FIELD") or "id"
        text_fields = tuple(filter(None, (_env(f"{prefix}_TEXT_FIELDS") or "text,content,body,title").split(",")))
        company_fields = tuple(filter(None, (_env(f"{prefix}_COMPANY_FIELDS") or "company,company_name,organization").split(",")))
        person_fields = tuple(filter(None, (_env(f"{prefix}_PERSON_FIELDS") or "author,author_name,person,user,username").split(",")))
        signal_type = _env(f"{prefix}_SIGNAL_TYPE") or "business_intent"
        source = _env(f"{prefix}_SOURCE") or lane
        header = _env(f"{prefix}_TOKEN_HEADER") or "Authorization"
        token_prefix = _env(f"{prefix}_TOKEN_PREFIX")
        timeout_raw = _env(f"{prefix}_TIMEOUT") or "20"
        try:
            timeout = int(timeout_raw)
        except ValueError as exc:
            raise DiscoveryConfigurationError(f"{prefix}_TIMEOUT must be an integer") from exc

        configs.append(DiscoverySourceConfig(
            lane=lane,
            source=source,
            endpoint=endpoint,
            token=token or None,
            token_header=header,
            token_prefix="Bearer " if token_prefix == "__DEFAULT__" or not token_prefix else token_prefix,
            records_path=records_path,
            id_field=id_field,
            url_field=url_field,
            text_fields=text_fields,
            company_fields=company_fields,
            person_fields=person_fields,
            signal_type=signal_type,
            timeout_seconds=timeout,
        ))

    if missing:
        raise DiscoveryConfigurationError("Missing required discovery source configuration: " + "; ".join(missing))
    return tuple(configs)


def collect_configured_discovery(*, required: bool = False, checkpoints: Optional[Mapping[str, str]] = None) -> List[DiscoveryCollectionResult]:
    configs = load_authorized_discovery_configs(required=required)
    checkpoint_map = dict(checkpoints or {})
    return [AuthorizedJsonDiscoveryCollector(config).collect(checkpoint_map.get(config.lane)) for config in configs]
