from typing import Any, Callable, Optional


class CheckpointRunner:
    def __init__(self, db, collector):
        self.db = db
        self.collector = collector

    def get_checkpoint(self) -> str:
        return self.db.get_checkpoint(
            self.collector
        )

    def save_checkpoint(self, checkpoint: Any) -> None:
        self.db.set_checkpoint(
            self.collector,
            checkpoint,
        )

    def run(
        self,
        fetch: Callable[[str], Any],
        process: Callable[[Any], Optional[Any]],
    ):
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
        fetch: Callable[[str], Any],
        process: Callable[[Any], Optional[Any]],
        checkpoint_for_item: Callable[[Any], Any],
    ):
        checkpoint = self.get_checkpoint()

        items = fetch(checkpoint)

        if items is None:
            return []

        results = []

        for item in items:
            result = process(item)

            results.append(result)

            next_checkpoint = checkpoint_for_item(item)

            if next_checkpoint is not None:
                self.save_checkpoint(
                    next_checkpoint
                )

        return results
