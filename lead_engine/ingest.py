from typing import Any, Dict, Iterable, List

from .collector import collect
from .pipeline import LeadPipeline


class LeadIngestor:
    """
    Connects discovered lead data to the LeadPipeline.

    The ingestor does not qualify leads.
    It only normalizes incoming records and passes them
    to the existing pipeline.
    """

    def __init__(self, pipeline: LeadPipeline):
        self.pipeline = pipeline

    def ingest_one(
        self,
        lead: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized = collect([lead])[0]

        return self.pipeline.process(
            source=normalized["source"],
            source_id=normalized["source_id"],
            url=normalized["url"],
            company=normalized["company"],
            signal=normalized["signal"],
            evidence=normalized["evidence"],
        )

    def ingest_many(
        self,
        leads: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        normalized_leads = collect(leads)

        results = []

        for lead in normalized_leads:
            results.append(
                self.pipeline.process(
                    source=lead["source"],
                    source_id=lead["source_id"],
                    url=lead["url"],
                    company=lead["company"],
                    signal=lead["signal"],
                    evidence=lead["evidence"],
                )
            )

        return results


if __name__ == "__main__":
    print(
        "Lead ingestor loaded. "
        "Use LeadIngestor to feed discovered leads into the pipeline."
    )
