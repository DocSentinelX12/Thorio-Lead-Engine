from unittest.mock import patch

from .source_adapters import (
    AdapterResult,
    JsonSourceAdapter,
    create_adapter,
)


def test_json_adapter_returns_normalized_records_and_checkpoint():
    payload = (
        b'{"jobs": ['
        b'{"id":"1",'
        b'"title":"Software Engineer",'
        b'"company":"Example Corp",'
        b'"url":"https://example.com/jobs/1"}'
        b'],'
        b'"nextCursor":"abc123"}'
    )

    with patch(
        "lead_engine.source_adapters.fetch_url",
        return_value=payload,
    ):
        adapter = JsonSourceAdapter(
            url="https://example.com/api",
            source="Example",
        )

        result = adapter.collect()

    assert isinstance(
        result,
        AdapterResult,
    )

    assert len(
        result.records
    ) == 1

    assert (
        result.records[0]["company"]
        == "Example Corp"
    )

    assert (
        result.records[0]["job_title"]
        == "Software Engineer"
    )

    assert (
        result.checkpoint
        == "abc123"
    )


def test_json_adapter_sends_checkpoint():
    payload = (
        b'{"jobs": [],'
        b'"nextCursor":"next123"}'
    )

    with patch(
        "lead_engine.source_adapters.fetch_url",
        return_value=payload,
    ) as fetch:
        adapter = JsonSourceAdapter(
            url="https://example.com/api",
            source="Example",
        )

        adapter.collect(
            checkpoint="previous123"
        )

    request = fetch.call_args.args[0]

    assert (
        "cursor=previous123"
        in request.full_url
    )


def test_html_adapter_does_not_invent_company():
    html = b"""
    <html>
      <a href="/jobs/software-engineer">
        Software Engineer
      </a>
    </html>
    """

    with patch(
        "lead_engine.source_adapters.fetch_url",
        return_value=html,
    ):
        from .source_adapters import HtmlSourceAdapter

        adapter = HtmlSourceAdapter(
            url="https://example.com/jobs",
            source="Example Source",
        )

        result = adapter.collect()

    assert result.records == []


def test_html_adapter_accepts_real_jobposting():
    html = b"""
    <html>
      <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Senior Software Engineer",
        "url": "https://example.com/jobs/123",
        "hiringOrganization": {
          "@type": "Organization",
          "name": "Example Corp"
        },
        "description": "Build software.",
        "jobLocation": {
          "@type": "Place",
          "address": {
            "@type": "PostalAddress",
            "addressLocality": "St. Louis",
            "addressRegion": "MO",
            "addressCountry": "US"
          }
        }
      }
      </script>
    </html>
    """

    with patch(
        "lead_engine.source_adapters.fetch_url",
        return_value=html,
    ):
        from .source_adapters import HtmlSourceAdapter

        adapter = HtmlSourceAdapter(
            url="https://example.com/jobs",
            source="Example Source",
        )

        result = adapter.collect()

    assert len(
        result.records
    ) == 1

    record = result.records[0]

    assert (
        record["company"]
        == "Example Corp"
    )

    assert (
        record["job_title"]
        == "Senior Software Engineer"
    )


def test_create_adapter_exposes_source_name():
    source = create_adapter(
        collector_type="json",
        url="https://example.com/api",
        source="Example API",
    )

    assert source.name == "Example API"
    assert (
        source.url
        == "https://example.com/api"
    )
