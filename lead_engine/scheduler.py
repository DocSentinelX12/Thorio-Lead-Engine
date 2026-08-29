import time
from typing import Any, Dict, Iterable, Optional

from .runner import LeadEngineRunner
from .sources import LeadSource
from .sync_worker import sync_pending


class LeadScheduler:
    """
    Continuous execution layer for lead sources.

    Sources are processed independently. A failure in one source
    does not prevent the remaining sources from running.

    Each cycle also retries locally pending Airtable syncs.

    The scheduler supports bounded execution so a GitHub Actions
    workflow can continuously work for a fixed window without
    running forever.
    """

    def __init__(self, runner: LeadEngineRunner):
        self.runner = runner

    def run(
        self,
        sources: Iterable[LeadSource],
    ) -> Dict[str, Any]:
        """
        Run each source once, then retry pending Airtable syncs.

        Every source receives an explicit production result containing:

            source
            discovered_count
            processed_count
            failed_count

        Source failures are isolated so one broken source cannot
        prevent other sources from running.
        """

        results = []
        failed = []

        for source in sources:
            try:
                result = self.runner.run_source(
                    source
                )

                result = dict(result)

                results.append(
                    {
                        "source": source.name,
                        "result": result,
                    }
                )

            except Exception as exc:
                failed.append(
                    {
                        "source": source.name,
                        "error": str(exc),
                    }
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
            "source_count": len(results) + len(failed),
            "successful_source_count": len(results),
            "failed_count": len(failed),
            "discovered_count": discovered_total,
            "accepted_count": accepted_total,
            "duplicate_count": duplicate_total,
            "processing_failed_count": processing_failed_total,
            "sync": sync_result,
        }

    def run_forever(
        self,
        sources: Iterable[LeadSource],
        interval_seconds: float = 60.0,
        max_cycles: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Continuously cycle through all configured sources.

        When max_cycles is supplied, execution stops after exactly
        that many completed cycles.

        If no sources are configured, execution stops immediately
        rather than repeatedly running empty cycles.
        """

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
                "sync": [],
                "source_count": 0,
                "successful_source_count": 0,
                "result_count": 0,
                "failed_count": 0,
                "discovered_count": 0,
                "accepted_count": 0,
                "duplicate_count": 0,
                "processing_failed_count": 0,
                "status": "no_sources_configured",
            }

        cycles = 0
        total_results = []
        total_failed = []
        total_sync = []

        total_discovered = 0
        total_accepted = 0
        total_duplicates = 0
        total_processing_failed = 0

        while max_cycles is None or cycles < max_cycles:
            result = self.run(
                source_list
            )

            total_results.extend(
                result["results"]
            )

            total_failed.extend(
                result["failed"]
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
            "sync": total_sync,
            "source_count": len(source_list),
            "successful_source_count": (
                len(source_list)
                - len(total_failed)
            ),
            "result_count": len(total_results),
            "failed_count": len(total_failed),
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
        """
        Run a bounded continuous execution window.

        This is the production-safe entry point for scheduled
        environments such as GitHub Actions.

        The local database is reused for every cycle, so leads,
        dedupe state, checkpoints, retry state, and pending
        synchronization records remain available throughout
        the entire execution window.
        """

        return self.run_forever(
            sources=sources,
            interval_seconds=interval_seconds,
            max_cycles=max_cycles,
        )


if __name__ == "__main__":
    print(
        "Lead scheduler loaded. "
        "Use run_bounded() for bounded production execution "
        "or run_forever() for an intentionally continuous process."
    )
