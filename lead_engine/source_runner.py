from typing import Any, Dict, Iterable, Optional

from .checkpoint_runner import CheckpointRunner
from .sources import LeadSource


class SourceRunner:
    """
    Runs configured lead sources through the canonical checkpoint
    and processing path.

    Source collection is isolated from processing so a failure in
    one source does not prevent other configured sources from running.
    """

    def __init__(
        self,
        checkpoint_runner: CheckpointRunner,
    ):
        self.checkpoint_runner = checkpoint_runner

    def run(
        self,
        source: LeadSource,
        process,
    ) -> Dict[str, Any]:
        """
        Run one source and persist its checkpoint only as records
        are successfully processed.
        """

        def fetch(checkpoint: Optional[str]):
            return source.collect()

        def process_item(item: Dict[str, Any]):
            return process(item)

        def checkpoint_for_item(item: Dict[str, Any]):
            return item.get("source_id")

        results = self.checkpoint_runner.run_with_checkpoint(
            fetch=fetch,
            process=process_item,
            checkpoint_for_item=checkpoint_for_item,
        )

        processed_count = 0
        failed_count = 0

        for result in results:
            if isinstance(result, dict):
                if result.get("status") == "failed":
                    failed_count += 1
                else:
                    processed_count += 1
            elif result is None:
                processed_count += 1
            else:
                processed_count += 1

        return {
            "source": source.name,
            "processed_count": processed_count,
            "failed_count": failed_count,
            "total": len(results),
            "results": results,
            "checkpoint": self.checkpoint_runner.get_checkpoint(),
        }
