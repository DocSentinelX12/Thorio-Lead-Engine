"""Surgical semantic normalization for research intelligence and qualification.

This module does not manufacture evidence. It only normalizes already researched,
structured evidence and groups semantically equivalent claims so the strict
research gates can evaluate the real evidence consistently.
"""
from __future__ import annotations

import json
from typing import Any, Mapping


def _evidence_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return str(value.get("evidence") or value.get("signal") or value.get("summary") or "").strip()
    if isinstance(value, list):
        parts = [_evidence_text(item) for item in value]
        return " ".join(part for part in parts if part)
    return ""


def _install_route_normalization() -> None:
    from . import qualification

    original = qualification._route_research

    def strict_route_research(lead: dict[str, Any], route: str) -> dict[str, Any]:
        sections = qualification._research_sections(lead)
        section = sections.get("route_research")
        if not isinstance(section, dict):
            return original(lead, route)
        routes = section.get("routes")
        route_item = routes.get(route) if isinstance(routes, Mapping) else section.get(route)
        if not isinstance(route_item, Mapping):
            return original(lead, route)
        verified = qualification._section_verified(dict(route_item))
        evidence = _evidence_text(route_item.get("evidence"))
        if not evidence:
            for key in ("business_need", "current_need", "need", "service_need", "requirement", "role", "description", "intent"):
                evidence = _evidence_text(route_item.get(key))
                if evidence:
                    break
        return {
            "verified": bool(verified and evidence),
            "evidence": evidence,
            "reason": f"{route} route research verified." if verified and evidence else f"{route} route research is incomplete.",
        }

    qualification._route_research = strict_route_research


def _install_conflict_normalization() -> None:
    from . import research_intelligence

    def semantic_claim_key(claim: Mapping[str, Any]) -> tuple[str, str]:
        claim_type = str(claim.get("claim_type") or "").strip().lower()
        subject = str(claim.get("subject") or "").strip().lower()
        predicate = str(claim.get("predicate") or "").strip().lower()
        aliases = {
            "current_intent": "current_need",
            "current_need": "current_need",
            "has_current_intent": "current_need",
            "has_current_need": "current_need",
            "business_need": "business_need",
            "has_business_need": "business_need",
        }
        semantic_type = aliases.get(claim_type, claim_type)
        semantic_predicate = aliases.get(predicate, predicate)
        if semantic_type == "current_need" or semantic_predicate == "current_need":
            return ("current_need", subject)
        return (semantic_type or semantic_predicate, subject)

    def detect_conflicts(claims: Any) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for claim in claims:
            if not isinstance(claim, Mapping):
                continue
            grouped.setdefault(semantic_claim_key(claim), []).append(claim)
        conflicts: list[dict[str, Any]] = []
        for (semantic_type, subject), values in grouped.items():
            distinct = {json.dumps(value.get("value"), sort_keys=True, ensure_ascii=False) for value in values}
            if len(distinct) <= 1:
                continue
            conflicts.append({
                "claim_type": semantic_type,
                "subject": subject,
                "predicate": "semantic_conflict",
                "claim_ids": [str(value.get("claim_id")) for value in values],
                "values": [value.get("value") for value in values],
                "resolution": "unresolved_conflict",
            })
        return conflicts

    research_intelligence._detect_conflicts = detect_conflicts


def install() -> None:
    _install_route_normalization()
    _install_conflict_normalization()
