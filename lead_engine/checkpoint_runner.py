from typing import Any, Callable, Iterable, Optional


class CheckpointRunner:
    """
    Execute a source from its persisted checkpoint.

    Checkpoints are advanced only after an item has been
    successfully processed. If processing raises an exception,
    the checkpoint is left unchanged so the item can be retried
    on the next engine run.
    """

    def __init__(self, db, collector):
        self.db = db
        self.collector = collector

    def get_checkpoint(self) -> str:
        checkpoint = self.db.get_checkpoint(
            self.collector
        )

        if checkpoint is None:
            return ""

        return str(checkpoint)

    def save_checkpoint(
        self,
        checkpoint: Any,
    ) -> None:
        self.db.set_checkpoint(
            self.collector,
            checkpoint,
        )

    def run(
        self,
        fetch: Callable[[str], Iterable[Any]],
        process: Callable[[Any], Optional[Any]],
    ):
        """
        Run records starting from the persisted checkpoint.

        This method preserves the existing non-checkpoint-aware
        behavior. Checkpoint persistence is handled by
        run_with_checkpoint().
        """

        checkpoint = self.get_checkpoint()

        items = fetch(checkpoint)

        if items is None:
            return []

        results = []

        for item in items:
            result = process(item)
            results.append(result)

        return results

    def run_with_checkpoint(
        self,
        fetch: Callable[[str], Iterable[Any]],
        process: Callable[[Any], Optional[Any]],
        checkpoint_for_item: Callable[[Any], Any],
    ):
        """
        Process source items while durably advancing the checkpoint.

        The critical ordering is:

            fetch
              ↓
            process item
              ↓
            determine checkpoint
              ↓
            persist checkpoint

        The checkpoint is NEVER advanced before process() succeeds.

        If process() raises an exception, the exception propagates and
        the checkpoint remains at the last successfully processed item.
        """

        checkpoint = self.get_checkpoint()

        items = fetch(checkpoint)

        if items is None:
            return []

        results = []

        for item in items:
            # Do not move the checkpoint before processing succeeds.
            result = process(item)

            results.append(result)

            next_checkpoint = checkpoint_for_item(item)

            if next_checkpoint is not None:
                self.save_checkpoint(
                    next_checkpoint
                )

                checkpoint = next_checkpoint

        return results
