import argparse
import faulthandler
import json
import os
import signal
import threading
import time

from .application import create_application
from .browser_discovery import configured_browser_discovery_sources
from .discovery_collectors import configured_discovery_sources
from .export import export_pending_leads
from .json_source import JsonLeadSource
from .runtime_lock import RuntimeLock
from .scheduler import LeadScheduler
from .production_research_gate import ProductionResearchGateError, validate_production_research_gate
from .source_registry import configured_sources
from .sync_worker import sync_pending

DEFAULT_SCHEDULE_INTERVAL = 60.0
DEFAULT_SCHEDULE_CYCLES = 10
DEFAULT_PRODUCTION_MAX_SECONDS = 720.0


def build_parser():
    parser = argparse.ArgumentParser(description="Thorio Lead Engine")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Show lead engine status.")
    subparsers.add_parser("health", help="Run lead engine health checks.")
    subparsers.add_parser("poll-approvals", help="Poll Airtable for human approval changes.")
    subparsers.add_parser("work-queue", help="Show the current human work queue.")
    subparsers.add_parser("run", help="Run all configured lead-discovery sources once.")
    scheduled_parser = subparsers.add_parser("run-scheduled", help="Run configured sources continuously for a bounded execution window.")
    scheduled_parser.add_argument("--interval", type=float, default=DEFAULT_SCHEDULE_INTERVAL, help="Seconds between source cycles.")
    scheduled_parser.add_argument("--cycles", type=int, default=DEFAULT_SCHEDULE_CYCLES, help="Number of source cycles to complete.")
    scheduled_parser.add_argument("--forever", action="store_true", help="Continue until the process is externally stopped.")
    import_parser = subparsers.add_parser("import-json", help="Import leads from a JSON file.")
    import_parser.add_argument("path", help="Path to the JSON lead file.")
    run_parser = subparsers.add_parser("run-json", help="Run a JSON lead source through the complete pipeline.")
    run_parser.add_argument("path", help="Path to the JSON lead source file.")
    export_parser = subparsers.add_parser("export-json", help="Export pending local leads to JSON.")
    export_parser.add_argument("path", help="Destination JSON file.")
    return parser


def _sync_pending_if_enabled(application):
    config = getattr(application, "config", None)
    if config is None or getattr(config, "sync_enabled", False) is not True:
        return None
    batch_size = getattr(config, "batch_size", None)
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size <= 0:
        batch_size = 50
    db = getattr(application, "db", None)
    if db is None:
        return None
    return sync_pending(db, limit=batch_size)


