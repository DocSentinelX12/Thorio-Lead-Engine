"""Evidence-grounded commercial psychology and next-best-action reasoning.

This module does not invent buyer psychology. It derives commercial hypotheses
from verified research, keeps facts separate from inference, and explicitly
records unknowns so the closer can discover them rather than fabricate them.
"""
from __future__ import annotations

from typing import Any, Mapping


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


def _research_value(lead: Mapping[str, Any], key: str, field: str) -> str:
    value = lead.get(key)
    if not _verified(value):
        return ""
    return _text(value.get(field))


def _conversation_state(lead: Mapping[str, Any]) -> str:
    lifecycle = _text(lead.get("revenue_lifecycle_state")).lower()
    outreach = _text(lead.get("outreach_state")).lower()
    if lifecycle in {"converted", "referred", "closed_lost", "disqualified", "stopped"}:
        return lifecycle
    if outreach in {"objection", "interested", "replied", "awaiting_response"}:
        return outreach
    if isinstance(lead.get("conversation_events"), list) and lead.get("conversation_events"):
        latest = lead["conversation_events"][-1]
        if isinstance(latest, Mapping):
            outcome = _text(latest.get("outcome")).lower()
            if outcome:
                return outcome
    return "new"


def _objection_category(text: str) -> str:
    value = text.lower()
    if any(token in value for token in ("stop", "remove me", "unsubscribe", "not interested", "no thanks")):
        return "opt_out"
    if any(token in value for token in ("price", "pricing", "cost", "expensive", "budget")):
        return "price"
    if any(token in value for token in ("already have", "in-house", "internal team", "internal engineering", "existing provider")):
        return "existing_solution"
    if any(token in value for token in ("later", "not now", "timing", "next quarter", "next month")):
        return "timing"
    if any(token in value for token in ("need to think", "think about it", "discuss internally", "talk internally")):
        return "decision_process"
    if any(token in value for token in ("how does this work", "how would this work", "process", "what do you do")):
        return "information"
    if any(token in value for token in ("trust", "proof", "case study", "experience", "references", "deliver reliably", "reliable delivery", "delivery risk", "can you deliver", "delivery capability")):
        return "trust"
    return "unspecified"



def _profile_entry(statement: str, evidence_refs: list[str], *, status: str = "verified") -> dict[str, Any]:
    return {
        "statement": statement,
        "status": status,
        "evidence_refs": list(dict.fromkeys(ref for ref in evidence_refs if ref)),
    }


def _verified_field(mapping: Any, *keys: str) -> tuple[str, list[str]]:
    if not _verified(mapping):
        return "", []
    value = next((_text(mapping.get(key)) for key in keys if _text(mapping.get(key))), "")
    ref = _evidence_ref(mapping)
    return value, [ref] if ref else []


