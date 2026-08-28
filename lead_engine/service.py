from typing import Any, Dict, Iterable

from .health import check_engine
from .outreach_queue import build_outreach_queue, summarize_queue
from .pipeline import LeadPipeline
from .source_runner import SourceRunner
from .status import get_engine_status
from .work_queue_service import (
    get_next_work_item,
    get_work_queue,
)


class LeadEngineService:
    """
    Application service boundary.

    Coordinates the database, lead pipeline, source runner,
    health checks, human work queue, and partner outreach queues.
    """

    def __init__(
        self,
        db,
        runner=None,
        work_queue_limit: int = 50,
    ):
        self.db = db
        self.work_queue_limit = work_queue_limit

        if runner is None:
            runner = SourceRunner(
                pipeline=LeadPipeline(
                    db=self.db
                )
            )

        self.runner = runner

    def process_records(
        self,
        records: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return self.runner.process(
            records
        )

    def run_sources(
        self,
        sources,
    ) -> Dict[str, Any]:
        """
        Run every configured source independently.

        A source that returns no records is considered a successful
        empty source. It must not be treated as a failure and must
        not prevent subsequent sources from running.

        A source collection or processing exception is isolated to
        that source and recorded in its result.
        """
        source_count = 0
        failed_count = 0
        results = []

        for source in sources:
            source_count += 1

            source_name = source.__class__.__name__

            try:
                result = self.runner.run_source(
                    source
                )

                if result is None:
                    result = {
                        "accepted_count": 0,
                        "duplicate_count": 0,
                        "failed_count": 0,
                        "empty": True,
                    }
                else:
                    result = dict(result)

                    if (
                        result.get("accepted_count", 0) == 0
                        and result.get("duplicate_count", 0) == 0
                        and result.get("failed_count", 0) == 0
                    ):
                        result.setdefault(
                            "empty",
                            True,
                        )

                results.append(
                    {
                        "source": source_name,
                        "result": result,
                    }
                )

            except Exception as exc:
                failed_count += 1

                results.append(
                    {
                        "source": source_name,
                        "result": {
                            "accepted_count": 0,
                            "duplicate_count": 0,
                            "failed_count": 1,
                            "error": str(exc),
                        },
                    }
                )

        return {
            "source_count": source_count,
            "failed_count": failed_count,
            "results": results,
        }

    def work_queue(
        self,
        limit: int | None = None,
    ):
        return get_work_queue(
            self.db,
            limit=(
                limit
                if limit is not None
                else self.work_queue_limit
            ),
        )

    def next_work_item(self):
        return get_next_work_item(
            self.db
        )

    def outreach_queues(
        self,
        leads: Iterable[Dict[str, Any]],
    ) -> Dict[str, list]:
        """
        Build partner delivery queues from processed leads.

        Only leads that satisfy the outreach queue rules are
        delivered to Shiftr, Paxus, or Thorio. Everything else
        remains in Review.
        """
        return build_outreach_queue(
            list(leads)
        )

    def outreach_summary(
        self,
        leads: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Return counts for all partner delivery queues.
        """
        return summarize_queue(
            list(leads)
        )

    def health(self):
        return check_engine(
            self.db
        )

    def status(self):
        return get_engine_status(
            self.db
        )
