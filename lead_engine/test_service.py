from unittest.mock import MagicMock

from .database import LeadDB
from .service import LeadEngineService
from .sources import StaticLeadSource


def test_service_reports_health(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    service = LeadEngineService(
        db=db
    )

    result = service.health()

    assert result["healthy"] is True


def test_service_runs_sources(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    service = LeadEngineService(
        db=db
    )

    service.runner.process = MagicMock(
        return_value={
            "accepted_count": 1,
            "duplicate_count": 0,
            "failed_count": 0,
        }
    )

    source = StaticLeadSource(
        [
            {
                "source": "test",
                "source_id": "service-001",
                "url": "https://example.com/service-001",
                "company": "Service Corp",
                "signal": "developer",
                "evidence": "Developer opening.",
            }
        ]
    )

    result = service.run_sources(
        [source]
    )

    assert result["source_count"] == 1
    assert result["failed_count"] == 0
    assert len(result["results"]) == 1


def test_service_work_queue_limit(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    service = LeadEngineService(
        db=db,
        work_queue_limit=7,
    )

    service.work_queue = MagicMock(
        return_value=[]
    )

    service.work_queue()

    service.work_queue.assert_called_once_with()


def test_service_continues_after_source_failure(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    service = LeadEngineService(
        db=db
    )

    successful_source = MagicMock()
    successful_source.__class__.__name__ = "SuccessfulSource"

    successful_source.collect.return_value = [
        {
            "source": "test",
            "source_id": "success-001",
            "url": "https://example.com/success-001",
            "company": "Success Corp",
            "signal": "developer",
            "evidence": "Developer opening.",
        }
    ]

    failed_source = MagicMock()
    failed_source.__class__.__name__ = "FailedSource"

    service.runner.run_source = MagicMock(
        side_effect=[
            Exception("temporary source failure"),
            {
                "accepted_count": 1,
                "duplicate_count": 0,
                "failed_count": 0,
            },
        ]
    )

    result = service.run_sources(
        [
            failed_source,
            successful_source,
        ]
    )

    assert result["source_count"] == 2
    assert result["failed_count"] == 1
    assert len(result["results"]) == 2

    assert result["results"][0]["result"]["error"] == (
        "temporary source failure"
    )

    assert result["results"][1]["result"] == {
        "accepted_count": 1,
        "duplicate_count": 0,
        "failed_count": 0,
    }

    assert service.runner.run_source.call_count == 2
