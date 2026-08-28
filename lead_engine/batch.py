from typing import Any, Dict, Iterable, List
import logging

from .ingest import LeadIngestor


logger = logging.getLogger(__name__)


class BatchProcessor:
    """
    Process discovered leads in batches.

    A failure on one lead does not prevent the remaining
    leads from being processed.
    """

    def __init__(self, ingestor: LeadIngestor):
        self.ingestor = ingestor

    def process(
        self,
        leads: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        processed: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        for lead in leads:
            try:
                result = self.ingestor.ingest_one(
                    lead
                )
                processed.append(result)

            except Exception:
                source = str(
                    lead.get(
                        "source",
                        "unknown",
                    )
                )
                source_id = str(
                    lead.get(
                        "source_id",
                        "unknown",
                    )
                )

                logger.exception(
                    "Lead ingestion failed: "
                    "source=%s source_id=%s",
                    source,
                    source_id,
                )

                failed.append(
                    {
                        "source": source,
                        "source_id": source_id,
                        "error": "lead processing failed",
                    }
                )

        return {
            "processed": processed,
            "failed": failed,
            "processed_count": len(processed),
            "failed_count": len(failed),
            "total": len(processed) + len(failed),
        }


if __name__ == "__main__":
    print(
        "Batch processor loaded. "
        "Use BatchProcessor.process() to process lead batches."
        )
