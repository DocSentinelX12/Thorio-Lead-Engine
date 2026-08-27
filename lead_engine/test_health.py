from .database import LeadDB
from .health import check_database, check_engine


def test_database_health_is_healthy(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    result = check_database(db)

    assert result["name"] == "database"
    assert result["healthy"] is True
    assert result["error"] is None


def test_engine_health_is_healthy(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    result = check_engine(db)

    assert result["healthy"] is True
    assert len(result["checks"]) == 1
    assert result["checks"][0]["healthy"] is True
