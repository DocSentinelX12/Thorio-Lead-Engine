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
        """

        results = []
        failed = []

        for source in sources:
            try:
                result = self.runner.run_source(source)

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

        return {
            "results": results,
            "failed": failed,
            "source_count": len(results),
            "failed_count": len(failed),
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
        that many completed cycles. This makes the scheduler safe
        for bounded CI execution.
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

        cycles = 0
        total_results = []
        total_failed = []
        total_sync = []

        while max_cycles is None or cycles < max_cycles:
            result = self.run(source_list)

            total_results.extend(
                result["results"]
            )
            total_failed.extend(
                result["failed"]
            )
            total_sync.append(
                result["sync"]
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
            "result_count": len(total_results),
            "failed_count": len(total_failed),
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
