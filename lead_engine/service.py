from typing import Any, Dict, Iterable

from .health import check_engine
from .work_queue_service import (
    get_next_work_item,
    get_work_queue,
)


class LeadEngineService:
    """
    Application service boundary.

    The service coordinates the existing runner and database
    components without changing their public interfaces.
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
            from .runner import Runner

            runner = Runner(
                db=self.db
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
        source_count = 0
        failed_count = 0
        results = []

        for source in sources:
            source_count += 1

            try:
                records = source.collect()

                result = self.runner.process(
                    records
                )

                results.append(
                    {
                        "source": source.__class__.__name__,
                        "result": result,
                    }
                )

            except Exception as exc:
                failed_count += 1

                results.append(
                    {
                        "source": source.__class__.__name__,
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

    def health(self):
        return check_engine(
            self.db
        )

    def status(self):
        return {
            "database": self.db.status(),
            "health": self.health(),
            "work_queue": len(
                self.work_queue()
            ),
        }
