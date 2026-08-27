from .config import LeadEngineConfig


def test_default_configuration():
    config = LeadEngineConfig()

    assert config.database_dir == "data"
    assert config.airtable_base_id == ""
    assert config.airtable_table == "Lead Radar"
    assert config.batch_size == 50
    assert config.sync_enabled is True


def test_configuration_reads_environment(monkeypatch):
    monkeypatch.setenv(
        "LEAD_ENGINE_DATA_DIR",
        "custom-data",
    )
    monkeypatch.setenv(
        "AIRTABLE_BASE_ID",
        "app_test",
    )
    monkeypatch.setenv(
        "AIRTABLE_LEAD_TABLE",
        "Custom Leads",
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
    assert config.airtable_base_id == "app_test"
    assert config.airtable_table == "Custom Leads"
    assert config.batch_size == 25
    assert config.sync_enabled is False


def test_invalid_batch_size_uses_safe_default(monkeypatch):
    monkeypatch.setenv(
        "LEAD_ENGINE_BATCH_SIZE",
        "not-a-number",
    )

    config = LeadEngineConfig.from_environment()

    assert config.batch_size == 50


def test_invalid_small_batch_size_uses_safe_default(monkeypatch):
    monkeypatch.setenv(
        "LEAD_ENGINE_BATCH_SIZE",
        "0",
    )

    config = LeadEngineConfig.from_environment()

    assert config.batch_size == 50
