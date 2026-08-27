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
