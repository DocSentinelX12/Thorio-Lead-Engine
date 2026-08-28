from unittest.mock import patch

from .cli import main


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
