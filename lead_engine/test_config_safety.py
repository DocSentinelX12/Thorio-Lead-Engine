import os

from .config import LeadEngineConfig


def test_config_does_not_require_airtable_credentials(
    monkeypatch,
):
    monkeypatch.delenv(
        "AIRTABLE_API_KEY",
        raising=False,
    )

    monkeypatch.delenv(
        "AIRTABLE_BASE_ID",
        raising=False,
    )

    config = LeadEngineConfig.from_environment()

    assert config.airtable_base_id == ""
    assert config.sync_enabled is True


def test_config_never_exposes_secret_values():
    config = LeadEngineConfig(
        airtable_base_id="app_test",
    )

    representation = repr(config)

    assert "AIRTABLE_API_KEY" not in representation
    assert "api_key" not in representation.lower()


def test_environment_values_are_loaded_without_logging(
    monkeypatch,
):
    monkeypatch.setenv(
        "AIRTABLE_BASE_ID",
        "app_example",
    )

    config = LeadEngineConfig.from_environment()

    assert config.airtable_base_id == "app_example"