def build_commercial_psychology_profile(lead: Mapping[str, Any]) -> dict[str, Any]:
    """Build an evidence-linked buyer profile without promoting inference to fact."""
    profile_unknowns: list[str] = []

    current_section = lead.get("current_intent_research")
    business_section = lead.get("business_need_research")
    impact_section = lead.get("business_impact_research")
    commercial_section = lead.get("commercial_research")
    company_section = lead.get("company_research")
    decision_section = lead.get("decision_maker_research")

    current_need, current_refs = _verified_field(current_section, "current_need", "business_need")
    business_need, business_refs = _verified_field(business_section, "business_need", "current_need")
    impact, impact_refs = _verified_field(impact_section, "business_impact")
    cost_of_inaction, cost_refs = _verified_field(impact_section, "cost_of_inaction")

    objective_values = list(dict.fromkeys(value for value in (business_need, current_need) if value))
    objective_refs = list(dict.fromkeys(business_refs + current_refs))
    if objective_values:
        observed_fact = _profile_entry(
            "The researched commercial objective includes " + " and ".join(objective_values) + ".",
            objective_refs,
        )
    else:
        observed_fact = _profile_entry(
            "The company's immediate commercial objective is not established by verified research.",
            [],
            status="unknown",
        )
        profile_unknowns.append("The company's immediate objective is not established.")

    if business_need:
        inference = _profile_entry(
            f"The verified need suggests that {business_need.rstrip('.!?')} is commercially relevant; the material business consequence still requires validation.",
            business_refs,
            status="inference",
        )
    elif current_need:
        inference = _profile_entry(
            f"The verified current need suggests that {current_need.rstrip('.!?')} is commercially relevant; the material business consequence still requires validation.",
            current_refs,
            status="inference",
        )
    else:
        inference = _profile_entry(
            "No evidence-backed commercial inference can be made until a verified need is established.",
            [],
            status="unknown",
        )

    recent_change_value = ""
    recent_change_refs: list[str] = []
    for section in (current_section, business_section, commercial_section, company_section):
        value, refs = _verified_field(
            section,
            "recent_change",
            "changed_recently",
            "change",
            "trigger",
            "recent_trigger",
        )
        if value:
            recent_change_value, recent_change_refs = value, refs
            break
    recent_change = (
        _profile_entry(f"Verified recent change: {recent_change_value}.", recent_change_refs)
        if recent_change_value
        else _profile_entry(
            "No verified recent change has been established.",
            [],
            status="unknown",
        )
    )
    if not recent_change_value:
        profile_unknowns.append("What changed recently remains unknown.")

    observable_problem = (
        _profile_entry(f"The observable business problem is {business_need}.", business_refs)
        if business_need
        else _profile_entry(
            f"The observable current need is {current_need}.",
            current_refs,
        )
        if current_need
        else _profile_entry(
            "No verified observable business problem has been established.",
            [],
            status="unknown",
        )
    )
    if not business_need and not current_need:
        profile_unknowns.append("The observable business problem is not established.")

    likely_consequence = (
        _profile_entry(f"The verified business consequence is {impact}.", impact_refs)
        if impact
        else _profile_entry(
            "The likely business consequence is not established and must be discovered.",
            [],
            status="unknown",
        )
    )
    if not impact:
        profile_unknowns.append("The business consequence of the problem is not established.")

    timing = _text(
        lead.get("current_need_at")
        or lead.get("last_inquiry_at")
        or lead.get("inquiry_at")
        or lead.get("intent_at")
    )
    timing_refs = []
    if timing:
        timing_refs = current_refs or business_refs or _evidence_ref(current_section) and [_evidence_ref(current_section)] or []
    why_now = (
        _profile_entry(
            "A verified timing signal exists; the commercial reason for urgency remains to be discovered.",
            timing_refs,
        )
        if timing
        else _profile_entry(
            "No verified timing signal exists; urgency remains unknown.",
            [],
            status="unknown",
        )
    )
    if not timing:
        profile_unknowns.append("Why this matters now is not established.")

    owner_name = ""
    owner_refs: list[str] = []
    if _verified(company_section):
        owner_name = _text(company_section.get("decision_maker"))
        ref = _text(company_section.get("decision_maker_evidence"))
        if ref:
            owner_refs.append(ref)
    if not owner_name and _verified(decision_section):
        owner_name = _text(decision_section.get("name") or decision_section.get("decision_maker"))
        ref = _evidence_ref(decision_section)
        if ref:
            owner_refs.append(ref)
    problem_owner = (
        _profile_entry(f"Verified problem owner candidate: {owner_name}.", owner_refs)
        if owner_name and _text(company_section.get("decision_maker_verification_status")).lower() == "verified"
        else _profile_entry(
            "The person who owns the business problem is not established beyond the verified contact.",
            owner_refs,
            status="unknown",
        )
    )
    if problem_owner["status"] == "unknown":
        profile_unknowns.append("The problem owner's specific responsibility is not established.")

    priority_value = ""
    priority_refs: list[str] = []
    for section in (decision_section, company_section):
        if not _verified(section):
            continue
        value, refs = _verified_field(
            section,
            "buyer_priorities",
            "priorities",
            "strategic_priorities",
            "goals",
            "success_metrics",
            "evaluation_criteria",
            "decision_criteria",
            "responsibilities",
        )
        if value:
            priority_value, priority_refs = value, refs
            break
    buyer_priorities = (
        _profile_entry(f"Verified buyer priority or evaluation criterion: {priority_value}.", priority_refs)
        if priority_value
        else _profile_entry(
            "The decision-maker's specific priorities and evaluation criteria are not established.",
            [],
            status="unknown",
        )
    )
    if not priority_value:
        profile_unknowns.append("The decision-maker's priorities and evaluation criteria are unknown.")

    if cost_of_inaction:
        cost_entry = _profile_entry(f"The verified cost of inaction is {cost_of_inaction}.", cost_refs)
    else:
        cost_entry = _profile_entry(
            "The cost of waiting is not established and must not be invented.",
            [],
            status="unknown",
        )
        profile_unknowns.append("The cost of waiting is not established.")

    return {
        "observed_fact": observed_fact,
        "sales_inference": inference,
        "recent_change": recent_change,
        "observable_problem": observable_problem,
        "likely_consequence": likely_consequence,
        "why_now": why_now,
        "problem_owner": problem_owner,
        "buyer_priorities": buyer_priorities,
        "cost_of_inaction": cost_entry,
        "unknowns": list(dict.fromkeys(profile_unknowns)),
        "evidence_policy": "Each verified or inferred statement must retain the evidence references that support it; unknowns remain explicitly unknown.",
    }


