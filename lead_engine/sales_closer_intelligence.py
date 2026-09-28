"""Evidence-grounded commercial psychology and next-best-action reasoning.

This module does not invent buyer psychology. It derives commercial hypotheses
from verified research, keeps facts separate from inference, and explicitly
records unknowns so the closer can discover them rather than fabricate them.
"""
from __future__ import annotations

from typing import Any, Mapping

from .buyer_intent_progression import build_buyer_intent_progression
from .buyer_signal_intelligence import classify_buyer_signal


def _text(value: Any) -> str:
    return str(value or "").strip()


def _verified(mapping: Any) -> bool:
    if not isinstance(mapping, Mapping):
        return False
    status = _text(mapping.get("verification_status") or mapping.get("status")).lower()
    return mapping.get("verified") is True or status in {"verified", "research_verified", "complete"}


def _evidence_ref(mapping: Any) -> str:
    if not isinstance(mapping, Mapping):
        return ""
    for key in ("evidence_url", "source_url", "evidence_ref", "source_id"):
        value = _text(mapping.get(key))
        if value:
            return value
    return ""


def _conversation_memory(lead: Mapping[str, Any]) -> dict[str, Any]:
    events = lead.get("conversation_events")
    if not isinstance(events, list):
        events = []
    fields = ("priority", "timeline", "budget", "decision_process", "current_provider", "authority", "stated_objection", "commitment", "next_step")
    memory: dict[str, Any] = {field: {"value": "", "event_index": None, "evidence_ref": ""} for field in fields}
    observed_events = []
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            continue
        event_ref = _text(event.get("evidence_ref") or event.get("source_id") or event.get("source_url") or event.get("event_id"))
        observed = {}
        for field in fields:
            value = _text(event.get(field))
            if value:
                memory[field] = {"value": value, "event_index": index, "evidence_ref": event_ref}
                observed[field] = value
        if observed or _text(event.get("text")):
            observed_events.append({"event_index": index, "outcome": _text(event.get("outcome")), "text": _text(event.get("text")), "evidence_ref": event_ref})
    return {"event_count": len(events), "known_context": memory, "observed_events": observed_events}


def _buying_signal_intelligence(lead: Mapping[str, Any], state: str) -> dict[str, Any]:
    signal = classify_buyer_signal(lead)
    return {"category": _text(signal.get("category")), "confidence": _text(signal.get("confidence")), "evidence_text": _text(signal.get("evidence_text")), "evidence_ref": _text(signal.get("evidence_ref")), "do_not_overstate": bool(signal.get("do_not_overstate", True))}


def _conversation_state_transition(lead: Mapping[str, Any], state: str, buying_signal: Mapping[str, Any], memory: Mapping[str, Any]) -> dict[str, Any]:
    category = _text(buying_signal.get("category"))
    if state in {"converted", "referred", "closed_lost", "disqualified", "stopped"}:
        return {"from_state": state, "candidate_state": state, "transition": "terminal", "required_evidence": [], "reason": "Terminal state requires no further persuasion."}
    if category == "explicit_commitment":
        return {"from_state": state, "candidate_state": "decision", "transition": "advance", "required_evidence": ["explicit commitment or concrete commercial action"], "reason": "The buyer has expressed a concrete commitment signal."}
    if category == "active_evaluation":
        return {"from_state": state, "candidate_state": "evaluation", "transition": "advance", "required_evidence": ["documented evaluation activity"], "reason": "The buyer is actively evaluating fit, economics, process, or approval."}
    if category == "interest":
        return {"from_state": state, "candidate_state": "interested", "transition": "advance", "required_evidence": ["explicit interest or request for a next conversation"], "reason": "Interest is present but does not establish purchase intent."}
    if state in {"replied", "interested"} and memory.get("known_context"):
        return {"from_state": state, "candidate_state": "discovery", "transition": "hold_and_discover", "required_evidence": ["desired outcome", "material business consequence"], "reason": "Conversation context exists, but the evidence required for a stronger commercial state is incomplete."}
    return {"from_state": state, "candidate_state": "discovery", "transition": "hold_and_discover", "required_evidence": ["active need", "desired outcome"], "reason": "The conversation needs evidence before a stronger state can be justified."}


def _latest_objection_event(lead: Mapping[str, Any]) -> Mapping[str, Any]:
    events = lead.get("conversation_events")
    if not isinstance(events, list):
        return {}
    for event in reversed(events):
        if isinstance(event, Mapping) and (_text(event.get("outcome")).lower() == "objection" or _text(event.get("objection"))):
            return event
    return {}


