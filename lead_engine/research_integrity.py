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

    def guarded_research(lead: Mapping[str, Any]) -> dict[str, Any]:
        candidate = dict(lead)
        company = str(candidate.get("company") or "").strip()
        exact_url = str(
            candidate.get("url")
            or candidate.get("job_url")
            or ""
        ).strip()
        source_url = str(candidate.get("source_url") or "").strip()

        # Job research must use the exact opportunity URL produced by the
        # collector. A source listing/API endpoint is discovery provenance,
        # never company-specific evidence.
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

        result = original(candidate)
        pages = result.get("raw_pages", []) if isinstance(result, Mapping) else []
        safe_pages = [
            page for page in pages
            if isinstance(page, Mapping) and _page_identity_matches(page, company)
        ]

        # Never promote facts from a page that does not identify the target
        # company. Rejected pages remain in the raw audit trail but cannot
        # populate company/product/hiring/decision-maker/need/commercial facts.
        classified = public_research._classify(safe_pages)
        audited_pages = []
        safe_ids = {str(page.get("url") or "") for page in safe_pages}
        for page in pages:
            audited = dict(page) if isinstance(page, Mapping) else {"value": page}
            url = str(audited.get("url") or "")
            if url in safe_ids:
                audited["evidence_admission_status"] = "admitted_company_identity_match"
            else:
                audited["evidence_admission_status"] = "rejected_company_identity_mismatch"
            audited_pages.append(audited)

        updated = dict(result)
        updated["facts"] = classified
        updated["raw_pages"] = audited_pages
        updated["pages_collected"] = len(safe_pages)
        updated["status"] = "evidence_found" if safe_pages else "no_company_matched_evidence"
        updated["identity_gate"] = "company_identity_required"
        updated["company_identity_match_count"] = len(safe_pages)
        updated["rejected_page_count"] = len(pages) - len(safe_pages)
        return updated

    public_research.research_public_web = guarded_research
    public_research._THORIO_IDENTITY_GUARD = True