def _conversation_intelligence(lead: Mapping[str, Any], state: str, objection_category: str) -> dict[str, Any]:
    """Turn observed conversation context into one evidence-safe next move."""
    events = lead.get("conversation_events")
    latest = events[-1] if isinstance(events, list) and events and isinstance(events[-1], Mapping) else {}
    known_context: list[str] = []
    context_fields = (
        ("priority", "priority"),
        ("timing", "timing"),
        ("decision_process", "decision_process"),
        ("budget", "budget"),
        ("authority", "authority"),
        ("desired_outcome", "desired_outcome"),
        ("success_metric", "success_metric"),
    )
    for field, label in context_fields:
        value = _text(latest.get(field))
        if value:
            known_context.append(value)

    if objection_category == "opt_out" or state in {"converted", "referred", "closed_lost", "disqualified", "stopped"}:
        return {
            "state": state,
            "known_buyer_context": known_context,
            "next_best_action": "stop_outreach",
            "next_best_question": "",
            "advance_condition": "The conversation is terminal or the prospect has opted out.",
        }

    if objection_category == "existing_solution":
        return {
            "state": state,
            "known_buyer_context": known_context,
            "next_best_action": "diagnose_capacity_gap",
            "next_best_question": "Where, if anywhere, is there still a capacity, specialization, speed, or delivery gap?",
            "advance_condition": "A concrete gap is either confirmed or ruled out without disparaging the existing team or provider.",
        }

    if objection_category == "price":
        return {
            "state": state,
            "known_buyer_context": known_context,
            "next_best_action": "establish_value_and_fit_before_price",
            "next_best_question": "Which outcome would need to justify the investment for this to be worth considering?",
            "advance_condition": "The relevant outcome and fit are understood well enough to discuss economics honestly.",
        }

    if objection_category == "trust":
        return {
            "state": state,
            "known_buyer_context": known_context,
            "next_best_action": "provide_verified_proof_or_offer_discovery",
            "next_best_question": "What would you need to verify before deciding whether a conversation is worthwhile?",
            "advance_condition": "The buyer's evidence requirement is known and can be answered with verified proof.",
        }

    if objection_category == "information":
        return {
            "state": state,
            "known_buyer_context": known_context,
            "next_best_action": "answer_and_advance",
            "next_best_question": "What part of the process would you like clarified before deciding whether to continue?",
            "advance_condition": "The requested information is answered accurately and the next step is clear.",
        }

    if objection_category == "decision_process" or (
        state == "interested" and _text(latest.get("decision_process"))
    ):
        return {
            "state": state,
            "known_buyer_context": known_context,
            "next_best_action": "map_decision_process",
            "next_best_question": "What part of the decision process is still unresolved, and who else needs to be involved?",
            "advance_condition": "The evaluation path and required participants are clear enough to define a concrete next step.",
        }

    if objection_category == "timing":
        return {
            "state": state,
            "known_buyer_context": known_context,
            "next_best_action": "clarify_timing",
            "next_best_question": "What event or condition determines when this becomes actionable?",
            "advance_condition": "A real timing condition is identified without manufacturing urgency.",
        }

    if state == "interested" and not known_context:
        return {
            "state": state,
            "known_buyer_context": known_context,
            "next_best_action": "answer_and_advance",
            "next_best_question": "What outcome matters most to your team, and how would you measure whether solving this was worthwhile?",
            "advance_condition": "The buyer's desired outcome and a concrete next step are clear.",
        }

    if state in {"replied", "interested"}:
        if _text(latest.get("desired_outcome")) or _text(latest.get("success_metric")):
            return {
                "state": state,
                "known_buyer_context": known_context,
                "next_best_action": "clarify_business_impact",
                "next_best_question": "What business consequence matters most if that outcome is not achieved?",
                "advance_condition": "The material consequence and its relevance to the buyer are understood.",
            }
        if _text(latest.get("priority")) or _text(latest.get("timing")):
            return {
                "state": state,
                "known_buyer_context": known_context,
                "next_best_action": "clarify_business_impact",
                "next_best_question": "What outcome would make addressing this matter worthwhile?",
                "advance_condition": "The desired outcome and material business consequence are clear.",
            }
        return {
            "state": state,
            "known_buyer_context": known_context,
            "next_best_action": "clarify_business_impact",
            "next_best_question": "What outcome would make solving this problem worthwhile?",
            "advance_condition": "The desired outcome and material business consequence are clear.",
        }

    return {
        "state": state,
        "known_buyer_context": known_context,
        "next_best_action": "discover_active_need",
        "next_best_question": "Is this need still active, and what outcome would make solving it worthwhile?",
        "advance_condition": "The need is confirmed as active and the desired outcome is understood.",
    }


