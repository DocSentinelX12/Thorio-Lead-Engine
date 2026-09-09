from typing import Any, Dict, Iterable, Optional
import logging

from .pipeline import LeadPipeline
from .discovery_gate import apply_discovery_gate
from .agent_queue import enqueue

logger = logging.getLogger(__name__)


_PRIORITY_MAP = {
    "critical": 3,
    "urgent": 3,
    "high": 2,
    "medium": 1,
    "normal": 1,
    "low": 0,
}


def _queue_priority(value: Any) -> int:
    """Normalize pipeline priority into the integer queue contract."""
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    if text in _PRIORITY_MAP:
        return _PRIORITY_MAP[text]
    try:
        return int(float(text))
    except (TypeError, ValueError):
        logger.warning("Unknown lead priority %r; defaulting to queue priority 0", value)
        return 0


class SourceRunner:
    """Run normalized source records through the existing lead pipeline."""

    def __init__(self, pipeline: LeadPipeline):
        self.pipeline = pipeline

    def process(self, records: Iterable[Dict[str, Any]]) -> Dict[str, int]:
        accepted = 0
        duplicates = 0
        failed = 0
        discovered = 0
        qualified = 0
        research_queued = 0
        agent_tasks_queued = 0

        for record in records:
            discovered += 1
            if not isinstance(record, dict):
                failed += 1
                logger.error(
                    "Lead pipeline rejected non-object source record: type=%s",
                    type(record).__name__,
                )
                continue
            try:
                result = self.pipeline.process(**record)
                result = apply_discovery_gate(self.pipeline, result)
            except Exception:
                failed += 1
                source = str(record.get("source", "unknown"))
                source_id = str(record.get("source_id", "unknown"))
                logger.exception(
                    "Lead pipeline failed while processing source record: source=%s source_id=%s",
                    source,
                    source_id,
                )
                continue

            if result.get("status") == "duplicate":
                duplicates += 1
            elif result.get("accepted") is True:
                accepted += 1

                fingerprint = str(result.get("fingerprint") or "").strip()
                lead = result.get("lead")
                if fingerprint and isinstance(lead, dict):
                    enqueue(
                        self.pipeline.db,
                        "qualification_a",
                        {"lead": dict(lead)},
                        priority=_queue_priority(result.get("priority")),
                        dedupe_key=fingerprint,
                    )
                    agent_tasks_queued += 1

            if result.get("qualification_status") == "qualified":
                qualified += 1
            if result.get("paxus_research_status") == "research_required":
                research_queued += 1

        summary = {
            "discovered_count": discovered,
            "accepted_count": accepted,
            "duplicate_count": duplicates,
            "failed_count": failed,
        }
        if qualified:
            summary["qualified_count"] = qualified
        if research_queued:
            summary["paxus_research_queued_count"] = research_queued
        if agent_tasks_queued:
            summary["agent_tasks_queued_count"] = agent_tasks_queued
        return summary

    def run_source(self, source, checkpoint: Optional[str] = None) -> Dict[str, Any]:
        """Collect one source using the supplied checkpoint."""
        try:
            records = source.collect(checkpoint=checkpoint)
        except TypeError as exc:
            message = str(exc)
            if "checkpoint" not in message or "unexpected keyword argument" not in message:
                raise
            records = source.collect()

        result = self.process(records)
        source_state = getattr(source, "__dict__", {})
        if "last_checkpoint" in source_state:
            result["checkpoint"] = source_state["last_checkpoint"]
        return result


if __name__ == "__main__":
    print("Source runner loaded. Normalized source records can now enter the lead pipeline.")
