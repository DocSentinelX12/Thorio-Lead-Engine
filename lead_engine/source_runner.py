from typing import Any, Dict, Iterable
import logging

from .pipeline import LeadPipeline


logger = logging.getLogger(__name__)


class SourceRunner:
    """
    Run normalized source records through the existing lead pipeline.

    The runner also reports how many records were discovered by the
    source before downstream processing. This allows production
    monitoring to distinguish an empty source from a source whose
    records failed downstream.
    """

    def __init__(self, pipeline: LeadPipeline):
        self.pipeline = pipeline

    def process(
        self,
        records: Iterable[Dict[str, Any]],
    ) -> Dict[str, int]:
        """
        Process every source record independently.

        A malformed record or pipeline failure must never stop
        subsequent records from being processed.
        """

        accepted = 0
        duplicates = 0
        failed = 0
        discovered = 0

        for record in records:
            discovered += 1

            if not isinstance(record, dict):
                failed += 1

                logger.error(
                    "Lead pipeline rejected non-object source record: "
                    "type=%s",
                    type(record).__name__,
                )
                continue

            try:
                result = self.pipeline.process(
                    **record
                )

            except Exception:
                failed += 1

                source = str(
                    record.get("source", "unknown")
                )
                source_id = str(
                    record.get("source_id", "unknown")
                )

                logger.exception(
                    "Lead pipeline failed while processing "
                    "source record: source=%s source_id=%s",
                    source,
                    source_id,
                )
                continue

            if result.get("status") == "duplicate":
                duplicates += 1

            elif result.get("accepted") is True:
                accepted += 1

        return {
            "discovered_count": discovered,
            "accepted_count": accepted,
            "duplicate_count": duplicates,
            "failed_count": failed,
        }

    def run_source(
        self,
        source,
    ) -> Dict[str, Any]:
        """
        Collect records from one source and process them.

        Source collection failures are allowed to propagate to the
        service boundary so the source itself is recorded as failed
        without terminating processing of other configured sources.
        """

        records = source.collect()

        return self.process(
            records
        )


if __name__ == "__main__":
    print(
        "Source runner loaded. "
        "Normalized source records can now enter the lead pipeline."
    )
