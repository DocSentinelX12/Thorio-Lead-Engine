from typing import Any, Dict, Iterable

from .audit import AuditLog
from .config import LeadEngineConfig
from .database import LeadDB
from .export import export_pending_leads
from .sources import LeadSource
from .service import LeadEngineService


class LeadEngineApplication:
    """
    Production-facing application wrapper.

    Configuration is centralized.
    The local database remains authoritative.
    Operational events are recorded separately
    in the append-only audit log.
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

        self.audit = AuditLog(
            str(
                self.config.database_path.parent
                / "audit.jsonl"
            )
        )

        self.service = LeadEngineService(
            db=self.db
        )

    def process_records(
        self,
        records: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        result = self.service.process_records(
            records
        )

        self.audit.record(
            "records_processed",
            result=result,
        )

        return result

    def run_sources(
        self,
        sources: Iterable[LeadSource],
    ) -> Dict[str, Any]:
        sources = list(sources)

        result = self.service.run_sources(
            sources
        )

        self.audit.record(
            "sources_processed",
            source_count=len(sources),
            result=result,
        )

        return result

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

    def export_pending(
        self,
        path: str,
    ) -> Dict[str, Any]:
        result = export_pending_leads(
            self.db,
            path,
        )

        self.audit.record(
            "pending_leads_exported",
            path=path,
            count=result["count"],
        )

        return result


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
