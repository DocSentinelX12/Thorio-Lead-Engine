from typing import Any, Dict


class CheckpointRunner:
    """
    Run a lead source while passing and persisting checkpoints.

    A checkpoint advances only after the source completes without
    downstream processing failures.
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

        return str(
            checkpoint
        )

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
        previous_checkpoint = (
            self.get_checkpoint(
                source
            )
        )

        # If the caller supplied an explicit checkpoint and the
        # database has no checkpoint yet, use the supplied value.
        effective_checkpoint = (
            previous_checkpoint
            or (
                str(checkpoint)
                if checkpoint is not None
                else ""
            )
        )

        result = self.runner.run_source(
            source,
            checkpoint=effective_checkpoint,
        )

        if not isinstance(
            result,
            dict,
        ):
            result = {
                "processed_count": 0,
                "failed_count": 1,
                "total": 0,
                "checkpoint": effective_checkpoint,
            }

        failed_count = result.get(
            "failed_count",
            0,
        )

        try:
            failed_count = int(
                failed_count or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            failed_count = 1

        next_checkpoint = result.get(
            "checkpoint"
        )

        if failed_count == 0:
            if next_checkpoint:
                self.save_checkpoint(
                    source,
                    next_checkpoint,
                )

            current_checkpoint = (
                next_checkpoint
                or effective_checkpoint
            )

        else:
            current_checkpoint = (
                previous_checkpoint
            )

        return {
            **result,
            "previous_checkpoint": (
                previous_checkpoint
            ),
            "checkpoint": (
                current_checkpoint
            ),
        }


if __name__ == "__main__":
    print(
        "Checkpoint runner loaded."
    )
