from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping


RESEARCH_SECTIONS = (
    "business_need_research",
    "current_intent_research",
    "technical_product_hiring_research",
    "commercial_research",
    "route_research",
    "closer_package",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence_items(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _evidence_refs(items: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    refs: list[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        url = str(item.get("url") or item.get("source_url") or item.get("evidence_url") or "").strip()
        evidence = str(item.get("evidence") or item.get("signal") or "").strip()
        observed_at = str(item.get("observed_at") or item.get("collected_at") or "").strip()
        if not url and not evidence:
            continue
        key = (url, evidence)
        if key in seen:
            continue
        seen.add(key)
        refs.append({"url": url, "evidence": evidence, "observed_at": observed_at, "verification_status": str(item.get("verification_status") or "observed_evidence")})
    return refs


def _section(*, evidence: list[Dict[str, Any]], summary: str, source_sections: list[str], status: str = "observed_evidence") -> Dict[str, Any]:
    refs = _evidence_refs(evidence)
    return {
        "verified": False,
        "verification_status": status,
        "researched_at": _now(),
        "summary": summary,
        "evidence": refs,
        "provenance": {
            "source_sections": list(source_sections),
            "evidence_count": len(refs),
        },
    }


def build_canonical_research_package(
    lead: Mapping[str, Any],
    company_research: Mapping[str, Any],
    specialist_findings: Mapping[str, Any] | None = None,
) -> Dict[str, Dict[str, Any]]:
    """Materialize every canonical research section without promoting observation to verification."""
    findings = specialist_findings if isinstance(specialist_findings, Mapping) else {}
    public_facts = company_research.get("public_web_research", {}).get("facts", {}) if isinstance(company_research.get("public_web_research"), Mapping) else {}
    social = _evidence_items(company_research.get("social_findings"))

    business = _evidence_items(company_research.get("public_business_need_facts")) + _evidence_items(public_facts.get("business_need")) + _evidence_items(findings.get("business_need"))
    intent = _evidence_items(findings.get("current_intent")) + _evidence_items(findings.get("recent_inquiry")) + _evidence_items(company_research.get("public_hiring_facts")) + social
    technical = _evidence_items(company_research.get("public_product_facts")) + _evidence_items(company_research.get("public_hiring_facts")) + _evidence_items(findings.get("technical_product_hiring"))
    commercial = _evidence_items(company_research.get("public_commercial_facts")) + _evidence_items(findings.get("commercial"))
    routes = _evidence_items(findings.get("route")) + business + technical
    all_evidence = business + intent + technical + commercial + routes + _evidence_items(company_research.get("public_company_facts")) + _evidence_items(company_research.get("public_decision_maker_facts"))

    summaries = {
        "business_need_research": "Public and specialist evidence relevant to the observed business need.",
        "current_intent_research": "Public and specialist evidence relevant to current or recent intent.",
        "technical_product_hiring_research": "Public and specialist evidence relevant to technical, product, or hiring needs.",
        "commercial_research": "Public and specialist evidence relevant to commercial context.",
        "route_research": "Evidence relevant to matching the opportunity to supported revenue routes.",
    }
    sources = {
        "business_need_research": ["public_business_need_facts", "specialist_findings.business_need"],
        "current_intent_research": ["public_hiring_facts", "social_findings", "specialist_findings.current_intent", "specialist_findings.recent_inquiry"],
        "technical_product_hiring_research": ["public_product_facts", "public_hiring_facts", "specialist_findings.technical_product_hiring"],
        "commercial_research": ["public_commercial_facts", "specialist_findings.commercial"],
        "route_research": ["specialist_findings.route", "business_need_research", "technical_product_hiring_research"],
    }
    package = {name: _section(evidence=items, summary=summaries[name], source_sections=sources[name]) for name, items in (("business_need_research", business), ("current_intent_research", intent), ("technical_product_hiring_research", technical), ("commercial_research", commercial), ("route_research", routes))}
    package["closer_package"] = {
        "ready": False,
        "verification_status": "research_required",
        "researched_at": _now(),
        "company": str(lead.get("company") or "").strip(),
        "contact": str(lead.get("contact_name") or lead.get("person") or "").strip(),
        "evidence": _evidence_refs(all_evidence),
        "required_verification": list(RESEARCH_SECTIONS[:-1]),
        "provenance": {
            "source": "canonical_research_sections",
            "evidence_count": len(_evidence_refs(all_evidence)),
        },
        "unknowns": ["company_verification", "decision_maker_verification", "current_need_verification", "route_verification"],
    }
    return package
