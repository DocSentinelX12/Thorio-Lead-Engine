from unittest.mock import patch

from .source_adapters import HtmlSourceAdapter


def test_html_fallback_extracts_semantic_job_card():
    html = b"""
    <article class="job-card">
      <a class="job-title" href="/jobs/software-engineer">
        Senior Software Engineer
      </a>
      <div class="company">Example Corp</div>
      <div class="location">Remote, US</div>
    </article>
    """

    with patch(
        "lead_engine.source_adapters.fetch_url",
        side_effect=[html, html],
    ):
        adapter = HtmlSourceAdapter(
            url="https://example.com/jobs",
            source="Example Source",
        )
        result = adapter.collect()

    assert len(result.records) == 1
    assert result.records[0]["job_title"] == "Senior Software Engineer"
    assert result.records[0]["company"] == "Example Corp"
    assert result.records[0]["url"] == "https://example.com/jobs/software-engineer"


def test_html_fallback_extracts_embedded_json_job_data():
    html = b"""
    <html>
      <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "job": {
              "id": "job-123",
              "title": "Data Engineer",
              "company": {"name": "Data Corp"},
              "url": "/jobs/data-engineer",
              "description": "Build data systems."
            }
          }
        }
      </script>
    </html>
    """

    with patch(
        "lead_engine.source_adapters.fetch_url",
        side_effect=[html, html],
    ):
        adapter = HtmlSourceAdapter(
            url="https://example.com/careers",
            source="Example Source",
        )
        result = adapter.collect()

    assert len(result.records) == 1
    assert result.records[0]["job_title"] == "Data Engineer"
    assert result.records[0]["company"] == "Data Corp"
    assert result.records[0]["source_id"] == "https://example.com/jobs/data-engineer"


def test_html_fallback_still_rejects_job_link_without_company():
    html = b"""
    <article class="job-card">
      <a class="job-title" href="/jobs/software-engineer">
        Software Engineer
      </a>
    </article>
    """

    with patch(
        "lead_engine.source_adapters.fetch_url",
        side_effect=[html, html],
    ):
        adapter = HtmlSourceAdapter(
            url="https://example.com/jobs",
            source="Example Source",
        )
        result = adapter.collect()

    assert result.records == []


def test_existing_json_ld_path_is_not_replaced_by_fallback():
    html = b"""
    <script type="application/ld+json">
      {
        "@type": "JobPosting",
        "title": "Software Engineer",
        "url": "https://example.com/jobs/1",
        "hiringOrganization": {"name": "Example Corp"}
      }
    </script>
    """

    with patch(
        "lead_engine.source_adapters.fetch_url",
        return_value=html,
    ) as fetch:
        adapter = HtmlSourceAdapter(
            url="https://example.com/jobs",
            source="Example Source",
        )
        result = adapter.collect()

    assert len(result.records) == 1
    assert fetch.call_count == 1
