from .sources import (
    LeadSource,
    StaticLeadSource,
    collect_from_source,
)


def test_static_source_returns_leads():
    leads = [
        {
            "source": "test",
            "source_id": "source-001",
            "url": "https://example.com/jobs/001",
            "company": "Acme",
            "signal": "remote developer",
            "evidence": "Developer opening.",
        },
        {
            "source": "test",
            "source_id": "source-002",
            "url": "https://example.com/jobs/002",
            "company": "Example Corp",
            "signal": "software engineer",
            "evidence": "Engineering opening.",
        },
    ]

    source = StaticLeadSource(leads)

    result = list(
        collect_from_source(source)
    )

    assert result == leads
    assert source.name == "static"


def test_source_implements_standard_interface():
    source = StaticLeadSource([])

    assert isinstance(source, LeadSource)
    assert hasattr(source, "collect")
    assert callable(source.collect)


def test_empty_source_is_safe():
    source = StaticLeadSource([])

    result = list(
        collect_from_source(source)
    )

    assert result == []
