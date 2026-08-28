from typing import Any, Dict


class CheckpointRunner:
    """
    Run a lead source through the existing LeadEngineRunner while
    persisting the source checkpoint only after a successful run.

    The local database remains authoritative for checkpoint state.
    """

    def __init__(
        self,
        db,
        runner,
    ):
        self.db = db
        self.runner = runner

    def get_checkpoint(
        self,
        source,
    ) -> str:
        checkpoint = self.db.get_checkpoint(
            source.name
        )

        if checkpoint is None:
            return ""

        return str(checkpoint)

    def save_checkpoint(
        self,
        source,
        checkpoint: Any,
    ) -> None:
        self.db.set_checkpoint(
            source.name,
            checkpoint,
        )

    def run(
        self,
        source,
        checkpoint: Any,
    ) -> Dict[str, Any]:
        """
        Run one source and persist its checkpoint only when the
        entire source run completes without failed records.

        A failed source run never advances the checkpoint.
        """

        previous_checkpoint = self.get_checkpoint(
            source
        )

        result = self.runner.run_source(
            source
        )

        if not isinstance(result, dict):
            result = {
                "result": result,
                "processed_count": 0,
                "failed_count": 1,
                "total": 0,
            }

        failed_count = result.get(
            "failed_count",
            0,
        )

        try:
            failed_count = int(
                failed_count or 0
            )
        except (TypeError, ValueError):
            failed_count = 1

        if failed_count == 0:
            self.save_checkpoint(
                source,
                checkpoint,
            )
            current_checkpoint = checkpoint
        else:
            current_checkpoint = previous_checkpoint

        return {
            **result,
            "previous_checkpoint": previous_checkpoint,
            "checkpoint": current_checkpoint,
        }


if __name__ == "__main__":
    print(
        "Checkpoint runner loaded."
    )
