from unittest.mock import MagicMock

from .database import LeadDB
from .service import LeadEngineService
from .sources import StaticLeadSource


def test_service_reports_status(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    service = LeadEngineService(
        db=db
    )

    result = service.status()

    assert result["total_leads"] == 0
    assert result["synced_leads"] == 0
    assert result["pending_leads"] == 0


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
