from .config import LeadEngineConfig


def test_config_safe_dict_excludes_airtable_base_id():
    config = LeadEngineConfig(
        database_dir="/tmp/test",
        airtable_base_id="SECRET_BASE_ID",
        airtable_table="Lead Radar",
    )

    result = config.safe_dict()

    assert "airtable_base_id" not in result
    assert result["airtable_configured"] is True


def test_config_safe_dict_contains_operational_settings():
    config = LeadEngineConfig(
        database_dir="/tmp/test",
        batch_size=25,
        sync_enabled=False,
    )

    result = config.safe_dict()

    assert result["database_dir"] == "/tmp/test"
    assert result["batch_size"] == 25
    assert result["sync_enabled"] is False


def test_config_database_path_uses_database_directory(
    tmp_path,
):
    config = LeadEngineConfig(
        database_dir=str(tmp_path)
    )

    assert (
        config.database_path
        == tmp_path / "leads.sqlite3"
    )


def test_environment_configuration(monkeypatch):
    monkeypatch.setenv(
        "LEAD_ENGINE_DATABASE_DIR",
        "custom-data",
    )
    monkeypatch.setenv(
        "AIRTABLE_BASE_ID",
        "base-secret",
    )
    monkeypatch.setenv(
        "AIRTABLE_TABLE",
        "Leads",
    )
    monkeypatch.setenv(
        "LEAD_ENGINE_BATCH_SIZE",
        "25",
    )
    monkeypatch.setenv(
        "LEAD_ENGINE_SYNC_ENABLED",
        "false",
    )

    config = LeadEngineConfig.from_environment()

    assert config.database_dir == "custom-data"
    assert config.airtable_base_id == "base-secret"
    assert config.airtable_table == "Leads"
    assert config.batch_size == 25
    assert config.sync_enabled is False