def _configured_runtime_sources():
    """Combine existing sources with free authenticated browser and API lanes."""
    if os.environ.get("THORIO_FREE_ONLY", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError("THORIO_FREE_ONLY must remain enabled; paid collection paths are prohibited")

    sources = list(configured_sources())
    discovery = list(configured_discovery_sources(required=False))
    browser = list(configured_browser_discovery_sources())
    existing = {str(getattr(source, "name", "")).strip().casefold() for source in sources}
    for source in discovery + browser:
        key = source.name.strip().casefold()
        if key not in existing:
            sources.append(source)
            existing.add(key)
    return sources


def _instrument_scheduler(scheduler):
    """Emit explicit production phase boundaries without changing scheduler behavior."""
    original_collection = scheduler._run_sources_parallel_collection
    original_sequential = scheduler._run_sources_sequential
    original_bridge = scheduler._bridge_remote
    original_agents = scheduler.agent_orchestrator.run_all_once

    def collection(*args, **kwargs):
        print("PRODUCTION PHASE: source collection and record processing started.", flush=True)
        started = time.monotonic()
        result = original_collection(*args, **kwargs)
        print(f"PRODUCTION PHASE: source collection and record processing finished in {time.monotonic() - started:.1f}s.", flush=True)
        return result

    def sequential(*args, **kwargs):
        print("PRODUCTION PHASE: sequential source collection and record processing started.", flush=True)
        started = time.monotonic()
        result = original_sequential(*args, **kwargs)
        print(f"PRODUCTION PHASE: sequential source collection and record processing finished in {time.monotonic() - started:.1f}s.", flush=True)
        return result

    def bridge(*args, **kwargs):
        print("PRODUCTION PHASE: remote compute bridge started.", flush=True)
        started = time.monotonic()
        result = original_bridge(*args, **kwargs)
        print(f"PRODUCTION PHASE: remote compute bridge finished in {time.monotonic() - started:.1f}s.", flush=True)
        return result

    def agents(*args, **kwargs):
        print("PRODUCTION PHASE: specialist workforce drain started.", flush=True)
        started = time.monotonic()
        result = original_agents(*args, **kwargs)
        print(f"PRODUCTION PHASE: specialist workforce drain finished in {time.monotonic() - started:.1f}s.", flush=True)
        return result

    scheduler._run_sources_parallel_collection = collection
    scheduler._run_sources_sequential = sequential
    scheduler._bridge_remote = bridge
    scheduler.agent_orchestrator.run_all_once = agents
    return scheduler


def _run_scheduled_with_lock(application, sources, interval_seconds, max_cycles, forever=False):
    lock_path = application.config.database_dir
    lock = RuntimeLock(str(__import__("pathlib").Path(lock_path) / "engine.lock"))
    if not lock.acquire():
        raise RuntimeError("Lead Engine is already running.")
    try:
        scheduler = _instrument_scheduler(LeadScheduler(application.service.runner))
        print(f"PRODUCTION START: {len(sources)} runtime source lanes loaded; interval={interval_seconds}s; cycles={'forever' if forever else max_cycles}.", flush=True)
        if forever:
            return scheduler.run_forever(sources=sources, interval_seconds=interval_seconds, max_cycles=None)
        return scheduler.run_bounded(sources=sources, interval_seconds=interval_seconds, max_cycles=max_cycles)
    finally:
        lock.release()


def _install_production_diagnostics():
    """Bound production runs and make hangs diagnostically actionable."""
    enabled = os.environ.get("THORIO_PRODUCTION_DIAGNOSTICS", "1").strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return None

    started = time.monotonic()
    stop_event = threading.Event()
    try:
        max_seconds = float(os.environ.get("THORIO_PRODUCTION_MAX_SECONDS", str(DEFAULT_PRODUCTION_MAX_SECONDS)))
    except (TypeError, ValueError):
        max_seconds = DEFAULT_PRODUCTION_MAX_SECONDS
    if max_seconds <= 0:
        max_seconds = DEFAULT_PRODUCTION_MAX_SECONDS

    def dump_stack(_signum, _frame):
        elapsed = time.monotonic() - started
        print(f"PRODUCTION STACK DUMP: requested after {elapsed:.0f}s; dumping all Python thread stacks.", flush=True)
        faulthandler.dump_traceback()

    def on_term(signum, _frame):
        elapsed = time.monotonic() - started
        print(f"PRODUCTION TERMINATION: received signal {signum} after {elapsed:.0f}s; dumping all Python thread stacks before exit.", flush=True)
        faulthandler.dump_traceback()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGUSR1, dump_stack)
    previous_term = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, on_term)

    def heartbeat():
        while not stop_event.wait(30.0):
            elapsed = time.monotonic() - started
            print(f"PRODUCTION HEARTBEAT: scheduler process is alive after {elapsed:.0f}s; bounded execution budget is {max_seconds:.0f}s.", flush=True)

    def watchdog():
        if stop_event.wait(max_seconds):
            return
        elapsed = time.monotonic() - started
        print(f"PRODUCTION TIME BUDGET EXCEEDED: no bounded cycle completed within {max_seconds:.0f}s. Capturing Python thread stacks and terminating honestly.", flush=True)
        faulthandler.dump_traceback()
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=heartbeat, name="production-heartbeat", daemon=True).start()
    threading.Thread(target=watchdog, name="production-watchdog", daemon=True).start()

    def cleanup():
        stop_event.set()
        signal.signal(signal.SIGTERM, previous_term)

    return cleanup


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    application = create_application()

    if args.command == "status":
        result = application.status()
    elif args.command == "health":
        result = application.health()
    elif args.command == "poll-approvals":
        result = application.poll_approvals()
    elif args.command == "work-queue":
        result = application.work_queue()
    elif args.command == "run":
        result = application.run_sources(_configured_runtime_sources())
        sync_result = _sync_pending_if_enabled(application)
        if sync_result is not None:
            result["sync"] = sync_result
    elif args.command == "run-scheduled":
        cleanup = _install_production_diagnostics()
        try:
            result = _run_scheduled_with_lock(application, _configured_runtime_sources(), args.interval, args.cycles, args.forever)
        finally:
            if cleanup is not None:
                cleanup()
    elif args.command in {"import-json", "run-json"}:
        result = application.run_sources([JsonLeadSource(args.path)])
        sync_result = _sync_pending_if_enabled(application)
        if sync_result is not None:
            result["sync"] = sync_result
    elif args.command == "export-json":
        result = export_pending_leads(application.db, args.path)
    else:
        parser.error(f"Unknown command: {args.command}")

    if args.command == "run-scheduled" and not args.forever:
        try:
            research_gate = validate_production_research_gate(application.db)
            result["research_closer_gate"] = research_gate
            print(
                f"PRODUCTION RESEARCH/CLOSER GATE VERIFIED: complete_research={research_gate['research_complete_checked']}, sales_eligible={research_gate['sales_eligible_checked']}, pending_closer_tasks={research_gate['closer_tasks_pending']}.",
                flush=True,
            )
        except ProductionResearchGateError as exc:
            print(str(exc), flush=True)
            return 1

        if result.get("status") not in {"completed", "sync_disabled"}:
            sync_summary = result.get("sync") if isinstance(result.get("sync"), dict) else {}
            agents_summary = result.get("agents") if isinstance(result.get("agents"), dict) else {}
            post_agents_summary = result.get("post_sync_agents") if isinstance(result.get("post_sync_agents"), dict) else {}
            source_failures = result.get("failed") if isinstance(result.get("failed"), list) else []
            sync_failures = sync_summary.get("failed") if isinstance(sync_summary.get("failed"), list) else []
            agent_failure_details = []
            for round_result in agents_summary.get("rounds", []):
                if not isinstance(round_result, dict):
                    continue
                for agent_result in round_result.get("agents", []):
                    if not isinstance(agent_result, dict) or not int(agent_result.get("failed_count", 0) or 0):
                        continue
                    agent_failure_details.append({
                        "agent": agent_result.get("agent"),
                        "failed_count": int(agent_result.get("failed_count", 0) or 0),
                    })
            failure_summary = {
                "status": result.get("status"),
                "source_failed_count": int(result.get("failed_count", 0) or 0),
                "processing_failed_count": int(result.get("processing_failed_count", 0) or 0),
                "sync_failed_count": int(result.get("sync_failed_count", 0) or 0),
                "agent_failed_count": int(result.get("agent_failed_count", 0) or 0),
                "post_sync_agent_failed_count": int(result.get("post_sync_agent_failed_count", 0) or 0),
                "source_failures": [
                    {"source": item.get("source"), "error": str(item.get("error", ""))[:240]}
                    for item in source_failures[:5] if isinstance(item, dict)
                ],
                "sync_failures": [
                    {"error": str(item.get("error", ""))[:240], "status": item.get("status")}
                    for item in sync_failures[:5] if isinstance(item, dict)
                ],
                "agent_failures": agent_failure_details[:10],
                "agent_remaining_queue_count": agents_summary.get("remaining_queue_count"),
                "airtable_drain": {
                    "batches": sync_summary.get("batches"),
                    "drain_complete": sync_summary.get("drain_complete"),
                    "elapsed_seconds": sync_summary.get("elapsed_seconds"),
                    "drain_budget_seconds": sync_summary.get("drain_budget_seconds"),
                },
                "post_sync_agent_remaining_queue_count": post_agents_summary.get("remaining_queue_count"),
            }
            print(
                "PRODUCTION EXECUTION GATE FAILURE: "
                + json.dumps(failure_summary, ensure_ascii=False, default=str),
                flush=True,
            )
            return 1

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
