from typing import Any, Dict, Iterable, Optional

from .pipeline import LeadPipeline
from .source_runner import SourceRunner
from .sources import LeadSource


class LeadEngineRunner:
    """
    Compatibility wrapper around the canonical SourceRunner.
    """

    def __init__(
        self,
        pipeline: LeadPipeline,
    ):
        self._runner = SourceRunner(
            pipeline=pipeline
        )

    @property
    def pipeline(
        self,
    ) -> LeadPipeline:
        return self._runner.pipeline

    def run_source(
        self,
        source: LeadSource,
        checkpoint: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = dict(
            self._runner.run_source(
                source,
                checkpoint=checkpoint,
            )
        )

        result.setdefault(
            "processed_count",
            result.get(
                "accepted_count",
                0,
            )
            + result.get(
                "duplicate_count",
                0,
            ),
        )

        result.setdefault(
            "total",
            result.get(
                "discovered_count",
                result.get(
                    "processed_count",
                    0,
                ),
            ),
        )

        return result

    def run_records(
        self,
        records: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        result = dict(
            self._runner.process(
                records
            )
        )

        result.setdefault(
            "processed_count",
            result.get(
                "accepted_count",
                0,
            )
            + result.get(
                "duplicate_count",
                0,
            ),
        )

        result.setdefault(
            "total",
            result.get(
                "processed_count",
                0,
            )
            + result.get(
                "failed_count",
                0,
            ),
        )

        return result


def run_source(
    source: LeadSource,
) -> Dict[str, Any]:
    pipeline = LeadPipeline()

    runner = LeadEngineRunner(
        pipeline=pipeline
    )

    return runner.run_source(
        source
    )


if __name__ == "__main__":
    print(
        "Lead engine runner loaded. "
        "Use LeadEngineRunner.run_source() "
        "to execute a source."
    )
