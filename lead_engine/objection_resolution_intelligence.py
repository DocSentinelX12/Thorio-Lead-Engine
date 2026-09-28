"""Evidence-grounded resolution handoff for diagnosed buyer concerns.

A resolved objection is not treated as commercially cleared merely because the
buyer used resolution language. The closer must see explicit post-resolution
buyer evidence before handing control back to progression.
"""
from __future__ import annotations

from typing import Any, Mapping


_TERMINAL = frozenset({"rejected", "conversion"})
_HANDOFF_STATES = frozenset({
    "engaged",
    "problem_acknowledged",
    "impact_acknowledged",
    "evaluation",
    "decision_process",
    "commercial_commitment",
})
_POLITE = frozenset({
    "thanks",
    "thank you",
    "helpful",
    "makes sense",
    "sounds good",
    "got it",
    "understood",
})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _ref(event: Mapping[str, Any], index: int) -> str:
    return _text(event.get("evidence_ref") or event.get("source_id") or event.get("source_url") or event.get("event_id")) or f"conversation_event:{index}"


def _is_polite_only(text: str) -> bool:
    value = text.lower().strip().rstrip(".!?")
    return (
        not value
        or value in _POLITE
        or value.startswith("thanks,")
        or value.startswith("thank you,")
    )


def _latest_resolution_event(events: list[Any]) -> tuple[Mapping[str, Any], int, str]:
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if not isinstance(event, Mapping):
            continue
        concern = _text(event.get("underlying_concern_resolution") or event.get("resolved_concern_type")).lower()
        if concern:
            return event, index, concern
    return {}, -1, ""


def _post_resolution_state(event: Mapping[str, Any]) -> str:
    text = _text(event.get("text")).lower()
    outcome = _text(event.get("outcome")).lower()
    if outcome in {"opted_out", "unsubscribe", "rejected", "closed_lost"}:
        return "rejected"
    if outcome in {"converted", "conversion"}:
        return "conversion"
    if outcome in {"objection", "timing", "timing_delay"}:
        return "reopened"
    if any(p in text for p in ("comparing providers", "comparing options", "reviewing proposals", "reviewing the proposal", "evaluating providers", "evaluating options")):
        return "evaluation"
    if any(p in text for p in ("approval process", "who needs to approve", "legal review", "security review", "procurement")):
        return "decision_process"
    if any(p in text for p in ("send the agreement", "send over the agreement", "kickoff", "move forward", "let's proceed", "lets proceed", "next step")):
        return "commercial_commitment"
    if _is_polite_only(text):
        return "polite"
    if outcome in {"replied", "interested"}:
        return "engaged"
    return "unknown"


