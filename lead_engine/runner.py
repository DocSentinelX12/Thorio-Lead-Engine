from typing import Any, Dict, Iterable

from .pipeline import LeadPipeline
from .sources import LeadSource


class LeadEngineRunner:
    """
    Compatibility runner for executing LeadSource instances.

    The application service is the production execution boundary.
    This runner delegates directly to the same LeadPipeline used by
    the application so there is only one processing path.

    Flow:

        Source
          ↓
        LeadPipeline
          ↓
        Local DB
          ↓
        Airtable sync

    The local database remains authoritative.
    """

    def __init__(self, pipeline: LeadPipeline):
        self.pipeline = pipeline

    def run_source(
        self,
        source: LeadSource,
    ) -> Dict[str, Any]:
        """
        Collect and process all records from one source.
        """
        records = source.collect()

        return self.run_records(
            records
        )

    def run_records(
        self,
        records: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Process already-collected records through the
        canonical lead pipeline.
        """
        accepted_count = 0
        duplicate_count = 0
        failed_count = 0

        for record in records:
            if not isinstance(record, dict):
                failed_count += 1
                continue

            try:
                result = self.pipeline.process(
                    **record
                )
            except Exception:
                failed_count += 1
                continue

            if result.get("status") == "duplicate":
                duplicate_count += 1

            elif result.get("accepted") is True:
                accepted_count += 1

        return {
            "accepted_count": accepted_count,
            "duplicate_count": duplicate_count,
            "failed_count": failed_count,
        }


def run_source(
    source: LeadSource,
) -> Dict[str, Any]:
    """
    Convenience function for running a source with
    the default lead pipeline.
    """
    pipeline = LeadPipeline()

    runner = LeadEngineRunner(
        pipeline=pipeline
    )

    return runner.run_source(
        source
    )


if __name__ == "__main__":
    print(
        "Lead engine runner loaded. "
        "Use LeadEngineRunner.run_source() to execute a source."
    )
