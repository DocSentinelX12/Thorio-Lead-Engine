from .application import LeadEngineApplication
from .config import LeadEngineConfig


def test_application_uses_configured_database(tmp_path):
    config = LeadEngineConfig(
        database_dir=str(tmp_path),
        batch_size=25,
    )

    application = LeadEngineApplication(
        config=config
    )

    status = application.status()

    assert status["total_leads"] == 0
    assert application.config.batch_size == 25


def test_application_reports_health(tmp_path):
    config = LeadEngineConfig(
        database_dir=str(tmp_path)
    )

    application = LeadEngineApplication(
        config=config
    )

    result = application.health()

    assert result["healthy"] is True


def test_application_uses_configured_work_queue_limit(tmp_path):
    config = LeadEngineConfig(
        database_dir=str(tmp_path),
        batch_size=10,
    )

    application = LeadEngineApplication(
        config=config
    )

    result = application.work_queue()

    assert result == []


def test_application_audits_processed_records(tmp_path):
    config = LeadEngineConfig(
        database_dir=str(tmp_path)
    )

    application = LeadEngineApplication(
        config=config
    )

    result = application.process_records(
        []
    )

    assert isinstance(result, dict)

    events = application.audit.read()

    assert len(events) == 1
    assert events[0]["event"] == "records_processed"


def test_application_exports_pending_leads(tmp_path):
    config = LeadEngineConfig(
        database_dir=str(tmp_path)
    )

    application = LeadEngineApplication(
        config=config
    )

    application.db.insert_if_new(
        {
            "fingerprint": "application-export-001",
            "company": "Application Export Corp",
            "signal": "developer",
            "status": "Unverified",
        }
    )

    destination = tmp_path / "export.json"

    result = application.export_pending(
        str(destination)
    )

    assert result["count"] == 1

    events = application.audit.read()

    assert events[-1]["event"] == (
        "pending_leads_exported"
    )
    assert events[-1]["count"] == 1
