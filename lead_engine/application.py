from typing import Any, Dict, Iterable

from .config import LeadEngineConfig
from .database import LeadDB
from .service import LeadEngineService
from .sources import LeadSource


class LeadEngineApplication:
    """
    Production-facing application wrapper.

    Configuration is centralized and the local database
    remains authoritative.
    """

    def __init__(
        self,
        config: LeadEngineConfig | None = None,
    ):
        self.config = (
            config
            or LeadEngineConfig.from_environment()
        )

        self.db = LeadDB(
            data_dir=self.config.database_dir
        )

        self.service = LeadEngineService(
            db=self.db
        )

    def process_records(
        self,
        records: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return self.service.process_records(
            records
        )

    def run_sources(
        self,
        sources: Iterable[LeadSource],
    ) -> Dict[str, Any]:
        return self.service.run_sources(
            sources
        )

    def status(self) -> Dict[str, Any]:
        return self.service.status()

    def health(self) -> Dict[str, Any]:
        return self.service.health()

    def work_queue(
        self,
        limit: int | None = None,
    ):
        queue_limit = (
            limit
            if limit is not None
            else self.config.batch_size
        )

        return self.service.work_queue(
            limit=queue_limit
        )


def create_application() -> LeadEngineApplication:
    """
    Create the default application instance.
    """

    return LeadEngineApplication()


if __name__ == "__main__":
    application = create_application()

    print(
        application.status()
    )
