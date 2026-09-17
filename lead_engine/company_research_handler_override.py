from __future__ import annotations

from typing import Any, Callable, Dict


def install() -> None:
    """Ensure the durable stateful company-research worker outranks stateless handlers."""
    from . import agent_workers

    original = agent_workers.handler_registry
    if getattr(original, "_company_research_override", False):
        return

    stateful_company_research = agent_workers._company_research

    def company_research(agent: str, payload: Dict[str, Any], ctx: Any) -> Dict[str, Any]:
        result = stateful_company_research(agent, payload, ctx)
        stored = result.get("lead") if isinstance(result, dict) else None
        if not isinstance(stored, dict):
            return result
        research = stored.get("company_research")
        if not isinstance(research, dict):
            return result
        status = str(research.get("decision_maker_verification_status") or "").strip().lower()
        person = str(stored.get("contact_name") or stored.get("person") or "").strip()
        if person and not status:
            research = dict(research)
            research["observed_decision_maker"] = person
            research["observed_decision_maker_evidence"] = "Named person was directly observed in collector evidence; role remains unverified."
            research["decision_maker_verification_status"] = "observed_needs_role_verification"
            stored = dict(stored)
            stored["company_research"] = research
            persisted = ctx.db.update_payload(str(stored.get("fingerprint") or "").strip(), stored)
            if persisted is not None:
                stored = persisted
                result = dict(result)
                result["lead"] = stored
                result["research"] = stored.get("company_research", research)
                result["decision_maker_verified"] = False
        return result

    def handler_registry() -> Dict[str, Callable[..., Dict[str, Any]]]:
        registry = original()
        registry["company_research"] = company_research
        return registry

    handler_registry._company_research_override = True
    agent_workers.handler_registry = handler_registry
