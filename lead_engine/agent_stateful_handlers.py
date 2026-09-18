"""Executable handlers for stateful workforce specialists.

These handlers never fabricate external evidence. They operate only on supplied
records and the existing LeadDB, and they fail closed when required research,
verification, or route qualification state is missing.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping

from .lead_routes import SUPPORTED_ROUTES, route_leads
from .lead_validation import validate_lead


class StatefulAgentError(ValueError):
    """Raised when a stateful specialist lacks valid inputs."""


def _lead(payload: Mapping[str, Any]) -> Dict[str, Any]:
    value = payload.get("lead", payload)
    if not isinstance(value, Mapping):
        raise StatefulAgentError("lead must be a mapping")
    result = dict(value)
    if not str(result.get("fingerprint") or "").strip():
        raise StatefulAgentError("lead requires fingerprint")
    return result


def _identity_keys(item: Mapping[str, Any]) -> Dict[str, str]:
    company = str(item.get("company") or "").strip().casefold()
    domain = str(item.get("domain") or item.get("company_domain") or "").strip().casefold()
    person = str(item.get("person") or item.get("contact_name") or "").strip().casefold()
    email = str(item.get("contact_email") or "").strip().casefold()
    return {"company": company, "domain": domain, "person": person, "email": email}


def identity_resolution(_: str, payload: Mapping[str, Any], __: Any) -> Dict[str, Any]:
    lead = _lead(payload)
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, Iterable) or isinstance(candidates, (str, bytes, Mapping)):
        raise StatefulAgentError("candidates must be a list-like collection")
    lead_keys = _identity_keys(lead)
    comparisons = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        keys = _identity_keys(candidate)
        exact = [field for field in lead_keys if lead_keys[field] and lead_keys[field] == keys[field]]
        comparisons.append({"fingerprint": str(candidate.get("fingerprint") or ""), "exact_identity_fields": exact, "same_identity": bool(exact)})
    return {"role": "identity_resolution", "fingerprint": lead["fingerprint"], "comparisons": comparisons, "identity_resolved": any(item["same_identity"] for item in comparisons), "preserve_distinct_opportunities": True}


_DECISION_MAKER_ROLE_TERMS = (
    "founder", "co founder", "co-founder", "chief executive officer", "chief technology officer",
    "chief information officer", "chief product officer", "ceo", "cto", "cio", "cpo",
    "vp engineering", "vice president of engineering", "head of engineering", "engineering manager",
    "head of technology", "recruiter", "head of talent", "talent acquisition", "chief people officer",
)


def _normalized_words(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _name_in_evidence(name: str, evidence: str) -> bool:
    normalized_name = _normalized_words(name)
    normalized_evidence = _normalized_words(evidence)
    if not normalized_name or not normalized_evidence:
        return False
    name_parts = normalized_name.split()
    evidence_parts = normalized_evidence.split()
    if len(name_parts) == 1:
        return name_parts[0] in evidence_parts
    width = len(name_parts)
    return any(evidence_parts[index : index + width] == name_parts for index in range(len(evidence_parts) - width + 1))


def _company_in_evidence(company: str, evidence: str) -> bool:
    normalized_company = _normalized_words(company)
    normalized_evidence = _normalized_words(evidence)
    if not normalized_company or not normalized_evidence:
        return False
    company_parts = normalized_company.split()
    evidence_parts = normalized_evidence.split()
    width = len(company_parts)
    return any(evidence_parts[index : index + width] == company_parts for index in range(len(evidence_parts) - width + 1))


def _role_in_evidence(evidence: str, matches: Any = None) -> bool:
    values = []
    if isinstance(matches, Iterable) and not isinstance(matches, (str, bytes, Mapping)):
        values.extend(str(item or "") for item in matches)
    values.append(evidence)
    normalized = " ".join(_normalized_words(item) for item in values)
    return any(_normalized_words(term) in normalized for term in _DECISION_MAKER_ROLE_TERMS)


def _verified_decision_maker_evidence(lead: Mapping[str, Any]) -> Dict[str, Any] | None:
    research = lead.get("company_research")
    if not isinstance(research, Mapping):
        return None
    observed_person = str(research.get("observed_decision_maker") or lead.get("contact_name") or lead.get("person") or research.get("decision_maker") or "").strip()
    company = str(lead.get("company") or "").strip()
    if not observed_person or not company:
        return None
    specialist_findings = lead.get("specialist_findings")
    if not isinstance(specialist_findings, Mapping):
        return None
    candidate = specialist_findings.get("social_decision_maker_research")
    if not isinstance(candidate, Mapping):
        return None
    findings = candidate.get("findings")
    if not isinstance(findings, list):
        return None
    for finding in findings:
        if not isinstance(finding, Mapping):
            continue
        evidence = str(finding.get("evidence") or "").strip()
        url = str(finding.get("url") or finding.get("source_url") or "").strip()
        if not evidence or not url:
            continue
        if not _name_in_evidence(observed_person, evidence):
            continue
        if not _company_in_evidence(company, evidence):
            continue
        if not _role_in_evidence(evidence, finding.get("matches")):
            continue
        return {
            "person": observed_person,
            "role_evidence": url,
            "evidence": evidence,
            "source": str(finding.get("source") or "").strip(),
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
    return None


def _verify_research_sections(lead: Mapping[str, Any]) -> tuple[Dict[str, Dict[str, Any]], list[str]]:
    """Independently validate canonical research evidence before final qualification.

    This verifies the evidence contract and re-applies the existing route rules.
    It never creates evidence, facts, contacts, or route matches that are not
    already present in the canonical package.
    """
    updates: Dict[str, Dict[str, Any]] = {}
    errors: list[str] = []
    sections = (
        "business_need_research",
        "current_intent_research",
        "technical_product_hiring_research",
        "commercial_research",
        "route_research",
    )
    company = str(lead.get("company") or "").strip()
    for name in sections:
        section = lead.get(name)
        if not isinstance(section, Mapping):
            errors.append(f"missing_{name}")
            continue
        refs = section.get("evidence")
        refs = refs if isinstance(refs, list) else []
        valid_refs: list[Dict[str, Any]] = []
        for index, ref in enumerate(refs):
            if not isinstance(ref, Mapping):
                errors.append(f"{name}_evidence_{index}_not_object")
                continue
            url = str(ref.get("url") or ref.get("source_url") or ref.get("evidence_url") or "").strip()
            evidence = str(ref.get("evidence") or ref.get("signal") or "").strip()
            if not url or not evidence:
                errors.append(f"{name}_evidence_{index}_incomplete")
                continue
            valid_refs.append(dict(ref))
        verified = bool(valid_refs)
        finding_status = "evidence_verified" if verified else "no_verified_evidence"
        if name == "current_intent_research":
            now = datetime.now(timezone.utc)
            recent = False
            for ref in valid_refs:
                value = ref.get("observed_at") or ref.get("collected_at")
                if not value:
                    continue
                try:
                    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                parsed = parsed.astimezone(timezone.utc)
                if now - timedelta(days=30) <= parsed <= now:
                    recent = True
                    break
            verified = recent
            finding_status = "recent_evidence_verified" if recent else "no_recent_verified_evidence"
        elif name in {"technical_product_hiring_research", "commercial_research"} and not valid_refs:
            public = lead.get("company_research")
            public_web = public.get("public_web_research") if isinstance(public, Mapping) else None
            attempted = isinstance(public_web, Mapping) and int(public_web.get("pages_attempted", 0) or 0) > 0
            verified = attempted
            finding_status = "researched_no_public_evidence" if attempted else "research_not_performed"
        update = dict(section)
        if verified:
            update.update({
                "verified": True,
                "verification_status": "verified",
                "verification_basis": "canonical_evidence_contract_recheck",
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "finding_status": finding_status,
            })
        else:
            update.update({
                "verified": False,
                "verification_status": "research_required",
                "verification_basis": "canonical_evidence_contract_recheck",
                "finding_status": finding_status,
            })
        updates[name] = update

    route = lead.get("route_research")
    if isinstance(route, Mapping):
        route_updates = dict(route)
        route_items = route.get("routes")
        if isinstance(route_items, Mapping):
            verified_route_count = 0
            new_routes: Dict[str, Dict[str, Any]] = {}
            for route_name, route_item in route_items.items():
                if not isinstance(route_item, Mapping):
                    continue
                item = dict(route_item)
                route_evidence = item.get("evidence")
                route_evidence = route_evidence if isinstance(route_evidence, list) else []
                verified_refs: list[Dict[str, Any]] = []
                for ref in route_evidence:
                    if not isinstance(ref, Mapping):
                        continue
                    evidence = str(ref.get("evidence") or ref.get("signal") or "").strip()
                    url = str(ref.get("url") or ref.get("source_url") or ref.get("evidence_url") or "").strip()
                    if not evidence or not url:
                        continue
                    scores = score_routes(company=company, signal=evidence, evidence=evidence)
                    if int(scores.get(str(route_name), 0) or 0) > 0:
                        verified_refs.append(dict(ref))
                if verified_refs:
                    item.update({
                        "verified": True,
                        "verification_status": "verified",
                        "verification_basis": "route_rule_recheck",
                        "verified_at": datetime.now(timezone.utc).isoformat(),
                        "evidence": verified_refs,
                        "provenance": {**(dict(item.get("provenance") or {}) if isinstance(item.get("provenance"), Mapping) else {}), "evidence_count": len(verified_refs)},
                    })
                    verified_route_count += 1
                else:
                    item.update({
                        "verified": False,
                        "verification_status": "research_required",
                        "verification_basis": "route_rule_recheck",
                    })
                new_routes[str(route_name)] = item
            route_updates["routes"] = new_routes
            route_updates["verified"] = verified_route_count > 0
            route_updates["verification_status"] = "verified" if verified_route_count > 0 else "research_required"
            route_updates["verification_basis"] = "route_rule_recheck"
            route_updates["verified_at"] = datetime.now(timezone.utc).isoformat()
            updates["route_research"] = route_updates
            if verified_route_count == 0:
                errors.append("route_research_has_no_verified_route_evidence")
        else:
            errors.append("route_research_missing_routes")
    return updates, errors


def verification(_: str, payload: Mapping[str, Any], __: Any) -> Dict[str, Any]:
    lead = _lead(payload)
    research_updates, research_errors = _verify_research_sections(lead)
    validation_lead = dict(lead)
    for name, section in research_updates.items():
        validation_lead[name] = section
    errors = validate_lead(validation_lead)
    if not validation_lead.get("potential_routes"):
        errors = [error for error in errors if error != "missing_route"]
    evidence = payload.get("evidence_events", [])
    if not isinstance(evidence, list):
        raise StatefulAgentError("evidence_events must be a list")
    evidence_errors = []
    for index, event in enumerate(evidence):
        if not isinstance(event, Mapping):
            evidence_errors.append(f"evidence_{index}_not_object")
            continue
        if not str(event.get("url") or event.get("source_url") or "").strip():
            evidence_errors.append(f"evidence_{index}_missing_url")
        if not str(event.get("signal") or event.get("evidence") or "").strip():
            evidence_errors.append(f"evidence_{index}_missing_signal")

    research = lead.get("company_research")
    if not isinstance(research, Mapping):
        errors.append("missing_company_research")
    else:
        if research.get("company_verified") is not True:
            errors.append("company_not_verified")
        if not str(research.get("decision_maker") or "").strip():
            errors.append("missing_verified_decision_maker")
        if not str(research.get("decision_maker_evidence") or "").strip():
            errors.append("missing_decision_maker_evidence")
        if str(research.get("decision_maker_verification_status") or "").strip().lower() != "verified":
            errors.append("decision_maker_not_verified")

    if lead.get("potential_routes") and str(validation_lead.get("research_status") or "").strip().lower() not in {"complete", "research_complete"}:
        errors.append("research_not_complete")

    qualification = lead.get("qualification_results")
    if not isinstance(qualification, Mapping):
        errors.append("missing_qualification_results")

    routes = lead.get("potential_routes", [])
    if routes is not None and not isinstance(routes, list):
        errors.append("invalid_potential_routes")
        routes = []

    checked_routes = []
    for route in routes:
        route_name = str(route).strip()
        if route_name not in SUPPORTED_ROUTES:
            errors.append(f"unsupported_route:{route_name}")
            continue
        checked_routes.append(route_name)
        route_result = qualification.get(route_name) if isinstance(qualification, Mapping) else None
        if not isinstance(route_result, Mapping) or route_result.get("qualified") is not True:
            errors.append(f"route_not_qualified:{route_name}")
        if route_name == "Paxus" and (not isinstance(route_result, Mapping) or route_result.get("true_referral") is not True):
            errors.append("paxus_true_referral_not_verified")

    decision_maker_verification = "not_required"
    decision_maker_role_evidence = ""
    decision_maker_verification_record: Dict[str, Any] | None = None
    if isinstance(research, Mapping) and (research.get("decision_maker") or research.get("observed_decision_maker") or research.get("decision_maker_verification_status")):
        if str(research.get("decision_maker_verification_status") or "").strip().lower() == "verified":
            decision_maker_verification = "verified"
            decision_maker_role_evidence = str(research.get("decision_maker_role_evidence") or research.get("decision_maker_evidence") or "").strip()
        else:
            decision_maker_verification_record = _verified_decision_maker_evidence(lead)
            if decision_maker_verification_record is not None:
                decision_maker_verification = "verified"
                decision_maker_role_evidence = decision_maker_verification_record["role_evidence"]
            else:
                decision_maker_verification = "observed_needs_role_verification"

    if decision_maker_verification == "verified":
        errors = [
            error for error in errors
            if error not in {"missing_verified_decision_maker", "missing_decision_maker_evidence", "decision_maker_not_verified"}
        ]

    all_errors = errors + evidence_errors + research_errors
    return {
        "role": "verification",
        "fingerprint": lead["fingerprint"],
        "errors": all_errors,
        "verified": not all_errors,
        "evidence_count": len(evidence),
        "checked_routes": checked_routes,
        "decision_maker_verification": decision_maker_verification,
        "decision_maker_role_evidence": decision_maker_role_evidence,
        "decision_maker_verification_record": decision_maker_verification_record,
        "research_section_updates": research_updates,
        "research_section_errors": research_errors,
    }


def routing(_: str, payload: Mapping[str, Any], __: Any) -> Dict[str, Any]:
    lead = _lead(payload)
    if payload.get("verified") is not True:
        raise StatefulAgentError("routing requires verified=True")
    routed = route_leads([lead])
    destinations = [route for route in SUPPORTED_ROUTES if routed[route]]
    return {"role": "routing", "fingerprint": lead["fingerprint"], "destinations": destinations, "review_required": bool(routed["Review"]), "multi_route": len(destinations) > 1}


def airtable_integrity(_: str, payload: Mapping[str, Any], ctx: Any) -> Dict[str, Any]:
    lead = _lead(payload)
    stored = ctx.db.get(lead["fingerprint"])
    if stored is None:
        raise StatefulAgentError("lead is not present in LeadDB")
    sync_state = ctx.db.get_sync_state(lead["fingerprint"])
    return {
        "role": "airtable_integrity",
        "fingerprint": lead["fingerprint"],
        "lead_db_present": True,
        "sync_status": "synced" if sync_state["synced"] else "pending",
        "sync_attempts": sync_state["attempts"],
        "sync_error_present": bool(sync_state["last_error"]),
        "sync_error": sync_state["last_error"],
        "airtable_verified": bool(sync_state["synced"] and not sync_state["last_error"]),
        "verification_basis": "LeadDB durable synchronization state",
    }
