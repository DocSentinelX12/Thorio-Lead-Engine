import argparse
import json

from .application import create_application
from .config import LeadEngineConfig
from .export import export_pending_leads
from .json_source import JsonLeadSource
from .source_registry import configured_sources
from .sync_worker import sync_pending


def build_parser():
    parser = argparse.ArgumentParser(
        description="Thorio Lead Engine"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    subparsers.add_parser(
        "status",
        help="Show lead engine status.",
    )

    subparsers.add_parser(
        "health",
        help="Run lead engine health checks.",
    )

    subparsers.add_parser(
        "work-queue",
        help="Show the current human work queue.",
    )

    subparsers.add_parser(
        "run",
        help="Run all configured lead-discovery sources.",
    )

    import_parser = subparsers.add_parser(
        "import-json",
        help="Import leads from a JSON file.",
    )

    import_parser.add_argument(
        "path",
        help="Path to the JSON lead file.",
    )

    run_parser = subparsers.add_parser(
        "run-json",
        help="Run a JSON lead source through the complete pipeline.",
    )

    run_parser.add_argument(
        "path",
        help="Path to the JSON lead source file.",
    )

    export_parser = subparsers.add_parser(
        "export-json",
        help="Export pending local leads to JSON.",
    )

    export_parser.add_argument(
        "path",
        help="Destination JSON file.",
    )

    return parser


def _sync_pending_if_enabled(
    application,
):
    config = getattr(
        application,
        "config",
        None,
    )

    if config is None:
        return None

    if not config.sync_enabled:
        return None

    return sync_pending(
        application.db,
        limit=config.batch_size,
    )


def main(argv=None):
    parser = build_parser()

    args = parser.parse_args(argv)

    application = create_application()

    if args.command == "status":
        result = application.status()

    elif args.command == "health":
        result = application.health()

    elif args.command == "work-queue":
        result = application.work_queue()

    elif args.command == "run":
        sources = configured_sources()

        result = application.run_sources(
            sources
        )

        sync_result = _sync_pending_if_enabled(
            application
        )

        if sync_result is not None:
            result["sync"] = sync_result

    elif args.command == "import-json":
        source = JsonLeadSource(
            args.path
        )

        result = application.run_sources(
            [source]
        )

        sync_result = _sync_pending_if_enabled(
            application
        )

        if sync_result is not None:
            result["sync"] = sync_result

    elif args.command == "run-json":
        source = JsonLeadSource(
            args.path
        )

        result = application.run_sources(
            [source]
        )

        sync_result = _sync_pending_if_enabled(
            application
        )

        if sync_result is not None:
            result["sync"] = sync_result

    elif args.command == "export-json":
        result = export_pending_leads(
            application.db,
            args.path,
        )

    else:
        parser.error(
            f"Unknown command: {args.command}"
        )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
)
