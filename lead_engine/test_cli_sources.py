from unittest.mock import patch

from .cli import _configured_runtime_sources, main


def test_run_command_uses_configured_sources():
    fake_source = object()

    with patch(
        "lead_engine.cli.configured_sources",
        return_value=[fake_source],
    ), patch(
        "lead_engine.cli.create_application"
    ) as mock_create_application:

        mock_app = mock_create_application.return_value
        mock_app.run_sources.return_value = {
            "accepted": 3,
            "rejected": 0,
        }

        result = main(["run"])

    assert result == 0
    mock_app.run_sources.assert_called_once_with(
        [fake_source]
    )


def test_run_command_handles_no_configured_sources():
    with patch(
        "lead_engine.cli.configured_sources",
        return_value=[],
    ), patch(
        "lead_engine.cli.create_application"
    ) as mock_create_application:

        mock_app = mock_create_application.return_value
        mock_app.run_sources.return_value = {
            "accepted": 0,
            "rejected": 0,
        }

        result = main(["run"])

    assert result == 0
    mock_app.run_sources.assert_called_once_with([])


def test_runtime_source_builder_preserves_full_catalog_and_adds_discovery_layers():
    catalog_sources = [type("Source", (), {"name": f"catalog-{i}"})() for i in range(42)]
    discovery_sources = [type("Source", (), {"name": "x_signal"})()]
    browser_sources = [type("Source", (), {"name": "linkedin_signal"})()]

    with patch(
        "lead_engine.cli.configured_sources",
        return_value=catalog_sources,
    ), patch(
        "lead_engine.cli.configured_discovery_sources",
        return_value=discovery_sources,
    ), patch(
        "lead_engine.cli.configured_browser_discovery_sources",
        return_value=browser_sources,
    ), patch.dict(
        "os.environ",
        {"THORIO_FREE_ONLY": "1"},
        clear=True,
    ):
        sources = _configured_runtime_sources()

    assert len(sources) == 44
    assert [source.name for source in sources[:42]] == [
        f"catalog-{i}" for i in range(42)
    ]
    assert {source.name for source in sources[42:]} == {
        "x_signal",
        "linkedin_signal",
    }
