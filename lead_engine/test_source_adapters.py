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


def test_json_adapter_uses_source_definition_record_path_and_fields():
    from .source_definition import SourceDefinition

    payload = (
        b'{'
        b'"data": {'
        b'"jobs": ['
        b'{'
        b'"job_id": "job-123",'
        b'"position": "Senior Engineer",'
        b'"company": {'
        b'"name": "Configured Corp"'
        b'},'
        b'"apply": {'
        b'"url": "https://example.com/apply/123"'
        b'},'
        b'"details": "Build important software."'
        b'}'
        b']'
        b'}'
        b'}'
    )

    definition = SourceDefinition(
        name="Configured API",
        provider="Configured",
        collector_type="json",
        url="https://example.com/api",
        record_path="data.jobs",
        title_field="position",
        company_field="company.name",
        description_field="details",
        url_field="apply.url",
        source_id_field="job_id",
        pagination_type="none",
    )

    with patch(
        "lead_engine.source_adapters.fetch_url",
        return_value=payload,
    ):
        adapter = create_adapter(
            definition=definition,
        )

        result = adapter.adapter.collect()

    assert len(result.records) == 1

    record = result.records[0]

    assert (
        record["source_id"]
        == "job-123"
    )

    assert (
        record["job_title"]
        == "Senior Engineer"
    )

    assert (
        record["company"]
        == "Configured Corp"
    )

    assert (
        record["url"]
        == "https://example.com/apply/123"
    )

    assert (
        "Build important software."
        in record["evidence"]
    )


def test_json_adapter_uses_configured_cursor_parameter():
    from .source_definition import SourceDefinition

    payload = (
        b'{'
        b'"jobs": [],'
        b'"pagination": {'
        b'"next": "next-token"'
        b'}'
        b'}'
    )

    definition = SourceDefinition(
        name="Cursor API",
        provider="Cursor",
        collector_type="json",
        url="https://example.com/api",
        pagination_type="cursor",
        cursor_parameter="page_token",
        cursor_response_field="pagination.next",
    )

    with patch(
        "lead_engine.source_adapters.fetch_url",
        return_value=payload,
    ) as fetch:
        adapter = create_adapter(
            definition=definition,
        )

        result = adapter.adapter.collect(
            checkpoint="previous-token"
        )

    request = fetch.call_args.args[0]

    assert (
        "page_token=previous-token"
        in request.full_url
    )

    assert (
        result.checkpoint
        == "next-token"
    )


def test_json_adapter_does_not_send_cursor_when_pagination_is_none():
    from .source_definition import SourceDefinition

    payload = (
        b'{'
        b'"jobs": []'
        b'}'
    )

    definition = SourceDefinition(
        name="Non Cursor API",
        provider="Non Cursor",
        collector_type="json",
        url="https://example.com/api",
        pagination_type="none",
    )

    with patch(
        "lead_engine.source_adapters.fetch_url",
        return_value=payload,
    ) as fetch:
        adapter = create_adapter(
            definition=definition,
        )

        adapter.adapter.collect(
            checkpoint="old-token"
        )

    request = fetch.call_args.args[0]

    assert (
        request.full_url
        == "https://example.com/api"
    )
