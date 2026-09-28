"""Evidence-grounded diagnosis of buyer objections and commercial constraints.

This module separates what a buyer explicitly said from hypotheses about why the
buyer said it. It never promotes an inferred concern to a fact without explicit
buyer evidence.
"""
from __future__ import annotations

from typing import Any, Mapping


_TERMINAL = frozenset({"conversion", "rejected"})
_DIAGNOSTIC_STATES = frozenset(
    {"no_need", "existing_solution", "timing_delay", "objection"}
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _event_ref(event: Mapping[str, Any], index: int) -> str:
    return (
        _text(
            event.get("evidence_ref")
            or event.get("source_id")
            or event.get("source_url")
            or event.get("event_id")
        )
        or f"conversation_event:{index}"
    )


def _latest_state_event(lead: Mapping[str, Any], state: str) -> tuple[Mapping[str, Any], int]:
    events = lead.get("conversation_events")
    if not isinstance(events, list):
        return {}, -1
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if not isinstance(event, Mapping):
            continue
        if _text(event.get("intent_state")).lower() == state:
            return event, index
        outcome = _text(event.get("outcome")).lower()
        text = _text(event.get("text")).lower()
        if state == "no_need" and (
            outcome in {"declined", "no_need", "no_need_stated"}
            or "do not need" in text
            or "don't need" in text
            or "not need" in text
        ):
            return event, index
        if state == "existing_solution" and (
            "already have" in text
            or "in-house" in text
            or "in house" in text
            or "internal team" in text
            or "existing provider" in text
        ):
            return event, index
        if state == "timing_delay" and (
            outcome in {"timing", "timing_delay"}
            or "not now" in text
            or "next quarter" in text
            or "next month" in text
            or "later" in text
        ):
            return event, index
        if state == "objection" and (
            outcome == "objection" or _text(event.get("objection"))
        ):
            return event, index
    return {}, -1


def _hypothesis_for(state: str, text: str) -> tuple[str, str, str]:
    value = text.lower()
    if state == "existing_solution":
        return (
            "existing_solution",
            "The buyer may believe the current team or provider already satisfies the relevant need.",
            "diagnose_capacity_gap",
        )
    if state == "timing_delay":
        return (
            "timing",
            "The buyer may face a timing or resource constraint that prevents action now.",
            "map_timing_constraint",
        )
    if any(token in value for token in ("budget", "price", "pricing", "cost", "expensive", "investment")):
        return (
            "economic",
            "The buyer may need the commercial value, economics, or constraint to be clearer before evaluating the option.",
            "clarify_economic_criteria",
        )
    if any(token in value for token in ("already have", "in-house", "in house", "internal team", "internal engineering", "existing provider")):
        return (
            "existing_solution",
            "The buyer may believe the current team or provider already satisfies the relevant need.",
            "diagnose_capacity_gap",
        )
    if any(token in value for token in ("later", "not now", "next quarter", "next month", "timing")):
        return (
            "timing",
            "The buyer may face a timing or resource constraint that prevents action now.",
            "map_timing_constraint",
        )
    if any(token in value for token in ("trust", "proof", "case study", "reference", "reliable", "delivery risk")):
        return (
            "trust",
            "The buyer may require verified proof about delivery capability or fit.",
            "provide_verified_proof_or_offer_discovery",
        )
    if any(token in value for token in ("do not understand", "don't understand", "how does this work", "what do you do")):
        return (
            "information",
            "The buyer may lack enough information to determine whether the offering fits.",
            "clarify_fit_requirements",
        )
    if state == "no_need":
        return (
            "",
            "",
            "diagnose_no_need",
        )
    return (
        "unspecified",
        "The underlying reason for the objection has not been established.",
        "diagnose_objection_before_persuading",
    )


def _confirmation_alias(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "capability_or_displacement_risk": "existing_solution",
        "existing_solution": "existing_solution",
        "timing_or_resource_constraint": "timing",
        "timing": "timing",
        "economic_risk": "economic",
        "economic": "economic",
        "price": "economic",
        "proof_or_delivery_risk": "trust",
        "trust": "trust",
        "fit_or_understanding_risk": "information",
        "information": "information",
    }
    return aliases.get(normalized, normalized)


def _state_evolution(
    events: list[Any],
    origin_index: int,
    hypothesis_type: str,
) -> dict[str, Any]:
    status = "hypothesis"
    state_evidence_ref = ""
    state_event_index: int | None = None
    transition = "none"
    active_type = hypothesis_type

    for index in range(origin_index + 1, len(events)):
        event = events[index]
        if not isinstance(event, Mapping):
            continue
        ref = _event_ref(event, index)
        confirmation = _confirmation_alias(
            _text(event.get("underlying_concern_confirmation") or event.get("confirmed_concern_type"))
        )
        rejection = _confirmation_alias(
            _text(event.get("underlying_concern_rejection") or event.get("rejected_concern_type"))
        )
        resolution = _confirmation_alias(
            _text(event.get("underlying_concern_resolution") or event.get("resolved_concern_type"))
        )
        replacement = _confirmation_alias(
            _text(event.get("underlying_concern_replacement") or event.get("replaced_concern_type"))
        )

        if confirmation and confirmation == hypothesis_type:
            status = "confirmed"
            state_evidence_ref = ref
            state_event_index = index
            transition = "confirmed"
        if rejection and rejection == hypothesis_type:
            status = "superseded"
            state_evidence_ref = ref
            state_event_index = index
            transition = "superseded"
        if resolution and resolution == hypothesis_type:
            status = "resolved"
            state_evidence_ref = ref
            state_event_index = index
            transition = "resolved"
        if replacement and replacement == hypothesis_type:
            status = "superseded"
            state_evidence_ref = ref
            state_event_index = index
            transition = "superseded"
            if replacement != hypothesis_type:
                active_type = replacement
        if rejection and rejection != hypothesis_type and status == "confirmed":
            status = "superseded"
            state_evidence_ref = ref
            state_event_index = index
            transition = "superseded"

    return {
        "status": status,
        "state_evidence_ref": state_evidence_ref,
        "state_event_index": state_event_index,
        "state_transition": transition,
        "active_hypothesis_type": active_type,
    }


def _verified_research(lead: Mapping[str, Any], hypothesis_type: str) -> list[str]:
    if not hypothesis_type:
        return []
    refs: list[str] = []
    for section_name in (
        "current_intent_research",
        "business_need_research",
        "business_impact_research",
        "commercial_research",
        "company_research",
        "decision_maker_research",
    ):
        section = lead.get(section_name)
        if not isinstance(section, Mapping):
            continue
        status = _text(section.get("verification_status") or section.get("status")).lower()
        if section.get("verified") is not True and status not in {"verified", "research_verified", "complete"}:
            continue
        ref = _text(section.get("evidence_url") or section.get("source_url") or section.get("evidence_ref"))
        if ref:
            refs.append(ref)
    return list(dict.fromkeys(refs))


def build_objection_constraint_diagnosis(
    lead: Mapping[str, Any],
    progression: Mapping[str, Any],
) -> dict[str, Any]:
    """Diagnose an interruption while preserving evidence and buyer autonomy."""
    lead = lead if isinstance(lead, Mapping) else {}
    progression = progression if isinstance(progression, Mapping) else {}
    state = _text(progression.get("current_state")).lower() or "unknown"
    events = lead.get("conversation_events")
    events = events if isinstance(events, list) else []

    if state in _TERMINAL:
        event, index = _latest_state_event(lead, state)
        ref = _event_ref(event, index) if event else _text(progression.get("evidence_ref"))
        return {
            "interruption_type": state,
            "status": "terminal",
            "hypothesis": "",
            "hypothesis_type": "",
            "observed_text": _text(event.get("text")) if event else "",
            "evidence_refs": [ref] if ref else [],
            "confirmation_evidence_ref": "",
            "state_evidence_ref": ref,
            "state_event_index": index if index >= 0 else None,
            "state_transition": "terminal",
            "active_hypothesis_type": "",
            "missing_evidence": [],
            "next_best_action": "stop_outreach",
            "next_best_question": "",
            "permitted_persuasion": "none",
            "relevant_verified_evidence": [],
            "evidence_policy": "Terminal rejection or conversion cannot be reopened by diagnosis.",
        }

    if state not in _DIAGNOSTIC_STATES:
        return {
            "interruption_type": "",
            "status": "not_applicable",
            "hypothesis": "",
            "hypothesis_type": "",
            "observed_text": "",
            "evidence_refs": [],
            "confirmation_evidence_ref": "",
            "state_evidence_ref": "",
            "state_event_index": None,
            "state_transition": "none",
            "active_hypothesis_type": "",
            "missing_evidence": [],
            "next_best_action": "",
            "next_best_question": "",
            "permitted_persuasion": "evidence_bounded_discovery",
            "relevant_verified_evidence": [],
            "evidence_policy": "Only explicit buyer evidence may confirm or resolve a diagnostic hypothesis.",
        }

    event, origin_index = _latest_state_event(lead, state)
    observed_text = _text(event.get("text") or event.get("objection"))
    evidence_ref = _event_ref(event, origin_index) if event else _text(progression.get("evidence_ref"))
    hypothesis_type, hypothesis, action = _hypothesis_for(state, observed_text)

    if not hypothesis_type and state == "no_need":
        evolution = {
            "status": "unconfirmed",
            "state_evidence_ref": "",
            "state_event_index": None,
            "state_transition": "none",
            "active_hypothesis_type": "",
        }
    else:
        evolution = _state_evolution(events, origin_index, hypothesis_type)

    questions = {
        "no_need": "What specifically makes this unnecessary right now, and is there any gap in the current approach worth evaluating?",
        "existing_solution": "Where, if anywhere, is there still a capacity, specialization, speed, or delivery gap?",
        "timing": "What event or condition would need to change before this becomes actionable?",
        "economic": "Which economic outcome or constraint should we evaluate first so we can determine whether the investment makes sense?",
        "trust": "What specific evidence about delivery would you need to verify before evaluating the fit?",
        "information": "What specific requirement would you need clarified to determine whether the approach fits?",
        "unspecified": "What specifically would need to change or be clarified for you to consider moving forward?",
    }

    if state == "no_need" and hypothesis_type:
        action = action
    elif state == "no_need":
        action = "diagnose_no_need"

    relevant_research = _verified_research(lead, hypothesis_type)
    if evolution["status"] == "resolved":
        action = "reconfirm_active_need"
    elif evolution["status"] == "superseded" and evolution["active_hypothesis_type"] == "timing":
        action = "map_timing_constraint"

    return {
        "interruption_type": state,
        "status": evolution["status"],
        "hypothesis": hypothesis,
        "hypothesis_type": hypothesis_type,
        "observed_text": observed_text,
        "evidence_refs": list(dict.fromkeys([ref for ref in (evidence_ref, evolution["state_evidence_ref"]) if ref])),
        "confirmation_evidence_ref": evolution["state_evidence_ref"] if evolution["status"] == "confirmed" else "",
        "state_evidence_ref": evolution["state_evidence_ref"],
        "state_event_index": evolution["state_event_index"],
        "state_transition": evolution["state_transition"],
        "active_hypothesis_type": evolution["active_hypothesis_type"],
        "missing_evidence": [] if evolution["status"] == "confirmed" else [hypothesis_type or "no_need_reason"],
        "next_best_action": action,
        "next_best_question": questions.get(evolution["active_hypothesis_type"] or state, questions["no_need"]),
        "permitted_persuasion": "evidence_bounded_discovery",
        "relevant_verified_evidence": relevant_research,
        "evidence_policy": "Hypotheses remain hypotheses until explicit buyer evidence confirms them. Verified research may support a response only when it is relevant to the diagnosed concern.",
    }
