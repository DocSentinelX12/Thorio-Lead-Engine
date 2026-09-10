from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping
from uuid import uuid4

from .agent_queue import enqueue, pending
from .agent_registry import ALL_AGENT_ROLES, agent_registry
from .agent_specializations import get_specialization
from .agent_workers import run_worker_once


class AgentOrchestrator:
    """Durable coordinator for the specialist workforce.

    Execution capacity is shared dynamically. The orchestrator validates the
    declared role family before dispatch so a specialist cannot silently run a
    different class of work.
    """

    def __init__(self, db, *, worker_prefix: str = "lead-engine"):
        self.db = db
        self.worker_prefix = worker_prefix

    def dispatch(self, agent: str, payload: Mapping[str, Any], *, priority: int = 0) -> Dict[str, Any]:
        get_specialization(agent)
        return enqueue(self.db, agent, dict(payload), priority=priority)

    def dispatch_discovery(self, agent: str, record: Mapping[str, Any], *, priority: int = 0) -> Dict[str, Any]:
        role = agent_registry().get(agent)
        if role is None or role.kind != "discovery":
            raise ValueError("dispatch_discovery requires a discovery specialist")
        if not isinstance(record, Mapping):
            raise ValueError("record must be a mapping")
        return self.dispatch(agent, {"record": dict(record), "lead": dict(record.get("lead", {})) if isinstance(record.get("lead"), Mapping) else {}, "evidence_events": list(record.get("evidence_events", [])) if isinstance(record.get("evidence_events"), list) else [], "specialization": role.name}, priority=priority)

    def dispatch_social_research(self, agent: str, payload: Mapping[str, Any], *, priority: int = 0) -> Dict[str, Any]:
        role = agent_registry().get(agent)
        if role is None or role.kind != "social_research":
            raise ValueError("dispatch_social_research requires a social research specialist")
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be a mapping")
        return self.dispatch(agent, payload, priority=priority)

    def dispatch_processing(self, agent: str, payload: Mapping[str, Any], *, priority: int = 0) -> Dict[str, Any]:
        role = agent_registry().get(agent)
        if role is None or role.kind != "processing":
            raise ValueError("dispatch_processing requires a processing specialist")
        return self.dispatch(agent, payload, priority=priority)

    def run_agent_once(self, agent: str, *, worker_id: str | None = None, limit: int = 1) -> Dict[str, Any]:
        get_specialization(agent)
        identity = worker_id or f"{self.worker_prefix}:{agent}:{uuid4().hex[:12]}"
        return run_worker_once(self.db, agent, worker_id=identity, limit=limit)

    @staticmethod
    def _max_drain_rounds() -> int:
        raw = os.environ.get("THORIO_AGENT_DRAIN_ROUNDS", "8").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 8
        return max(1, min(value, 32))

    def run_all_once(self, *, limit_per_agent: int = 1, max_rounds: int | None = None) -> Dict[str, Any]:
        """Run specialist work in dependency rounds until the queue stops progressing.

        ``max_rounds`` is an explicit per-invocation bound used by bounded
        production execution. When omitted, the normal environment-configured
        drain limit is retained for continuous operation.
        """
        if limit_per_agent <= 0:
            raise ValueError("limit_per_agent must be greater than zero")
        if max_rounds is not None and max_rounds < 1:
            raise ValueError("max_rounds must be greater than zero")

        rounds: List[Dict[str, Any]] = []
        total_claimed = total_completed = total_failed = 0
        effective_max_rounds = self._max_drain_rounds() if max_rounds is None else max_rounds

        for round_number in range(1, effective_max_rounds + 1):
            queued_agents = {
                str(task.get("agent"))
                for task in pending(self.db)
                if task.get("status") in {None, "queued"} and task.get("agent")
            }
            if not queued_agents:
                break

            results: List[Dict[str, Any]] = []
            for role in ALL_AGENT_ROLES:
                if role.name not in queued_agents:
                    continue
                results.append(self.run_agent_once(role.name, limit=min(limit_per_agent, role.max_concurrency)))

            claimed = sum(int(item.get("claimed_count", 0) or 0) for item in results)
            completed = sum(int(item.get("completed_count", 0) or 0) for item in results)
            failed = sum(int(item.get("failed_count", 0) or 0) for item in results)
            rounds.append({"round": round_number, "claimed_count": claimed, "completed_count": completed, "failed_count": failed, "agents": results})
            total_claimed += claimed
            total_completed += completed
            total_failed += failed

            if claimed == 0:
                break

        remaining = pending(self.db)
        return {
            "agent_count": len(ALL_AGENT_ROLES),
            "claimed_count": total_claimed,
            "completed_count": total_completed,
            "failed_count": total_failed,
            "round_count": len(rounds),
            "drain_complete": not remaining,
            "remaining_queue_count": len(remaining),
            "rounds": rounds,
            "agents": rounds[-1]["agents"] if rounds else [],
        }

    def status(self) -> Dict[str, Any]:
        tasks = pending(self.db)
        by_agent: Dict[str, int] = {role.name: 0 for role in ALL_AGENT_ROLES}
        running_by_agent: Dict[str, int] = {role.name: 0 for role in ALL_AGENT_ROLES}
        for task in tasks:
            agent = task.get("agent")
            if agent in by_agent:
                by_agent[agent] += 1
                if task.get("status") == "running":
                    running_by_agent[agent] += 1
        return {"agent_count": len(ALL_AGENT_ROLES), "pending_count": len(tasks), "queued_by_agent": by_agent, "running_by_agent": running_by_agent}
