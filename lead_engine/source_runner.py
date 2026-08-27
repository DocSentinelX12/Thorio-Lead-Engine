from typing import Any, Dict, Iterable

from .pipeline import LeadPipeline


class SourceRunner:
    """
    Run normalized source records through the existing lead pipeline.
    """

    def __init__(self, pipeline: LeadPipeline):
        self.pipeline = pipeline

    def process(
        self,
        records: Iterable[Dict[str, Any]],
    ) -> Dict[str, int]:
        """
        Process every record independently.

        A failure on one record does not stop the remaining records.
        """

        accepted = 0
        duplicates = 0
        failed = 0

        for record in records:
            try:
                result = self.pipeline.process(
                    **record
                )

            except Exception:
                failed += 1
                continue

            if result.get("status") == "duplicate":
                duplicates += 1

            elif result.get("accepted") is True:
                accepted += 1

        return {
            "accepted_count": accepted,
            "duplicate_count": duplicates,
            "failed_count": failed,
        }


if __name__ == "__main__":
    print(
        "Source runner loaded. "
        "Normalized source records can now enter the lead pipeline."
    )
