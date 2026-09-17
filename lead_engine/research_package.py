from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping

from .router import ROUTES

VERIFIABLE_RESEARCH_SECTIONS = (
    "business_need_research",
    "current_intent_research",
    "technical_product_hiring_research",
    "commercial_research",
    "route_research",
)
RESEARCH_SECTIONS = VERIFIABLE_RESEARCH_SECTIONS + ("research_gaps", "closer_package")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _items(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _refs(items: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    refs: list[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        url = str(item.get("url") or item.get("source_url") or item.get("evidence_url") or "").strip()
        evidence = str(item.get("evidence") or item.get("signal") or "").strip()
        observed_at = str(item.get("observed_at") or item.get("collected_at") or "").strip()
        if not url and not evidence:
            continue
        key = (url, evidence, observed_at)
        if key in seen:
            continue
        seen.add(key)
        refs.append({
            "url": url,
            "evidence": evidence,
            "observed_at": observed_at,
            "verification_status": str(item.get("verification_status") or "observed_evidence").strip() or "observed_evidence",
        })
    return refs


def _section(evidence: list[Dict[str, Any]], summary: str, source_sections: list[str]) -> Dict[str, Any]:
    refs = _refs(evidence)
    return {
        "verified": False,
        "verification_status": "observed_evidence",
        "researched_at": _now(),
        "summary": summary,
        "evidence": refs,
        "provenance": {
            "source_sections": list(source_sections),
            "evidence_count": len(refs),
        },
    }


def _specialist_items(findings: Mapping[str, Any], agents: Iterable[str]) -> list[Dict[str, Any]]:
    items: list[Dict[str, Any]] = []
    for agent in agents:
        result = findings.get(agent)
        if not isinstance(result, Mapping):
            continue
        items.extend(_items(result.get("findings")))
        items.extend(_items(result.get("evidence")))
    return items


def _route_section(evidence: list[Dict[str, Any]]) -> Dict[str, Any]:
    section = _section(evidence, "Evidence relevant to matching the opportunity to supported revenue routes.", ["specialist_findings", "business_need_research", "technical_product_hiring_research"])
    refs = section["evidence"]
    section["routes"] = {
        route: {
            "verified": False,
            "verification_status": "observed_evidence" if refs else "research_required",
            "evidence": list(refs),
            "provenance": {"source": "canonical_route_evidence", "evidence_count": len(refs)},
        }
        for route in ROUTES
    }
    return section


def build_canonical_research_package(
    lead: Mapping[str, Any],
    company_research: Mapping[str, Any],
    specialist_findings: Mapping[str, Any] | None = None,
) -> Dict[str, Dict[str, Any]]:
    """Materialize canonical research sections without promoting observation to verification."""
    findings = specialist_findings if isinstance(specialist_findings, Mapping) else {}
    public = company_research.get("public_web_research")
    public_facts = public.get("facts", {}) if isinstance(public, Mapping) else {}
    social = _items(company_research.get("social_findings"))

    business = (
        _items(company_research.get("public_business_need_facts"))
        + _items(public_facts.get("business_need"))
        + _specialist_items(findings, ("engineering_demand_discovery", "ai_demand_discovery", "product_design_demand_discovery", "contract_team_demand_discovery", "social_inquiry_research"))
    )
    intent = (
        _items(company_research.get("public_hiring_facts"))
        + _specialist_items(findings, ("recent_inquiry_discovery", "social_hiring_research", "social_inquiry_research", "social_intelligence"))
        + social
    )
    technical = (
        _items(company_research.get("public_product_facts"))
        + _items(company_research.get("public_hiring_facts"))
        + _specialist_items(findings, ("engineering_demand_discovery", "ai_demand_discovery", "product_design_demand_discovery", "contract_team_demand_discovery", "social_hiring_research", "social_company_context"))
    )
    commercial = (
        _items(company_research.get("public_commercial_facts"))
        + _specialist_items(findings, ("social_company_context", "social_intelligence"))
    )
    route = (
        _specialist_items(findings, ("engineering_demand_discovery", "ai_demand_discovery", "product_design_demand_discovery", "contract_team_demand_discovery"))
        + business
        + technical
    )

    package: Dict[str, Dict[str, Any]] = {
        "business_need_research": _section(business, "Public and specialist evidence relevant to the observed business need.", ["public_business_need_facts", "specialist_findings"]),
        "current_intent_research": _section(intent, "Public and specialist evidence relevant to current or recent intent.", ["public_hiring_facts", "social_findings", "specialist_findings"]),
        "technical_product_hiring_research": _section(technical, "Public and specialist evidence relevant to technical, product, or hiring needs.", ["public_product_facts", "public_hiring_facts", "specialist_findings"]),
        "commercial_research": _section(commercial, "Public and specialist evidence relevant to commercial context.", ["public_commercial_facts", "specialist_findings"]),
        "route_research": _route_section(route),
    }

    missing = [name for name in VERIFIABLE_RESEARCH_SECTIONS if not package[name]["evidence"]]
    package["research_gaps"] = {
        "verified": False,
        "verification_status": "research_required" if missing else "observed_evidence",
        "researched_at": _now(),
        "missing_sections": missing,
        "unknowns": [
            "company_verification",
            "decision_maker_verification",
            "current_need_verification",
            "route_verification",
        ],
        "provenance": {
            "source": "canonical_research_sections",
            "checked_sections": list(VERIFIABLE_RESEARCH_SECTIONS),
            "missing_count": len(missing),
        },
    }
    all_refs = _refs(business + intent + technical + commercial + route + _items(company_research.get("public_company_facts")) + _items(company_research.get("public_decision_maker_facts")))
    package["closer_package"] = {
        "ready": False,
        "verification_status": "research_required",
        "researched_at": _now(),
        "company": str(lead.get("company") or "").strip(),
        "contact": str(lead.get("contact_name") or lead.get("person") or "").strip(),
        "evidence": all_refs,
        "required_verification": list(VERIFIABLE_RESEARCH_SECTIONS),
        "provenance": {"source": "canonical_research_sections", "evidence_count": len(all_refs)},
        "unknowns": list(package["research_gaps"]["unknowns"]),
    }
    return package
