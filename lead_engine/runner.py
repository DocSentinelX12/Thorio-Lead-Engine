from typing import Any, Dict, Iterable

from .pipeline import LeadPipeline
from .sources import LeadSource


class LeadEngineRunner:
    """
    Compatibility runner for executing LeadSource instances.

    The application service is the production execution boundary.
    This runner delegates to the canonical LeadPipeline.

    The runner preserves the established result contract:

        processed_count
        failed_count
        total
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
        Process collected records through the canonical
        lead pipeline.

        A record counts as processed when the pipeline accepts
        the record or identifies it as a duplicate.

        A record counts as failed when the record is invalid or
        pipeline processing raises an exception.
        """
        processed_count = 0
        failed_count = 0
        total = 0

        for record in records:
            total += 1

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

            if isinstance(result, dict):
                processed_count += 1
            else:
                failed_count += 1

        return {
            "processed_count": processed_count,
            "failed_count": failed_count,
            "total": total,
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
