from typing import Any, Dict, Iterable

from .batch import BatchProcessor
from .ingest import LeadIngestor
from .pipeline import LeadPipeline
from .sources import LeadSource


class LeadEngineRunner:
    """
    Operational entry point connecting a source to the lead engine.

    Flow:

        Source
          ↓
        Ingest
          ↓
        Pipeline
          ↓
        Local DB
          ↓
        Airtable sync

    The local database remains authoritative.
    """

    def __init__(self, pipeline: LeadPipeline):
        self.pipeline = pipeline
        self.ingestor = LeadIngestor(pipeline)
        self.batch = BatchProcessor(self.ingestor)

    def run_source(
        self,
        source: LeadSource,
    ) -> Dict[str, Any]:
        """
        Collect and process all records from one source.
        """

        records = source.collect()

        return self.batch.process(records)

    def run_records(
        self,
        records: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Process already-collected records.
        """

        return self.batch.process(records)


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

    return runner.run_source(source)


if __name__ == "__main__":
    print(
        "Lead engine runner loaded. "
        "Use LeadEngineRunner.run_source() to execute a source."
    )
