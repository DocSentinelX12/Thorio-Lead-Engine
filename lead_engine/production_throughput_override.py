from __future__ import annotations

import os


def install() -> None:
    """Increase bounded production specialist draining without changing role semantics."""
    from .scheduler import LeadScheduler

    if getattr(LeadScheduler, "_production_throughput_override", False):
        return

    original = LeadScheduler._agent_drain_rounds

    def _agent_drain_rounds(self) -> int:
        configured = int(original(self))
        # Production currently supplies a conservative four-round setting. Real
        # research is network-bound, so give the durable queue enough dependency
        # rounds to advance research in the same cycle while preserving the
        # configured upper bound of 32.
        if os.environ.get("LEAD_ENGINE_SYNC_ENABLED", "").strip().lower() == "true":
            return max(12, min(configured, 32))
        return configured

    LeadScheduler._agent_drain_rounds = _agent_drain_rounds
    LeadScheduler._production_throughput_override = True
