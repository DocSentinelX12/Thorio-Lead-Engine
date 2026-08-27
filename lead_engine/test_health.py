from .config import LeadEngineConfig
from .database import LeadDB
from .health import (
    check_configuration,
    check_database,
    health_report,
)


def test_database_health_is_healthy(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    result = check_database(db)

    assert result["ok"] is True
    assert result["status"] == "healthy"


def test_configuration_health_is_healthy(tmp_path):
    config = LeadEngineConfig(
        database_dir=str(tmp_path),
        batch_size=50,
    )

    result = check_configuration(config)

    assert result["ok"] is True
    assert result["status"] == "healthy"


def test_health_report_is_healthy(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    config = LeadEngineConfig(
        database_dir=str(tmp_path)
    )

    result = health_report(
        db,
        config,
    )

    assert result["ok"] is True
    assert result["status"] == "healthy"
    assert len(result["checks"]) == 2


def test_configuration_health_rejects_invalid_batch_size(
    tmp_path,
):
    config = LeadEngineConfig(
        database_dir=str(tmp_path),
        batch_size=0,
    )

    result = check_configuration(config)

    assert result["ok"] is False
    assert result["status"] == "unhealthy"
