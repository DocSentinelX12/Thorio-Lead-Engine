from typing import Any, Dict

from .database import LeadDB
from .runner import LeadEngineRunner
from .sources import LeadSource


class CheckpointRunner:
    """
    Runs a source while maintaining its durable checkpoint.

    The local database remains authoritative.
    """

    def __init__(
        self,
        db: LeadDB,
        runner: LeadEngineRunner,
    ):
        self.db = db
        self.runner = runner

    def get_checkpoint(
        self,
        source: LeadSource,
    ) -> str:
        return self.db.get_checkpoint(source.name)

    def set_checkpoint(
        self,
        source: LeadSource,
        checkpoint: str,
    ) -> None:
        self.db.set_checkpoint(
            source.name,
            checkpoint,
        )

    def run(
        self,
        source: LeadSource,
        checkpoint: str = "",
    ) -> Dict[str, Any]:
        """
        Run a source and save its checkpoint only after
        successful processing.
        """

        previous_checkpoint = self.get_checkpoint(source)

        result = self.runner.run_source(source)

        if result.get("failed_count", 0) == 0:
            if checkpoint:
                self.set_checkpoint(
                    source,
                    checkpoint,
                )

        return {
            "source": source.name,
            "previous_checkpoint": previous_checkpoint,
            "checkpoint": self.get_checkpoint(source),
            "result": result,
        }


if __name__ == "__main__":
    print(
        "Checkpoint runner loaded. "
        "Sources can now maintain durable checkpoints."
    )
