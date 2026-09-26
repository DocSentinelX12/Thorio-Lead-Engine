from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping

from .opportunity_provenance import canonical_evidence_key, normalize_evidence_event, validate_provenance_scope
VERIFIABLE_RESEARCH_SECTIONS = (
    "business_need_research",
    "current_intent_research",
    "technical_product_hiring_research",
    "commercial_research",
    "route_research",
)

RESEARCH_INTELLIGENCE_VERSION = "1"
STALE_AFTER_DAYS = 90
_VERIFIED = {"verified", "research_verified", "complete"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _status(value: Mapping[str, Any] | None) -> str:
    if not isinstance(value, Mapping):
        return "unknown"
    if value.get("verified") is True:
        return "verified"
    raw = _text(value.get("verification_status") or value.get("status")).lower()
    if raw in _VERIFIED:
        return "verified"
    if raw in {"observed_evidence", "observed"}:
        return "observed"
    return "unknown"


def _evidence_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _claim_key(claim_type: str, subject: str, predicate: str, value: Any) -> str:
    raw = json.dumps(
        (_text(claim_type), _text(subject), _text(predicate), value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_timestamp(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _freshness(observed_at: Any, now: datetime) -> str:
    parsed = _parse_timestamp(observed_at)
    if parsed is None:
        return "unknown"
    return "stale" if now - parsed > timedelta(days=STALE_AFTER_DAYS) else "current"


def _field_value(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _collect_evidence(lead: Mapping[str, Any], opportunity_id: str) -> dict[str, Dict[str, Any]]:
    nodes: dict[str, Dict[str, Any]] = {}
    sections = list(VERIFIABLE_RESEARCH_SECTIONS) + ["closer_package", "decision_maker_research"]
    for section_name in sections:
        section = lead.get(section_name)
        if not isinstance(section, Mapping):
            continue
        route_items = section.get("routes")
        if section_name == "route_research" and isinstance(route_items, Mapping):
            for route, route_item in route_items.items():
                if not isinstance(route_item, Mapping):
                    continue
                for raw in _evidence_list(route_item.get("evidence")):
                    event = normalize_evidence_event(
                        raw,
                        opportunity_id=opportunity_id,
                        research_section="route_research",
                        route=str(route),
                        collector="research_intelligence",
                    )
                    nodes[event["canonical_evidence_key"]] = {
                        **event,
                        "research_section": "route_research",
                        "route": str(route),
                    }
        for raw in _evidence_list(section.get("evidence")):
            event = normalize_evidence_event(
                raw,
                opportunity_id=opportunity_id,
                research_section=section_name,
                route=_text(raw.get("route")) or None,
                collector="research_intelligence",
            )
            nodes[event["canonical_evidence_key"]] = {**event, "research_section": section_name}
    company = lead.get("company_research")
    if isinstance(company, Mapping):
        for field in (
            "public_company_facts",
            "public_business_need_facts",
            "public_hiring_facts",
            "public_product_facts",
            "public_commercial_facts",
            "public_decision_maker_facts",
            "social_findings",
        ):
            for raw in _evidence_list(company.get(field)):
                event = normalize_evidence_event(
                    raw,
                    opportunity_id=opportunity_id,
                    research_section="company_research",
                    collector="research_intelligence",
                )
                nodes[event["canonical_evidence_key"]] = {**event, "research_section": "company_research"}
    return nodes


def _profile(lead: Mapping[str, Any], company: Mapping[str, Any], decision: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    company_known: dict[str, Any] = {}
    for key in (
        "company",
        "company_website",
        "company_description",
        "description",
        "industry",
        "company_size",
        "stage",
        "location",
        "headquarters",
        "business_model",
        "products",
        "services",
        "technology",
        "technologies",
        "growth",
        "hiring",
        "strategic_signals",
    ):
        value = lead.get(key) if key in lead else company.get(key)
        if value not in (None, "", [], {}):
            company_known[key] = value

    need_known: dict[str, Any] = {}
    for key in (
        "business_need",
        "current_need",
        "need_at",
        "current_need_at",
        "hiring_need_at",
        "inquiry_at",
        "inquired_at",
        "last_inquiry_at",
        "intent_at",
        "signal",
        "signal_type",
        "job_title",
    ):
        value = lead.get(key)
        if value not in (None, "", [], {}):
            need_known[key] = value
    for key in (
        "business_need",
        "current_need",
        "need",
        "requirement",
        "urgency",
        "scope",
        "skills",
        "technologies",
        "team",
        "project",
        "timing",
        "trigger",
    ):
        value = company.get(key)
        if value not in (None, "", [], {}):
            need_known[key] = value

    decision_known: dict[str, Any] = {}
    for key in (
        "decision_maker",
        "observed_decision_maker",
        "decision_maker_title",
        "decision_maker_email",
        "decision_maker_phone",
        "decision_maker_linkedin_url",
        "decision_maker_role",
        "decision_maker_responsibilities",
    ):
        value = company.get(key)
        if value not in (None, "", [], {}):
            decision_known[key] = value
    for key in ("name", "person", "title", "role", "responsibilities", "email", "phone", "linkedin_url"):
        value = decision.get(key)
        if value not in (None, "", [], {}):
            decision_known[key] = value
    for key in ("contact_name", "contact_title", "contact_email", "contact_phone", "linkedin_url", "person"):
        value = lead.get(key)
        if value not in (None, "", [], {}):
            decision_known.setdefault(key, value)

    return (
        {"name": _text(lead.get("company")), "known": company_known},
        {"known": need_known},
        {"known": decision_known},
    )


def _claim(
    claim_type: str,
    subject: str,
    predicate: str,
    value: Any,
    *,
    evidence_keys: list[str],
    status: str,
    section: str,
) -> Dict[str, Any]:
    return {
        "claim_id": _claim_key(claim_type, subject, predicate, value),
        "claim_type": claim_type,
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "status": status,
        "research_section": section,
        "supporting_evidence_keys": list(dict.fromkeys(evidence_keys)),
    }


def _claims_for_section(
    section_name: str,
    section: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    refs = [item for item in _evidence_list(section.get("evidence")) if isinstance(item, Mapping)]
    keys = [str(item.get("canonical_evidence_key") or canonical_evidence_key(item)) for item in refs]
    explicit: list[Dict[str, Any]] = []
    for item, key in zip(normalized_refs, keys):
        claim_type = _text(item.get("claim_type"))
        claim_value = item.get("claim_value")
        if not claim_type or claim_value in (None, ""):
            continue
        explicit.append(
            _claim(
                claim_type,
                _text(item.get("subject") or "opportunity"),
                _text(item.get("predicate") or "observed"),
                claim_value,
                evidence_keys=[key],
                status="verified" if _status(item) == "verified" else "observed",
                section=section_name,
            )
        )
    if explicit:
        return explicit

    mapping = {
        "business_need_research": ("business_need", "has_business_need", "business_need"),
        "current_intent_research": ("current_intent", "has_current_intent", "current_need"),
        "technical_product_hiring_research": ("technical_need", "has_technical_or_hiring_signal", "evidence"),
        "commercial_research": ("commercial_context", "has_commercial_context", "evidence"),
    }
    spec = mapping.get(section_name)
    if spec is None or not refs:
        return []
    claim_type, predicate, value_key = spec
    value = _text(section.get(value_key))
    if not value:
        value = _text(refs[0].get("evidence") or refs[0].get("signal"))
    return [
        _claim(
            claim_type,
            "opportunity",
            predicate,
            value,
            evidence_keys=keys,
            status="verified" if _status(section) == "verified" and any(_status(item) == "verified" for item in refs) else ("corroborated" if len(set(keys)) > 1 else "observed"),
            section=section_name,
        )
    ]


def _route_claims(section: Mapping[str, Any], opportunity_id: str) -> list[Dict[str, Any]]:
    result: list[Dict[str, Any]] = []
    routes = section.get("routes")
    if not isinstance(routes, Mapping):
        return result
    for route, item in routes.items():
        if not isinstance(item, Mapping):
            continue
        keys = [
            str(ref.get("canonical_evidence_key") or canonical_evidence_key(ref))
            for ref in _evidence_list(item.get("evidence"))
        ]
        if not keys:
            continue
        result.append(
            _claim(
                "route_support",
                "opportunity",
                "supports_route",
                str(route),
                evidence_keys=keys,
                status="verified" if _status(item) == "verified" else ("corroborated" if len(set(keys)) > 1 else "observed"),
                section="route_research",
            )
        )
    return result


def _structured_claims(lead: Mapping[str, Any], company: Mapping[str, Any], decision: Mapping[str, Any], nodes: Mapping[str, Mapping[str, Any]]) -> list[Dict[str, Any]]:
    result: list[Dict[str, Any]] = []
    company_keys = [key for key, node in nodes.items() if node.get("research_section") == "company_research"]
    decision_status = _text(company.get("decision_maker_verification_status")).lower()
    if _text(lead.get("company")):
        result.append(
            _claim(
                "company_identity",
                "opportunity",
                "company",
                _text(lead.get("company")),
                evidence_keys=company_keys,
                status="verified" if company.get("company_verified") is True and company_keys else ("observed" if company_keys else "unknown"),
                section="company_research",
            )
        )
    decision_name = _text(company.get("decision_maker") or company.get("observed_decision_maker") or decision.get("name") or lead.get("contact_name") or lead.get("person"))
    if decision_name:
        decision_keys = [
            key for key, node in nodes.items()
            if node.get("research_section") in {"decision_maker_research", "company_research"}
            and decision_name.casefold() in _text(node.get("evidence")).casefold()
        ]
        result.append(
            _claim(
                "decision_maker_identity",
                "opportunity",
                "decision_maker",
                decision_name,
                evidence_keys=decision_keys,
                status="verified" if decision_status in _VERIFIED and decision_keys else ("observed" if decision_keys else "unknown"),
                section="decision_maker_research",
            )
        )
    return result


def _detect_conflicts(claims: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for claim in claims:
        key = (_text(claim.get("claim_type")), _text(claim.get("subject")), _text(claim.get("predicate")))
        grouped.setdefault(key, []).append(claim)
    conflicts: list[Dict[str, Any]] = []
    for key, values in grouped.items():
        distinct = {json.dumps(value.get("value"), sort_keys=True, ensure_ascii=False) for value in values}
        if len(distinct) <= 1:
            continue
        conflicts.append(
            {
                "claim_type": key[0],
                "subject": key[1],
                "predicate": key[2],
                "claim_ids": [str(value.get("claim_id")) for value in values],
                "values": [value.get("value") for value in values],
                "resolution": "unresolved_conflict",
            }
        )
    return conflicts


def validate_research_intelligence(intelligence: Mapping[str, Any], *, opportunity_id: str) -> None:
    if not isinstance(intelligence, Mapping):
        raise ValueError("Research intelligence must be an object.")
    expected = _text(opportunity_id)
    supplied = _text(intelligence.get("opportunity_id") or intelligence.get("fingerprint"))
    if not expected:
        raise ValueError("Research intelligence requires an opportunity_id.")
    if supplied != expected:
        raise ValueError("Research intelligence opportunity does not match containing opportunity.")
    if _text(intelligence.get("fingerprint")) and _text(intelligence.get("fingerprint")) != expected:
        raise ValueError("Research intelligence fingerprint does not match containing opportunity.")
    graph = intelligence.get("evidence_graph")
    if not isinstance(graph, Mapping) or not isinstance(graph.get("nodes"), Mapping):
        raise ValueError("Research intelligence requires an evidence graph.")
    for node in graph["nodes"].values():
        if not isinstance(node, Mapping):
            raise ValueError("Research intelligence evidence nodes must be objects.")
        validate_provenance_scope(node, opportunity_id=expected, route=_text(node.get("route")) or None)
    claims = intelligence.get("claims")
    if not isinstance(claims, list):
        raise ValueError("Research intelligence requires claims.")
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise ValueError("Research intelligence claims must be objects.")
        for key in ("claim_id", "claim_type", "status", "supporting_evidence_keys"):
            if key not in claim:
                raise ValueError(f"Research intelligence claim missing {key}.")
        for evidence_key in claim["supporting_evidence_keys"]:
            if evidence_key not in graph["nodes"]:
                raise ValueError("Research intelligence claim references unknown evidence.")


def build_research_intelligence(lead: Mapping[str, Any], *, now: datetime | None = None) -> Dict[str, Any]:
    if not isinstance(lead, Mapping):
        raise ValueError("Research intelligence requires a lead mapping.")
    opportunity_id = _text(lead.get("opportunity_id") or lead.get("fingerprint"))
    if not opportunity_id:
        raise ValueError("Research intelligence requires a canonical opportunity identity.")
    fingerprint = _text(lead.get("fingerprint")) or opportunity_id
    if fingerprint != opportunity_id:
        raise ValueError("Research intelligence opportunity_id and fingerprint must match.")
    current_time = now or datetime.now(timezone.utc)
    company = lead.get("company_research") if isinstance(lead.get("company_research"), Mapping) else {}
    decision = lead.get("decision_maker_research") if isinstance(lead.get("decision_maker_research"), Mapping) else {}

    nodes = _collect_evidence(lead, opportunity_id)
    company_profile, need_profile, decision_profile = _profile(lead, company, decision)

    claims: list[Dict[str, Any]] = []
    for section_name in VERIFIABLE_RESEARCH_SECTIONS:
        section = lead.get(section_name)
        if isinstance(section, Mapping):
            claims.extend(_claims_for_section(section_name, section, nodes, opportunity_id, lead))
    route = lead.get("route_research")
    if isinstance(route, Mapping):
        claims.extend(_route_claims(route, opportunity_id))
    claims.extend(_structured_claims(lead, company, decision, nodes))

    stale = []
    for node in nodes.values():
        node["freshness_status"] = _freshness(node.get("observed_at") or node.get("collected_at"), current_time)
        if node["freshness_status"] == "stale":
            stale.append(str(node["canonical_evidence_key"]))

    conflicts = _detect_conflicts(claims)
    if conflicts:
        conflict_ids = {claim_id for conflict in conflicts for claim_id in conflict["claim_ids"]}
        for claim in claims:
            if claim.get("claim_id") in conflict_ids and claim.get("status") != "verified":
                claim["status"] = "contested"

    routes = [str(route).strip() for route in lead.get("potential_routes", []) if str(route).strip()]
    known_unknowns = []
    gaps = lead.get("research_gaps")
    if isinstance(gaps, Mapping):
        known_unknowns.extend(str(item).strip() for item in gaps.get("unknowns", []) if str(item).strip())
    if isinstance(gaps, Mapping):
        known_unknowns.extend(str(item).strip() for item in gaps.get("missing_sections", []) if str(item).strip())

    intelligence = {
        "intelligence_version": RESEARCH_INTELLIGENCE_VERSION,
        "opportunity_id": opportunity_id,
        "fingerprint": fingerprint,
        "company": {
            **company_profile,
            "verification_status": "verified" if company.get("company_verified") is True else ("observed" if company_profile["known"] else "unknown"),
        },
        "need": {
            **need_profile,
            "verification_status": "verified" if any(claim.get("claim_type") in {"business_need", "current_intent", "technical_need"} and claim.get("status") == "verified" for claim in claims) else ("observed" if need_profile["known"] else "unknown"),
        },
        "decision_maker": {
            "name": _text(company.get("decision_maker") or company.get("observed_decision_maker") or decision.get("name") or lead.get("contact_name") or lead.get("person")),
            "title": _text(company.get("decision_maker_title") or decision.get("title") or lead.get("contact_title")),
            "email": _text(company.get("decision_maker_email") or decision.get("email") or lead.get("contact_email")),
            "linkedin_url": _text(company.get("decision_maker_linkedin_url") or decision.get("linkedin_url") or lead.get("linkedin_url")),
            "verification_status": "verified" if _text(company.get("decision_maker_verification_status")).lower() in _VERIFIED else "observed" if decision_profile["known"] else "unknown",
            "known": decision_profile["known"],
        },
        "commercial": {
            "routes": routes,
            "route_research": lead.get("route_research") if isinstance(lead.get("route_research"), Mapping) else {},
            "qualification": lead.get("qualification_results") if isinstance(lead.get("qualification_results"), Mapping) else {},
            "sales_eligibility": _text(lead.get("sales_eligibility")) or "unknown",
        },
        "stakeholders": {
            "decision_maker": _text(company.get("decision_maker") or decision.get("name") or lead.get("contact_name") or lead.get("person")),
            "known": decision_profile["known"],
            "unknowns": ["stakeholder_relationships"] if not decision_profile["known"] else [],
        },
        "evidence_graph": {
            "node_count": len(nodes),
            "nodes": nodes,
            "claim_count": len(claims),
            "edge_count": sum(len(claim.get("supporting_evidence_keys", [])) for claim in claims),
        },
        "claims": claims,
        "conflicts": conflicts,
        "stale_evidence": stale,
        "unknowns": list(dict.fromkeys(known_unknowns)),
        "research_gaps": gaps if isinstance(gaps, Mapping) else {},
        "handoff": {
            "ready": bool(lead.get("research_status") in {"complete", "research_complete"}),
            "required_next_research": list(dict.fromkeys(known_unknowns)),
            "preserved_sections": list(VERIFIABLE_RESEARCH_SECTIONS),
            "downstream_consumers": ["qualification", "sales_handoff", "outreach_closer", "follow_up"],
        },
    }
    validate_research_intelligence(intelligence, opportunity_id=opportunity_id)
    return intelligence


def merge_research_intelligence(existing: Mapping[str, Any], incoming: Mapping[str, Any], *, opportunity_id: str) -> Dict[str, Any]:
    validate_research_intelligence(existing, opportunity_id=opportunity_id)
    validate_research_intelligence(incoming, opportunity_id=opportunity_id)
    merged = dict(existing)
    existing_nodes = dict((existing.get("evidence_graph") or {}).get("nodes") or {})
    incoming_nodes = dict((incoming.get("evidence_graph") or {}).get("nodes") or {})
    nodes = {**existing_nodes, **incoming_nodes}
    existing_claims = {str(item.get("claim_id")): dict(item) for item in existing.get("claims", []) if isinstance(item, Mapping)}
    for item in incoming.get("claims", []):
        if isinstance(item, Mapping):
            key = str(item.get("claim_id"))
            if key in existing_claims:
                combined = dict(existing_claims[key])
                combined["supporting_evidence_keys"] = list(dict.fromkeys(existing_claims[key].get("supporting_evidence_keys", []) + item.get("supporting_evidence_keys", [])))
                if item.get("status") == "verified" or existing_claims[key].get("status") != "verified":
                    combined["status"] = item.get("status")
                existing_claims[key] = combined
            else:
                existing_claims[key] = dict(item)
    merged["evidence_graph"] = {
        **dict(existing.get("evidence_graph") or {}),
        **dict(incoming.get("evidence_graph") or {}),
        "nodes": nodes,
        "node_count": len(nodes),
        "claim_count": len(existing_claims),
        "edge_count": sum(len(item.get("supporting_evidence_keys", [])) for item in existing_claims.values()),
    }
    merged["claims"] = list(existing_claims.values())
    merged["conflicts"] = _detect_conflicts(merged["claims"])
    merged["stale_evidence"] = [
        key for key, node in nodes.items() if node.get("freshness_status") == "stale"
    ]
    merged["unknowns"] = list(dict.fromkeys(list(existing.get("unknowns", [])) + list(incoming.get("unknowns", []))))
    merged["handoff"] = {
        **dict(existing.get("handoff") or {}),
        **dict(incoming.get("handoff") or {}),
        "required_next_research": list(dict.fromkeys(list(existing.get("handoff", {}).get("required_next_research", [])) + list(incoming.get("handoff", {}).get("required_next_research", [])))),
    }
    validate_research_intelligence(merged, opportunity_id=opportunity_id)
    return merged
