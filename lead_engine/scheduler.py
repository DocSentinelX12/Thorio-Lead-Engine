import time
from typing import Any, Dict, Iterable, Optional

from .checkpoint_runner import CheckpointRunner
from .runner import LeadEngineRunner
from .sources import LeadSource
from .sync_worker import sync_pending


class LeadScheduler:
    """
    Continuous execution layer for lead sources.

    Each configured source is isolated from every other source.
    A source failure is recorded without preventing subsequent
    sources from running.

    Each source may define its own polling interval through its
    SourceDefinition. Sources are only executed when they are due.

    Checkpoints are integrated into the actual production source
    execution path. A source checkpoint advances only after that
    source completes without processing failures.
    """

    def __init__(self, runner: LeadEngineRunner):
        self.runner = runner
        self.checkpoint_runner = CheckpointRunner(
            db=runner.pipeline.db,
            runner=runner,
        )

        self._next_run_at: Dict[str, float] = {}

    def _source_key(
        self,
        source: LeadSource,
    ) -> str:
        definition = getattr(
            source,
            "definition",
            None,
        )

        if definition is not None:
            source_key = getattr(
                definition,
                "source_key",
                None,
            )

            if source_key:
                return str(source_key)

        return str(source.name)

    def _poll_interval(
        self,
        source: LeadSource,
    ) -> float:
        definition = getattr(
            source,
            "definition",
            None,
        )

        if definition is None:
            return 0.0

        value = getattr(
            definition,
            "poll_interval_seconds",
            0,
        )

        try:
            interval = float(value)
        except (
            TypeError,
            ValueError,
        ):
            return 0.0

        if interval <= 0:
            return 0.0

        return interval

    def _is_due(
        self,
        source: LeadSource,
        now: float,
    ) -> bool:
        key = self._source_key(source)

        next_run_at = self._next_run_at.get(
            key
        )

        if next_run_at is None:
            return True

        return now >= next_run_at

    def _schedule_next_run(
        self,
        source: LeadSource,
        started_at: float,
    ) -> None:
        interval = self._poll_interval(
            source
        )

        if interval <= 0:
            return

        key = self._source_key(source)

        self._next_run_at[key] = (
            started_at + interval
        )

    def run(
        self,
        sources: Iterable[LeadSource],
    ) -> Dict[str, Any]:
        results = []
        failed = []
        skipped = []

        source_list = list(sources)
        source_count = len(source_list)

        now = time.monotonic()

        for source in source_list:
            source_name = source.name

            if not self._is_due(
                source,
                now,
            ):
                skipped.append(
                    {
                        "source": source_name,
                        "reason": "not_due",
                    }
                )
                continue

            started_at = time.monotonic()

            try:
                previous_checkpoint = (
                    self.checkpoint_runner.get_checkpoint(
                        source
                    )
                )

                result = self.checkpoint_runner.run(
                    source=source,
                    checkpoint=previous_checkpoint,
                )

                result = dict(result)

                failed_count = result.get(
                    "failed_count",
                    0,
                )

                try:
                    failed_count = int(
                        failed_count or 0
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    failed_count = 1

                if failed_count != 0:
                    result["checkpoint"] = (
                        previous_checkpoint
                    )

                results.append(
                    {
                        "source": source_name,
                        "result": result,
                    }
                )

                self._schedule_next_run(
                    source,
                    started_at,
                )

            except Exception as exc:
                failed.append(
                    {
                        "source": source_name,
                        "error": str(exc),
                    }
                )

                self._schedule_next_run(
                    source,
                    started_at,
                )

        sync_result = sync_pending(
            self.runner.pipeline.db
        )

        discovered_total = sum(
            int(
                item["result"].get(
                    "discovered_count",
                    item["result"].get(
                        "total",
                        0,
                    ),
                )
                or 0
            )
            for item in results
        )

        accepted_total = sum(
            int(
                item["result"].get(
                    "accepted_count",
                    0,
                )
                or 0
            )
            for item in results
        )

        duplicate_total = sum(
            int(
                item["result"].get(
                    "duplicate_count",
                    0,
                )
                or 0
            )
            for item in results
        )

        processing_failed_total = sum(
            int(
                item["result"].get(
                    "failed_count",
                    0,
                )
                or 0
            )
            for item in results
        )

        return {
            "results": results,
            "failed": failed,
            "skipped": skipped,
            "source_count": source_count,
            "successful_source_count": len(
                results
            ),
            "failed_count": len(failed),
            "skipped_count": len(skipped),
            "discovered_count": discovered_total,
            "accepted_count": accepted_total,
            "duplicate_count": duplicate_total,
            "processing_failed_count": (
                processing_failed_total
            ),
            "sync": sync_result,
        }

    def run_forever(
        self,
        sources: Iterable[LeadSource],
        interval_seconds: float = 60.0,
        max_cycles: Optional[int] = None,
    ) -> Dict[str, Any]:
        source_list = list(sources)

        if interval_seconds < 0:
            raise ValueError(
                "interval_seconds must be greater than or equal to 0."
            )

        if max_cycles is not None and max_cycles < 1:
            raise ValueError(
                "max_cycles must be greater than or equal to 1."
            )

        if not source_list:
            return {
                "cycles": 0,
                "results": [],
                "failed": [],
                "skipped": [],
                "sync": [],
                "source_count": 0,
                "successful_source_count": 0,
                "result_count": 0,
                "failed_count": 0,
                "skipped_count": 0,
                "discovered_count": 0,
                "accepted_count": 0,
                "duplicate_count": 0,
                "processing_failed_count": 0,
                "status": "no_sources_configured",
            }

        cycles = 0
        total_results = []
        total_failed = []
        total_skipped = []
        total_sync = []

        total_discovered = 0
        total_accepted = 0
        total_duplicates = 0
        total_processing_failed = 0

        while (
            max_cycles is None
            or cycles < max_cycles
        ):
            result = self.run(
                source_list
            )

            total_results.extend(
                result["results"]
            )

            total_failed.extend(
                result["failed"]
            )

            total_skipped.extend(
                result.get(
                    "skipped",
                    [],
                )
            )

            total_sync.append(
                result["sync"]
            )

            total_discovered += result.get(
                "discovered_count",
                0,
            )

            total_accepted += result.get(
                "accepted_count",
                0,
            )

            total_duplicates += result.get(
                "duplicate_count",
                0,
            )

            total_processing_failed += result.get(
                "processing_failed_count",
                0,
            )

            cycles += 1

            if (
                max_cycles is not None
                and cycles >= max_cycles
            ):
                break

            if interval_seconds:
                time.sleep(
                    interval_seconds
                )

        return {
            "cycles": cycles,
            "results": total_results,
            "failed": total_failed,
            "skipped": total_skipped,
            "sync": total_sync,
            "source_count": len(
                source_list
            ),
            "successful_source_count": len(
                total_results
            ),
            "result_count": len(
                total_results
            ),
            "failed_count": len(
                total_failed
            ),
            "skipped_count": len(
                total_skipped
            ),
            "discovered_count": total_discovered,
            "accepted_count": total_accepted,
            "duplicate_count": total_duplicates,
            "processing_failed_count": (
                total_processing_failed
            ),
            "status": "completed",
        }

    def run_bounded(
        self,
        sources: Iterable[LeadSource],
        interval_seconds: float = 60.0,
        max_cycles: int = 10,
    ) -> Dict[str, Any]:
        return self.run_forever(
            sources=sources,
            interval_seconds=interval_seconds,
            max_cycles=max_cycles,
        )


if __name__ == "__main__":
    print(
        "Lead scheduler loaded. "
        "Configured sources are isolated during execution."
    )
