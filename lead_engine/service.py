from typing import Any, Dict, Iterable

from .database import LeadDB
from .health import check_engine
from .pipeline import LeadPipeline
from .scheduler import LeadScheduler
from .source_runner import SourceRunner
from .sources import LeadSource
from .status import get_engine_status
from .work_queue_service import get_work_queue


class LeadEngineService:
    """
    High-level service facade for the lead engine.

    Application code should use this service instead of
    directly coordinating internal modules.
    """

    def __init__(
        self,
        db: LeadDB | None = None,
    ):
        self.db = db or LeadDB()

        self.pipeline = LeadPipeline(
            db=self.db
        )

        self.runner = SourceRunner(
            pipeline=self.pipeline
        )

        self.scheduler = LeadScheduler(
            runner=self.runner
        )

    def process_records(
        self,
        records: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Process already-collected lead records.
        """

        return self.runner.process(
            records
        )

    def run_sources(
        self,
        sources: Iterable[LeadSource],
    ) -> Dict[str, Any]:
        """
        Run multiple lead sources.
        """

        return self.scheduler.run(
            sources
        )

    def work_queue(
        self,
        limit: int = 50,
    ):
        """
        Return leads requiring human work.
        """

        return get_work_queue(
            self.db,
            limit=limit,
        )

    def status(self) -> Dict[str, Any]:
        """
        Return current engine status.
        """

        return get_engine_status(
            self.db
        )

    def health(self) -> Dict[str, Any]:
        """
        Return current engine health.
        """

        return check_engine(
            self.db
        )


if __name__ == "__main__":
    service = LeadEngineService()

    print(
        service.status()
    )
