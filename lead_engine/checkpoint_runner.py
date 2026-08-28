class CheckpointRunner:
    def __init__(self, db, runner):
        self.db = db
        self.runner = runner

    def run(self, source, checkpoint):
        previous_checkpoint = self.db.get_checkpoint(
            source.name
        )

        result = self.runner.run_source(
            source,
            checkpoint,
        )

        if result["failed_count"] == 0:
            self.db.set_checkpoint(
                source.name,
                checkpoint,
            )
            saved_checkpoint = checkpoint
        else:
            saved_checkpoint = previous_checkpoint

        return {
            **result,
            "previous_checkpoint": previous_checkpoint,
            "checkpoint": saved_checkpoint,
        }