def _conversation_memory(lead: Mapping[str, Any]) -> dict[str, Any]:
    """Aggregate conversation facts across events, with the latest observation winning."""
    events = lead.get("conversation_events")
    events = events if isinstance(events, list) else []
    fields = ("priority", "timing", "decision_process", "budget", "authority", "desired_outcome", "success_metric")
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
            observed_events.append({"event_index": index, "outcome": _text(event.get("outcome")).lower(), "observed_fields": observed, "evidence_ref": event_ref})
    known = {field: item for field, item in memory.items() if item["value"]}
    return {"event_count": len(events), "known_context": known, "observed_events": observed_events, "latest_event_index": len(events) - 1 if events else None}


def _buying_signal_intelligence(lead: Mapping[str, Any], state: str) -> dict[str, Any]:
    """Classify observed buying intent without treating generic positive language as commitment."""
    events = lead.get("conversation_events")
    latest = events[-1] if isinstance(events, list) and events and isinstance(events[-1], Mapping) else {}
    text = _text(latest.get("text")).lower()
    explicit = any(token in text for token in ("send the agreement", "send contract", "start the contract", "ready to sign", "let's move forward", "lets move forward", "book the kickoff", "start next week"))
    evaluation = any(token in text for token in ("compare", "evaluate", "review", "proposal", "quote", "pricing", "procurement", "who needs to approve"))
    interested = any(token in text for token in ("interested", "tell me more", "sounds good", "let's talk", "lets talk", "schedule", "book"))
    objection = _objection_category(text) if text else ""
    if explicit:
        category, confidence = "explicit_commitment", "high"
    elif evaluation:
        category, confidence = "active_evaluation", "high"
    elif objection and objection != "unspecified":
        category, confidence = "objection", "high"
    elif interested or state == "interested":
        category, confidence = "interest", "medium"
    elif text:
        category, confidence = "engagement", "low"
    else:
        category, confidence = "no_signal", "none"
    return {
        "category": category,
        "confidence": confidence,
        "evidence_text": _text(latest.get("text")),
        "evidence_ref": _text(latest.get("evidence_ref") or latest.get("source_id") or latest.get("source_url") or latest.get("event_id")),
        "do_not_overstate": category not in {"explicit_commitment", "active_evaluation"},
    }


def _conversation_state_transition(lead: Mapping[str, Any], state: str, buying_signal: Mapping[str, Any], memory: Mapping[str, Any]) -> dict[str, Any]:
    """Describe an evidence-based transition without silently mutating lifecycle state."""
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
    """Return the most recent conversation event that actually records an objection."""
    events = lead.get("conversation_events")
    if not isinstance(events, list):
        return {}
    for event in reversed(events):
        if not isinstance(event, Mapping):
            continue
        outcome = _text(event.get("outcome")).lower()
        objection = _text(event.get("objection"))
        if outcome == "objection" or objection:
            return event
    return {}


def _underlying_concern_intelligence(lead: Mapping[str, Any], objection_category: str) -> dict[str, Any]:
    """Generate a falsifiable concern hypothesis from observed language, never a buyer fact."""
    latest = _latest_objection_event(lead)
    text = _text(latest.get("text") or latest.get("objection"))
    origin_index = None
    events = lead.get("conversation_events")
    if isinstance(events, list):
        for index in range(len(events) - 1, -1, -1):
            if events[index] is latest:
                origin_index = index
                break
    hypotheses = {
        "price": ("economic_risk", "The buyer may be concerned that the economics are not justified by the expected value.", "Which outcome or constraint would need to be clear before the economics could be evaluated?"),
        "existing_solution": ("capability_or_displacement_risk", "The buyer may be concerned that changing or adding a provider would create unnecessary disruption because the current solution already works.", "What would need to be different from the current solution for an additional option to be worth evaluating?"),
        "timing": ("timing_or_resource_constraint", "The buyer may be constrained by timing, competing priorities, or available resources.", "What condition would make this worth revisiting, and what constraint is preventing action today?"),
        "decision_process": ("internal_decision_risk", "The buyer may need internal alignment, approval, or confidence about how a decision will be evaluated.", "What part of the internal decision process is still uncertain?"),
        "trust": ("proof_or_delivery_risk", "The buyer may need evidence that the proposed capability can be delivered reliably in their context.", "What specific evidence would reduce the uncertainty you have?"),
        "information": ("fit_or_understanding_risk", "The buyer may not yet have enough information to determine whether the offering fits the need.", "What specific part of the approach would you need to understand to evaluate fit?"),
    }
    if objection_category not in hypotheses:
        return {"status": "unconfirmed", "hypothesis": "", "concern_type": "", "evidence_refs": [], "validation_question": "", "confirmation_criteria": "No underlying concern is established from the available conversation evidence."}
    concern_type, hypothesis, question = hypotheses[objection_category]
    evidence_ref = _text(latest.get("evidence_ref") or latest.get("source_id") or latest.get("source_url") or latest.get("event_id"))
    return {
        "status": "hypothesis",
        "hypothesis": hypothesis,
        "concern_type": concern_type,
        "evidence_refs": [evidence_ref] if evidence_ref else [],
        "observed_text": text,
        "origin_event_index": origin_index,
        "validation_question": question,
        "confirmation_criteria": "Confirm only if the buyer explicitly validates the concern; otherwise retain it as unconfirmed and do not use it as a factual claim.",
        "state_policy": "A later explicit confirmation, rejection, resolution, or replacement can change this state; ordinary replies do not.",
    }


