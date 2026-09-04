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


def test_json_adapter_definition_page_pagination():
    from .source_definition import SourceDefinition

    responses = {
        "https://example.com/api?page=1": (
            b'{'
            b'"jobs": ['
            b'{'
            b'"id": "1",'
            b'"title": "Engineer One",'
            b'"company": "Company One",'
            b'"url": "https://example.com/1"'
            b'}'
            b']}'
        ),
        "https://example.com/api?page=2": (
            b'{'
            b'"jobs": ['
            b'{'
            b'"id": "2",'
            b'"title": "Engineer Two",'
            b'"company": "Company Two",'
            b'"url": "https://example.com/2"'
            b'}'
            b']}'
        ),
    }

    definition = SourceDefinition(
        name="Page API",
        provider="Example",
        collector_type="json",
        url="https://example.com/api",
        pagination_type="page",
        page_parameter="page",
        page_start=1,
        max_pages=2,
        max_requests=2,
    )


    def fake_fetch(request, timeout):
      return responses[request.full_url]

    with patch(
        "lead_engine.source_adapters.fetch_url",
        side_effect=fake_fetch,
    ) as fetch:
        adapter = create_adapter(
            definition=definition,
        )

        result = adapter.adapter.collect()

    assert len(result.records) == 2

    assert fetch.call_count == 2

    assert result.records[0]["source_id"] == "1"
    assert result.records[1]["source_id"] == "2"

    assert result.checkpoint == "3"


def test_json_adapter_definition_offset_pagination():
    from .source_definition import SourceDefinition

    payload = (
        b'{'
        b'"jobs": ['
        b'{'
        b'"id": "1",'
        b'"title": "Engineer",'
        b'"company": "Offset Corp",'
        b'"url": "https://example.com/1"'
        b'}'
        b']}'
    )

    definition = SourceDefinition(
        name="Offset API",
        provider="Example",
        collector_type="json",
        url="https://example.com/api",
        pagination_type="offset",
        offset_parameter="offset",
        offset_start=0,
        offset_step=50,
        max_pages=2,
        max_requests=2,
    )

    with patch(
        "lead_engine.source_adapters.fetch_url",
        return_value=payload,
    ) as fetch:
        adapter = create_adapter(
            definition=definition,
        )

        result = adapter.adapter.collect()

    assert fetch.call_count == 2

    first_request = (
        fetch.call_args_list[0].args[0]
    )

    second_request = (
        fetch.call_args_list[1].args[0]
    )

    assert (
        "offset=0"
        in first_request.full_url
    )

    assert (
        "offset=50"
        in second_request.full_url
    )

    assert result.checkpoint == "100"


def test_json_adapter_definition_next_url_pagination():
    from .source_definition import SourceDefinition

    first_payload = (
        b'{'
        b'"jobs": ['
        b'{'
        b'"id": "1",'
        b'"title": "Engineer One",'
        b'"company": "Next Corp",'
        b'"url": "https://example.com/1"'
        b'}'
        b'],'
        b'"pagination": {'
        b'"next": "https://example.com/api?page=2"'
        b'}'
        b'}'
    )

    second_payload = (
        b'{'
        b'"jobs": ['
        b'{'
        b'"id": "2",'
        b'"title": "Engineer Two",'
        b'"company": "Next Corp",'
        b'"url": "https://example.com/2"'
        b'}'
        b']'
        b'}'
    )

    responses = {
        "https://example.com/api":
            first_payload,
        "https://example.com/api?page=2":
            second_payload,
    }

    definition = SourceDefinition(
        name="Next URL API",
        provider="Example",
        collector_type="json",
        url="https://example.com/api",
        pagination_type="next_url",
        next_url_field="pagination.next",
        max_pages=2,
        max_requests=2,
    )

    with patch(
        "lead_engine.source_adapters.fetch_url",
        side_effect=lambda request, timeout:
            responses[request.full_url],
    ) as fetch:
        adapter = create_adapter(
            definition=definition,
        )

        result = adapter.adapter.collect()

    assert fetch.call_count == 2

    assert len(result.records) == 2

    assert result.checkpoint is None


def test_json_adapter_encodes_cursor_checkpoint():
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
        name="Encoded Cursor API",
        provider="Example",
        collector_type="json",
        url="https://example.com/api?existing=value",
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

        adapter.adapter.collect(
            checkpoint="abc+123&next=value"
        )

    request = fetch.call_args.args[0]

    assert (
        "page_token=abc%2B123%26next%3Dvalue"
        in request.full_url
    )

    assert (
        "existing=value"
        in request.full_url
    )


def test_json_adapter_replaces_existing_pagination_parameter():
    from .source_definition import SourceDefinition

    payload = (
        b'{'
        b'"jobs": []'
        b'}'
    )

    definition = SourceDefinition(
        name="Existing Page API",
        provider="Example",
        collector_type="json",
        url="https://example.com/api?page=99&existing=value",
        pagination_type="page",
        page_parameter="page",
        page_start=1,
        max_pages=1,
        max_requests=1,
    )

    with patch(
        "lead_engine.source_adapters.fetch_url",
        return_value=payload,
    ) as fetch:
        adapter = create_adapter(
            definition=definition,
        )

        adapter.adapter.collect()

    request = fetch.call_args.args[0]

    assert (
        request.full_url
        == "https://example.com/api?page=1&existing=value"
    )
