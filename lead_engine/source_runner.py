from typing import Any, Dict, Iterable, Optional
import logging

from .pipeline import LeadPipeline
from .discovery_gate import apply_discovery_gate


logger = logging.getLogger(__name__)


class SourceRunner:
    """
    Run normalized source records through the existing lead pipeline.

    Checkpoints are passed into checkpoint-aware sources. A checkpoint is
    returned only when the source exposes a real checkpoint value.

    Every persisted opportunity then passes through the company-specific
    qualification gate. This keeps discovery, qualification, Paxus research,
    and Airtable synchronization connected without making any source adapter
    responsible for business decisions.
    """

    def __init__(
        self,
        pipeline: LeadPipeline,
    ):
        self.pipeline = pipeline

    def process(
        self,
        records: Iterable[Dict[str, Any]],
    ) -> Dict[str, int]:
        accepted = 0
        duplicates = 0
        failed = 0
        discovered = 0
        qualified = 0
        research_queued = 0

        for record in records:
            discovered += 1

            if not isinstance(
                record,
                dict,
            ):
                failed += 1

                logger.error(
                    "Lead pipeline rejected non-object "
                    "source record: type=%s",
                    type(record).__name__,
                )
                continue

            try:
                result = self.pipeline.process(
                    **record
                )
                result = apply_discovery_gate(
                    self.pipeline,
                    result,
                )

            except Exception:
                failed += 1

                source = str(
                    record.get(
                        "source",
                        "unknown",
                    )
                )

                source_id = str(
                    record.get(
                        "source_id",
                        "unknown",
                    )
                )

                logger.exception(
                    "Lead pipeline failed while processing "
                    "source record: source=%s source_id=%s",
                    source,
                    source_id,
                )
                continue

            if result.get(
                "status"
            ) == "duplicate":
                duplicates += 1

            elif result.get(
                "accepted"
            ) is True:
                accepted += 1

            if result.get("qualification_status") == "qualified":
                qualified += 1

            if result.get("paxus_research_status") == "research_required":
                research_queued += 1

        return {
            "discovered_count": discovered,
            "accepted_count": accepted,
            "duplicate_count": duplicates,
            "failed_count": failed,
            "qualified_count": qualified,
            "paxus_research_queued_count": research_queued,
        }

    def run_source(
        self,
        source,
        checkpoint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Collect one source using the supplied checkpoint.

        The source may expose a real string checkpoint after collection.
        Legacy sources that do not expose one continue returning the
        original result shape.
        """

        try:
            records = source.collect(
                checkpoint=checkpoint
            )
        except TypeError as exc:
            message = str(exc)

            if (
                "checkpoint" not in message
                or "unexpected keyword argument" not in message
            ):
                raise

            records = source.collect()

        result = self.process(
            records
        )

        source_state = getattr(
            source,
            "__dict__",
            {},
        )

        if "last_checkpoint" in source_state:
            result["checkpoint"] = (
                source_state["last_checkpoint"]
            )

        return result


if __name__ == "__main__":
    print(
        "Source runner loaded. "
        "Normalized source records can now enter "
        "the lead pipeline."
    )
