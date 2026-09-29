"""Evidence-grounded advancement control for the commercial closer.

This layer converts buyer intent progression into an auditable advancement plan.
It never treats persuasion as permission to skip missing evidence, manufacture
urgency, or turn a hypothesis into a fact.
"""
from __future__ import annotations

from typing import Any, Mapping


_TERMINAL_STATES = frozenset({"conversion", "rejected"})
_INTERRUPTION_STATES = frozenset(
    {"objection", "timing_delay", "no_need", "existing_solution", "rejected"}
)

_STAGE_PSYCHOLOGY = {
    "unknown": (
        "discover",
        "Establish whether a real active need exists before attempting to persuade.",
    ),
    "engaged": (
        "diagnose",
        "Understand the problem in the buyer's own terms before presenting value.",
    ),
    "problem_acknowledged": (
        "clarify_impact",
        "Connect the acknowledged problem to a buyer-stated business consequence.",
    ),
    "impact_acknowledged": (
        "establish_timing",
        "Identify the real condition that makes the problem actionable without manufacturing urgency.",
    ),
    "evaluation": (
        "map_decision",
        "Understand evaluation criteria, participants, and approval steps before pushing for commitment.",
    ),
    "decision_process": (
        "clarify_economics",
        "Establish the actual commercial criteria rather than assuming budget or affordability.",
    ),
    "commercial_commitment": (
        "confirm_execution",
        "Turn the explicit commitment into a concrete, mutually understood next step.",
    ),
    "conversion": (
        "protect_conversion",
        "Stop persuasion and preserve the verified commercial outcome.",
    ),
    "re_engagement": (
        "reconfirm_change",
        "Determine what changed before restarting a prior commercial conversation.",
    ),
    "objection": (
        "diagnose_objection",
        "Understand the stated objection before attempting to overcome it.",
    ),
    "timing_delay": (
        "map_constraint",
        "Identify the real timing condition without creating artificial urgency.",
    ),
    "no_need": (
        "respect_decision",
        "Do not manufacture a need the buyer has explicitly rejected.",
    ),
    "existing_solution": (
        "diagnose_gap",
        "Identify a concrete capability gap without attacking the existing team or provider.",
    ),
    "rejected": (
        "stop_outreach",
        "Respect the explicit rejection and do not continue persuasion.",
    ),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _known_value(known: Mapping[str, Any], dimension: str) -> str:
    value = known.get(dimension)
    if isinstance(value, Mapping):
        return _text(value.get("value"))
    return _text(value)


def _current_evidence(progression: Mapping[str, Any]) -> dict[str, Any]:
    current = _text(progression.get("current_state")).lower()
    history = progression.get("history")
    if not isinstance(history, list):
        return {"state": current, "evidence_ref": "", "evidence_text": "", "event_index": None}
    for item in reversed(history):
        if isinstance(item, Mapping) and _text(item.get("current_state")).lower() == current:
            return {
                "state": current,
                "evidence_ref": _text(item.get("evidence_ref")),
                "evidence_text": _text(item.get("evidence_text")),
                "event_index": item.get("event_index"),
            }
    return {
        "state": current,
        "evidence_ref": _text(progression.get("evidence_ref")),
        "evidence_text": "",
        "event_index": progression.get("event_index"),
    }


def build_buyer_intent_advancement(
    progression: Mapping[str, Any],
    conversation_memory: Mapping[str, Any] | None = None,
    buying_signal: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the safest commercially useful advancement plan from verified state."""
    progression = progression if isinstance(progression, Mapping) else {}
    memory = conversation_memory if isinstance(conversation_memory, Mapping) else {}
    signal = buying_signal if isinstance(buying_signal, Mapping) else {}

    state = _text(progression.get("current_state")).lower() or "unknown"
    # After explicit re-engagement, historical qualification is retained in
    # known_qualification for auditability, but only the post-reengagement
    # active qualification may satisfy current advancement requirements.
    active_known = progression.get("active_qualification")
    active_known = active_known if isinstance(active_known, Mapping) else None
    known = active_known if active_known is not None else progression.get("known_qualification")
    known = known if isinstance(known, Mapping) else {}
    missing = progression.get("missing_qualification")
    missing = missing if isinstance(missing, Mapping) else {}
    missing_dimension = _text(missing.get("dimension"))

    stage_evidence = _current_evidence(progression)
    mode, psychology = _STAGE_PSYCHOLOGY.get(state, _STAGE_PSYCHOLOGY["unknown"])

    if state in _TERMINAL_STATES:
        mode = "stop"
    elif state in _INTERRUPTION_STATES:
        mode = "resolve_interruption"

    required = bool(missing.get("required"))
    missing_value = not _known_value(known, missing_dimension) if missing_dimension else False

    if state == "commercial_commitment":
        commitment = _known_value(known, "commitment_details") or _known_value(known, "active_need")
        advance_allowed = bool(commitment)
        blocked_reason = (
            ""
            if advance_allowed
            else "An explicit commitment exists, but the concrete execution details are not established."
        )
        if not _known_value(known, "commitment_details") or (required and missing_value):
            advance_allowed = False
            blocked_reason = "An explicit commitment exists, but the concrete execution details are not established."
    elif state == "conversion":
        advance_allowed = False
        blocked_reason = "Conversion is terminal."
    elif state in {"rejected", "no_need"}:
        advance_allowed = False
        blocked_reason = "The buyer has explicitly rejected or declined the need."
    elif state in _INTERRUPTION_STATES:
        advance_allowed = False
        blocked_reason = "An active interruption must be understood or resolved before normal progression resumes."
    else:
        advance_allowed = not (required and missing_value)
        blocked_reason = (
            f"Required qualification is missing: {missing_dimension}."
            if not advance_allowed and missing_dimension
            else ""
        )

    signal_category = _text(signal.get("category"))
    overstatement_guard = bool(signal.get("do_not_overstate", True))
    if overstatement_guard and state not in _TERMINAL_STATES:
        allowed_persuasion = "evidence_bounded_discovery"
    else:
        allowed_persuasion = "execution_confirmation" if state == "commercial_commitment" else "none"

    missing_evidence = []
    if missing_dimension and missing_value:
        missing_evidence.append(missing_dimension)

    memory_context = memory.get("known_context")
    memory_context = memory_context if isinstance(memory_context, Mapping) else {}
    for dimension in missing_evidence:
        if _known_value(memory_context, dimension):
            missing_evidence.remove(dimension)

    return {
        "current_state": state,
        "mode": mode,
        "psychological_strategy": psychology,
        "stage_evidence": stage_evidence,
        "advance_allowed": advance_allowed,
        "blocked_reason": blocked_reason,
        "missing_evidence": missing_evidence,
        "required_evidence": [missing_dimension] if missing_dimension and required else [],
        "known_qualification": dict(known),
        "buyer_signal_category": signal_category,
        "overstatement_guard": overstatement_guard,
        "allowed_persuasion": allowed_persuasion,
        "next_best_action": _text(progression.get("next_best_action")),
        "next_best_question": _text(progression.get("next_best_question")),
        "conversion_claim_allowed": state == "conversion",
        "commitment_claim_allowed": state == "commercial_commitment" and not overstatement_guard,
        "evidence_policy": (
            "Advance only from explicit buyer evidence. Preserve historical evidence. "
            "Do not infer budget, authority, urgency, motivation, or commitment."
        ),
    }
