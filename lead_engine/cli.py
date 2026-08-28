import argparse
import json

from .application import create_application
from .export import export_pending_leads
from .json_source import JsonLeadSource


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

    elif args.command == "import-json":
        source = JsonLeadSource(
            args.path
        )

        result = application.run_sources(
            [source]
        )

    elif args.command == "run-json":
        source = JsonLeadSource(
            args.path
        )

        result = application.run_sources(
            [source]
        )

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
