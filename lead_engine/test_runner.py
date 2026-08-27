from unittest.mock import MagicMock

from .runner import LeadEngineRunner
from .sources import StaticLeadSource


def test_runner_processes_source_records():
    pipeline = MagicMock()

    pipeline.process.side_effect = [
        {
            "status": "accepted",
            "accepted": True,
        },
        {
            "status": "duplicate",
            "accepted": False,
        },
    ]

    runner = LeadEngineRunner(
        pipeline=pipeline
    )

    source = StaticLeadSource(
        [
            {
                "source": "test",
                "source_id": "runner-001",
                "url": "https://example.com/1",
                "company": "Acme",
                "signal": "developer",
                "evidence": "Developer opening.",
            },
            {
                "source": "test",
                "source_id": "runner-002",
                "url": "https://example.com/2",
                "company": "Beta",
                "signal": "remote role",
                "evidence": "Remote opening.",
            },
        ]
    )

    result = runner.run_source(source)

    assert result["processed_count"] == 2
    assert result["failed_count"] == 0
    assert pipeline.process.call_count == 2


def test_runner_handles_failed_record():
    pipeline = MagicMock()

    pipeline.process.side_effect = [
        RuntimeError("temporary failure"),
        {
            "status": "accepted",
            "accepted": True,
        },
    ]

    runner = LeadEngineRunner(
        pipeline=pipeline
    )

    result = runner.run_records(
        [
            {
                "source": "test",
                "source_id": "runner-003",
                "url": "https://example.com/3",
                "company": "Failure Corp",
                "signal": "developer",
                "evidence": "Developer opening.",
            },
            {
                "source": "test",
                "source_id": "runner-004",
                "url": "https://example.com/4",
                "company": "Good Corp",
                "signal": "remote role",
                "evidence": "Remote opening.",
            },
        ]
    )

    assert result["processed_count"] == 1
    assert result["failed_count"] == 1
    assert result["total"] == 2
