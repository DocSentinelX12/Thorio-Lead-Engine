from __future__ import annotations

from typing import Any, Callable, Dict


def install() -> None:
    """Route company research through real public-web acquisition before canonicalization."""
    from . import agent_workers
    from .advanced_agent_logic import company_research as acquire_public_research

    original = agent_workers.handler_registry
    if getattr(original, "_company_research_override", False):
        return

    stateful_company_research = agent_workers._company_research

    def company_research(agent: str, payload: Dict[str, Any], ctx: Any) -> Dict[str, Any]:
        # The stateful handler owns canonical package construction and all
        # downstream handoffs. The advanced handler owns the actual bounded
        # public-web evidence acquisition. Run acquisition first, then feed its
        # research into the canonical stateful handler so neither path replaces
        # or bypasses the other.
        acquired = acquire_public_research(payload, ctx)
        acquired_lead = acquired.get("lead") if isinstance(acquired, dict) else None
        acquired_research = acquired.get("research") if isinstance(acquired, dict) else None
        if not isinstance(acquired_lead, dict):
            raise RuntimeError("public company research did not return a persisted lead")
        if not isinstance(acquired_research, dict):
            raise RuntimeError("public company research did not return research facts")

        canonical_payload = dict(payload)
        canonical_payload["lead"] = acquired_lead
        canonical_payload["research"] = acquired_research
        return stateful_company_research(agent, canonical_payload, ctx)

    def handler_registry() -> Dict[str, Callable[..., Dict[str, Any]]]:
        registry = original()
        registry["company_research"] = company_research
        return registry

    handler_registry._company_research_override = True
    agent_workers.handler_registry = handler_registry
