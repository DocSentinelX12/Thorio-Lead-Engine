import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class AuditLog:
    """
    Append-only local audit log.

    The audit log records operational events without becoming
    the source of truth for lead data.
    """

    def __init__(self, path="data/audit.jsonl"):
        self.path = Path(path)

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def record(
        self,
        event: str,
        **details: Any,
    ) -> Dict[str, Any]:
        entry = {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "event": event,
            **details,
        }

        with self.path.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                json.dumps(
                    entry,
                    ensure_ascii=False,
                )
                + "\n"
            )

        return entry

    def read(self):
        if not self.path.exists():
            return []

        entries = []

        with self.path.open(
            "r",
            encoding="utf-8",
        ) as handle:
            for line in handle:
                line = line.strip()

                if not line:
                    continue

                entries.append(
                    json.loads(line)
                )

        return entries
