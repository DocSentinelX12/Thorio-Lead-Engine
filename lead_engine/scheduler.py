import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from .agent_orchestrator import AgentOrchestrator
from .agent_registry import ALL_AGENT_ROLES
from .batch_delivery import sync_pending_batched
from .airtable_drain_override import drain_pending
from .compute_bridge import bridge_once
from .compute_worker import ComputeWorkerClient
from .database import LeadDB
from .revenue_conversation import enqueue_due_followups
from .research_queue import process_paxus_research_queue
from .handoff_recovery import recover_processing_handoffs
from .runner import LeadEngineRunner
from .sources import LeadSource
from .source_collection_metrics import record_source_collection_metrics

sync_pending = sync_pending_batched


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
        return max(1, min(value, 64))

    def _agent_drain_rounds(self) -> int:
        raw = os.environ.get("THORIO_AGENT_DRAIN_ROUNDS", "4").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 4
        return max(1, min(value, 32))

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

    @staticmethod
    def _source_collection_metrics_input(result: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize legacy scheduler summaries to collection telemetry counts."""
        processed = int(result.get("processed_count", 0) or 0)
        discovered = int(result.get("discovered_count", result.get("total", processed)) or 0)
        accepted = int(result.get("accepted_count", processed) or 0)
        return {
            "discovered_count": discovered,
            "accepted_count": accepted,
            "duplicate_count": int(result.get("duplicate_count", 0) or 0),
            "failed_count": int(result.get("failed_count", 0) or 0),
        }

    def _record_source_metrics(self, source: LeadSource, result: Dict[str, Any]) -> Dict[str, Any] | None:
        db = getattr(getattr(self.runner, "pipeline", None), "db", None)
        if not isinstance(db, LeadDB):
            return None
        return record_source_collection_metrics(
            db,
            source.name,
            self._source_collection_metrics_input(result),
        )

    def _agent_batch_limit(self) -> int:
        return max(role.max_concurrency for role in ALL_AGENT_ROLES)

    def _bridge_remote(self, *, publish_limit: int = 20, reconcile_limit: int = 50) -> Dict[str, Any]:
        if self._remote_compute is None:
            return {"status": "disabled", "published_count": 0, "completed_count": 0, "retried_count": 0}
        return bridge_once(self.runner.pipeline.db, self._remote_compute, publish_limit=publish_limit, reconcile_limit=reconcile_limit)

    def _run_without_immediate_sync(self, callback):
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
                result = dict(self._run_without_immediate_sync(lambda: self.checkpoint_runner.run(source=source, checkpoint=previous_checkpoint)))
                failed_count = int(result.get("failed_count", 0) or 0)
                if failed_count != 0:
                    result["checkpoint"] = previous_checkpoint
                source_metrics = self._record_source_metrics(source, result)
                result["source_collection_metrics"] = source_metrics
                results.append({"source": source.name, "result": result})
                self._schedule_next_run(source, started_at, started_wall)
            except Exception as exc:
                failed.append({"source": source.name, "error": str(exc)})
                self._schedule_next_run(source, started_at, started_wall)

    def _run_sources_parallel_collection(self, due_sources, results, failed):
        collected = {}
        workers = min(self._collection_workers(), max(1, len(due_sources)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="source-collector") as executor:
            futures = {executor.submit(self._collect_source, source, previous_checkpoint): index for index, (source, previous_checkpoint, _started_at, _started_wall) in enumerate(due_sources)}
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
                result = dict(self._run_without_immediate_sync(lambda: self.runner.process(records)))
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
        sync_started_at = datetime.now(timezone.utc).isoformat()
        remote_before = self._bridge_remote()
        due_followups = enqueue_due_followups(db)
        revenue_inbound_health = db.get_state("revenue_inbound_health") if hasattr(db, "get_state") else None
        handoff_recovery = recover_processing_handoffs(db)
        if agent_max_rounds is None:
            agent_result = self.agent_orchestrator.run_all_once(limit_per_agent=self._agent_batch_limit())
        else:
            agent_result = self.agent_orchestrator.run_all_once(limit_per_agent=self._agent_batch_limit(), max_rounds=agent_max_rounds)
        remote_after = self._bridge_remote()
        paxus_research = process_paxus_research_queue(db)
        sync_result = drain_pending(db, sync_batch=sync_pending)
        post_sync_agents = None
        if int(sync_result.get("synced_count", 0) or 0) or int(sync_result.get("already_exists_count", 0) or 0):
            if agent_max_rounds is None:
                post_sync_agents = self.agent_orchestrator.run_all_once(limit_per_agent=self._agent_batch_limit())
            else:
                post_sync_agents = self.agent_orchestrator.run_all_once(limit_per_agent=self._agent_batch_limit(), max_rounds=self._agent_drain_rounds())
        discovered_total = sum(int(item["result"].get("discovered_count", item["result"].get("total", 0)) or 0) for item in results)
        accepted_total = sum(int(item["result"].get("accepted_count", 0) or 0) for item in results)
        duplicate_total = sum(int(item["result"].get("duplicate_count", 0) or 0) for item in results)
        processing_failed_total = sum(int(item["result"].get("failed_count", 0) or 0) for item in results)

        # Persist operational telemetry only after the bounded cycle has
        # produced its authoritative aggregate result.
        db = self.runner.pipeline.db
        checked_at = datetime.now(timezone.utc).isoformat()
        source_started_wall_times = [item[3] for item in due_sources]
        latest_source_started_at = (
            datetime.fromtimestamp(max(source_started_wall_times), timezone.utc).isoformat()
            if source_started_wall_times
            else None
        )

        source_state = db.get_state("source_observability") if hasattr(db, "get_state") else {}
        source_state = dict(source_state) if isinstance(source_state, dict) else {}
        db.set_state(
            "source_observability",
            {
                **source_state,
                "sources_started": int(source_state.get("sources_started", 0) or 0) + len(due_sources),
                "sources_completed": int(source_state.get("sources_completed", 0) or 0) + len(results),
                "sources_failed": int(source_state.get("sources_failed", 0) or 0) + len(failed),
                "last_source": results[-1]["source"] if results else None,
                "last_source_started_at": latest_source_started_at if due_sources else source_state.get("last_source_started_at"),
                "last_source_completed_at": checked_at if results else source_state.get("last_source_completed_at"),
                "last_source_failure_at": checked_at if failed else source_state.get("last_source_failure_at"),
                "last_source_error": (failed[-1].get("error") if failed else None),
                "last_source_record_count": int(results[-1]["result"].get("discovered_count", results[-1]["result"].get("total", 0)) or 0) if results else 0,
            },
        )

        sync_state = db.get_state("sync_observability") if hasattr(db, "get_state") else {}
        sync_state = dict(sync_state) if isinstance(sync_state, dict) else {}
        sync_failed = int(sync_result.get("failed_count", 0) or 0)
        sync_successes = int(sync_result.get("synced_count", 0) or 0) + int(sync_result.get("already_exists_count", 0) or 0)
        failed_items = sync_result.get("failed")
        failed_items = failed_items if isinstance(failed_items, list) else []
        first_sync_error = failed_items[0].get("error") if failed_items and isinstance(failed_items[0], dict) else None
        db.set_state(
            "sync_observability",
            {
                **sync_state,
                "sync_runs": int(sync_state.get("sync_runs", 0) or 0) + 1,
                "successful_sync_runs": int(sync_state.get("successful_sync_runs", 0) or 0) + (1 if sync_failed == 0 else 0),
                "failed_sync_runs": int(sync_state.get("failed_sync_runs", 0) or 0) + (1 if sync_failed > 0 else 0),
                "last_sync_started_at": sync_started_at,
                "last_sync_completed_at": checked_at,
                "last_successful_sync": checked_at if sync_failed == 0 else sync_state.get("last_successful_sync"),
                "last_sync_failure": checked_at if sync_failed > 0 else sync_state.get("last_sync_failure"),
                "last_sync_error": first_sync_error if sync_failed > 0 else None,
                "last_sync_processed_count": int(sync_result.get("synced_count", 0) or 0) + int(sync_result.get("already_exists_count", 0) or 0) + int(sync_result.get("failed_count", 0) or 0) + int(sync_result.get("deferred_research_count", 0) or 0),
                "last_sync_success_count": sync_successes,
                "last_sync_failure_count": sync_failed,
            },
        )

        return {"results": results, "failed": failed, "skipped": skipped, "source_count": source_count, "successful_source_count": len(results), "failed_count": len(failed), "skipped_count": len(skipped), "discovered_count": discovered_total, "accepted_count": accepted_total, "duplicate_count": duplicate_total, "processing_failed_count": processing_failed_total, "sync": sync_result, "agents": agent_result, "post_sync_agents": post_sync_agents, "due_followups_enqueued": due_followups, "revenue_inbound_health": revenue_inbound_health, "remote_compute_before": remote_before, "remote_compute_after": remote_after, "paxus_research": paxus_research, "handoff_recovery": handoff_recovery}

    def run_bounded(self, sources: Iterable[LeadSource], interval_seconds: float = 60.0, max_cycles: int = 1) -> Dict[str, Any]:
        """Run a finite production window and force each supplied source through its bounded cycles."""
        source_list = list(sources)
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be greater than or equal to 0.")
        if max_cycles < 1:
            raise ValueError("max_cycles must be greater than or equal to 1.")
        if not source_list:
            return {"status": "completed", "cycles": 0, "results": [], "source_count": 0, "successful_source_count": 0, "failed_count": 0, "skipped_count": 0, "discovered_count": 0, "accepted_count": 0, "duplicate_count": 0, "processing_failed_count": 0}
        cycle_results = []
        for cycle_index in range(max_cycles):
            for source in source_list:
                key = self._source_key(source)
                self._next_run_at[key] = 0.0
            cycle_results.append(self.run(source_list, agent_max_rounds=self._agent_drain_rounds()))
            if cycle_index + 1 < max_cycles:
                time.sleep(interval_seconds)
        if len(cycle_results) == 1:
            result = dict(cycle_results[0])
        else:
            result = {
                "results": [item for cycle in cycle_results for item in cycle["results"]],
                "failed": [item for cycle in cycle_results for item in cycle["failed"]],
                "skipped": [item for cycle in cycle_results for item in cycle["skipped"]],
                "source_count": len(source_list),
                "successful_source_count": sum(cycle["successful_source_count"] for cycle in cycle_results),
                "failed_count": sum(cycle["failed_count"] for cycle in cycle_results),
                "skipped_count": sum(cycle["skipped_count"] for cycle in cycle_results),
                "discovered_count": sum(cycle["discovered_count"] for cycle in cycle_results),
                "accepted_count": sum(cycle["accepted_count"] for cycle in cycle_results),
                "duplicate_count": sum(cycle["duplicate_count"] for cycle in cycle_results),
                "processing_failed_count": sum(cycle["processing_failed_count"] for cycle in cycle_results),
                "sync": [cycle["sync"] for cycle in cycle_results],
                "agents": [cycle["agents"] for cycle in cycle_results],
                "due_followups_enqueued": sum(int(cycle.get("due_followups_enqueued", 0) or 0) for cycle in cycle_results),
                "remote_compute_before": [cycle["remote_compute_before"] for cycle in cycle_results],
                "remote_compute_after": [cycle["remote_compute_after"] for cycle in cycle_results],
                "paxus_research": [cycle["paxus_research"] for cycle in cycle_results],
            }
        sync_failures = sum(
            int(cycle.get("sync", {}).get("failed_count", 0) or 0)
            if isinstance(cycle.get("sync"), dict)
            else sum(int(item.get("failed_count", 0) or 0) for item in cycle.get("sync", []) if isinstance(item, dict))
            for cycle in cycle_results
        )
        agent_failures = sum(
            int(cycle.get("agents", {}).get("failed_count", 0) or 0)
            if isinstance(cycle.get("agents"), dict)
            else sum(int(item.get("failed_count", 0) or 0) for item in cycle.get("agents", []) if isinstance(item, dict))
            for cycle in cycle_results
        )
        post_sync_agent_failures = sum(
            int(cycle.get("post_sync_agents", {}).get("failed_count", 0) or 0)
            if isinstance(cycle.get("post_sync_agents"), dict)
            else sum(int(item.get("failed_count", 0) or 0) for item in cycle.get("post_sync_agents", []) if isinstance(item, dict))
            for cycle in cycle_results
            if cycle.get("post_sync_agents") is not None
        )
        result["sync_failed_count"] = sync_failures
        result["agent_failed_count"] = agent_failures
        result["post_sync_agent_failed_count"] = post_sync_agent_failures
        result["status"] = (
            "failed"
            if int(result.get("failed_count", 0) or 0)
            or int(result.get("processing_failed_count", 0) or 0)
            or sync_failures
            or agent_failures
            or post_sync_agent_failures
            else "completed"
        )
        result["cycles"] = max_cycles
        return result

    def run_forever(self, sources: Iterable[LeadSource], interval_seconds: float = 60.0, max_cycles: Optional[int] = None, *, agent_max_rounds: Optional[int] = None) -> Dict[str, Any]:
        source_list = list(sources)
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be greater than or equal to 0.")
        if max_cycles is not None and max_cycles < 1:
            raise ValueError("max_cycles must be greater than or equal to 1.")
        cycles = 0
        failed = False
        last_result: Dict[str, Any] = {}
        while max_cycles is None or cycles < max_cycles:
            last_result = self.run(source_list, agent_max_rounds=agent_max_rounds)
            cycles += 1
            if last_result.get("failed_count") or last_result.get("processing_failed_count"):
                failed = True
            sync = last_result.get("sync")
            if isinstance(sync, dict) and int(sync.get("failed_count", 0) or 0):
                failed = True
            agents = last_result.get("agents")
            if isinstance(agents, dict) and int(agents.get("failed_count", 0) or 0):
                failed = True
            post_sync_agents = last_result.get("post_sync_agents")
            if isinstance(post_sync_agents, dict) and int(post_sync_agents.get("failed_count", 0) or 0):
                failed = True
            if max_cycles is None or cycles < max_cycles:
                time.sleep(interval_seconds)
        return {"status": "failed" if failed else "completed", "cycles": cycles}
