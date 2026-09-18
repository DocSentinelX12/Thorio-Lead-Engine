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
        refs.append({"url": url, "evidence": evidence, "observed_at": observed_at, "verification_status": str(item.get("verification_status") or "observed_evidence").strip() or "observed_evidence"})
    return refs


def _section(evidence: list[Dict[str, Any]], summary: str, source_sections: list[str]) -> Dict[str, Any]:
    refs = _refs(evidence)
    return {"verified": False, "verification_status": "observed_evidence", "researched_at": _now(), "summary": summary, "evidence": refs, "provenance": {"source_sections": list(source_sections), "evidence_count": len(refs)}}


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
    section["routes"] = {route: {"verified": False, "verification_status": "observed_evidence" if refs else "research_required", "evidence": list(refs), "provenance": {"source": "canonical_route_evidence", "evidence_count": len(refs)}} for route in ROUTES}
    return section


def _merge_evidence(generated: Iterable[Mapping[str, Any]], existing: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    return _refs(list(generated) + list(existing))


def merge_canonical_section(generated: Mapping[str, Any], existing: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge newly collected evidence without discarding existing verified or human-reviewed fields."""
    result = dict(generated)
    existing_status = str(existing.get("verification_status") or existing.get("status") or "").strip().lower()
    if existing.get("verified") is True or existing_status in {"verified", "research_verified", "complete"}:
        return dict(existing)
    result.update(dict(existing))
    result["evidence"] = _merge_evidence(generated.get("evidence", []), existing.get("evidence", []))
    generated_provenance = generated.get("provenance") if isinstance(generated.get("provenance"), Mapping) else {}
    existing_provenance = existing.get("provenance") if isinstance(existing.get("provenance"), Mapping) else {}
    sources = []
    for value in list(generated_provenance.get("source_sections", [])) + list(existing_provenance.get("source_sections", [])):
        if value not in sources:
            sources.append(value)
    result["provenance"] = {**dict(generated_provenance), **dict(existing_provenance), "source_sections": sources, "evidence_count": len(result["evidence"])}
    if isinstance(generated.get("routes"), Mapping) and isinstance(existing.get("routes"), Mapping):
        routes = {str(name): dict(value) for name, value in generated["routes"].items() if isinstance(value, Mapping)}
        for name, value in existing["routes"].items():
            if not isinstance(value, Mapping):
                continue
            current = dict(routes.get(str(name), {})); current.update(dict(value)); current["evidence"] = _merge_evidence(routes.get(str(name), {}).get("evidence", []), value.get("evidence", []))
            routes[str(name)] = current
        result["routes"] = routes
    return result


def _explicitly_verified(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("verified") is True:
        return True
    return str(value.get("verification_status") or value.get("status") or "").strip().lower() in {"verified", "research_verified", "complete"}


def research_readiness(lead: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the single canonical readiness decision for completed research and closer handoff."""
    missing_sections = [
        section
        for section in VERIFIABLE_RESEARCH_SECTIONS
        if not _explicitly_verified(lead.get(section))
    ]
    company_research = lead.get("company_research")
    company_verified = isinstance(company_research, Mapping) and company_research.get("company_verified") is True
    decision_maker_verified = (
        isinstance(company_research, Mapping)
        and bool(str(company_research.get("decision_maker") or "").strip())
        and bool(str(company_research.get("decision_maker_evidence") or "").strip())
        and str(company_research.get("decision_maker_verification_status") or "").strip().lower() == "verified"
    )
    closer = lead.get("closer_package")
    closer_evidence = isinstance(closer, Mapping) and bool(closer.get("evidence"))
    closer_package_ready = isinstance(closer, Mapping) and closer.get("ready") is True
    ready = not missing_sections and company_verified and decision_maker_verified and closer_evidence
    blockers = list(missing_sections)
    if not company_verified:
        blockers.append("company_verification")
    if not decision_maker_verified:
        blockers.append("decision_maker_verification")
    if not closer_evidence:
        blockers.append("closer_package_evidence")
    if not closer_package_ready:
        blockers.append("closer_package_not_ready")
    return {
        "ready": ready,
        "missing_sections": missing_sections,
        "company_verified": company_verified,
        "decision_maker_verified": decision_maker_verified,
        "closer_evidence_present": closer_evidence,
        "closer_package_ready": closer_package_ready,
        "blockers": list(dict.fromkeys(blockers)),
    }


def finalize_closer_package(lead: Mapping[str, Any], package: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Materialize closer readiness without promoting observed evidence to verification."""
    result = dict(package or (lead.get("closer_package") if isinstance(lead.get("closer_package"), Mapping) else {}))
    readiness_input = dict(lead)
    readiness_input["closer_package"] = result
    readiness = research_readiness(readiness_input)
    result["ready"] = bool(readiness["ready"])
    result["verification_status"] = "verified" if readiness["ready"] else "research_required"
    result["required_verification"] = list(VERIFIABLE_RESEARCH_SECTIONS)
    result["unknowns"] = list(readiness["blockers"])
    return result


def finalize_research_readiness(lead: Mapping[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Apply canonical closer, research-gap, and status state from one readiness decision."""
    updated = dict(lead)
    updated["closer_package"] = finalize_closer_package(updated, updated.get("closer_package"))
    readiness = research_readiness(updated)
    gaps = dict(updated.get("research_gaps") or {}) if isinstance(updated.get("research_gaps"), Mapping) else {}
    gaps["verified"] = bool(readiness["ready"])
    if readiness["ready"]:
        gaps["verification_status"] = "verified"
    else:
        has_observed_evidence = any(
            isinstance(updated.get(section), Mapping) and bool(updated.get(section, {}).get("evidence"))
            for section in VERIFIABLE_RESEARCH_SECTIONS
        )
        existing_status = str(gaps.get("verification_status") or "").strip().lower()
        gaps["verification_status"] = (
            "observed_evidence"
            if has_observed_evidence or existing_status == "observed_evidence"
            else "research_required"
        )
    existing_missing_sections = gaps.get("missing_sections")
    if isinstance(existing_missing_sections, list):
        gaps["missing_sections"] = [str(item) for item in existing_missing_sections]
    else:
        gaps["missing_sections"] = [
            section
            for section in VERIFIABLE_RESEARCH_SECTIONS
            if not (
                isinstance(updated.get(section), Mapping)
                and bool(updated.get(section, {}).get("evidence"))
            )
        ]
    gaps["unknowns"] = list(readiness["blockers"])
    updated["research_gaps"] = gaps
    updated["research_status"] = "complete" if readiness["ready"] else "research_required"
    updated["research_verified_fields"] = [
        section for section in VERIFIABLE_RESEARCH_SECTIONS if _explicitly_verified(updated.get(section))
    ]
    return updated, readiness


def build_canonical_research_package(lead: Mapping[str, Any], company_research: Mapping[str, Any], specialist_findings: Mapping[str, Any] | None = None) -> Dict[str, Dict[str, Any]]:
    """Materialize canonical research sections without promoting observation to verification."""
    findings = specialist_findings if isinstance(specialist_findings, Mapping) else {}
    public = company_research.get("public_web_research")
    public_facts = public.get("facts", {}) if isinstance(public, Mapping) else {}
    social = _items(company_research.get("social_findings"))
    business = _items(company_research.get("public_business_need_facts")) + _items(public_facts.get("business_need")) + _specialist_items(findings, ("engineering_demand_discovery", "ai_demand_discovery", "product_design_demand_discovery", "contract_team_demand_discovery", "social_inquiry_research"))
    intent = _items(company_research.get("public_hiring_facts")) + _specialist_items(findings, ("recent_inquiry_discovery", "social_hiring_research", "social_inquiry_research", "social_intelligence")) + social
    technical = _items(company_research.get("public_product_facts")) + _items(company_research.get("public_hiring_facts")) + _specialist_items(findings, ("engineering_demand_discovery", "ai_demand_discovery", "product_design_demand_discovery", "contract_team_demand_discovery", "social_hiring_research", "social_company_context"))
    commercial = _items(company_research.get("public_commercial_facts")) + _specialist_items(findings, ("social_company_context", "social_intelligence"))
    route = _specialist_items(findings, ("engineering_demand_discovery", "ai_demand_discovery", "product_design_demand_discovery", "contract_team_demand_discovery")) + business + technical
    package: Dict[str, Dict[str, Any]] = {
        "business_need_research": _section(business, "Public and specialist evidence relevant to the observed business need.", ["public_business_need_facts", "specialist_findings"]),
        "current_intent_research": _section(intent, "Public and specialist evidence relevant to current or recent intent.", ["public_hiring_facts", "social_findings", "specialist_findings"]),
        "technical_product_hiring_research": _section(technical, "Public and specialist evidence relevant to technical, product, or hiring needs.", ["public_product_facts", "public_hiring_facts", "specialist_findings"]),
        "commercial_research": _section(commercial, "Public and specialist evidence relevant to commercial context.", ["public_commercial_facts", "specialist_findings"]),
        "route_research": _route_section(route),
    }
    missing_evidence = [name for name in VERIFIABLE_RESEARCH_SECTIONS if not package[name]["evidence"]]
    has_any_evidence = any(package[name]["evidence"] for name in VERIFIABLE_RESEARCH_SECTIONS)
    missing_sections = [] if has_any_evidence else list(VERIFIABLE_RESEARCH_SECTIONS)
    package["research_gaps"] = {"verified": False, "verification_status": "observed_evidence" if has_any_evidence else "research_required", "researched_at": _now(), "missing_sections": missing_sections, "unknowns": ["company_verification", "decision_maker_verification", "current_need_verification", "route_verification"] + missing_evidence, "provenance": {"source": "canonical_research_sections", "checked_sections": list(VERIFIABLE_RESEARCH_SECTIONS), "missing_count": len(missing_evidence)}}
    all_refs = _refs(business + intent + technical + commercial + route + _items(company_research.get("public_company_facts")) + _items(company_research.get("public_decision_maker_facts")))
    package["closer_package"] = {"ready": False, "verification_status": "research_required", "researched_at": _now(), "company": str(lead.get("company") or "").strip(), "contact": str(lead.get("contact_name") or lead.get("person") or "").strip(), "evidence": all_refs, "required_verification": list(VERIFIABLE_RESEARCH_SECTIONS), "provenance": {"source": "canonical_research_sections", "evidence_count": len(all_refs)}, "unknowns": list(package["research_gaps"]["unknowns"])}
    return package
