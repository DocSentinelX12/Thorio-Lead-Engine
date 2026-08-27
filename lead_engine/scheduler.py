from typing import Any, Dict, Iterable

from .runner import LeadEngineRunner
from .sources import LeadSource


class LeadScheduler:
    """
    Controlled execution layer for lead sources.

    The scheduler does not store credentials, qualify leads,
    or replace the durable local database.
    """

    def __init__(self, runner: LeadEngineRunner):
        self.runner = runner

    def run(
        self,
        sources: Iterable[LeadSource],
    ) -> Dict[str, Any]:
        """
        Run each source independently.

        A failure in one source does not prevent other sources
        from running.
        """

        results = []
        failed = []

        for source in sources:
            try:
                result = self.runner.run_source(source)

                results.append(
                    {
                        "source": source.name,
                        "result": result,
                    }
                )

            except Exception as exc:
                failed.append(
                    {
                        "source": source.name,
                        "error": str(exc),
                    }
                )

        return {
            "results": results,
            "failed": failed,
            "source_count": len(results),
            "failed_count": len(failed),
        }


if __name__ == "__main__":
    print(
        "Lead scheduler loaded. "
        "Sources can now be executed independently."
    )
