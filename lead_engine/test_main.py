from unittest.mock import patch

from . import __main__


def test_module_entry_point_calls_cli():
    with patch(
        "lead_engine.__main__.main",
        return_value=0,
    ) as mock_main:
        with patch(
            "lead_engine.__main__.__name__",
            "__main__",
        ):
            result = __main__.main()

    assert result == 0
    mock_main.assert_called_once()
