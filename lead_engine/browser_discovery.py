from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .collector import normalize_lead_input
from .sources import LeadSource


class BrowserDiscoveryConfigurationError(RuntimeError):
    """Raised when the free authenticated browser collector is misconfigured."""


class BrowserDiscoveryUnavailable(RuntimeError):
    """Raised when the optional browser runtime is not installed or usable."""


@dataclass(frozen=True)
class BrowserDiscoveryTarget:
    lane: str
    name: str
    url: str
    company_selector: str = ""
    author_selector: str = ""
    text_selector: str = ""
    link_selector: str = ""
    item_selector: str = ""
    max_items: int = 100

    def __post_init__(self) -> None:
        if not self.lane.strip() or not self.name.strip():
            raise BrowserDiscoveryConfigurationError("Browser target lane and name are required")
        if not self.url.startswith(("https://", "http://")):
            raise BrowserDiscoveryConfigurationError(f"Browser target URL must be HTTP(S): {self.url!r}")
        if self.max_items <= 0:
            raise BrowserDiscoveryConfigurationError("Browser target max_items must be positive")


@dataclass(frozen=True)
class BrowserDiscoveryResult:
    lane: str
    target: str
    records: list[dict[str, Any]]
    checkpoint: Optional[str]
    collected_at: str


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _required_profile() -> Path:
    value = _env("THORIO_BROWSER_PROFILE_DIR")
    if not value:
        raise BrowserDiscoveryConfigurationError(
            "THORIO_BROWSER_PROFILE_DIR is required for free authenticated browser discovery"
        )
    path = Path(value).expanduser()
    if not path.exists() or not path.is_dir():
        raise BrowserDiscoveryConfigurationError(f"Browser profile directory does not exist: {path}")
    return path


def _targets_from_environment() -> tuple[BrowserDiscoveryTarget, ...]:
    raw = _env("THORIO_BROWSER_DISCOVERY_TARGETS")
    if not raw:
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BrowserDiscoveryConfigurationError("THORIO_BROWSER_DISCOVERY_TARGETS must be valid JSON") from exc
    if not isinstance(payload, list):
        raise BrowserDiscoveryConfigurationError("THORIO_BROWSER_DISCOVERY_TARGETS must be a JSON list")

    targets: list[BrowserDiscoveryTarget] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise BrowserDiscoveryConfigurationError(f"Browser target {index} must be an object")
        lane = str(item.get("lane", "")).strip()
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not lane or not name or not url.startswith(("https://", "http://")):
            raise BrowserDiscoveryConfigurationError(f"Browser target {index} requires lane, name and HTTP(S) url")
        max_items = int(item.get("max_items", 100))
        targets.append(BrowserDiscoveryTarget(
            lane=lane,
            name=name,
            url=url,
            company_selector=str(item.get("company_selector", "")).strip(),
            author_selector=str(item.get("author_selector", "")).strip(),
            text_selector=str(item.get("text_selector", "")).strip(),
            link_selector=str(item.get("link_selector", "")).strip(),
            item_selector=str(item.get("item_selector", "")).strip(),
            max_items=max_items,
        ))
    return tuple(targets)


def _fingerprint(url: str, text: str) -> str:
    return hashlib.sha256(f"{url}\n{text}".encode("utf-8")).hexdigest()


def _text(node: Any) -> str:
    try:
        return " ".join((node.inner_text() or "").split())
    except Exception:
        return ""


class FreeAuthenticatedBrowserCollector:
    """Collect from pages using an existing local authenticated browser profile.

    This collector never receives passwords or API tokens. Authentication stays
    in the browser profile owned by the operator. It is intended for a free
    self-hosted runner or another already-authorized browser environment.
    """

    def __init__(self, target: BrowserDiscoveryTarget):
        self.target = target

    def collect(self, checkpoint: Optional[str] = None) -> BrowserDiscoveryResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserDiscoveryUnavailable(
                "Playwright is required for browser discovery; install it in the authorized local runner environment"
            ) from exc

        profile = _required_profile()
        seen_after = checkpoint or ""
        records: list[dict[str, Any]] = []
        next_checkpoint: Optional[str] = None

        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=_env("THORIO_BROWSER_HEADLESS", "1").lower() in {"1", "true", "yes", "on"},
            )
            try:
                page = context.new_page()
                page.goto(self.target.url, wait_until="domcontentloaded", timeout=60_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=30_000)
                except Exception:
                    pass

                if not self.target.item_selector or not self.target.text_selector:
                    raise BrowserDiscoveryConfigurationError(
                        f"Target {self.target.name} must define item_selector and text_selector"
                    )

                items = page.locator(self.target.item_selector)
                count = min(items.count(), self.target.max_items)
                for index in range(count):
                    item = items.nth(index)
                    text_node = item.locator(self.target.text_selector)
                    text = _text(text_node.first()) if text_node.count() else _text(item)
                    if not text:
                        continue

                    link = ""
                    if self.target.link_selector:
                        link_node = item.locator(self.target.link_selector).first()
                        if link_node.count():
                            link = str(link_node.get_attribute("href") or "").strip()
                    if not link:
                        link = self.target.url

                    company = ""
                    if self.target.company_selector:
                        node = item.locator(self.target.company_selector).first()
                        if node.count():
                            company = _text(node)
                    if not company:
                        continue

                    author = ""
                    if self.target.author_selector:
                        node = item.locator(self.target.author_selector).first()
                        if node.count():
                            author = _text(node)

                    fingerprint = _fingerprint(link, text)
                    if seen_after and fingerprint == seen_after:
                        next_checkpoint = fingerprint
                        break

                    record = {
                        "source": self.target.name,
                        "source_id": fingerprint,
                        "url": link,
                        "company": company,
                        "signal": f"{author}: {text}" if author else text,
                        "evidence": f"Source: {self.target.name}\nURL: {link}\nSignal: {author + ': ' if author else ''}{text}",
                        "signal_type": "business_intent",
                        "source_url": link,
                        "discovery_agent": self.target.lane,
                        "discovery_timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    if author:
                        record["person"] = author
                    records.append(normalize_lead_input(record))
                    next_checkpoint = fingerprint
            finally:
                context.close()

        return BrowserDiscoveryResult(
            lane=self.target.lane,
            target=self.target.name,
            records=records,
            checkpoint=next_checkpoint,
            collected_at=datetime.now(timezone.utc).isoformat(),
        )


class BrowserDiscoveryLeadSource(LeadSource):
    """Adapter from the free browser collector into the existing LeadSource pipeline."""

    def __init__(self, target: BrowserDiscoveryTarget):
        self.target = target
        self.name = target.name
        self.last_checkpoint: Optional[str] = None
        self._collector = FreeAuthenticatedBrowserCollector(target)

    def collect(self, checkpoint: Optional[str] = None) -> Iterable[dict[str, Any]]:
        result = self._collector.collect(checkpoint=checkpoint)
        self.last_checkpoint = result.checkpoint
        return result.records


def configured_browser_discovery_sources() -> tuple[BrowserDiscoveryLeadSource, ...]:
    return tuple(BrowserDiscoveryLeadSource(target) for target in _targets_from_environment())
