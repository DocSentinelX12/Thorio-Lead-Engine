from typing import Any, Dict, Iterable

from .pipeline import LeadPipeline
from .source_runner import SourceRunner
from .sources import LeadSource


class LeadEngineRunner:
    """
    Compatibility wrapper around the canonical SourceRunner.

    SourceRunner is the single record-processing execution path.
    This class preserves the existing LeadEngineRunner API while
    exposing the complete production result needed by the scheduler.
    """

    def __init__(self, pipeline: LeadPipeline):
        self._runner = SourceRunner(
            pipeline=pipeline
        )

    @property
    def pipeline(self) -> LeadPipeline:
        return self._runner.pipeline

    def run_source(
        self,
        source: LeadSource,
    ) -> Dict[str, Any]:
        """
        Collect and process one source through the canonical runner.

        Preserves the canonical SourceRunner result while exposing the
        compatibility fields required by existing callers.
        """
        result = dict(
            self._runner.run_source(
                source
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
        """
        Process records through the canonical SourceRunner.

        Failed records are isolated by SourceRunner. Preserve its
        canonical result while exposing the compatibility fields
        required by existing callers.
        """
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
    """
    Compatibility convenience function.

    Uses the canonical SourceRunner through LeadEngineRunner.
    """
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
        "Use LeadEngineRunner.run_source() to execute a source."
    )
