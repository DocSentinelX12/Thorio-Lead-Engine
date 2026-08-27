from typing import Any, Dict


class LeadEngineMetrics:
    """
    In-memory operational metrics for one engine process.

    Metrics are observational only.
    They do not replace the durable local database.
    """

    def __init__(self):
        self.counters = {
            "sources_started": 0,
            "sources_completed": 0,
            "sources_failed": 0,
            "records_processed": 0,
            "records_accepted": 0,
            "records_duplicate": 0,
            "records_failed": 0,
            "records_synced": 0,
            "records_pending": 0,
        }

    def increment(
        self,
        name: str,
        amount: int = 1,
    ) -> int:
        if name not in self.counters:
            self.counters[name] = 0

        self.counters[name] += amount

        return self.counters[name]

    def set(
        self,
        name: str,
        value: int,
    ) -> int:
        self.counters[name] = value
        return value

    def get(
        self,
        name: str,
    ) -> int:
        return self.counters.get(name, 0)

    def snapshot(self) -> Dict[str, int]:
        return dict(self.counters)

    def update_from_result(
        self,
        result: Dict[str, Any],
    ) -> None:
        mappings = {
            "accepted_count": "records_accepted",
            "duplicate_count": "records_duplicate",
            "failed_count": "records_failed",
        }

        for source_key, metric_key in mappings.items():
            if source_key in result:
                self.increment(
                    metric_key,
                    int(result[source_key] or 0),
                )

        total = (
            int(result.get("accepted_count", 0) or 0)
            + int(result.get("duplicate_count", 0) or 0)
            + int(result.get("failed_count", 0) or 0)
        )

        if total:
            self.increment(
                "records_processed",
                total,
            )

    def reset(self) -> None:
        for key in self.counters:
            self.counters[key] = 0
