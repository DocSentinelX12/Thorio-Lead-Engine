from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .account_auth import SUPPORTED_ACCOUNTS, ensure_authenticated
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
    account: str = ""
    authenticated_selector: str = ""
    login_url: str = ""
    max_items: int = 100

    def __post_init__(self) -> None:
        if not self.lane.strip() or not self.name.strip():
            raise BrowserDiscoveryConfigurationError("Browser target lane and name are required")
        if not self.url.startswith(("https://", "http://")):
            raise BrowserDiscoveryConfigurationError(f"Browser target URL must be HTTP(S): {self.url!r}")
        if self.max_items <= 0:
            raise BrowserDiscoveryConfigurationError("Browser target max_items must be positive")
        account = normalize_account(self.account)
        if account and account not in SUPPORTED_ACCOUNTS:
            raise BrowserDiscoveryConfigurationError(f"Unsupported authenticated browser account: {account}")
        if account and not self.authenticated_selector.strip():
            raise BrowserDiscoveryConfigurationError(
                f"{account}: authenticated_selector is required for an authenticated browser lane"
            )


@dataclass(frozen=True)
class BrowserDiscoveryResult:
    lane: str
    target: str
    records: list[dict[str, Any]]
    checkpoint: Optional[str]
    collected_at: str
    authenticated: bool = False
    relogin_attempted: bool = False


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def normalize_account(account: str) -> str:
    return account.strip().lower().replace("-", "_").replace(" ", "_")


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
    seen_lanes: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise BrowserDiscoveryConfigurationError(f"Browser target {index} must be an object")
        lane = str(item.get("lane", "")).strip()
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not lane or not name or not url.startswith(("https://", "http://")):
            raise BrowserDiscoveryConfigurationError(f"Browser target {index} requires lane, name and HTTP(S) url")
        lane_key = lane.casefold()
        if lane_key in seen_lanes:
            raise BrowserDiscoveryConfigurationError(f"Duplicate browser lane: {lane}")
        seen_lanes.add(lane_key)
        try:
            max_items = int(item.get("max_items", 100))
        except (TypeError, ValueError) as exc:
            raise BrowserDiscoveryConfigurationError(f"Browser target {index} max_items must be an integer") from exc
        targets.append(BrowserDiscoveryTarget(
            lane=lane,
            name=name,
            url=url,
            company_selector=str(item.get("company_selector", "")).strip(),
            author_selector=str(item.get("author_selector", "")).strip(),
            text_selector=str(item.get("text_selector", "")).strip(),
            link_selector=str(item.get("link_selector", "")).strip(),
            item_selector=str(item.get("item_selector", "")).strip(),
            account=normalize_account(str(item.get("account", ""))),
            authenticated_selector=str(item.get("authenticated_selector", "")).strip(),
            login_url=str(item.get("login_url", "")).strip(),
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


def _browser_endpoint() -> str:
    return _env("THORIO_BROWSER_CDP_URL")


def _browser_navigation_timeout() -> int:
    """Return a bounded per-target navigation timeout in milliseconds."""
    try:
        seconds = int(_env("THORIO_BROWSER_NAVIGATION_TIMEOUT", "30"))
    except ValueError:
        seconds = 30
    return max(5, min(seconds, 120)) * 1000


def _account_env(account: str, suffix: str) -> str:
    return _env(f"THORIO_ACCOUNT_{normalize_account(account).upper()}_{suffix}")


def authenticated_browser_lane_status(targets: Iterable[BrowserDiscoveryTarget]) -> dict[str, Any]:
    """Return non-secret readiness evidence for the six supported account lanes."""
    target_list = tuple(targets)
    target_accounts = {
        normalize_account(target.account)
        for target in target_list
        if target.account
    }
    authenticated_lanes = sum(
        1 for target in target_list
        if target.account and target.authenticated_selector
    )
    return {
        "supported_accounts": list(SUPPORTED_ACCOUNTS),
        "configured_accounts": sorted(target_accounts),
        "configured_lane_count": len(target_list),
        "authenticated_lane_count": authenticated_lanes,
        "all_six_account_types_supported": set(SUPPORTED_ACCOUNTS) == target_accounts,
    }


def validate_authenticated_browser_configuration(
    targets: Iterable[BrowserDiscoveryTarget],
    *,
    require_credentials_or_storage: bool = False,
) -> dict[str, Any]:
    """Validate the complete six-lane account configuration without exposing secrets.

    This validates repository/runtime wiring only. It does not claim that a
    live browser session is currently authenticated.
    """
    target_list = tuple(targets)
    by_account: dict[str, list[BrowserDiscoveryTarget]] = {account: [] for account in SUPPORTED_ACCOUNTS}
    for target in target_list:
        account = normalize_account(target.account)
        if account:
            if account not in by_account:
                raise BrowserDiscoveryConfigurationError(f"Unsupported authenticated browser account: {account}")
            by_account[account].append(target)

    missing = [account for account, lanes in by_account.items() if not lanes]
    if missing:
        raise BrowserDiscoveryConfigurationError(
            "Missing authenticated browser lanes for: " + ", ".join(missing)
        )

    invalid: list[str] = []
    from .account_auth import auth_status
    statuses = auth_status()
    for account, lanes in by_account.items():
        for lane in lanes:
            if not lane.authenticated_selector:
                invalid.append(f"{account}/{lane.lane}: authenticated_selector missing")
            if not lane.item_selector or not lane.text_selector:
                invalid.append(f"{account}/{lane.lane}: item_selector and text_selector are required")
            login_ready = all(
                (
                    lane.login_url or _account_env(account, "LOGIN_URL"),
                    _account_env(account, "USERNAME_SELECTOR"),
                    _account_env(account, "PASSWORD_SELECTOR"),
                    _account_env(account, "SUBMIT_SELECTOR"),
                )
            )
            if require_credentials_or_storage:
                status = statuses[account]
                if not status["configured"]:
                    invalid.append(f"{account}/{lane.lane}: credentials or storage state not configured")
                elif not status["session_ready"] and not (status["relogin_ready"] and login_ready):
                    invalid.append(
                        f"{account}/{lane.lane}: authenticated storage state or complete automatic re-login configuration required"
                    )

    if invalid:
        raise BrowserDiscoveryConfigurationError("; ".join(invalid))

    return {
        "supported_accounts": list(SUPPORTED_ACCOUNTS),
        "configured_accounts": list(SUPPORTED_ACCOUNTS),
        "configured_lane_count": len(target_list),
        "authenticated_lane_count": sum(len(lanes) for lanes in by_account.values()),
        "automatic_relogin_ready_accounts": [
            account for account in SUPPORTED_ACCOUNTS
            if all(
                (
                    _account_env(account, "USERNAME_SELECTOR"),
                    _account_env(account, "PASSWORD_SELECTOR"),
                    _account_env(account, "SUBMIT_SELECTOR"),
                    _account_env(account, "LOGIN_URL"),
                )
            )
        ],
        "secrets_exposed": False,
    }


class FreeAuthenticatedBrowserCollector:
    """Collect from an operator-owned persistent browser with bounded recovery."""

    def __init__(self, target: BrowserDiscoveryTarget):
        self.target = target

    def _open_context(self, playwright: Any) -> tuple[Any, bool]:
        endpoint = _browser_endpoint()
        if endpoint:
            try:
                browser = playwright.chromium.connect_over_cdp(endpoint, timeout=30_000)
            except Exception as exc:
                raise BrowserDiscoveryUnavailable(
                    f"Persistent browser CDP endpoint is unavailable: {endpoint}"
                ) from exc
            contexts = browser.contexts
            if not contexts:
                raise BrowserDiscoveryUnavailable("Persistent CDP browser has no active browser context")
            return contexts[0], False

        profile = _required_profile()
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=_env("THORIO_BROWSER_HEADLESS", "1").lower() in {"1", "true", "yes", "on"},
        )
        return context, True

    def _session_is_valid(self, page: Any) -> bool:
        selector = self.target.authenticated_selector
        if not selector:
            return True
        try:
            return page.locator(selector).count() > 0
        except Exception:
            return False

    def _login(self, page: Any, account: str, credentials: Any = None) -> None:
        login_url = self.target.login_url or _account_env(account, "LOGIN_URL")
        username_selector = _account_env(account, "USERNAME_SELECTOR")
        password_selector = _account_env(account, "PASSWORD_SELECTOR")
        submit_selector = _account_env(account, "SUBMIT_SELECTOR")
        if not login_url or not username_selector or not password_selector or not submit_selector:
            raise BrowserDiscoveryConfigurationError(
                f"{account}: login URL and username/password/submit selectors must be configured for automatic re-login"
            )

        if credentials is None:
            from .account_auth import login_credentials
            credentials = login_credentials(account)
        page.goto(login_url, wait_until="domcontentloaded", timeout=_browser_navigation_timeout())
        page.locator(username_selector).fill(credentials.username)
        page.locator(password_selector).fill(credentials.password)
        page.locator(submit_selector).click()
        try:
            page.wait_for_load_state("domcontentloaded", timeout=_browser_navigation_timeout())
        except Exception:
            pass
        if not self._session_is_valid(page):
            raise BrowserDiscoveryUnavailable(f"{account}: authorized login completed without a valid authenticated session")

    def _ensure_authenticated(self, page: Any) -> tuple[bool, bool]:
        account = normalize_account(self.target.account)
        if not account or not self.target.authenticated_selector:
            return True, False
        was_valid = self._session_is_valid(page)
        ensure_authenticated(
            account,
            lambda: self._session_is_valid(page),
            lambda credentials: self._login(page, account, credentials),
        )
        if not self._session_is_valid(page):
            raise BrowserDiscoveryUnavailable(f"{account}: browser session is not authenticated")
        return True, not was_valid

    def collect(self, checkpoint: Optional[str] = None) -> BrowserDiscoveryResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserDiscoveryUnavailable(
                "Playwright is required for browser discovery; install it in the authorized local runner environment"
            ) from exc

        seen_after = checkpoint or ""
        records: list[dict[str, Any]] = []
        next_checkpoint: Optional[str] = None
        page: Any = None
        authenticated = False
        relogin_attempted = False

        with sync_playwright() as playwright:
            context, owns_context = self._open_context(playwright)
            try:
                page = context.new_page()
                navigation_timeout = _browser_navigation_timeout()
                page.goto(self.target.url, wait_until="domcontentloaded", timeout=navigation_timeout)
                authenticated, relogin_attempted = self._ensure_authenticated(page)
                if page.url != self.target.url:
                    page.goto(self.target.url, wait_until="domcontentloaded", timeout=navigation_timeout)
                try:
                    page.wait_for_load_state("networkidle", timeout=navigation_timeout)
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
                        "authenticated": authenticated,
                    }
                    if author:
                        record["person"] = author
                    records.append(normalize_lead_input(record))
                    next_checkpoint = fingerprint
            finally:
                if page is not None:
                    try:
                        page.close()
                    except Exception:
                        pass
                if owns_context:
                    context.close()

        return BrowserDiscoveryResult(
            lane=self.target.lane,
            target=self.target.name,
            records=records,
            checkpoint=next_checkpoint,
            collected_at=datetime.now(timezone.utc).isoformat(),
            authenticated=authenticated,
            relogin_attempted=relogin_attempted,
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
