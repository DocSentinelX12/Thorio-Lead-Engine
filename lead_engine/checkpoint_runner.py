from typing import Any, Dict


class CheckpointRunner:
    """
    Run a lead source while passing and persisting checkpoints.

    A checkpoint advances only after the source completes without
    downstream processing failures.

    If the database already has a checkpoint, it takes precedence over
    any checkpoint supplied by the caller.

    If the database has no checkpoint and the caller supplies one, that
    checkpoint is used as the effective starting checkpoint.

    After a successful run, a checkpoint returned by the runner is
    persisted. If the runner does not return a new checkpoint, the
    effective checkpoint is persisted instead.

    After a failed run, the previously persisted database checkpoint is
    retained and no new checkpoint is saved.
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

        # An already persisted database checkpoint always wins.
        # Otherwise, use the checkpoint explicitly supplied by the
        # caller as the starting checkpoint.
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

        checkpoint_returned = (
            "checkpoint" in result
        )

        next_checkpoint = result.get(
            "checkpoint"
        )

        if failed_count == 0:
            # An explicitly returned checkpoint, including None,
            # represents the source's current pagination state.
            # A missing checkpoint means the source did not provide
            # checkpoint information, so retain the effective value.
            if checkpoint_returned:
                current_checkpoint = (
                    next_checkpoint
                )
            else:
                current_checkpoint = (
                    effective_checkpoint
                )

            # An empty checkpoint clears the persisted pagination
            # state. This allows exhausted paginated sources to start
            # a fresh cycle on their next scheduled run.
            if current_checkpoint is None:
                self.save_checkpoint(
                    source,
                    "",
                )
            else:
                self.save_checkpoint(
                    source,
                    current_checkpoint,
                )

        else:
            # Never advance the persisted checkpoint after a failed
            # downstream processing run.
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
