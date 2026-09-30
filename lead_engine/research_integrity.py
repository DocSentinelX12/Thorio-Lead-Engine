"""Research integrity guard: never promote evidence belonging to another lead."""
from __future__ import annotations

import re
from typing import Any, Mapping


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _company_variants(company: str) -> list[str]:
    normalized = _normalized(company)
    if not normalized:
        return []
    variants = [normalized]
    core = re.sub(
        r"\b(incorporated|inc|corp|corporation|llc|ltd|limited|co|company)\b",
        " ",
        normalized,
    )
    core = re.sub(r"\s+", " ", core).strip()
    if core and core != normalized:
        variants.append(core)
    return list(dict.fromkeys(variants))


def _page_identity_matches(page: Mapping[str, Any], company: str) -> bool:
    if page.get("status") != "collected":
        return False
    values: list[str] = []
    for fact in page.get("facts", []) if isinstance(page.get("facts"), list) else []:
        if isinstance(fact, Mapping):
            values.append(str(fact.get("value") or ""))
    text = _normalized(" ".join(values))
    if not text:
        return False
    return any(variant in text for variant in _company_variants(company))


def install() -> None:
    """Install the identity gate before advanced_agent_logic imports research_public_web."""
    from . import public_research

    if getattr(public_research, "_THORIO_IDENTITY_GUARD", False):
        return

    original = public_research.research_public_web

    def guarded_research(lead: Mapping[str, Any], checkpoint: Any = None) -> dict[str, Any]:
        candidate = dict(lead)
        company = str(candidate.get("company") or "").strip()
        exact_url = str(
            candidate.get("url")
            or candidate.get("job_url")
            or ""
        ).strip()
        source_url = str(candidate.get("source_url") or "").strip()

        signal_type = str(candidate.get("signal_type") or "").strip().lower()
        if signal_type == "hiring" and not exact_url:
            return {
                "status": "no_exact_opportunity_url",
                "research_method": "public_web_http",
                "researched_at": public_research._now(),
                "pages_attempted": 0,
                "pages_collected": 0,
                "sources": ([{"url": source_url, "status": "not_collected", "reason": "listing_or_api_url_not_admitted_as_company_evidence"}] if source_url else []),
                "facts": {"company": [], "product": [], "hiring": [], "decision_maker": [], "business_need": [], "commercial": []},
                "raw_pages": [],
                "verified_fields": [],
                "fabricated_fields": [],
                "identity_gate": "blocked_without_exact_opportunity_url",
            }

        if exact_url:
            candidate["source_url"] = exact_url

        result = original(candidate, checkpoint=checkpoint)
        pages = result.get("raw_pages", []) if isinstance(result, Mapping) else []

        # A blocked, failed, or otherwise uncollected page is a collection
        # outcome, not an identity mismatch. Preserve that original outcome.
        collected_pages = [
            page for page in pages
            if isinstance(page, Mapping) and page.get("status") == "collected"
        ]
        if not collected_pages:
            return dict(result)

        matching_pages = [page for page in collected_pages if _page_identity_matches(page, company)]
        if matching_pages:
            return dict(result)

        guarded = dict(result)
        guarded["status"] = "identity_mismatch"
        guarded["identity_gate"] = "blocked_company_identity_mismatch"
        guarded["facts"] = {"company": [], "product": [], "hiring": [], "decision_maker": [], "business_need": [], "commercial": []}
        guarded["verified_fields"] = []
        guarded["fabricated_fields"] = []
        guarded["identity_mismatch_pages"] = [dict(page) for page in matching_pages]
        guarded["raw_pages"] = [
            {**dict(page), "evidence_admission_status": "rejected_company_identity_mismatch"}
            for page in pages
            if isinstance(page, Mapping)
        ]
        return guarded

    public_research.research_public_web = guarded_research
    public_research._THORIO_IDENTITY_GUARD = True