def build_objection_resolution_intelligence(
    lead: Mapping[str, Any],
    diagnosis: Mapping[str, Any],
    progression: Mapping[str, Any],
) -> dict[str, Any]:
    lead = lead if isinstance(lead, Mapping) else {}
    diagnosis = diagnosis if isinstance(diagnosis, Mapping) else {}
    progression = progression if isinstance(progression, Mapping) else {}
    diagnosis_status = _text(diagnosis.get("status")).lower()
    events = lead.get("conversation_events")
    events = events if isinstance(events, list) else []
    resolution_event, resolution_index, resolved_type = _latest_resolution_event(events)
    if diagnosis_status != "resolved" and resolved_type:
        diagnosis_status = "resolved"
        diagnosis = {**diagnosis, "state_evidence_ref": _ref(resolution_event, resolution_index), "state_event_index": resolution_index, "hypothesis_type": resolved_type}

    if _text(progression.get("current_state")).lower() in _TERMINAL or diagnosis_status == "terminal":
        return {
            "status": "terminal",
            "progression_handoff_allowed": False,
            "resolution_evidence_ref": _text(diagnosis.get("state_evidence_ref")),
            "post_resolution_evidence_ref": "",
            "next_best_action": "stop_outreach",
            "next_best_question": "",
            "evidence_policy": "Terminal outcomes cannot be reopened by resolution analysis.",
        }

    if diagnosis_status in {"hypothesis", "unconfirmed"}:
        return {
            "status": "unresolved",
            "progression_handoff_allowed": False,
            "resolution_evidence_ref": "",
            "post_resolution_evidence_ref": "",
            "next_best_action": _text(diagnosis.get("next_best_action")) or "diagnose_objection_before_persuading",
            "next_best_question": _text(diagnosis.get("next_best_question")),
            "evidence_policy": "A hypothesis cannot be treated as resolved without explicit buyer evidence.",
        }

    resolution_ref = _text(diagnosis.get("state_evidence_ref")) if diagnosis_status == "resolved" else ""
    resolution_index = diagnosis.get("state_event_index")
    if not resolution_ref or not isinstance(resolution_index, int):
        if diagnosis_status == "confirmed":
            return {
                "status": "active_concern",
                "progression_handoff_allowed": False,
                "resolution_evidence_ref": "",
                "post_resolution_evidence_ref": "",
                "next_best_action": _text(diagnosis.get("next_best_action")),
                "next_best_question": _text(diagnosis.get("next_best_question")),
                "evidence_policy": "A confirmed concern remains active until explicit resolution evidence appears.",
            }
        return {
            "status": "unresolved",
            "progression_handoff_allowed": False,
            "resolution_evidence_ref": "",
            "post_resolution_evidence_ref": "",
            "next_best_action": _text(diagnosis.get("next_best_action")) or "diagnose_objection_before_persuading",
            "next_best_question": _text(diagnosis.get("next_best_question")),
            "evidence_policy": "Only explicit resolution evidence can clear a diagnosed concern.",
        }

    post_resolution = []
    reopened = False
    for index in range(resolution_index + 1, len(events)):
        event = events[index]
        if not isinstance(event, Mapping):
            continue
        confirmation = _text(event.get("underlying_concern_confirmation") or event.get("confirmed_concern_type")).lower()
        resolution_type = _text(diagnosis.get("hypothesis_type")).lower()
        if confirmation == resolution_type:
            reopened = True
            post_resolution.append((index, "reopened"))
            continue
        state = _post_resolution_state(event)
        if state in {"rejected", "conversion", "reopened"}:
            post_resolution.append((index, state))
        elif state in _HANDOFF_STATES:
            post_resolution.append((index, state))

    if reopened:
        index, _ = post_resolution[-1]
        return {
            "status": "reopened",
            "progression_handoff_allowed": False,
            "resolution_evidence_ref": resolution_ref,
            "post_resolution_evidence_ref": _ref(events[index], index),
            "next_best_action": _text(diagnosis.get("next_best_action")) or "diagnose_objection_before_persuading",
            "next_best_question": _text(diagnosis.get("next_best_question")),
            "evidence_policy": "Later explicit buyer evidence reopens the concern and supersedes the prior resolution.",
        }

    strong = [(index, state) for index, state in post_resolution if state in _HANDOFF_STATES]
    if strong:
        index, state = strong[-1]
        action_map = {
            "evaluation": "map_evaluation_process",
            "decision_process": "map_decision_process",
            "commercial_commitment": "confirm_commitment_details",
            "impact_acknowledged": "clarify_business_impact",
            "problem_acknowledged": "clarify_business_impact",
            "engaged": "clarify_business_impact",
        }
        return {
            "status": "resolved_and_reengaged",
            "progression_handoff_allowed": True,
            "resolution_evidence_ref": resolution_ref,
            "post_resolution_evidence_ref": _ref(events[index], index),
            "next_best_action": action_map.get(state, _text(progression.get("next_best_action"))),
            "next_best_question": _text(progression.get("next_best_question")),
            "evidence_policy": "Progression resumes only from explicit post-resolution buyer evidence.",
        }

    return {
        "status": "resolved_pending_reconfirmation",
        "progression_handoff_allowed": False,
        "resolution_evidence_ref": resolution_ref,
        "post_resolution_evidence_ref": "",
        "next_best_action": "reconfirm_active_need",
        "next_best_question": "With that concern addressed, is the underlying need still active, and what outcome would make solving it worthwhile?",
        "evidence_policy": "Resolution clears the diagnosed concern but does not prove renewed buying intent. Politeness or vague agreement is insufficient for progression handoff.",
    }