def _conversation_event_ref(event: Mapping[str, Any], index: int) -> str:
    return _text(event.get("evidence_ref") or event.get("source_id") or event.get("source_url") or event.get("event_id")) or f"conversation_event:{index}"


def _concern_state_evolution(lead: Mapping[str, Any], concern: Mapping[str, Any]) -> dict[str, Any]:
    """Track explicit concern transitions without inferring resolution from ordinary replies."""
    events = lead.get("conversation_events")
    if not isinstance(events, list):
        return {"status": "unconfirmed", "evidence_ref": "", "event_index": None, "transition": "none"}

    concern_type = _text(concern.get("concern_type"))
    origin_index = concern.get("origin_event_index")
    if not isinstance(origin_index, int):
        origin_index = -1

    state = "unconfirmed"
    evidence_ref = ""
    event_index = None
    transition = "none"

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
        if replacement and (replacement == concern_type or replacement.lower() == "superseded"):
            state, evidence_ref, event_index, transition = "superseded", ref, index, "superseded"
        if new_objection:
            state, evidence_ref, event_index, transition = "superseded", ref, index, "superseded"
        if _text(event.get("outcome")).lower() == "objection":
            state, evidence_ref, event_index, transition = "superseded", ref, index, "superseded"

    return {"status": state, "evidence_ref": evidence_ref, "event_index": event_index, "transition": transition}


