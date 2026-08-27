import argparse
import json

from .application import create_application


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
