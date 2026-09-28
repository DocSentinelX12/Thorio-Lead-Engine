"""Evidence-linked buyer intent progression across the full conversation history.

This module tracks what the buyer has explicitly demonstrated over time. It
never upgrades a prospect from generic engagement to a later commercial state
without explicit evidence.
"""
from __future__ import annotations

from typing import Any, Mapping

from .buyer_signal_intelligence import classify_buyer_signal


TERMINAL_STATES = frozenset({"rejected", "conversion"})
NON_LINEAR_STATES = frozenset(
    {"objection", "timing_delay", "no_need", "existing_solution", "rejected", "re_engagement"}
)
PROGRESSION_STATES = (
    "unknown",
    "engaged",
    "problem_acknowledged",
    "impact_acknowledged",
    "evaluation",
    "decision_process",
    "commercial_commitment",
    "conversion",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _event_ref(event: Mapping[str, Any], index: int) -> str:
    return _text(
        event.get("evidence_ref")
        or event.get("source_id")
        or event.get("source_url")
        or event.get("event_id")
    ) or f"conversation_event:{index}"


def _explicit(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _problem_acknowledged(text: str) -> bool:
    if _explicit(
        text,
        (
            "we have a problem",
            "this is a problem",
            "we're struggling",
            "we are struggling",
            "we need help",
            "we need this",
            "we need to solve",
            "we need to address",
            "this is causing a problem",
            "the issue is",
        ),
    ):
        return True
    if "problem" not in text:
        return False
    if _explicit(
        text,
        (
            "we have no problem",
            "we don't have a problem",
            "we do not have a problem",
            "we solved the problem",
            "we fixed the problem",
            "the problem is resolved",
        ),
    ):
        return False
    active_subjects = (
        "we have ",
        "we're facing ",
        "we are facing ",
        "we're experiencing ",
        "we are experiencing ",
        "we're dealing with ",
        "we are dealing with ",
    )
    problem_index = text.find("problem")
    return any(prefix in text[:problem_index] for prefix in active_subjects)


def _event_signal(event: Mapping[str, Any], index: int = 0) -> dict[str, Any]:
    text = _text(event.get("text")).lower()
    outcome = _text(event.get("outcome")).lower()
    signal = classify_buyer_signal({"conversation_events": [event]})
    ref = _event_ref(event, index)

    if outcome in {"converted", "conversion"}:
        return {"state": "conversion", "reason": "explicit conversion event", "ref": ref}
    if outcome in {"opted_out", "unsubscribe"} or _explicit(
        text, ("unsubscribe", "remove me", "stop contacting", "stop following up", "do not contact me")
    ):
        return {"state": "rejected", "reason": "explicit opt-out", "ref": ref, "terminal_reason": "opt_out"}
    if outcome in {"declined", "rejected", "closed_lost"} or _explicit(
        text, ("we do not need this", "we don't need this", "no need", "not a fit", "we will not move forward")
    ):
        return {"state": "no_need" if _explicit(text, ("no need", "don't need", "do not need")) else "rejected", "reason": "explicit rejection or no-need statement", "ref": ref}
    if outcome == "objection":
        if _explicit(text, ("already have", "in-house", "internal team", "existing provider")):
            state = "existing_solution"
        elif _explicit(text, ("later", "not now", "next quarter", "next month", "timing")):
            state = "timing_delay"
        else:
            state = "objection"
        return {"state": state, "reason": "explicit objection condition", "ref": ref}
    if outcome in {"timing", "timing_delay"} or _explicit(
        text, ("not now", "later", "next quarter", "next month", "revisit in", "circle back in")
    ):
        return {"state": "timing_delay", "reason": "explicit timing constraint", "ref": ref}
    if outcome in {"re_engagement", "reengaged"} or _explicit(
        text, ("let's revisit", "lets revisit", "circle back", "re-engage", "reengage")
    ):
        return {"state": "re_engagement", "reason": "explicit re-engagement evidence", "ref": ref}

    if _explicit(text, ("who needs to approve", "approval process", "legal review", "security review", "needs to approve", "need to approve")):
        return {"state": "decision_process", "reason": "explicit decision-process language", "ref": ref}
    if _explicit(
        text,
        (
            "who needs to approve",
            "approval process",
            "legal review",
            "security review",
            "needs to approve",
            "need to approve",
        ),
    ):
        return {"state": "decision_process", "reason": "explicit decision-process language", "ref": ref}
    if signal["category"] == "explicit_commitment":
        return {"state": "commercial_commitment", "reason": "explicit commercial commitment language", "ref": ref}
    if signal["category"] == "active_evaluation" or _explicit(
        text,
        (
            "comparing providers",
            "comparing options",
            "reviewing proposals",
            "reviewing the proposal",
            "evaluating providers",
            "evaluating options",
            "evaluating this",
            "reviewing options",
        ),
    ):
        return {"state": "evaluation", "reason": "explicit evaluation activity", "ref": ref}
    if _problem_acknowledged(text):
        return {"state": "problem_acknowledged", "reason": "buyer explicitly acknowledged a problem", "ref": ref}
    if _explicit(
        text,
        (
            "we have a problem",
            "this is a problem",
            "we're struggling",
            "we are struggling",
            "we need help",
            "we need this",
            "we need to solve",
            "we need to address",
            "this is causing a problem",
            "the issue is",
        ),
    ):
        return {"state": "problem_acknowledged", "reason": "buyer explicitly acknowledged a problem", "ref": ref}
    if _explicit(
        text,
        (
            "it is costing",
            "it's costing",
            "costs us",
            "causes delays",
            "causing delays",
            "release delays",
            "causing release delays",
            "hurts revenue",
            "losing revenue",
            "business impact",
            "material impact",
            "creates a risk",
            "increases risk",
            "we are losing",
            "we're losing",
            "impact is",
        ),
    ):
        return {"state": "impact_acknowledged", "reason": "buyer explicitly stated a business consequence", "ref": ref}
    if signal["category"] == "interest":
        return {"state": "engaged", "reason": "explicit interest without evaluation or commitment", "ref": ref}
    if signal["category"] in {"commercial_engagement", "general_engagement"} or _text(event.get("text")):
        return {"state": "engaged", "reason": "buyer replied without stronger progression evidence", "ref": ref}
    return {"state": "unknown", "reason": "no explicit buyer evidence", "ref": ref}


def _explicit_contradiction(event: Mapping[str, Any], current_state: str) -> dict[str, str] | None:
    """Return an explicit, evidence-bounded replacement for a stale active state.

    A contradiction may change the active state only when the buyer explicitly
    negates the prior condition or explicitly names the replacement condition.
    Historical progression is never deleted.
    """
    text = _text(event.get("text")).lower()
    if not text or current_state in {"unknown", "engaged"}:
        return None

    replacements: dict[str, tuple[str, tuple[str, ...]]] = {
        "problem_acknowledged": (
            "no_need",
            (
                "we no longer have a problem",
                "we don't have a problem anymore",
                "we do not have a problem anymore",
                "the problem is resolved",
                "we solved the problem",
                "we fixed the problem",
            ),
        ),
        "impact_acknowledged": (
            "problem_acknowledged",
            (
                "the impact isn't material",
                "the impact is not material",
                "the impact is no longer material",
                "it's not materially impacting us",
                "it is not materially impacting us",
                "the impact is not significant",
            ),
        ),
        "evaluation": (
            "engaged",
            (
                "we are not evaluating",
                "we're not evaluating",
                "we are no longer evaluating",
                "we're no longer evaluating",
                "we stopped evaluating",
                "we are not comparing providers",
                "we're not comparing providers",
                "we are no longer comparing providers",
                "we're no longer comparing providers",
                "we are not reviewing proposals",
                "we're not reviewing proposals",
                "we are just gathering information",
                "we're just gathering information",
                "we are only gathering information",
                "we're only gathering information",
            ),
        ),
        "decision_process": (
            "evaluation",
            (
                "we are not at the approval stage",
                "we're not at the approval stage",
                "we are not discussing approval yet",
                "we're not discussing approval yet",
                "approval is not part of this yet",
            ),
        ),
        "commercial_commitment": (
            "rejected",
            (
                "we are not moving forward",
                "we're not moving forward",
                "we will not move forward",
                "we won't move forward",
                "we decided not to proceed",
                "we have decided not to proceed",
            ),
        ),
    }

    replacement = replacements.get(current_state)
    if not replacement:
        return None
    state, phrases = replacement
    if not _explicit(text, phrases):
        return None
    return {
        "state": state,
        "reason": f"explicit buyer contradiction superseded active {current_state} state",
    }


def _qualification_from_event(event: Mapping[str, Any], state: str) -> dict[str, str]:
    text = _text(event.get("text")).lower()
    values = {
        "active_need": _text(event.get("active_need") or event.get("need")),
        "desired_outcome": _text(event.get("desired_outcome") or event.get("success_metric")),
        "business_impact": _text(event.get("business_impact") or event.get("impact")),
        "timing": _text(event.get("timing") or event.get("timeline") or event.get("decision_date") or event.get("start_date")),
        "decision_process": _text(event.get("decision_process")),
        "authority_participants": _text(event.get("authority") or event.get("decision_authority") or event.get("decision_role")),
        "economic_criteria": _text(event.get("budget") or event.get("budget_signal") or event.get("commercial_constraint")),
        "existing_solution": "",
    }
    if not values["active_need"] and _explicit(text, ("we need", "we have a problem", "we're struggling", "we are struggling")):
        values["active_need"] = _text(event.get("text"))
    if not values["desired_outcome"] and _explicit(text, ("we want", "we need to achieve", "goal is", "looking to achieve")):
        values["desired_outcome"] = _text(event.get("text"))
    if not values["business_impact"] and _explicit(
        text, ("costs us", "costing", "causes delays", "hurts revenue", "losing revenue", "business impact", "creates a risk", "increases risk")
    ):
        values["business_impact"] = _text(event.get("text"))
    if not values["decision_process"] and _explicit(text, ("approval process", "who needs to approve", "procurement", "legal review", "security review")):
        values["decision_process"] = _text(event.get("text"))
    if not values["authority_participants"] and _explicit(text, ("cto", "vp engineering", "ceo", "cfo", "needs to approve", "need to approve")):
        values["authority_participants"] = _text(event.get("text"))
    if not values["economic_criteria"] and _explicit(text, ("budget", "pricing", "cost", "investment", "commercial criteria")):
        values["economic_criteria"] = _text(event.get("text"))
    if _explicit(text, ("already have", "in-house", "internal team", "existing provider")):
        values["existing_solution"] = _text(event.get("text"))
    return values


def _next_requirement(state: str, known: Mapping[str, Any]) -> tuple[str, str, str]:
    requirements = {
        "unknown": ("active_need", "discover_active_need", "Is this need still active, and what outcome would make solving it worthwhile?"),
        "engaged": ("active_need", "establish_problem", "What problem or need is important enough to address here?"),
        "problem_acknowledged": ("business_impact", "clarify_business_impact", "What business consequence matters most if this problem remains unresolved?"),
        "impact_acknowledged": ("timing", "establish_real_timeline", "What event or condition determines when addressing this becomes actionable?"),
        "evaluation": ("decision_process", "map_evaluation_process", "What criteria, people, and approval steps will determine whether you move forward?"),
        "decision_process": ("economic_criteria", "clarify_economic_criteria", "What commercial or economic criteria will determine whether this is viable?"),
        "commercial_commitment": ("commitment_details", "confirm_commitment_details", "What specific next step should we put in motion, and who needs to be involved to complete it?"),
        "conversion": ("none", "stop_outreach", ""),
        "objection": ("objection", "diagnose_objection_before_persuading", "What specifically would need to change or be clarified for you to consider moving forward?"),
        "timing_delay": ("timing", "map_timing_constraint", "What event or condition would need to change before this becomes actionable?"),
        "no_need": ("no_need_reason", "diagnose_no_need", "What specifically makes this unnecessary right now, and is there any gap in the current approach worth evaluating?"),
        "existing_solution": ("existing_solution", "diagnose_capacity_gap", "Where, if anywhere, is there still a capacity, specialization, speed, or delivery gap?"),
        "rejected": ("none", "stop_outreach", ""),
        "re_engagement": ("active_need", "reconfirm_active_need", "What has changed, if anything, that makes revisiting this worthwhile now?"),
    }
    dimension, action, question = requirements.get(state, requirements["unknown"])
    if dimension != "none" and known.get(dimension):
        fallback = {
            "active_need": ("desired_outcome", "clarify_desired_outcome", "What outcome would make addressing this worthwhile?"),
            "business_impact": ("timing", "establish_real_timeline", "What event or condition determines when this becomes actionable?"),
            "timing": ("decision_process", "map_decision_process", "Who needs to be involved, and what approval process would apply?"),
            "decision_process": ("economic_criteria", "clarify_economic_criteria", "What commercial or economic criteria will determine whether this is viable?"),
            "economic_criteria": ("commitment_details", "confirm_commitment_details", "What specific next step should we put in motion?"),
        }
        dimension, action, question = fallback.get(dimension, (dimension, action, question))
    return dimension, action, question


def build_buyer_intent_progression(lead: Mapping[str, Any]) -> dict[str, Any]:
    events = lead.get("conversation_events")
    events = events if isinstance(events, list) else []
    current = "unknown"
    history: list[dict[str, Any]] = []
    known: dict[str, dict[str, Any]] = {}
    supersession: dict[str, Any] | None = None
    last_supersession: dict[str, Any] | None = None
    active_terminal = False
    last_ref = ""
    last_index: int | None = None

    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            continue
        evidence = _event_signal(event, index)
        candidate = evidence["state"]
        if candidate == "unknown":
            continue
        qualification = _qualification_from_event(event, candidate)
        for dimension, value in qualification.items():
            if value:
                known[dimension] = {
                    "value": value,
                    "event_index": index,
                    "evidence_ref": _event_ref(event, index),
                }

        if candidate == "conversion":
            transition_type = "advanced" if current != candidate else "confirmed"
            current = candidate
            active_terminal = True
        elif candidate == "re_engagement":
            if active_terminal:
                transition_type = "reengaged"
                current = "re_engagement"
                active_terminal = False
            else:
                transition_type = "observed"
                current = "re_engagement"
        elif candidate in NON_LINEAR_STATES:
            transition_type = "interrupted" if current != candidate else "confirmed"
            current = candidate
            active_terminal = candidate in {"rejected", "no_need"}
        else:
            if active_terminal:
                continue
            contradiction = _explicit_contradiction(event, current)
            if contradiction:
                prior_state = current
                current = contradiction["state"]
                transition_type = "contradicted"
                evidence = {
                    **evidence,
                    "state": current,
                    "reason": contradiction["reason"],
                }
                supersession = {
                    "status": "superseded",
                    "prior_state": prior_state,
                    "active_state": current,
                    "evidence_ref": evidence["ref"],
                    "event_index": index,
                    "evidence_text": _text(event.get("text")),
                    "reason": contradiction["reason"],
                }
                last_supersession = supersession
            else:
                supersession = None
                if current in NON_LINEAR_STATES and candidate == "engaged":
                    continue
                rank = {state: index for index, state in enumerate(PROGRESSION_STATES)}
                if rank[candidate] >= rank.get(current, 0):
                    transition_type = "advanced" if candidate != current else "confirmed"
                    current = candidate
                else:
                    transition_type = "superseded"
                    continue

        last_ref = evidence["ref"]
        last_index = index
        history.append(
            {
                "prior_state": history[-1]["current_state"] if history else "unknown",
                "current_state": current,
                "transition_type": transition_type,
                "evidence_ref": evidence["ref"],
                "evidence_text": _text(event.get("text")),
                "event_index": index,
                "reason": evidence["reason"],
                **({"supersession": supersession} if supersession else {}),
            }
        )
        supersession = None

    # Explicit conversion/rejection stored on the lead is respected only as
    # an already-established lifecycle state, not as inferred buyer intent.
    lifecycle = _text(lead.get("revenue_lifecycle_state")).lower()
    if lifecycle == "converted":
        current = "conversion"
    elif lifecycle in {"closed_lost", "stopped"}:
        current = "rejected"
        active_terminal = True

    known_values = {key: item["value"] for key, item in known.items()}
    missing_dimension, next_action, next_question = _next_requirement(current, known_values)
    transition = history[-1] if history else {
        "prior_state": "unknown",
        "current_state": current,
        "transition_type": "none",
        "evidence_ref": "",
        "evidence_text": "",
        "event_index": None,
        "reason": "No explicit buyer progression evidence is available.",
    }

    return {
        "current_state": current,
        "history": history,
        "transition": transition,
        "evidence_ref": last_ref,
        "event_index": last_index,
        "known_qualification": known,
        "missing_qualification": {
            "dimension": missing_dimension,
            "required": missing_dimension != "none",
            "reason": f"The current state requires explicit evidence for {missing_dimension}." if missing_dimension != "none" else "No additional qualification is required for the current state.",
        },
        "next_best_action": next_action,
        "next_best_question": next_question,
        "active_state_supersession": last_supersession or {
            "status": "none",
            "prior_state": "",
            "active_state": current,
            "evidence_ref": "",
            "event_index": None,
            "evidence_text": "",
            "reason": "No explicit contradiction has superseded the active progression state.",
        },
        "evidence_policy": "Progression requires explicit buyer evidence. Explicit contradictory buyer evidence may supersede the stale active state while every historical state remains auditable.",
    }
