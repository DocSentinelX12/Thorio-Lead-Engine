import time
from typing import Any, Dict, Iterable, List, Optional

from .agent_orchestrator import AgentOrchestrator
from .agent_registry import ALL_AGENT_ROLES
from .checkpoint_runner import CheckpointRunner
from .research_queue import process_paxus_research_queue
from .runner import LeadEngineRunner
from .sources import LeadSource
from .sync_worker import sync_pending


class LeadScheduler:
    """Continuous execution layer for lead sources, agents, and Paxus research."""

    _POLLING_STATE_KEY = "lead_scheduler_polling"

    def __init__(self, runner: LeadEngineRunner):
        self.runner = runner
        self.checkpoint_runner = CheckpointRunner(db=runner.pipeline.db, runner=runner)
        self.agent_orchestrator = AgentOrchestrator(runner.pipeline.db)
        self._next_run_at: Dict[str, float] = {}
        self._persisted_next_run_at: Dict[str, float] = {}
        self._load_polling_state()

    def _source_key(self, source: LeadSource) -> str:
        definition = getattr(source, "definition", None)
        if definition is not None:
            source_key = getattr(definition, "source_key", None)
            if source_key:
                return str(source_key)
        return str(source.name)

    def _poll_interval(self, source: LeadSource) -> float:
        definition = getattr(source, "definition", None)
        if definition is None:
            return 0.0
        try:
            interval = float(getattr(definition, "poll_interval_seconds", 0))
        except (TypeError, ValueError):
            return 0.0
        return interval if interval > 0 else 0.0

    def _load_polling_state(self) -> None:
        try:
            state = self.runner.pipeline.db.get_state(self._POLLING_STATE_KEY)
        except Exception:
            return
        if not isinstance(state, dict):
            return
        persisted = state.get("next_run_at")
        if not isinstance(persisted, dict):
            return
        for source_key, deadline in persisted.items():
            try:
                self._persisted_next_run_at[str(source_key)] = float(deadline)
            except (TypeError, ValueError):
                continue

    def _save_polling_state(self) -> None:
        try:
            self.runner.pipeline.db.set_state(self._POLLING_STATE_KEY, {"next_run_at": dict(self._persisted_next_run_at)})
        except Exception:
            return

    def _is_due(self, source: LeadSource, now: float) -> bool:
        interval = self._poll_interval(source)
        if interval <= 0:
            return True
        key = self._source_key(source)
        next_run_at = self._next_run_at.get(key)
        if next_run_at is not None:
            return now >= next_run_at
        persisted = self._persisted_next_run_at.get(key)
        if persisted is None:
            return True
        return time.time() >= persisted

    def _schedule_next_run(self, source: LeadSource, started_at: float, started_wall: float) -> None:
        interval = self._poll_interval(source)
        key = self._source_key(source)
        if interval <= 0:
            self._next_run_at.pop(key, None)
            self._persisted_next_run_at.pop(key, None)
            self._save_polling_state()
            return
        self._next_run_at[key] = started_at + interval
        self._persisted_next_run_at[key] = started_wall + interval
        self._save_polling_state()

    def _agent_batch_limit(self) -> int:
        """Use the registry's declared capacity instead of processing one task."""
        return max(role.max_concurrency for role in ALL_AGENT_ROLES)

    def run(self, sources: Iterable[LeadSource]) -> Dict[str, Any]:
        results = []
        failed = []
        skipped = []
        source_list = list(sources)
        source_count = len(source_list)
        now = time.monotonic()

        for source in source_list:
            source_name = source.name
            if not self._is_due(source, now):
                skipped.append({"source": source_name, "reason": "not_due"})
                continue

            started_at = time.monotonic()
            started_wall = time.time()
            try:
                previous_checkpoint = self.checkpoint_runner.get_checkpoint(source)
                result = dict(self.checkpoint_runner.run(source=source, checkpoint=previous_checkpoint))
                failed_count = result.get("failed_count", 0)
                try:
                    failed_count = int(failed_count or 0)
                except (TypeError, ValueError):
                    failed_count = 1
                if failed_count != 0:
                    result["checkpoint"] = previous_checkpoint
                results.append({"source": source_name, "result": result})
                self._schedule_next_run(source, started_at, started_wall)
            except Exception as exc:
                failed.append({"source": source_name, "error": str(exc)})
                self._schedule_next_run(source, started_at, started_wall)

        db = self.runner.pipeline.db
        sync_result = sync_pending(db)

        try:
            agent_result = self.agent_orchestrator.run_all_once(
                limit_per_agent=self._agent_batch_limit()
            )
        except Exception as exc:
            agent_result = {
                "agent_count": 0,
                "claimed_count": 0,
                "completed_count": 0,
                "failed_count": 1,
                "error": str(exc),
            }

        try:
            paxus_research = process_paxus_research_queue(db)
        except Exception as exc:
            paxus_research = {
                "status": "failed",
                "processed": [],
                "completed": [],
                "still_required": [],
                "errors": [{"error": str(exc)}],
                "queued_count": len(db.pending_research(1_000_000)),
            }

        discovered_total = sum(int(item["result"].get("discovered_count", item["result"].get("total", 0)) or 0) for item in results)
        accepted_total = sum(int(item["result"].get("accepted_count", 0) or 0) for item in results)
        duplicate_total = sum(int(item["result"].get("duplicate_count", 0) or 0) for item in results)
        processing_failed_total = sum(int(item["result"].get("failed_count", 0) or 0) for item in results)

        return {
            "results": results,
            "failed": failed,
            "skipped": skipped,
            "source_count": source_count,
            "successful_source_count": len(results),
            "failed_count": len(failed),
            "skipped_count": len(skipped),
            "discovered_count": discovered_total,
            "accepted_count": accepted_total,
            "duplicate_count": duplicate_total,
            "processing_failed_count": processing_failed_total,
            "sync": sync_result,
            "agents": agent_result,
            "paxus_research": paxus_research,
        }

    def run_forever(self, sources: Iterable[LeadSource], interval_seconds: float = 60.0, max_cycles: Optional[int] = None) -> Dict[str, Any]:
        source_list = list(sources)
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be greater than or equal to 0.")
        if max_cycles is not None and max_cycles < 1:
            raise ValueError("max_cycles must be greater than or equal to 1.")
        if not source_list:
            return {"cycles": 0, "results": [], "failed": [], "skipped": [], "sync": [], "agents": [], "paxus_research": [], "source_count": 0, "successful_source_count": 0, "result_count": 0, "failed_count": 0, "skipped_count": 0, "discovered_count": 0, "accepted_count": 0, "duplicate_count": 0, "processing_failed_count": 0, "status": "no_sources_configured"}

        cycles = 0
        total_results = []
        total_failed = []
        total_skipped = []
        total_sync = []
        total_agents = []
        total_paxus_research = []
        total_discovered = total_accepted = total_duplicates = total_processing_failed = 0

        while max_cycles is None or cycles < max_cycles:
            result = self.run(source_list)
            total_results.extend(result["results"])
            total_failed.extend(result["failed"])
            total_skipped.extend(result.get("skipped", []))
            total_sync.append(result["sync"])
            total_agents.append(result["agents"])
            total_paxus_research.append(result["paxus_research"])
            total_discovered += result.get("discovered_count", 0)
            total_accepted += result.get("accepted_count", 0)
            total_duplicates += result.get("duplicate_count", 0)
            total_processing_failed += result.get("processing_failed_count", 0)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            if interval_seconds:
                time.sleep(interval_seconds)

        return {"cycles": cycles, "results": total_results, "failed": total_failed, "skipped": total_skipped, "sync": total_sync, "agents": total_agents, "paxus_research": total_paxus_research, "source_count": len(source_list), "successful_source_count": len(total_results), "result_count": len(total_results), "failed_count": len(total_failed), "skipped_count": len(total_skipped), "discovered_count": total_discovered, "accepted_count": total_accepted, "duplicate_count": total_duplicates, "processing_failed_count": total_processing_failed, "status": "completed"}

    def run_bounded(self, sources: Iterable[LeadSource], interval_seconds: float = 60.0, max_cycles: int = 10) -> Dict[str, Any]:
        if max_cycles < 1:
            raise ValueError("max_cycles must be greater than or equal to 1.")
        return self.run_forever(sources=sources, interval_seconds=interval_seconds, max_cycles=max_cycles)
