"""Evidence-grounded next-evidence planning for incomplete research packages.

This module identifies the concrete evidence still needed to resolve known
research gaps. It creates research targets only; it never treats a target as
evidence or promotes an observed signal to a verified claim.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from .signal_outcome_feedback import apply_feedback_to_research_target, signal_feedback_priority


VERSION = "1"

_BASE_TARGETS = {
    "business_need_research": (
        "Find first-party or directly attributable evidence describing the specific business problem, requested capability, project scope, or operational need.",
        "Confirm the business consequence or affected workflow from evidence, without estimating impact when the evidence does not quantify it.",
    ),
    "current_intent_research": (
        "Find the most recent attributable evidence that the underlying need is still active or was recently expressed.",
        "Capture the observation timestamp and source so current intent can be distinguished from historical context.",
    ),
    "technical_product_hiring_research": (
        "Find attributable evidence of the technical, product, engineering, AI, design, or hiring requirement connected to this opportunity.",
        "Identify the concrete capability, technology, role, project, or team requirement stated by the source.",
    ),
    "commercial_research": (
        "Find attributable commercial evidence such as funding, product launch, enterprise contract, acquisition, partnership search, development need, or other explicitly stated business activity.",
        "Preserve the exact commercial trigger and source context rather than inferring budget, purchasing authority, or causality.",
    ),
    "route_research": (
        "Find evidence that directly supports one or more currently eligible revenue routes.",
        "Keep route evidence independently scoped so one route's evidence is never presented as proof for another route.",
    ),
}

_ROUTE_TARGETS = {
    "Shiftr": "Look specifically for an explicit development partner, technology partner, software development, AI/LLM integration, engineering team, staff augmentation, outsourcing, or related implementation need.",
    "Paxus": "Look specifically for a current technology hiring, recruitment, staffing, talent acquisition, or engineering hiring need plus attributable evidence of a recent inquiry where the route requires it.",
    "Thorio": "Look specifically for current remote technology hiring evidence tied to software engineering, data, product, design, ML, or AI roles.",
    "Astrivon Labs": "Look specifically for an explicit development agency, MVP, AI/ML, automation, B2B outreach, product development, or technology partner need.",
}


def build_next_evidence_plan(lead: Mapping[str, Any], *, feedback: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Return concrete research targets for currently unresolved evidence gaps."""
    if not isinstance(lead, Mapping):
        raise ValueError("lead must be a mapping.")

    missing = []
    gaps = lead.get("research_gaps")
    if isinstance(gaps, Mapping) and isinstance(gaps.get("missing_sections"), list):
        missing.extend(str(item).strip() for item in gaps["missing_sections"] if str(item).strip())
    if not missing:
        for section in _BASE_TARGETS:
            value = lead.get(section)
            evidence = value.get("evidence") if isinstance(value, Mapping) else None
            if not isinstance(evidence, list) or not evidence:
                missing.append(section)

    missing = list(dict.fromkeys(section for section in missing if section in _BASE_TARGETS))
    routes = [
        str(route).strip()
        for route in (lead.get("eligible_routes") or lead.get("potential_routes") or [])
        if str(route).strip() in _ROUTE_TARGETS
    ]

    targets = []
    for section in missing:
        primary, secondary = _BASE_TARGETS[section]
        target = {
            "research_section": section,
            "priority": 1,
            "evidence_to_find": [primary, secondary],
            "route": None,
        }
        if feedback is not None:
            target = apply_feedback_to_research_target(target, priority=signal_feedback_priority(lead, feedback))
        if section == "route_research":
            target["route_targets"] = [
                {"route": route, "evidence_to_find": _ROUTE_TARGETS[route]}
                for route in dict.fromkeys(routes)
            ]
            if not target["route_targets"]:
                target["evidence_to_find"].append("Identify which supported route, if any, is directly supported by observed evidence before routing the opportunity.")
        targets.append(target)

    return {
        "intelligence_version": VERSION,
        "opportunity_id": str(lead.get("opportunity_id") or lead.get("fingerprint") or "").strip(),
        "missing_sections": missing,
        "targets": targets,
        "target_count": len(targets),
        "feedback_applied": bool(feedback),
        "interpretation_note": (
            "These are evidence-search targets only. They are not evidence, "
            "qualification decisions, urgency signals, budget estimates, or route claims. "
            "Any feedback priority is historical association only and does not establish causality."
        ),
    }
