from unittest.mock import patch

from .web_source_config import create_web_source_from_env


def test_web_source_config_returns_none_when_unconfigured():
    with patch.dict(
        "os.environ",
        {},
        clear=True,
    ):
        assert create_web_source_from_env() is None


def test_web_source_config_creates_source():
    with patch.dict(
        "os.environ",
        {
            "THORIO_LEAD_SOURCE_URL": "https://example.com/leads.json",
            "THORIO_LEAD_SOURCE_TIMEOUT": "30",
        },
        clear=True,
    ):
        source = create_web_source_from_env()

    assert source is not None
    assert source.url == "https://example.com/leads.json"
    assert source.timeout == 30
