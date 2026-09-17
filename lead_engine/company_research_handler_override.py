from __future__ import annotations

from typing import Any, Callable, Dict


def install() -> None:
    """Ensure the durable stateful company-research worker outranks stateless handlers."""
    from . import agent_workers

    original = agent_workers.handler_registry
    if getattr(original, "_company_research_override", False):
        return

    def handler_registry() -> Dict[str, Callable[..., Dict[str, Any]]]:
        registry = original()
        registry["company_research"] = agent_workers._company_research
        return registry

    handler_registry._company_research_override = True
    agent_workers.handler_registry = handler_registry
