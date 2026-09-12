"""Real inbound revenue observation through an operator-authenticated browser.

This adapter is configuration-driven. It never invents provider URLs,
selectors, account names, or message identifiers. A target is usable only
when the operator supplies the exact authenticated inbox selectors. The
conversation thread URL is taken from the real outbound provider result that
was persisted after a confirmed send.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

from .account_auth import ensure_authenticated
from .revenue_conversation import record_inbound_event


class BrowserRevenueInboundConfigurationError(RuntimeError):
    """Raised when real inbound browser configuration is incomplete."""


class BrowserRevenueInboundUnavailable(RuntimeError):
    """Raised when an authenticated browser cannot observe a configured inbox."""


@dataclass(frozen=True)
class BrowserRevenueInboundTarget:
    channel: str
    account: str
    inbox_url: str
    message_selector: str
    message_author_selector: str
    message_id_selector: str
    timestamp_selector: str
    body_selector: str
    self_marker: str
    authenticated_selector: str = ""
    login_url: str = ""

    def __post_init__(self) -> None:
        required = {
            "channel": self.channel,
            "account": self.account,
            "inbox_url": self.inbox_url,
            "message_selector": self.message_selector,
            "message_author_selector": self.message_author_selector,
            "message_id_selector": self.message_id_selector,
            "timestamp_selector": self.timestamp_selector,
            "body_selector": self.body_selector,
            "self_marker": self.self_marker,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise BrowserRevenueInboundConfigurationError(
                f"inbound browser target missing required fields: {', '.join(missing)}"
            )
        value = self.inbox_url.strip()
        if not value.startswith(("https://", "http://")):
            raise BrowserRevenueInboundConfigurationError(
                f"inbound browser inbox_url must be HTTP(S): {value!r}"
            )


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def configured_browser_revenue_inbound_targets() -> dict[str, BrowserRevenueInboundTarget]:
    raw = _env("THORIO_REVENUE_BROWSER_INBOUND_TARGETS")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BrowserRevenueInboundConfigurationError(
            "THORIO_REVENUE_BROWSER_INBOUND_TARGETS must be valid JSON"
        ) from exc
    if not isinstance(payload, list):
        raise BrowserRevenueInboundConfigurationError(
            "THORIO_REVENUE_BROWSER_INBOUND_TARGETS must be a JSON list"
        )

    targets: dict[str, BrowserRevenueInboundTarget] = {}
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise BrowserRevenueInboundConfigurationError(
                f"inbound browser target {index} must be an object"
            )
        target = BrowserRevenueInboundTarget(
            channel=str(item.get("channel", "")).strip().lower(),
            account=str(item.get("account", "")).strip().lower().replace("-", "_").replace(" ", "_"),
            inbox_url=str(item.get("inbox_url", "")).strip(),
            message_selector=str(item.get("message_selector", "")).strip(),
            message_author_selector=str(item.get("message_author_selector", "")).strip(),
            message_id_selector=str(item.get("message_id_selector", "")).strip(),
            timestamp_selector=str(item.get("timestamp_selector", "")).strip(),
            body_selector=str(item.get("body_selector", "")).strip(),
            self_marker=str(item.get("self_marker", "")).strip(),
            authenticated_selector=str(item.get("authenticated_selector", "")).strip(),
            login_url=str(item.get("login_url", "")).strip(),
        )
        if target.channel in targets:
            raise BrowserRevenueInboundConfigurationError(
                f"duplicate inbound browser channel: {target.channel}"
            )
        targets[target.channel] = target
    return targets


class BrowserRevenueInboundObserver:
    """Observe actual inbound messages from an authenticated browser session."""

    def __init__(self, targets: Mapping[str, BrowserRevenueInboundTarget] | None = None):
        self.targets = dict(targets or configured_browser_revenue_inbound_targets())
        if not self.targets:
            raise BrowserRevenueInboundConfigurationError(
                "no real inbound browser targets are configured"
            )

    @staticmethod
    def _endpoint() -> str:
        return _env("THORIO_BROWSER_CDP_URL")

    @staticmethod
    def _profile_dir() -> str:
        value = _env("THORIO_BROWSER_PROFILE_DIR")
        if not value:
            raise BrowserRevenueInboundConfigurationError(
                "THORIO_BROWSER_PROFILE_DIR is required for browser inbound observation"
            )
        return value

    @staticmethod
    def _navigation_timeout() -> int:
        try:
            seconds = int(_env("THORIO_BROWSER_NAVIGATION_TIMEOUT") or "30")
        except ValueError:
            seconds = 30
        return max(5, min(seconds, 120)) * 1000

    def _open_context(self, playwright: Any) -> tuple[Any, bool, Any | None]:
        endpoint = self._endpoint()
        if endpoint:
            try:
                browser = playwright.chromium.connect_over_cdp(endpoint, timeout=30_000)
            except Exception as exc:
                raise BrowserRevenueInboundUnavailable(
                    "persistent browser CDP endpoint is unavailable"
                ) from exc
            if not browser.contexts:
                raise BrowserRevenueInboundUnavailable(
                    "persistent CDP browser has no active browser context"
                )
            return browser.contexts[0], False, browser
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=self._profile_dir(),
                headless=_env("THORIO_BROWSER_HEADLESS", "1").lower()
                in {"1", "true", "yes", "on"},
            )
        except Exception as exc:
            raise BrowserRevenueInboundUnavailable(
                "persistent browser profile could not be opened"
            ) from exc
        return context, True, None

    @staticmethod
    def _session_is_valid(page: Any, target: BrowserRevenueInboundTarget) -> bool:
        if target.authenticated_selector:
            try:
                return page.locator(target.authenticated_selector).count() > 0
            except Exception:
                return False
        try:
            url = str(page.url or "").lower()
        except Exception:
            return False
        return not any(marker in url for marker in ("/login", "/signin", "/sign-in", "authwall", "/checkpoint"))

    def _login(self, page: Any, target: BrowserRevenueInboundTarget, credentials: Any) -> None:
        prefix = f"THORIO_ACCOUNT_{target.account.upper()}"
        username_selector = _env(prefix + "_USERNAME_SELECTOR")
        password_selector = _env(prefix + "_PASSWORD_SELECTOR")
        submit_selector = _env(prefix + "_SUBMIT_SELECTOR")
        login_url = target.login_url or _env(prefix + "_LOGIN_URL")
        if not all((login_url, username_selector, password_selector, submit_selector)):
            raise BrowserRevenueInboundConfigurationError(
                f"{target.channel}: normal authorized login configuration is incomplete"
            )
        page.goto(login_url, wait_until="domcontentloaded", timeout=self._navigation_timeout())
        page.locator(username_selector).fill(credentials.username)
        page.locator(password_selector).fill(credentials.password)
        page.locator(submit_selector).click()
        try:
            page.wait_for_load_state("domcontentloaded", timeout=self._navigation_timeout())
        except Exception:
            pass
        if not self._session_is_valid(page, target):
            raise BrowserRevenueInboundUnavailable(
                f"{target.channel}: authorized login did not produce an authenticated session"
            )

    def _ensure_authenticated(self, page: Any, target: BrowserRevenueInboundTarget) -> None:
        ensure_authenticated(
            target.account,
            lambda: self._session_is_valid(page, target),
            lambda supplied: self._login(page, target, supplied),
        )
        if not self._session_is_valid(page, target):
            raise BrowserRevenueInboundUnavailable(
                f"{target.channel}: browser session is not authenticated"
            )

    def observe(self, *, channel: str, thread_url: str) -> list[dict[str, Any]]:
        target = self.targets.get(str(channel or "").strip().lower())
        if target is None:
            raise BrowserRevenueInboundConfigurationError(
                f"no real inbound browser target is configured for channel {channel!r}"
            )
        destination = str(thread_url or "").strip()
        if not destination:
            raise BrowserRevenueInboundConfigurationError(
                f"{target.channel}: real persisted thread URL is required"
            )
        if not destination.startswith(("https://", "http://")):
            raise BrowserRevenueInboundConfigurationError(
                f"{target.channel}: persisted thread URL must be HTTP(S): {destination!r}"
            )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserRevenueInboundUnavailable(
                "Playwright is required for real browser inbound observation"
            ) from exc

        with sync_playwright() as playwright:
            context, owns_context, browser = self._open_context(playwright)
            page = None
            try:
                page = context.new_page()
                page.goto(destination, wait_until="domcontentloaded", timeout=self._navigation_timeout())
                self._ensure_authenticated(page, target)
                if page.url != destination:
                    page.goto(destination, wait_until="domcontentloaded", timeout=self._navigation_timeout())
                rows = page.locator(target.message_selector)
                events: list[dict[str, Any]] = []
                for index in range(rows.count()):
                    row = rows.nth(index)
                    author = row.locator(target.message_author_selector).inner_text().strip()
                    if author == target.self_marker:
                        continue
                    body = row.locator(target.body_selector).inner_text().strip()
                    message_node = row.locator(target.message_id_selector)
                    message_id = message_node.get_attribute("data-message-id") or message_node.inner_text().strip()
                    timestamp = row.locator(target.timestamp_selector).inner_text().strip()
                    if not message_id or not body:
                        continue
                    events.append({
                        "channel": target.channel,
                        "account": target.account,
                        "thread_url": destination,
                        "event_id": f"{target.channel}:{message_id}",
                        "message_id": message_id,
                        "author": author,
                        "body": body,
                        "timestamp": timestamp,
                    })
                return events
            except BrowserRevenueInboundUnavailable:
                raise
            except Exception as exc:
                raise BrowserRevenueInboundUnavailable(
                    f"authenticated browser inbound observation failed for {target.channel}/{target.account}: {exc}"
                ) from exc
            finally:
                if page is not None:
                    try:
                        page.close()
                    except Exception:
                        pass
                if owns_context:
                    context.close()
                elif browser is not None:
                    browser.close()


def _thread_url_from_lead(lead: Mapping[str, Any]) -> str:
    history = lead.get("outreach_history")
    if not isinstance(history, list):
        return ""
    for item in reversed(history):
        if not isinstance(item, Mapping):
            continue
        provider_result = item.get("provider_result")
        if isinstance(provider_result, Mapping) and str(provider_result.get("thread_url") or "").strip():
            return str(provider_result["thread_url"]).strip()
    return ""


def poll_browser_revenue_inbound(db: Any, *, observer: BrowserRevenueInboundObserver | None = None, limit: int = 100) -> dict[str, Any]:
    targets = configured_browser_revenue_inbound_targets()
    if not targets:
        return {"status": "disabled", "observed_count": 0, "recorded_count": 0, "failed_count": 0, "failures": []}
    observer = observer or BrowserRevenueInboundObserver(targets)
    observed = 0
    recorded = 0
    failures: list[dict[str, str]] = []
    for lead in db.all_leads():
        if observed >= limit:
            break
        lifecycle = str(lead.get("revenue_lifecycle_state") or "").strip().lower()
        if lifecycle in {"converted", "closed_lost", "disqualified", "stopped"}:
            continue
        conversation_id = str(lead.get("conversation_id") or "").strip()
        channel = str(lead.get("outreach_channel") or "").strip().lower()
        thread_url = _thread_url_from_lead(lead)
        if not conversation_id or not channel or not thread_url or channel not in targets:
            continue
        try:
            events = observer.observe(channel=channel, thread_url=thread_url)
            observed += 1
            for event in events:
                result = record_inbound_event(
                    db,
                    opportunity_id=str(lead.get("fingerprint") or ""),
                    conversation_id=conversation_id,
                    event_id=str(event["event_id"]),
                    text=str(event["body"]),
                )
                recorded += 1 if result else 0
        except Exception as exc:
            failures.append({
                "opportunity_id": str(lead.get("fingerprint") or ""),
                "channel": channel,
                "error": str(exc),
            })
    return {
        "status": "completed",
        "observed_count": observed,
        "recorded_count": recorded,
        "failed_count": len(failures),
        "failures": failures,
    }
