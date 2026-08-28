from unittest.mock import patch

from .source_registry import configured_sources


def test_configured_sources_empty_when_unconfigured():
    with patch.dict(
        "os.environ",
        {},
        clear=True,
    ):
        sources = configured_sources()

    assert sources == []


def test_configured_sources_includes_web_source():
    with patch.dict(
        "os.environ",
        {
            "THORIO_LEAD_SOURCE_URL": "https://example.com/leads.json",
            "THORIO_LEAD_SOURCE_TIMEOUT": "20",
        },
        clear=True,
    ):
        sources = configured_sources()

    assert len(sources) == 1
    assert sources[0].name == "web"
    assert sources[0].url == "https://example.com/leads.json"
