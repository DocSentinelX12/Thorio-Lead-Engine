"""Real outbound revenue transport through an operator-authenticated browser.

This adapter intentionally contains no platform URLs or selectors. Every
platform-specific navigation and UI selector is supplied by runtime
configuration, so the engine cannot silently guess a recipient or click an
unknown control. It uses the same authorized persistent browser foundation as
browser discovery and never bypasses MFA, CAPTCHA, rate limits, or platform
security controls.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

from .account_auth import ensure_authenticated


class BrowserRevenueConfigurationError(RuntimeError):
    """Raised when real browser revenue transport configuration is incomplete."""


class BrowserRevenueUnavailable(RuntimeError):
    """Raised when the authorized browser cannot perform the requested send."""


@dataclass(frozen=True)
class BrowserRevenueTarget:
    channel: str
    account: str
    recipient_url_template: str
    composer_selector: str
    body_selector: str
    send_selector: str
    sent_selector: str
    subject_selector: str = ""
    authenticated_selector: str = ""
    login_url: str = ""

    def __post_init__(self) -> None:
        required = {
            "channel": self.channel,
            "account": self.account,
            "recipient_url_template": self.recipient_url_template,
            "composer_selector": self.composer_selector,
            "body_selector": self.body_selector,
            "send_selector": self.send_selector,
            "sent_selector": self.sent_selector,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise BrowserRevenueConfigurationError(
                f"revenue browser target missing required fields: {', '.join(missing)}"
            )
        if not self.recipient_url_template.startswith(("https://", "http://")):
            raise BrowserRevenueConfigurationError(
                f"revenue browser recipient_url_template must be HTTP(S): {self.recipient_url_template!r}"
            )


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def configured_browser_revenue_targets() -> dict[str, BrowserRevenueTarget]:
    """Load explicit runtime target definitions. No platform defaults are guessed."""
    raw = _env("THORIO_REVENUE_BROWSER_TARGETS")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BrowserRevenueConfigurationError(
            "THORIO_REVENUE_BROWSER_TARGETS must be valid JSON"
        ) from exc
    if not isinstance(payload, list):
        raise BrowserRevenueConfigurationError(
            "THORIO_REVENUE_BROWSER_TARGETS must be a JSON list"
        )

    targets: dict[str, BrowserRevenueTarget] = {}
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise BrowserRevenueConfigurationError(
                f"revenue browser target {index} must be an object"
            )
        target = BrowserRevenueTarget(
            channel=str(item.get("channel", "")).strip().lower(),
            account=str(item.get("account", "")).strip().lower().replace("-", "_").replace(" ", "_"),
            recipient_url_template=str(item.get("recipient_url_template", "")).strip(),
            composer_selector=str(item.get("composer_selector", "")).strip(),
            body_selector=str(item.get("body_selector", "")).strip(),
            send_selector=str(item.get("send_selector", "")).strip(),
            sent_selector=str(item.get("sent_selector", "")).strip(),
            subject_selector=str(item.get("subject_selector", "")).strip(),
            authenticated_selector=str(item.get("authenticated_selector", "")).strip(),
            login_url=str(item.get("login_url", "")).strip(),
        )
        if target.channel in targets:
            raise BrowserRevenueConfigurationError(
                f"duplicate revenue browser channel: {target.channel}"
            )
        targets[target.channel] = target
    return targets


class BrowserRevenueTransport:
    """Send through an already-authorized persistent browser session."""

    def __init__(self, targets: Mapping[str, BrowserRevenueTarget] | None = None):
        self.targets = dict(targets or configured_browser_revenue_targets())
        if not self.targets:
            raise BrowserRevenueConfigurationError(
                "no real revenue browser targets are configured"
            )

    @staticmethod
    def _browser_endpoint() -> str:
        return _env("THORIO_BROWSER_CDP_URL")

    @staticmethod
    def _profile_dir() -> str:
        value = _env("THORIO_BROWSER_PROFILE_DIR")
        if not value:
            raise BrowserRevenueConfigurationError(
                "THORIO_BROWSER_PROFILE_DIR is required for browser revenue transport"
            )
        return value

    @staticmethod
    def _navigation_timeout() -> int:
        try:
            seconds = int(_env("THORIO_BROWSER_NAVIGATION_TIMEOUT") or "30")
        except ValueError:
            seconds = 30
        return max(5, min(seconds, 120)) * 1000

    def _open_context(self, playwright: Any) -> tuple[Any, bool]:
        endpoint = self._browser_endpoint()
        if endpoint:
            try:
                browser = playwright.chromium.connect_over_cdp(endpoint, timeout=30_000)
            except Exception as exc:
                raise BrowserRevenueUnavailable(
                    "persistent browser CDP endpoint is unavailable"
                ) from exc
            if not browser.contexts:
                raise BrowserRevenueUnavailable(
                    "persistent CDP browser has no active browser context"
                )
            return browser.contexts[0], False

        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=self._profile_dir(),
                headless=_env("THORIO_BROWSER_HEADLESS", "1").lower()
                in {"1", "true", "yes", "on"},
            )
        except Exception as exc:
            raise BrowserRevenueUnavailable(
                "persistent browser profile could not be opened"
            ) from exc
        return context, True

    @staticmethod
    def _session_is_valid(page: Any, target: BrowserRevenueTarget) -> bool:
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

    def _login(self, page: Any, target: BrowserRevenueTarget, credentials: Any) -> None:
        prefix = f"THORIO_ACCOUNT_{target.account.upper()}"
        username_selector = _env(prefix + "_USERNAME_SELECTOR")
        password_selector = _env(prefix + "_PASSWORD_SELECTOR")
        submit_selector = _env(prefix + "_SUBMIT_SELECTOR")
        login_url = target.login_url or _env(prefix + "_LOGIN_URL")
        if not all((login_url, username_selector, password_selector, submit_selector)):
            raise BrowserRevenueConfigurationError(
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
            raise BrowserRevenueUnavailable(
                f"{target.channel}: authorized login did not produce an authenticated session"
            )

    def _ensure_authenticated(self, page: Any, target: BrowserRevenueTarget) -> None:
        ensure_authenticated(
            target.account,
            lambda: self._session_is_valid(page, target),
            lambda supplied: self._login(page, target, supplied),
        )
        if not self._session_is_valid(page, target):
            raise BrowserRevenueUnavailable(
                f"{target.channel}: browser session is not authenticated"
            )

    def send(
        self,
        *,
        channel: str,
        recipient: Mapping[str, Any],
        subject: str,
        body: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        target = self.targets.get(str(channel or "").strip().lower())
        if target is None:
            raise BrowserRevenueConfigurationError(
                f"no real browser revenue target is configured for channel {channel!r}"
            )
        recipient_value = str(
            recipient.get("url")
            or recipient.get("profile_url")
            or recipient.get("email")
            or ""
        ).strip()
        if not recipient_value:
            raise BrowserRevenueConfigurationError(
                f"{target.channel}: recipient must include an explicit url, profile_url, or email"
            )
        try:
            destination = target.recipient_url_template.format(
                recipient_url=recipient_value,
                recipient=recipient_value,
            )
        except KeyError as exc:
            raise BrowserRevenueConfigurationError(
                f"{target.channel}: recipient_url_template contains an unsupported field {exc.args[0]!r}"
            ) from exc

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserRevenueUnavailable(
                "Playwright is required for real browser revenue transport"
            ) from exc

        with sync_playwright() as playwright:
            context, owns_context = self._open_context(playwright)
            page = None
            try:
                page = context.new_page()
                page.goto(destination, wait_until="domcontentloaded", timeout=self._navigation_timeout())
                self._ensure_authenticated(page, target)
                if page.url != destination:
                    page.goto(destination, wait_until="domcontentloaded", timeout=self._navigation_timeout())
                try:
                    page.wait_for_load_state("networkidle", timeout=self._navigation_timeout())
                except Exception:
                    pass

                composer = page.locator(target.composer_selector)
                if composer.count() == 0:
                    raise BrowserRevenueUnavailable(
                        f"{target.channel}: configured composer selector was not found"
                    )
                if target.subject_selector:
                    subject_node = page.locator(target.subject_selector)
                    if subject_node.count() == 0:
                        raise BrowserRevenueUnavailable(
                            f"{target.channel}: configured subject selector was not found"
                        )
                    subject_node.first().fill(str(subject or ""))
                page.locator(target.body_selector).fill(str(body))
                page.locator(target.send_selector).click()

                sent = page.locator(target.sent_selector)
                try:
                    sent.first().wait_for(state="visible", timeout=self._navigation_timeout())
                except Exception as exc:
                    raise BrowserRevenueUnavailable(
                        f"{target.channel}: send control was clicked but configured sent confirmation was not observed"
                    ) from exc

                return {
                    "transport": "browser",
                    "channel": target.channel,
                    "idempotency_key": idempotency_key,
                    "confirmed_by": "configured_sent_selector",
                    "destination": destination,
                }
            finally:
                if page is not None:
                    try:
                        page.close()
                    except Exception:
                        pass
                if owns_context:
                    context.close()

    def reconcile(self, *, idempotency_key: str) -> Mapping[str, Any] | None:
        """Browser sessions do not expose a generic provider-side idempotency lookup."""
        return None