def _underlying_concern_intelligence(lead: Mapping[str, Any], objection_category: str) -> dict[str, Any]:
    latest = _latest_objection_event(lead)
    text = _text(latest.get("text") or latest.get("objection"))
    origin_index = None
    events = lead.get("conversation_events")
    if isinstance(events, list):
        for index in range(len(events) - 1, -1, -1):
            if events[index] is latest:
                origin_index = index
                break
    hypotheses = {"price": ("economic_risk", "The buyer may be concerned that the economics are not justified by the expected value.", "Which outcome or constraint would need to be clear before the economics could be evaluated?"), "existing_solution": ("capability_or_displacement_risk", "The buyer may be concerned that changing or adding a provider would create unnecessary disruption because the current solution already works.", "What would need to be different from the current solution for an additional option to be worth evaluating?"), "timing": ("timing_or_resource_constraint", "The buyer may be constrained by timing, competing priorities, or available resources.", "What condition would make this worth revisiting, and what constraint is preventing action today?"), "decision_process": ("internal_decision_risk", "The buyer may need internal alignment, approval, or confidence about how a decision will be evaluated.", "What part of the internal decision process is still uncertain?"), "trust": ("proof_or_delivery_risk", "The buyer may need evidence that the proposed capability can be delivered reliably in their context.", "What specific evidence would reduce the uncertainty you have?"), "information": ("fit_or_understanding_risk", "The buyer may not yet have enough information to determine whether the offering fits the need.", "What specific part of the approach would you need to understand to evaluate fit?")}
    if objection_category not in hypotheses:
        return {"status": "unconfirmed", "hypothesis": "", "concern_type": "", "evidence_refs": [], "validation_question": "", "confirmation_criteria": "No underlying concern is established from the available conversation evidence."}
    concern_type, hypothesis, question = hypotheses[objection_category]
    evidence_ref = _text(latest.get("evidence_ref") or latest.get("source_id") or latest.get("source_url") or latest.get("event_id"))
    return {"status": "hypothesis", "hypothesis": hypothesis, "concern_type": concern_type, "evidence_refs": [evidence_ref] if evidence_ref else [], "observed_text": text, "origin_event_index": origin_index, "validation_question": question, "confirmation_criteria": "Confirm only if the buyer explicitly validates the concern; otherwise retain it as unconfirmed and do not use it as a factual claim.", "state_policy": "A later explicit confirmation, rejection, resolution, or replacement can change this state; ordinary replies do not."}


def _conversation_event_ref(event: Mapping[str, Any], index: int) -> str:
    return _text(event.get("evidence_ref") or event.get("source_id") or event.get("source_url") or event.get("event_id")) or f"conversation_event:{index}"


def _concern_state_evolution(lead: Mapping[str, Any], concern: Mapping[str, Any]) -> dict[str, Any]:
    events = lead.get("conversation_events")
    if not isinstance(events, list):
        return {"status": "unconfirmed", "evidence_ref": "", "event_index": None, "transition": "none"}
    concern_type = _text(concern.get("concern_type"))
    origin_index = concern.get("origin_event_index") if isinstance(concern.get("origin_event_index"), int) else -1
    state, evidence_ref, event_index, transition = "unconfirmed", "", None, "none"
    for index, event in enumerate(events):
        if not isinstance(event, Mapping) or index <= origin_index:
            continue
        ref = _conversation_event_ref(event, index)
        confirmation = _text(event.get("underlying_concern_confirmation") or event.get("confirmed_concern_type"))
        rejection = _text(event.get("underlying_concern_rejection") or event.get("rejected_concern_type"))
        resolution = _text(event.get("underlying_concern_resolution") or event.get("resolved_concern_type"))
        replacement = _text(event.get("underlying_concern_replacement") or event.get("replaced_concern_type"))
        new_objection = _text(event.get("new_objection"))
        if confirmation and (confirmation == concern_type or confirmation.lower() == "confirmed"):
            state, evidence_ref, event_index, transition = "confirmed", ref, index, "confirmed"
        if rejection and (rejection == concern_type or rejection.lower() == "rejected"):
            state, evidence_ref, event_index, transition = "rejected", ref, index, "rejected"
        if resolution and (resolution == concern_type or resolution.lower() == "resolved"):
            state, evidence_ref, event_index, transition = "resolved", ref, index, "resolved"
        if replacement and (replacement == concern_type or replacement.lower() == "replaced"):
            state, evidence_ref, event_index, transition = "replaced", ref, index, "replaced"
        if new_objection and new_objection.lower() != concern_type.lower():
            state, evidence_ref, event_index, transition = "replaced", ref, index, "replaced"
    return {"status": state, "evidence_ref": evidence_ref, "event_index": event_index, "transition": transition}

