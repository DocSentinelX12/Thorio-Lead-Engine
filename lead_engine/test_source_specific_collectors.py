import json

from lead_engine.source_adapters import create_adapter
from lead_engine.source_definition import SourceDefinition


def _definition(name: str, url: str, collector_type: str = "html") -> SourceDefinition:
    return SourceDefinition(
        name=name,
        provider=name,
        collector_type=collector_type,
        url=url,
        pagination_type="none",
        max_pages=1,
        max_requests=1,
        max_records=10,
    )


def test_source_specific_html_adapter_uses_definition_url(monkeypatch):
    import lead_engine.source_specific_collectors as collectors

    requested = []

    def fake_fetch(request, timeout, deadline=None):
        requested.append((request.full_url, deadline))
        return b"<html><body>No job links</body></html>"

    monkeypatch.setattr(collectors, "fetch_url", fake_fetch)
    adapter = create_adapter(definition=_definition("NoDesk", "https://nodesk.co/remote-jobs/"), timeout=12)
    adapter.collect()
    assert requested[0][0] == "https://nodesk.co/remote-jobs/"
    assert requested[0][1] is not None


def test_renamed_html_detail_sources_keep_their_specialized_adapter(monkeypatch):
    import lead_engine.source_specific_collectors as collectors

    requested = []

    def fake_fetch(request, timeout, deadline=None):
        requested.append(request.full_url)
        return b"<html><body></body></html>"

    monkeypatch.setattr(collectors, "fetch_url", fake_fetch)
    definitions = (
        _definition("USA Remote Work", "https://www.usaremotework.com/jobs"),
        _definition("Remote Landers", "https://remotelanders.com/jobs"),
    )
    for definition in definitions:
        create_adapter(definition=definition, timeout=12).collect()
    assert requested == [
        "https://www.usaremotework.com/jobs",
        "https://remotelanders.com/jobs",
    ]


def test_source_specific_html_collection_stops_when_deadline_is_reached(monkeypatch):
    import lead_engine.source_specific_collectors as collectors

    monkeypatch.setenv("THORIO_SOURCE_DETAIL_COLLECTION_DEADLINE_SECONDS", "1")
    clock = [100.0]

    class _FakeClock:
        @staticmethod
        def monotonic():
            return clock[0]

    monkeypatch.setattr(collectors, "time", _FakeClock())

    calls = []

    def fake_fetch(request, timeout, deadline=None):
        calls.append(request.full_url)
        if request.full_url.endswith("/listing"):
            return b'<a href="https://example.com/remote-jobs/job/1">job</a><a href="https://example.com/remote-jobs/job/2">job</a>'
        clock[0] = 102.0
        return b"<script type=\"application/ld+json\">{\"@type\":\"JobPosting\",\"title\":\"Engineer\",\"hiringOrganization\":{\"name\":\"Acme\"},\"url\":\"https://example.com/remote-jobs/job/1\"}</script>"

    monkeypatch.setattr(collectors, "fetch_url", fake_fetch)
    adapter = create_adapter(definition=_definition("NoDesk", "https://example.com/listing"), timeout=5)
    try:
        adapter.collect()
    except collectors.HTTPRetryError as exc:
        assert "deadline" in str(exc).lower()
    else:
        raise AssertionError("Expected the source-specific collection deadline to stop collection")
    assert calls == ["https://example.com/listing", "https://example.com/remote-jobs/job/1"]


def test_json_replacement_sources_do_not_get_html_specialization(monkeypatch):
    import lead_engine.source_adapters as source_adapters

    requested = []

    def fake_fetch(request, timeout, deadline=None):
        requested.append(request.full_url)
        return b'{"jobs": []}'

    monkeypatch.setattr(source_adapters, "fetch_url", fake_fetch)
    for name in ("Rocketship", "Remote Landers"):
        definition = _definition(
            name,
            "https://remotelanders.com/api/jobs?limit=100&page=1",
            collector_type="json",
        )
        result = source_adapters.create_adapter(definition=definition, timeout=12).collect()
        assert result == []
    assert requested == [
        "https://remotelanders.com/api/jobs?limit=100&page=1",
        "https://remotelanders.com/api/jobs?limit=100&page=1",
    ]


def test_welcome_to_the_jungle_extracts_credentials_from_javascript_env():
    from lead_engine.source_specific_collectors import _extract_algolia_credentials

    raw = b'window.__ENV__={"algoliaApplicationId":"CSEKHVMS53","algoliaSearchApiKey":"0123456789abcdef0123456789abcdef"};'
    assert _extract_algolia_credentials(raw) == (
        "CSEKHVMS53",
        "0123456789abcdef0123456789abcdef",
    )


def test_welcome_to_the_jungle_uses_current_algolia_query_shape(monkeypatch):
    import lead_engine.source_specific_collectors as collectors

    requests = []

    def fake_fetch(request, timeout, deadline=None):
        requests.append(request)
        if request.full_url.endswith("/api/env"):
            return b'window.__ENV__={"algoliaApplicationId":"CSEKHVMS53","algoliaSearchApiKey":"0123456789abcdef0123456789abcdef"};'
        return json.dumps({
            "results": [{
                "hits": [{
                    "objectID": "job-1",
                    "name": "Senior Software Engineer",
                    "organization": {"name": "Example Co", "slug": "example-co"},
                    "slug": "senior-software-engineer",
                    "descriptions": {"en": "Build software."},
                    "office": {"city": "Remote"},
                }]
            }]
        }).encode("utf-8")

    monkeypatch.setattr(collectors, "fetch_url", fake_fetch)
    definition = SourceDefinition(
        name="Welcome to the Jungle",
        provider="Welcome to the Jungle",
        collector_type="json",
        url="https://www.welcometothejungle.com/en/pages/jobs",
        pagination_type="none",
        max_pages=1,
        max_requests=1,
        max_records=100,
    )
    result = create_adapter(definition=definition, timeout=12).collect()
    assert len(result) == 1
    algolia_request = requests[1]
    assert "/1/indexes/*/queries" in algolia_request.full_url
    assert algolia_request.headers["Content-type"] == "application/x-www-form-urlencoded"
    body = json.loads(algolia_request.data.decode("utf-8"))
    assert body["requests"][0]["indexName"] == "wk_cms_jobs_production"
    assert "hitsPerPage=100" in body["requests"][0]["params"]