def _apply_confirmed_concern_state(lead: Mapping[str, Any], concern: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve confirmation while allowing later explicit state transitions to override it."""
    evolution = _concern_state_evolution(lead, concern)
    return {
        "status": evolution["status"],
        "confirmed_by": evolution["evidence_ref"] if evolution["status"] == "confirmed" else "",
        "state_evidence_ref": evolution["evidence_ref"],
        "state_event_index": evolution["event_index"],
        "transition": evolution["transition"],
    }

def _confirmed_concern_next_action(concern: Mapping[str, Any]) -> dict[str, Any]:
    """Translate only a buyer-confirmed concern into a targeted, evidence-safe next move."""
    if _text(concern.get("status")).lower() != "confirmed":
        return {"applied": False, "next_best_action": "", "next_best_question": "", "reason": "The concern is not buyer-confirmed, so it remains a validation hypothesis."}
    actions = {
        "economic_risk": (
            "clarify_economic_criteria",
            "Which economic outcome or constraint should we evaluate first so we can determine whether the investment makes sense?",
            "The buyer-confirmed economic concern is addressed through explicit evaluation criteria, without assuming ROI or affordability.",
        ),
        "capability_or_displacement_risk": (
            "de_risk_augmentation_fit",
            "What would need to be true for an additional capability to fit alongside the current team without creating the disruption you want to avoid?",
            "The buyer-confirmed displacement or disruption concern is addressed by defining a non-disruptive fit condition.",
        ),
        "timing_or_resource_constraint": (
            "map_timing_constraint",
            "Which timing or resource constraint would need to change before this could become actionable?",
            "The buyer-confirmed constraint is mapped without manufacturing urgency.",
        ),
        "internal_decision_risk": (
            "map_internal_decision_risk",
            "What internal approval or alignment point is creating the remaining decision risk?",
            "The buyer-confirmed internal decision concern is mapped to its actual approval or alignment requirement.",
        ),
        "proof_or_delivery_risk": (
            "provide_verified_proof_or_offer_discovery",
            "What specific evidence about delivery would you need to verify before evaluating the fit?",
            "The buyer-confirmed proof concern is handled with verified evidence rather than unsupported reassurance.",
        ),
        "fit_or_understanding_risk": (
            "clarify_fit_requirements",
            "What specific requirement would you need clarified to determine whether the approach fits?",
            "The buyer-confirmed fit concern is handled by identifying the concrete evaluation requirement.",
        ),
    }
    action = actions.get(_text(concern.get("concern_type")))
    if not action:
        return {"applied": False, "next_best_action": "", "next_best_question": "", "reason": "The confirmed concern type has no defined safe action."}
    return {"applied": True, "next_best_action": action[0], "next_best_question": action[1], "reason": action[2]}


def _research_reentry_intelligence(strategy_inputs: Mapping[str, Any], state: str, next_best_action: str) -> dict[str, Any]:
    """Identify when research should be revisited instead of filling evidence gaps with persuasion."""
    unknowns = [str(item).strip() for item in strategy_inputs.get("unknowns", []) if str(item).strip()] if isinstance(strategy_inputs.get("unknowns"), (list, tuple)) else []
    required = []
    if next_best_action in {"clarify_business_impact", "establish_value_and_fit_before_price", "diagnose_capacity_gap"}:
        required.append("verified business impact or buyer-stated consequence")
    if next_best_action == "map_decision_process":
        required.append("verified decision participants or buyer-stated process")
    if next_best_action == "provide_verified_proof_or_offer_discovery":
        required.append("verified evidence matching the buyer's proof requirement")
    reentry = bool(required and unknowns)
    return {"recommended": reentry, "required_evidence": required, "reason": "Re-enter research before making a factual claim if the required evidence cannot be obtained from the conversation." if reentry else "Current evidence is sufficient for the defined next discovery action.", "unknowns": unknowns}


def _persuasion_quality(strategy: Mapping[str, Any], conversation_intelligence: Mapping[str, Any], buying_signal: Mapping[str, Any], research_reentry: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate strategy quality before a message is drafted, without optimizing for pressure."""
    violations: list[str] = []
    action = _text(strategy.get("next_best_action"))
    question = _text(conversation_intelligence.get("next_best_question"))
    if not action:
        violations.append("missing_next_best_action")
    if action != "stop_outreach" and not question:
        violations.append("missing_discovery_question")
    if research_reentry.get("recommended") and action in {"claim_value", "claim_urgency", "claim_outcome"}:
        violations.append("evidence_insufficient_for_persuasion_claim")
    if buying_signal.get("do_not_overstate") and _text(strategy.get("psychological_objective")) in {"close", "force_decision"}:
        violations.append("psychological_objective_exceeds_signal")
    return {"passed": not violations, "violations": violations, "next_best_action_supported": bool(action), "question_supported": bool(question) or action == "stop_outreach", "pressure_free": not any(item in violations for item in ("psychological_objective_exceeds_signal",))}

def build_commercial_strategy(lead: Mapping[str, Any], *, objection: str = "") -> dict[str, Any]:
    verified_facts: list[str] = []
    evidence_refs: list[str] = []
    unknowns: list[str] = []
    value_hypotheses: list[str] = []
    commercial_psychology_profile = build_commercial_psychology_profile(lead)
    unknowns.extend(commercial_psychology_profile["unknowns"])

    company = _text(lead.get("company"))
    research = lead.get("company_research")
    if isinstance(research, Mapping):
        if research.get("company_verified") is True and company:
            verified_facts.append(f"Company identity verified: {company}.")
        decision_maker = _text(research.get("decision_maker"))
        if decision_maker and _text(research.get("decision_maker_verification_status")).lower() == "verified":
            verified_facts.append(f"Decision-maker verified: {decision_maker}.")
        ref = _text(research.get("decision_maker_evidence"))
        if ref:
            evidence_refs.append(ref)

    current_need = _research_value(lead, "current_intent_research", "current_need")
    business_need = _research_value(lead, "business_need_research", "business_need")
    if current_need:
        verified_facts.append(f"Verified current need: {current_need}.")
        value_hypotheses.append(f"Determine whether solving {current_need.rstrip('.!?')} would improve a measurable business outcome.")
        ref = _evidence_ref(lead.get("current_intent_research"))
        if ref:
            evidence_refs.append(ref)
    else:
        unknowns.append("The prospect's current priority and desired outcome need further discovery.")

    if business_need:
        verified_facts.append(f"Verified business need: {business_need}.")
        value_hypotheses.append(f"Explore whether {business_need.rstrip('.!?')} is creating a capacity, revenue, cost, delivery, or risk consequence.")
        ref = _evidence_ref(lead.get("business_need_research"))
        if ref:
            evidence_refs.append(ref)
    else:
        unknowns.append("The business impact of the verified need is not yet established.")

    commercial = lead.get("commercial_research")
    if _verified(commercial):
        commercial_signal = _text(commercial.get("commercial_signal") or commercial.get("buying_signal"))
        if commercial_signal:
            verified_facts.append(f"Verified commercial signal: {commercial_signal}.")
        ref = _evidence_ref(commercial)
        if ref:
            evidence_refs.append(ref)

    impact_research = lead.get("business_impact_research")
    verified_impact = _research_value(lead, "business_impact_research", "business_impact")
    cost_of_inaction = _research_value(lead, "business_impact_research", "cost_of_inaction")
    if verified_impact:
        verified_facts.append(f"Verified business impact: {verified_impact}.")
        value_hypotheses.append(f"Test whether addressing the need changes the verified impact: {verified_impact.rstrip('.!?')}.")
        ref = _evidence_ref(impact_research)
        if ref:
            evidence_refs.append(ref)
    if cost_of_inaction:
        verified_facts.append(f"Verified cost of inaction: {cost_of_inaction}.")
        value_hypotheses.append(f"Determine whether the verified cost of inaction, {cost_of_inaction.rstrip('.!?')}, is material enough to justify action.")
    elif impact_research and not _verified(impact_research):
        unknowns.append("Business impact research exists but is not verified, so its impact cannot be used as fact.")

    timing = _text(
        lead.get("current_need_at")
        or lead.get("last_inquiry_at")
        or lead.get("inquiry_at")
        or lead.get("intent_at")
    )
    urgency_basis = "verified_timing_signal" if timing else "none_verified"
    if not timing:
        unknowns.append("Timing and urgency have not been independently established.")

    state = _conversation_state(lead)
    objection_event = _latest_objection_event(lead) if state == "objection" else {}
    if state == "objection":
        observed_objection = objection or _text(objection_event.get("objection")) or _text(objection_event.get("text"))
    else:
        observed_objection = objection
    objection_category = _objection_category(observed_objection) if observed_objection else ""
    conversation_intelligence = _conversation_intelligence(lead, state, objection_category)
    conversation_memory = _conversation_memory(lead)
    buying_signal_intelligence = _buying_signal_intelligence(lead, state)
    underlying_concern = _underlying_concern_intelligence(lead, objection_category)
    concern_confirmation = _apply_confirmed_concern_state(lead, underlying_concern)
    underlying_concern = {
        **underlying_concern,
        "status": concern_confirmation["status"],
        "state_evidence_ref": concern_confirmation["state_evidence_ref"],
        "state_event_index": concern_confirmation["state_event_index"],
        "state_transition": concern_confirmation["transition"],
    }
    if concern_confirmation["status"] == "confirmed":
        underlying_concern["confirmation_evidence_ref"] = concern_confirmation["confirmed_by"]
    confirmed_concern_action = _confirmed_concern_next_action(underlying_concern)
    if confirmed_concern_action["applied"]:
        conversation_intelligence = {
            **conversation_intelligence,
            "next_best_action": confirmed_concern_action["next_best_action"],
            "next_best_question": confirmed_concern_action["next_best_question"],
            "advance_condition": confirmed_concern_action["reason"],
            "action_basis": "buyer_confirmed_underlying_concern",
        }
    else:
        action_basis = "observed_conversation_context"
        if _text(underlying_concern.get("status")).lower() in {"rejected", "resolved", "superseded"}:
            action_basis = "concern_state_evolution"
        conversation_intelligence = {**conversation_intelligence, "action_basis": action_basis}
    state_transition = _conversation_state_transition(lead, state, buying_signal_intelligence, conversation_memory)

    objectives = {
        "new": ("diagnose", "ask_one_high_value_question"),
        "replied": ("diagnose", "clarify_problem_and_impact"),
        "interested": ("clarify_value", "answer_and_advance"),
        "objection": ("resolve_objection", "resolve_then_advance"),
        "awaiting_response": ("advance", "make_next_step_easy"),
        "timing": ("clarify_timing", "establish_real_timeline"),
        "converted": ("protect_conversion", "stop_outreach"),
        "referred": ("protect_referral", "stop_outreach"),
        "closed_lost": ("respect_decision", "stop_outreach"),
        "disqualified": ("protect_integrity", "stop_outreach"),
        "stopped": ("respect_stop", "stop_outreach"),
    }
    psychological_objective, next_best_action = objectives.get(state, objectives["new"])

    if objection_category == "existing_solution":
        next_best_action = "diagnose_capacity_gap"
        psychological_objective = "differentiate_without_attacking"
    elif objection_category == "price":
        next_best_action = "establish_value_and_fit_before_price"
        psychological_objective = "reduce_risk_without_misrepresenting_price"
    elif objection_category == "timing":
        next_best_action = "establish_real_timeline"
        psychological_objective = "clarify_priority_without_creating_false_urgency"
    elif objection_category == "trust":
        next_best_action = "provide_verified_proof_or_offer_discovery"
        psychological_objective = "reduce_perceived_risk"
    elif objection_category == "decision_process":
        next_best_action = "map_decision_process"
        psychological_objective = "reduce_decision_friction"
    elif objection_category == "information":
        next_best_action = "answer_and_advance"
        psychological_objective = "increase_clarity"

    research_reentry = _research_reentry_intelligence({"unknowns": unknowns}, state, conversation_intelligence["next_best_action"])
    persuasion_quality = _persuasion_quality(
        {"next_best_action": conversation_intelligence["next_best_action"], "psychological_objective": psychological_objective},
        conversation_intelligence,
        buying_signal_intelligence,
        research_reentry,
    )

    return {
        "conversation_state": state,
        "objection_category": objection_category,
        "verified_facts": list(dict.fromkeys(verified_facts)),
        "value_hypotheses": list(dict.fromkeys(value_hypotheses)),
        "unknowns": list(dict.fromkeys(unknowns)),
        "evidence_refs": list(dict.fromkeys(evidence_refs)),
        "urgency_basis": urgency_basis,
        "verified_business_impact": verified_impact,
        "verified_cost_of_inaction": cost_of_inaction,
        "psychological_objective": psychological_objective,
        "next_best_action": conversation_intelligence["next_best_action"],
        "conversation_intelligence": conversation_intelligence,
        "conversation_memory": conversation_memory,
        "buying_signal_intelligence": buying_signal_intelligence,
        "underlying_concern": underlying_concern,
        "confirmed_concern_action": confirmed_concern_action,
        "state_transition": state_transition,
        "research_reentry": research_reentry,
        "persuasion_quality": persuasion_quality,
        "commercial_psychology_profile": commercial_psychology_profile,
        "ethical_constraints": [
            "Never convert inference into fact.",
            "Never manufacture urgency, scarcity, social proof, pain, pricing, or outcomes.",
            "Use questions to discover unknown buyer conditions.",
            "Use only verified evidence for factual claims.",
            "Stop immediately on opt-out or terminal commercial states.",
            "Do not treat ordinary buyer replies as proof that a concern was resolved or rejected.",
            "When a concern is explicitly resolved, rejected, or superseded, remove its stale action from the active strategy.",
        ],
    }


def evaluate_closer_message(body: str, strategy: Mapping[str, Any], buying_signal: str) -> dict[str, Any]:
    """Fail closed on unsupported pressure while checking for a concrete next step."""
    text = _text(body)
    lowered = text.lower()
    violations: list[str] = []
    if _text(strategy.get("urgency_basis")) == "none_verified" and any(
        phrase in lowered for phrase in ("urgent", "act now", "last chance", "limited time", "deadline", "expires")
    ):
        violations.append("unsupported_urgency")
    if any(
        phrase in lowered
        for phrase in ("guaranteed", "guarantee", "best in the market", "everyone is using", "no risk", "will save you", "will increase revenue")
    ):
        violations.append("unsupported_outcome_claim")
    if not text:
        violations.append("empty_message")
    if buying_signal and buying_signal.lower() not in lowered:
        violations.append("verified_need_not_reflected")
    clear_next_step = any(
        marker in lowered
        for marker in ("would you", "could we", "are you open", "would it be useful", "what is the main", "what would need")
    )
    if not clear_next_step:
        violations.append("missing_next_step")
    return {
        "passed": not violations,
        "truthfulness": not any(item in violations for item in ("unsupported_urgency", "unsupported_outcome_claim", "verified_need_not_reflected")),
        "clear_next_step": clear_next_step,
        "unsupported_urgency": "unsupported_urgency" in violations,
        "violations": violations,
    }


def build_objection_response(objection: str, route: str, *, lead: Mapping[str, Any] | None = None) -> str:
    text = _text(objection)
    lowered = text.lower()
    if any(token in lowered for token in ("not interested", "no thanks", "stop", "remove me", "unsubscribe")):
        return "Understood. I will not follow up further."

    strategy = build_commercial_strategy(lead or {}, objection=text)
    category = strategy["objection_category"]

    if category == "price":
        return (
            f"I understand the concern. I do not want to make assumptions or defend a price before establishing whether "
            f"{route} is actually a fit. If useful, I can first clarify the outcome you need and then "
            "we can determine whether the economics make sense."
        )
    if category == "existing_solution":
        return (
            "That makes sense. I would not suggest replacing something that is already working. "
            "The useful question is whether there is a capacity, specialization, speed, or delivery gap "
            "your current team is not trying to cover. Is there a gap like that today?"
        )
    if category == "timing":
        return (
            "Understood. I do not want to manufacture urgency. What would need to change for this to "
            "become a priority, and is there a real date or event driving that decision?"
        )
    if category == "decision_process":
        return (
            "Absolutely. Rather than push for a decision prematurely, what does the evaluation process "
            "normally look like on your side, and who else needs to be involved?"
        )
    if category == "trust":
        return (
            "Fair question. I would rather use specific, verifiable evidence than make a broad claim. "
            "What would you need to verify before deciding whether a conversation is worthwhile?"
        )
    if category == "information":
        return (
            f"Happy to explain. The goal is to determine whether {route} addresses the need you described. "
            "If I answer that directly, would the next useful step be deciding whether a deeper conversation makes sense?"
        )

    return (
        "Thanks for the context. I do not want to assume the reason behind your concern. "
        "What is the main issue you would need resolved before considering a next step?"
    )
