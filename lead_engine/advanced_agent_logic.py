from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping

from .agent_queue import enqueue_many


def _source_signal(agent: str, payload: Mapping[str, Any], db: Any = None) -> Dict[str, Any]:
    record = dict(payload.get("record", payload)) if isinstance(payload.get("record", payload), Mapping) else {}
    signal = str(record.get("signal") or record.get("evidence") or "").strip()
    if not signal:
        raise OutreachContractError(f"{agent} requires observed signal/evidence")
    fingerprint = str(record.get("fingerprint") or payload.get("fingerprint") or "").strip()
    lead = db.get(fingerprint) if db is not None and fingerprint else None
    normalized = dict(record)
    normalized["source_lane"] = agent
    normalized["observed"] = True
    normalized["qualification_performed"] = False
    provenance = dict(record.get("provenance") or {}) if isinstance(record.get("provenance"), Mapping) else {}
    provenance.update({"collector_agent": agent, "source_lane": agent, "collected_at": datetime.now(timezone.utc).isoformat()})
    normalized["provenance"] = provenance
    handoffs = []
    if fingerprint and lead is not None and db is not None:
        tasks = [
            {
                "agent": "qualification_a",
                "payload": {"lead": dict(lead), "evidence_events": [normalized], "discovery_agent": agent},
                "priority": 1,
                "dedupe_key": f"qualification_a:{fingerprint}",
            }
        ]
        handoffs.append("qualification_a")

        # Build the complete fan-out first, then persist the queue once.
        # The previous per-agent enqueue calls rewrote the entire JSON queue
        # state for every handoff and could stall production on large queues.
        for discovery_agent in DISCOVERY_TARGETS:
            tasks.append({
                "agent": discovery_agent,
                "payload": {"lead": dict(lead), "evidence_events": [normalized], "source_lane": agent},
                "priority": 3,
                "dedupe_key": f"{discovery_agent}:{fingerprint}:{agent}",
            })
            handoffs.append(discovery_agent)

        if agent != "web_job_signal":
            for social_agent in SOCIAL_TARGETS:
                tasks.append({
                    "agent": social_agent,
                    "payload": {"lead": dict(lead), "evidence_events": [normalized], "discovery_agent": agent},
                    "priority": 3,
                    "dedupe_key": f"{social_agent}:{fingerprint}:{agent}",
                })
                handoffs.append(social_agent)

        enqueue_many(db, tasks)

    return {"agent": agent, "role": "discovery", "source": record.get("source") or _SOURCE_SIGNAL_ALIASES.get(agent, agent), "source_lane": agent, "record": normalized, "observed": True, "qualification_performed": False, "handoffs": handoffs, "handoff": handoffs[0] if handoffs else "awaiting_persistence", "provenance": provenance}
