import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from .agent_orchestrator import AgentOrchestrator
from .agent_registry import ALL_AGENT_ROLES
from .compute_bridge import bridge_once
from .compute_worker import ComputeWorkerClient
from .database import LeadDB
from .research_queue import process_paxus_research_queue
from .runner import LeadEngineRunner
from .sources import LeadSource
from .sync_worker import sync_pending


class LeadScheduler:
    """Continuous execution layer for lead sources, agents, Paxus research, and free remote specialists."""

    _POLLING_STATE_KEY = "lead_scheduler_polling"

    def __init__(self, runner: LeadEngineRunner):
        self.runner = runner
        from .checkpoint_runner import CheckpointRunner
        self.checkpoint_runner = CheckpointRunner(db=runner.pipeline.db, runner=runner)
        self.agent_orchestrator = AgentOrchestrator(runner.pipeline.db)
        self._next_run_at: Dict[str, float] = {}
        self._persisted_next_run_at: Dict[str, float] = {}
        self._remote_compute = self._remote_client_from_environment()
        self._load_polling_state()

    @staticmethod
    def _remote_client_from_environment() -> Optional[ComputeWorkerClient]:
        url = os.environ.get("THORIO_COMPUTE_COORDINATOR_URL", "").strip()
        token = os.environ.get("THORIO_COMPUTE_AUTH_TOKEN", "").strip()
        if not url and not token:
            return None
        if not url or not token:
            raise RuntimeError("THORIO_COMPUTE_COORDINATOR_URL and THORIO_COMPUTE_AUTH_TOKEN must be configured together")
        parsed = urlparse(url)
        if parsed.scheme == "https":
            pass
        elif parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
            pass
        else:
            raise RuntimeError("THORIO_COMPUTE_COORDINATOR_URL must use HTTPS for non-local remote compute")
        worker_id = os.environ.get("THORIO_WORKER_ID", "scheduler-bridge").strip() or "scheduler-bridge"
        return ComputeWorkerClient(url, token, worker_id, int(os.environ.get("THORIO_COMPUTE_HTTP_TIMEOUT", "20")))

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

    def _collection_workers(self) -> int:
        raw = os.environ.get("THORIO_SOURCE_COLLECTION_WORKERS", "1").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 1
        return max(1, min(value, 16))

    def _collect_source(self, source: LeadSource, checkpoint: str):
        try:
            records = source.collect(checkpoint=checkpoint)
        except TypeError as exc:
            message = str(exc)
            if "checkpoint" not in message or "unexpected keyword argument" not in message:
                raise
            records = source.collect()
        return list(records), getattr(source, "last_checkpoint", checkpoint)

    def _load_polling_state(self) -> None:
        db = getattr(getattr(self.runner, "pipeline", None), "db", None)
        if not isinstance(db, LeadDB):
            return
        state = db.get_state(self._POLLING_STATE_KEY)
        if state is None:
            return
        if not isinstance(state, dict):
            raise RuntimeError("lead scheduler polling state is corrupt")
        persisted = state.get("next_run_at", {})
        if not isinstance(persisted, dict):
            raise RuntimeError("lead scheduler next_run_at state is corrupt")
        for source_key, deadline in persisted.items():
            try:
                self._persisted_next_run_at[str(source_key)] = float(deadline)
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"invalid persisted scheduler deadline for {source_key!r}") from exc

    def _save_polling_state(self) -> None:
        db = getattr(getattr(self.runner, "pipeline", None), "db", None)
        if not isinstance(db, LeadDB):
            return
        db.set_state(self._POLLING_STATE_KEY, {"next_run_at": dict(self._persisted_next_run_at)})

    def _is_due(self, source: LeadSource, now: float, wall_now: Optional[float] = None) -> bool:
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
        if wall_now is None:
            wall_now = time.time()
        return wall_now >= persisted

    def _schedule_next_run(self, source: LeadSource, started_at: float, started_wall: float) -> None:
        interval = self._poll_interval(source)
        key = self._source_key(source)
        if interval <= 0:
            self._next_run_at.pop(key, None)
            self._persisted_next_run_at.pop(key, None)
        else:
            self._next_run_at[key] = started_at + interval
            self._persisted_next_run_at[key] = started_wall + interval
        self._save_polling_state()

    def _agent_batch_limit(self) -> int:
        return max(role.max_concurrency for role in ALL_AGENT_ROLES)

    def _bridge_remote(self, *, publish_limit: int = 20, reconcile_limit: int = 50) -> Dict[str, Any]:
        if self._remote_compute is None:
            return {"status": "disabled", "published_count": 0, "completed_count": 0, "retried_count": 0}
        return bridge_once(self.runner.pipeline.db, self._remote_compute, publish_limit=publish_limit, reconcile_limit=reconcile_limit)

    def _run_without_immediate_sync(self, callback):
        """Run collection processing with Airtable deferred until specialists finish."""
        pipeline = getattr(self.runner, "pipeline", None)
        original = getattr(pipeline, "sync_enabled", None)
        if original is not True:
            return callback()
        pipeline.sync_enabled = False
        try:
            return callback()
        finally:
            pipeline.sync_enabled = original

    def _run_sources_sequential(self, due_sources, results, failed):
        for source, previous_checkpoint, started_at, started_wall in due_sources:
            try:
                result = dict(self._run_without_immediate_sync(
                    lambda: self.checkpoint_runner.run(source=source, checkpoint=previous_checkpoint)
                ))
                failed_count = int(result.get("failed_count", 0) or 0)
                if failed_count != 0:
                    result["checkpoint"] = previous_checkpoint
                results.append({"source": source.name, "result": result})
                self._schedule_next_run(source, started_at, started_wall)
            except Exception as exc:
                failed.append({"source": source.name, "error": str(exc)})
                self._schedule_next_run(source, started_at, started_wall)

    def _run_sources_parallel_collection(self, due_sources, results, failed):
        collected = {}
        workers = min(self._collection_workers(), max(1, len(due_sources)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="source-collector") as executor:
            futures = {
                executor.submit(self._collect_source, source, previous_checkpoint): index
                for index, (source, previous_checkpoint, _started_at, _started_wall) in enumerate(due_sources)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    collected[index] = future.result()
                except Exception as exc:
                    collected[index] = exc

        for index, (source, previous_checkpoint, started_at, started_wall) in enumerate(due_sources):
            collected_value = collected.get(index)
            try:
                if isinstance(collected_value, Exception):
                    raise collected_value
                records, next_checkpoint = collected_value
                result = dict(self._run_without_immediate_sync(
                    lambda: self.runner.process(records)
                ))
                failed_count = int(result.get("failed_count", 0) or 0)
                if failed_count == 0:
                    current_checkpoint = "" if next_checkpoint is None else next_checkpoint
                    self.checkpoint_runner.save_checkpoint(source, current_checkpoint)
                else:
                    current_checkpoint = previous_checkpoint
                result["previous_checkpoint"] = previous_checkpoint
                result["checkpoint"] = current_checkpoint
                results.append({"source": source.name, "result": result})
                self._schedule_next_run(source, started_at, started_wall)
            except Exception as exc:
                failed.append({"source": source.name, "error": str(exc)})
                self._schedule_next_run(source, started_at, started_wall)

    def run(self, sources: Iterable[LeadSource], *, agent_max_rounds: Optional[int] = None) -> Dict[str, Any]:
        results = []
        failed = []
        skipped = []
        source_list = list(sources)
        source_count = len(source_list)
        now = time.monotonic()
        wall_now = time.time()
        due_sources = []
        for source in source_list:
            source_name = source.name
            if not self._is_due(source, now, wall_now):
                skipped.append({"source": source_name, "reason": "not_due"})
                continue
            due_sources.append((source, self.checkpoint_runner.get_checkpoint(source), time.monotonic(), time.time()))

        if self._collection_workers() > 1 and len(due_sources) > 1:
            self._run_sources_parallel_collection(due_sources, results, failed)
        else:
            self._run_sources_sequential(due_sources, results, failed)

        db = self.runner.pipeline.db
        remote_before = self._bridge_remote()
        if agent_max_rounds is None:
            agent_result = self.agent_orchestrator.run_all_once(limit_per_agent=self._agent_batch_limit())
        else:
            agent_result = self.agent_orchestrator.run_all_once(
                limit_per_agent=self._agent_batch_limit(),
                max_rounds=agent_max_rounds,
            )
        remote_after = self._bridge_remote()

        # Airtable is the delivery/approval gate. Defer it until the bounded
        # specialist pass has consumed the freshly persisted discovery queue.
        sync_result = sync_pending(db)
        paxus_research = process_paxus_research_queue(db)
        discovered_total = sum(int(item["result"].get("discovered_count", item["result"].get("total", 0)) or 0) for item in results)
        accepted_total = sum(int(item["result"].get("accepted_count", 0) or 0) for item in results)
        duplicate_total = sum(int(item["result"].get("duplicate_count", 0) or 0) for item in results)
        processing_failed_total = sum(int(item["result"].get("failed_count", 0) or 0) for item in results)
        return {"results": results, "failed": failed, "skipped": skipped, "source_count": source_count, "successful_source_count": len(results), "failed_count": len(failed), "skipped_count": len(skipped), "discovered_count": discovered_total, "accepted_count": accepted_total, "duplicate_count": duplicate_total, "processing_failed_count": processing_failed_total, "sync": sync_result, "remote_compute_before": remote_before, "agents": agent_result, "remote_compute_after": remote_after, "paxus_research": paxus_research}

    def run_forever(self, sources: Iterable[LeadSource], interval_seconds: float = 60.0, max_cycles: Optional[int] = None, *, agent_max_rounds: Optional[int] = None) -> Dict[str, Any]:
        source_list = list(sources)
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be greater than or equal to 0.")
        if max_cycles is not None and max_cycles < 1:
            raise ValueError("max_cycles must be greater than or equal to 1.")
        if agent_max_rounds is not None and agent_max_rounds < 1:
            raise ValueError("agent_max_rounds must be greater than zero")
        if not source_list:
            return {"cycles": 0, "results": [], "failed": [], "skipped": [], "sync": [], "remote_compute": [], "agents": [], "paxus_research": [], "source_count": 0, "successful_source_count": 0, "result_count": 0, "failed_count": 0, "skipped_count": 0, "discovered_count": 0, "accepted_count": 0, "duplicate_count": 0, "processing_failed_count": 0, "status": "no_sources_configured"}
        cycles = 0
        total_results: List[Any] = []
        total_failed: List[Any] = []
        total_skipped: List[Any] = []
        total_sync: List[Any] = []
        total_remote_compute: List[Any] = []
        total_agents: List[Any] = []
        total_paxus_research: List[Any] = []
        total_discovered = total_accepted = total_duplicates = total_processing_failed = 0
        while max_cycles is None or cycles < max_cycles:
            result = self.run(source_list, agent_max_rounds=agent_max_rounds)
            total_results.extend(result["results"])
            total_failed.extend(result["failed"])
            total_skipped.extend(result.get("skipped", []))
            total_sync.append(result["sync"])
            total_remote_compute.append({"before": result.get("remote_compute_before"), "after": result.get("remote_compute_after")})
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
        return {"cycles": cycles, "results": total_results, "failed": total_failed, "skipped": total_skipped, "sync": total_sync, "remote_compute": total_remote_compute, "agents": total_agents, "paxus_research": total_paxus_research, "source_count": len(source_list), "successful_source_count": len(total_results), "result_count": len(total_results), "failed_count": len(total_failed), "skipped_count": len(total_skipped), "discovered_count": total_discovered, "accepted_count": total_accepted, "duplicate_count": total_duplicates, "processing_failed_count": total_processing_failed, "status": "completed"}

    def run_bounded(self, sources: Iterable[LeadSource], interval_seconds: float = 60.0, max_cycles: int = 10) -> Dict[str, Any]:
        if max_cycles < 1:
            raise ValueError("max_cycles must be greater than or equal to 1.")
        source_list = list(sources)
        for source in source_list:
            key = self._source_key(source)
            self._next_run_at.pop(key, None)
            self._persisted_next_run_at.pop(key, None)
        self._save_polling_state()
        return self.run_forever(
            sources=source_list,
            interval_seconds=interval_seconds,
            max_cycles=max_cycles,
            agent_max_rounds=1,
        )
