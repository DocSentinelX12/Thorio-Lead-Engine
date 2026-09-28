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
    if any(token in value for token in ("trust", "proof", "case study", "experience", "references")):
        return "trust"
    return "unspecified"


def build_commercial_strategy(lead: Mapping[str, Any], *, objection: str = "") -> dict[str, Any]:
    verified_facts: list[str] = []
    evidence_refs: list[str] = []
    unknowns: list[str] = []
    value_hypotheses: list[str] = []

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
    objection_category = _objection_category(objection) if objection else ""

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

    return {
        "conversation_state": state,
        "objection_category": objection_category,
        "verified_facts": list(dict.fromkeys(verified_facts)),
        "value_hypotheses": list(dict.fromkeys(value_hypotheses)),
        "unknowns": list(dict.fromkeys(unknowns)),
        "evidence_refs": list(dict.fromkeys(evidence_refs)),
        "urgency_basis": urgency_basis,\n        "verified_business_impact": verified_impact,\n        "verified_cost_of_inaction": cost_of_inaction,
        "psychological_objective": psychological_objective,
        "next_best_action": next_best_action,
        "ethical_constraints": [
            "Never convert inference into fact.",
            "Never manufacture urgency, scarcity, social proof, pain, pricing, or outcomes.",
            "Use questions to discover unknown buyer conditions.",
            "Use only verified evidence for factual claims.",
            "Stop immediately on opt-out or terminal commercial states.",
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
