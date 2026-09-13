"""Bounded public-web research with provenance and no synthetic facts."""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from typing import Any, Dict, Iterable, Mapping

import requests

USER_AGENT = "ThorioLeadResearch/1.0 (+https://thorio.co)"
REQUEST_TIMEOUT = (5, 15)
MAX_BYTES = 1_000_000
MAX_TEXT = 12_000
MIN_DOMAIN_DELAY = 1.0
MAX_PAGES = 6

_LOCK = threading.Lock()
_LAST_REQUEST: dict[str, float] = defaultdict(float)
_ROBOTS_CACHE: dict[str, tuple[float, RobotFileParser | None, str]] = {}
_PAGE_CACHE: dict[str, tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL = 24 * 3600


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(text: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().split(":", 1)[0]


def _allowed(url: str) -> tuple[bool, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False, "invalid_public_url"
    domain = _domain(url)
    now = time.time()
    cached = _ROBOTS_CACHE.get(domain)
    if cached and now - cached[0] < _CACHE_TTL:
        parser, status = cached[1], cached[2]
    else:
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            response = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
            if response.status_code == 404:
                parser, status = None, "robots_not_found"
            elif response.status_code >= 400:
                return False, f"robots_http_{response.status_code}"
            else:
                parser = RobotFileParser()
                parser.set_url(robots_url)
                parser.parse(response.text.splitlines())
                status = "robots_checked"
            _ROBOTS_CACHE[domain] = (now, parser, status)
        except requests.RequestException as exc:
            return False, f"robots_fetch_failed:{type(exc).__name__}"
    if parser is not None and not parser.can_fetch(USER_AGENT, url):
        return False, "robots_disallowed"
    return True, status


def _throttle(domain: str) -> None:
    with _LOCK:
        wait = MIN_DOMAIN_DELAY - (time.monotonic() - _LAST_REQUEST[domain])
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST[domain] = time.monotonic()


def _fetch(url: str) -> Dict[str, Any]:
    cached = _PAGE_CACHE.get(url)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return dict(cached[1])
    allowed, robots_status = _allowed(url)
    base = {"url": url, "observed_at": _now(), "robots_status": robots_status, "facts": [], "links": []}
    if not allowed:
        base["status"] = "not_collected"
        base["reason"] = robots_status
        return base
    domain = _domain(url)
    _throttle(domain)
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}, timeout=REQUEST_TIMEOUT, stream=True)
        if response.status_code >= 400:
            base.update({"status": "not_collected", "http_status": response.status_code, "reason": f"http_{response.status_code}"})
            return base
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=16384):
            if not chunk:
                continue
            chunks.append(chunk)
            size += len(chunk)
            if size >= MAX_BYTES:
                break
        html = b"".join(chunks)[:MAX_BYTES].decode(response.encoding or "utf-8", errors="replace")
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        description_match = re.search(r'<meta[^>]+name=[\"\']description[\"\'][^>]+content=[\"\'](.*?)[\"\']', html, re.I | re.S)
        text = _clean(html)[:MAX_TEXT]
        links = []
        for match in re.finditer(r'<a[^>]+href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>', html, re.I | re.S):
            href, label = match.group(1).strip(), _clean(match.group(2))
            absolute = urljoin(url, href)
            if urlparse(absolute).scheme in {"http", "https"} and _domain(absolute) == domain:
                links.append({"url": absolute, "label": label[:160]})
            if len(links) >= 40:
                break
        facts = []
        if title_match:
            facts.append({"field": "page_title", "value": _clean(title_match.group(1))[:500], "evidence_url": url})
        if description_match:
            facts.append({"field": "meta_description", "value": _clean(description_match.group(1))[:1000], "evidence_url": url})
        if text:
            facts.append({"field": "page_text", "value": text, "evidence_url": url})
        result = {**base, "status": "collected", "http_status": response.status_code, "content_type": response.headers.get("content-type", ""), "facts": facts, "links": links}
        _PAGE_CACHE[url] = (time.time(), result)
        return result
    except (requests.RequestException, UnicodeError) as exc:
        base.update({"status": "not_collected", "reason": f"fetch_failed:{type(exc).__name__}"})
        return base


def _candidate_urls(lead: Mapping[str, Any]) -> list[str]:
    verified_company_urls = [lead.get("website"), lead.get("company_url")]
    company_domains: set[str] = set()
    raw_roots: list[str] = []
    for value in verified_company_urls:
        if not value:
            continue
        value = str(value).strip()
        if not value.startswith(("http://", "https://")):
            continue
        parsed = urlparse(value)
        if parsed.netloc:
            company_domains.add(_domain(value))
            raw_roots.append(f"{parsed.scheme}://{parsed.netloc}/")
            raw_roots.append(value)
    source_url = str(lead.get("source_url") or lead.get("url") or "").strip()
    if source_url.startswith(("http://", "https://")) and _domain(source_url) in company_domains:
        raw_roots.append(source_url)
    ordered: list[str] = []
    seen: set[str] = set()
    for root in raw_roots:
        base = root.rstrip("/") + "/"
        paths = ["", "about", "company", "team", "product", "careers", "jobs"] if root.endswith("/") else [""]
        for path in paths:
            candidate = urljoin(base, path)
            if candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)
            if len(ordered) >= MAX_PAGES:
                return ordered
    return ordered


def _classify(pages: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, list[Dict[str, Any]]] = {"company": [], "product": [], "hiring": [], "decision_maker": [], "business_need": [], "commercial": []}
    patterns = {
        "company": ("about", "company", "mission", "customers", "team"),
        "product": ("product", "platform", "saas", "software", "technology", "api"),
        "hiring": ("career", "careers", "jobs", "hiring", "open roles", "join our team"),
        "decision_maker": ("ceo", "cto", "founder", "co-founder", "leadership", "executive"),
        "business_need": ("need", "problem", "solution", "customers", "scale", "growth", "automation"),
        "commercial": ("pricing", "plans", "enterprise", "contact sales", "budget"),
    }
    for page in pages:
        if page.get("status") != "collected":
            continue
        url = page.get("url")
        for fact in page.get("facts", []):
            if not isinstance(fact, Mapping):
                continue
            text = str(fact.get("value") or "")
            lower = text.lower()
            for category, terms in patterns.items():
                matches = [term for term in terms if term in lower]
                if matches:
                    result[category].append({"url": url, "matches": matches, "evidence": text[:3000], "observed_at": page.get("observed_at"), "verification_status": "observed_evidence"})
    return result


def research_public_web(lead: Mapping[str, Any]) -> Dict[str, Any]:
    """Collect bounded public evidence only from the company's verified domain inputs."""
    urls = _candidate_urls(lead)
    pages = []
    for url in urls:
        page = _fetch(url)
        pages.append(page)
        if len(pages) >= MAX_PAGES:
            break
    collected = [page for page in pages if page.get("status") == "collected"]
    classified = _classify(pages)
    sources = [{"url": page.get("url"), "observed_at": page.get("observed_at"), "status": page.get("status"), "robots_status": page.get("robots_status"), "http_status": page.get("http_status")} for page in pages]
    return {"status": "evidence_found" if collected else "no_public_evidence", "research_method": "public_web_http", "researched_at": _now(), "pages_attempted": len(pages), "pages_collected": len(collected), "sources": sources, "facts": classified, "raw_pages": pages, "verified_fields": [], "fabricated_fields": []}
